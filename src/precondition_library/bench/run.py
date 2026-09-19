"""Running episodes: the repeat structure that makes the claim testable.

Why the shape of this file is part of the argument rather than plumbing: a
claim about amortization needs repeats, and repeats need to be *comparable*.
Each fault type is therefore injected `occurrences` times with different seeds,
so that occurrence_index counts genuine recurrences of a task family rather
than repetitions of one scripted scenario. The seed varies across occurrences
and the fault type stays fixed, which is the experimental design in one line.

Repeats are also the difficulty, and the runner has to be honest about it. A
fault's injector declares only a handful of states, so a later occurrence can
select a state an earlier one already injected -- and a program admitted from
that earlier episode will be offered for it. That occurrence is a genuine repeat
of the same state and a *dependent* observation of the same experiment, so the
runner labels every row with the role the plan gives it (`bench.splits`) rather
than leaving the report to infer independence from the occurrence index. Both
things are wanted: the recurrence is what makes amortization visible, and the
label is what keeps it out of an independence claim.

Each arm builds its library from empty and sees the same faults in the same
order, so the arms cannot differ by luck of scheduling.

Two rules from the design decide the code below, and both are easy to break by
"simplifying" the flow:

* **The arm decides when to stop; the caller grades afterwards.** `react.solve`
  is never allowed to consult the fault's checker, and neither is anything here:
  the checker runs once, after the arm has stopped, and its verdict becomes
  `ground_truth_ok`. Using it to decide whether an episode is "done" would hand
  the compiled arms an oracle arm 1 was denied (issue #9).
* **An episode that could not run is recorded, not dropped.** A sandbox that
  fails to build becomes an `EpisodeRecord` with `outcome=INVALID`, because
  dropping it would shrink every denominator silently (spec §7, item 9).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from ..agents.compile import admit, compile_program
from ..agents.dispatch import Dispatch, dispatch_preconditions, dispatch_semantic
from ..agents.react import solve
from ..library import Library, ProgramIdCollisionError
from ..program import EpisodeOutcome, ProgramStatus
from ..provider import Completion, Provider, ProviderError
from ..runtime.probes import evaluate_preconditions
from ..runtime.replay import ReplayResult, replay
from ..sandbox import Sandbox
from ..signatures import StateFingerprint, TaskSignature
from ..tasks.faults import FAULTS, build_sandbox
from ..tasks.intent import IntentSpec, ResolutionVariant
from ..tasks.invariants import refs_intact
from ..tasks.registry import EXCLUDED_FROM_BENCHMARK, ambiguous_intents
from .ledger import Arm, EpisodeRecord, OccurrenceRole, append
from .splits import occurrence_roles

_EXCLUDED_NOTICE = (
    "excluded from the benchmark: their request text is a fixed sentence, so the "
    "text is the class label and a text-reading dispatcher could not mis-fire. "
    "Refusing the request rather than skipping it silently (issue #25)"
)

_RATE_LIMIT_STATUS = 429
"""HTTP 429: the provider is asking the caller to slow down, so it is retryable."""

_SERVER_ERROR_FLOOR = 500
"""5xx is transient by HTTP's own contract, unlike a 4xx the request caused."""

_MAX_RETRY_ATTEMPTS = 3
"""One initial call plus two retries. A small cap: an episode must still fail in
bounded time, and a transient rate limit is the case this exists for."""

_RETRY_BASE_DELAY_S = 0.5
_RETRY_MAX_DELAY_S = 2.0
"""Capped exponential backoff: 0.5s then 1.0s, never more than the cap."""


class _AccountingProvider:
    """Wrap a `Provider` and sum what one episode spends through it.

    Every call in an episode — the ReAct loop's turns and the compile step's one
    reply — goes through this object, so the ledger's token fields are the sum of
    the completions the episode actually made rather than an estimate assembled
    from return values. Nothing else counts tokens: the compile result carries
    its own usage, but that completion was already seen here, and adding both
    would double the compile's cost onto the episode that triggered it.

    Spec §8 gives retry policy to the caller and requires it to be visible, so a
    rate-limit or 5xx response is retried here with a capped backoff and a 4xx is
    not. Every *attempt* is added to `llm_calls`, including the ones that raised,
    which is what keeps a retry from hiding itself: the ledger records three
    calls for a completion that took three tries, and the token totals stay the
    sum of the responses that actually returned usage. A failed request's token
    spend is unknown to us, and inventing a value would be worse than the gap —
    the count of calls is the part that is knowable, so it is the part recorded.
    """

    def __init__(self, provider: Provider) -> None:
        self._provider = provider
        self.tokens_in = 0
        self.tokens_out = 0
        self.uncached_tokens_in = 0
        self.cached_tokens_in = 0
        self.cache_write_tokens_in = 0
        self.llm_calls = 0

    def complete(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> Completion:
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                completion = self._provider.complete(system=system, messages=messages, tools=tools)
            except ProviderError as error:
                self.llm_calls += 1
                if attempt == _MAX_RETRY_ATTEMPTS or not _is_retryable(error):
                    raise
                time.sleep(_retry_delay_s(attempt))
                continue
            self.tokens_in += completion.usage.tokens_in
            self.tokens_out += completion.usage.tokens_out
            self.uncached_tokens_in += completion.usage.uncached_tokens_in
            self.cached_tokens_in += completion.usage.cached_tokens_in
            self.cache_write_tokens_in += completion.usage.cache_write_tokens_in
            self.llm_calls += completion.llm_calls
            return completion
        raise AssertionError("unreachable: the loop returns or raises")


def _is_retryable(error: ProviderError) -> bool:
    """Whether a provider error is transient (spec §8): rate limit or 5xx only.

    A 4xx means the request itself was wrong and will be wrong again, so retrying
    it would only spend more of the budget on the same failure. A `ProviderError`
    with no status is a malformed body, which is deterministic for the same
    reply, or a transport failure the caller did not classify.
    """
    status = error.status_code
    return status is not None and (status == _RATE_LIMIT_STATUS or status >= _SERVER_ERROR_FLOOR)


def _retry_delay_s(attempt: int) -> float:
    """The capped exponential backoff before retry number `attempt + 1`."""
    return min(_RETRY_BASE_DELAY_S * (2 ** (attempt - 1)), _RETRY_MAX_DELAY_S)


@dataclass
class _ArmResult:
    """How the arm's mechanism completed, before ground truth is applied.

    Mutable because the compile step runs after grading (the sandbox it would
    otherwise rebuild at the same path is destroyed first), and it fills in
    `admitted`/`program_id` when the arm had to solve a task it could not replay.
    """

    outcome: EpisodeOutcome
    transcript: list[dict] | None
    """The ReAct transcript, when the arm solved. `None` means the episode was a
    replay: no model was consulted and there is nothing to compile."""
    fired_variant: str | None
    program_id: str | None
    dispatch_score: float | None
    admitted: bool | None
    refusal_reason: str | None
    """The guard's own reason, set only when the body it refused was the outcome."""
    compile_failure_reason: str | None
    """Why the fallback's compile or admission produced no usable program.

    A separate field from `refusal_reason` because they are different signals:
    the guard refusal rate is a safety metric, the compile success rate a
    compile-quality one, and one field cannot carry both without conflating
    them (issue #60)."""
    replay_failure_reason: str | None
    """Why a fired program could not be run at all, when that is the cause a row
    must name (issue #76). None for a refusal, which carries `refusal_reason`,
    and for a body that ran and failed its postconditions, whose evidence is the
    demotion and the postcondition results."""
    timed_out: bool
    compilable: bool
    """Whether this episode solved a task whose solution should be compiled.

    Set by `_run_arm` from what actually happened: true only when a compiled arm
    had to solve, has a transcript, and owns a library to store into. It is a
    property of the result rather than of the arm so `_learn_from_solution`
    branches on the episode, not on which arm ran it -- §4 keeps arm-specific
    logic inside `dispatch.py`, and a fourth arm must not need this file audited
    for it. Arm 1's solve is not compilable because arm 1 has no library; a
    replay hit is not compilable because no model ran."""


def run_benchmark(
    *,
    arms: list[Arm],
    faults: list[str],
    occurrences: int,
    seeds: list[int],
    out: Path,
    model: str,
    provider: Provider,
) -> Path:
    """Run every (arm, fault, occurrence) episode and write the ledger.

    Episodes within an arm run in occurrence order — the library must accumulate
    the way it would in use, so an arm cannot benefit from a program compiled
    against a later state. Returns the ledger path.

    `seeds` supplies the seed for each occurrence, positionally: occurrence `k`
    runs against `seeds[k - 1]`, so the same seed reaches every arm and the
    comparison stays paired. `provider` is injected rather than built from
    `model` because the provider owns its credentials and this repository reads
    no environment variables; `model` is the identifier recorded on every row.

    Each occurrence's role -- variant the first time a resolution is seen, replay
    every later time -- is read from the plan (`bench.splits.occurrence_roles`)
    and written onto the row, so the report can group by it instead of inferring
    it. The roles depend only on the seed sequence and the fault, never on the
    arm, so they are computed once and shared; a reader can therefore reproduce
    the labelling from the ledger's `seed` and `fault_type` alone.

    Only faults with a registered, ambiguous intent are measurable. A fault in
    `EXCLUDED_FROM_BENCHMARK`, or one with no intent at all, raises before any
    episode runs: silently skipping it would make the run's denominator a
    property of the caller's typo rather than of the design.
    """
    _require_measurable(faults)
    if occurrences < 1:
        raise ValueError(f"occurrences must be at least 1, got {occurrences}")
    if len(seeds) < occurrences:
        raise ValueError(
            f"{occurrences} occurrence(s) need {occurrences} seed(s), got {len(seeds)}; "
            f"reusing one seed across occurrences would make them one instance, not repeats"
        )

    # The plan's role for each occurrence, per fault. Arm-independent, so it is
    # computed once: every arm must label the same occurrence the same way, or
    # the report's grouping would be a property of the arm rather than of the
    # plan. `seeds[:occurrences]` because the extra seeds, if any, are never run.
    roles = {fault_type: occurrence_roles(seeds[:occurrences], fault_type) for fault_type in faults}

    for arm in arms:
        library_root = out.parent / f"library-{arm.value}"
        _require_empty_library(library_root, arm)
        library = Library(library_root, evaluate_preconditions=evaluate_preconditions)
        for occurrence in range(1, occurrences + 1):
            for fault_type in faults:
                record = run_episode(
                    arm,
                    fault_type,
                    seeds[occurrence - 1],
                    occurrence,
                    role=roles[fault_type][occurrence - 1],
                    provider=provider,
                    library=library,
                    model=model,
                )
                append(out, record)
    return out


def run_episode(
    arm: Arm,
    fault_type: str,
    seed: int,
    occurrence: int,
    *,
    role: OccurrenceRole,
    provider: Provider,
    library: Library,
    model: str,
) -> EpisodeRecord:
    """One episode: build a sandbox, let the arm act, check ground truth, record.

    Ground truth is checked for every arm with the same fault checker, so
    success means the same thing everywhere. The record is returned rather than
    written, so the caller owns the ledger path and `run_benchmark` appends one
    line per episode.

    `role` is required and never defaulted: only the caller that owns the whole
    seed sequence can know whether this occurrence is the first sight of its
    state, and a default would silently label a repeat as an independent
    observation -- the one error the field exists to prevent. `run_benchmark`
    reads it from the plan; a caller running one episode in isolation labels it
    explicitly.

    The three arms differ in exactly one place, `_run_arm`: arm 1 solves with
    the agent, arms 2 and 3 ask their dispatcher for a stored program and fall
    back to solving when none applies. Everything after that — the checker, the
    record, the token accounting — is shared, which is what makes a difference
    between arms attributable to dispatch.

    `library` is unused by arm 1 (it has no library) and required anyway, so the
    three arms share one call shape rather than one arm having a different
    signature.
    """
    intent = _intent_for(fault_type)
    fault = FAULTS[fault_type]
    started = time.monotonic()
    accounting = _AccountingProvider(provider)
    # Read the digest before the arm runs: it describes the library the episode
    # dispatched against, and the compile below may add to it afterwards.
    library_hash = library.library_hash()
    box: Sandbox | None = None
    try:
        try:
            box = build_sandbox(seed, [fault_type])
            state = StateFingerprint.observe(box)
        except Exception as exc:
            return _invalid_record(
                arm,
                intent.name,
                fault_type,
                seed,
                occurrence,
                role,
                model,
                started,
                str(exc),
                accounting=accounting,
                library_hash=library_hash,
                threshold=library.threshold,
            )

        request = fault.task_text(seed)
        correct = intent.correct_variant(state)
        signature = TaskSignature(intent=request, fingerprint=state, target=str(box.work))

        result = _run_arm(arm, signature, box, library, fault_type, seed, occurrence, accounting)
        refs_ok: bool | None = None
        try:
            verdict = fault.check(box)
            if verdict.ok:
                # Reaching the expected state is not sufficient on its own: a
                # resolution can reach it by discarding everything else, and then the
                # arm would be scored as succeeding by destroying the repository
                # rather than by repairing the fault (issue #9, item 3). Checked only
                # when the fault's own clause passed, so a fault-level failure keeps
                # its own reason rather than being reported as a ref violation.
                intact = refs_intact(box)
                refs_ok = intact.ok
                verdict = intact
            ground_truth_ok = verdict.ok
        except Exception as exc:
            return _invalid_record(
                arm,
                intent.name,
                fault_type,
                seed,
                occurrence,
                role,
                model,
                started,
                str(exc),
                accounting=accounting,
                library_hash=library_hash,
                threshold=library.threshold,
            )

        # Grading is done with this sandbox, so it is safe to release it now.
        # Admission (below) rebuilds sandboxes at deterministic paths, and one of
        # them is this episode's own (seed, fault) pair; leaving the box alive
        # would let admission's `build_sandbox` replace it under the checker.
        box.destroy()
        _learn_from_solution(
            result, signature, box, library, fault_type, seed, occurrence, accounting
        )
        _record_mismatch(result, library, correct, fault_type, seed, occurrence)

        return EpisodeRecord(
            arm=arm,
            task_id=intent.name,
            fault_type=fault_type,
            occurrence_index=occurrence,
            occurrence_role=role,
            seed=seed,
            tokens_in=accounting.tokens_in,
            tokens_out=accounting.tokens_out,
            uncached_tokens_in=accounting.uncached_tokens_in,
            cached_tokens_in=accounting.cached_tokens_in,
            cache_write_tokens_in=accounting.cache_write_tokens_in,
            llm_calls=accounting.llm_calls,
            wall_clock_s=time.monotonic() - started,
            outcome=result.outcome,
            correct_variant=correct.id if correct is not None else None,
            fired_variant=result.fired_variant,
            ground_truth_ok=ground_truth_ok,
            refs_intact=refs_ok,
            program_id=result.program_id,
            dispatch_score=result.dispatch_score,
            similarity_threshold=library.threshold,
            library_hash=library_hash,
            admitted=result.admitted,
            refusal_reason=result.refusal_reason,
            compile_failure_reason=result.compile_failure_reason,
            replay_failure_reason=result.replay_failure_reason,
            timed_out=result.timed_out,
            model=model,
        )
    finally:
        if box is not None:
            box.destroy()


def _run_arm(
    arm: Arm,
    signature: TaskSignature,
    box: Sandbox,
    library: Library,
    fault_type: str,
    seed: int,
    occurrence: int,
    accounting: _AccountingProvider,
) -> _ArmResult:
    """The one arm-specific decision. Everything downstream is shared.

    Arm 1 solves and stops when the model declares itself finished. Arms 2 and 3
    dispatch first; a hit is replayed with no model call, and anything else — no
    applicable program, a fire whose body or postconditions failed, or a guard
    refusal — falls back to the agent for this episode only, at full price (spec
    §8). A fallback is a cost, and the tokens it spends are charged to the arm
    that had to pay them.
    """
    if arm is Arm.REACT:
        outcome, transcript = solve(signature, box, accounting)
        return _ArmResult(
            outcome,
            transcript,
            fired_variant=None,
            program_id=None,
            dispatch_score=None,
            admitted=None,
            refusal_reason=None,
            compile_failure_reason=None,
            replay_failure_reason=None,
            timed_out=False,
            # Arm 1 has no library, so its solution is not compiled.
            compilable=False,
        )

    decision: Dispatch = (
        dispatch_semantic(signature, library)
        if arm is Arm.SEMANTIC
        else dispatch_preconditions(signature, library, box)
    )

    if decision.program is None:
        outcome, transcript = solve(signature, box, accounting)
        return _ArmResult(
            _after_fallback(outcome),
            transcript,
            fired_variant=None,
            program_id=None,
            dispatch_score=decision.score,
            admitted=None,
            refusal_reason=None,
            compile_failure_reason=None,
            replay_failure_reason=None,
            timed_out=False,
            compilable=True,
        )

    fired = decision.program
    replayed = replay(fired, box)
    if replayed.ok:
        # The replay path never touched `accounting`, which is the invariant the
        # cost model rests on: a program that applies costs zero LLM calls.
        return _ArmResult(
            EpisodeOutcome.SUCCESS,
            None,
            fired_variant=fired.variant,
            program_id=fired.id,
            dispatch_score=decision.score,
            admitted=True,
            refusal_reason=None,
            compile_failure_reason=None,
            replay_failure_reason=None,
            timed_out=False,
            # No model ran, so there is no transcript to compile.
            compilable=False,
        )

    fired_variant = None if replayed.refused else fired.variant
    if _is_genuine_miss(replayed):
        # §8: a fire that could not work is demoted, and the fallback is charged
        # to this episode. That is a body whose postconditions failed, and also a
        # body that never ran because this environment cannot bind a parameter it
        # names (issue #76) -- the program fired on a state it cannot serve, which
        # is the same "too permissive to be correct" defect. Anything else -- a
        # guard refusal, a timeout -- is a runtime outcome rather than evidence
        # the program is wrong, so the program is left as it was.
        library.set_status(
            fired.id, ProgramStatus.DEMOTED, episode_id=_episode_id(fault_type, seed, occurrence)
        )

    outcome, transcript = solve(signature, box, accounting)
    if replayed.refused:
        return _ArmResult(
            EpisodeOutcome.REFUSAL,
            transcript,
            fired_variant=None,
            program_id=fired.id,
            dispatch_score=decision.score,
            admitted=True,
            refusal_reason=replayed.reason,
            compile_failure_reason=None,
            # A refusal is a safety signal, not a replay failure: it must not be
            # read as one, or the refusal rate would pick up rows no guard refused
            # (issue #60).
            replay_failure_reason=None,
            timed_out=replayed.timed_out,
            compilable=True,
        )
    return _ArmResult(
        _after_fallback(outcome),
        transcript,
        fired_variant=fired_variant,
        program_id=fired.id,
        dispatch_score=decision.score,
        admitted=True,
        refusal_reason=None,
        compile_failure_reason=None,
        # None for a postcondition miss, whose evidence is the demotion; set when
        # the body could not run at all (issue #76).
        replay_failure_reason=replayed.reason if replayed.unbound_parameter else None,
        timed_out=replayed.timed_out,
        compilable=True,
    )


def _record_mismatch(
    result: _ArmResult,
    library: Library,
    correct: ResolutionVariant | None,
    fault_type: str,
    seed: int,
    occurrence: int,
) -> None:
    """Count one wrong-variant fire against the program that fired (spec §8).

    `misfired` is the ledger's own definition -- a program fired a resolution
    that was not this state's ground truth -- and it is independent of episode
    success, which is why this is a separate step from the demotion in
    `_is_genuine_miss`. A program can be wrong about the resolution and still
    satisfy its postconditions (`rebase` on a state that requires `merge` reaches
    a synced tree), so it is never demoted and would mis-fire on every later
    occurrence; `Library.record_mismatch` withdraws it after the second.

    Nothing is counted when the body did not run to completion: a guard refusal
    leaves `fired_variant` None, and a timeout is a runtime mishap rather than
    evidence about the program, matching the bar `_is_genuine_miss` sets for
    demotion. This runs after grading because the row is derived once the arm has
    stopped -- the arm itself is never allowed to see ground truth.
    """
    correct_id = correct.id if correct is not None else None
    if result.fired_variant is None or result.fired_variant == correct_id:
        return
    if result.program_id is None or result.timed_out:
        return
    library.record_mismatch(result.program_id, episode_id=_episode_id(fault_type, seed, occurrence))


def _is_genuine_miss(replayed: ReplayResult) -> bool:
    """Whether a failed replay is evidence the program is wrong (spec §8).

    Demotion is terminal (`library._TRANSITIONS`), so it must rest on the
    program's own contract, not on the runtime's mood. Two outcomes qualify: a
    body that ran to completion and left its postconditions unsatisfied, and a
    body this environment cannot bind a declared parameter for, which never ran
    at all (issue #76). Both are the program's own defect -- its preconditions
    accepted a state where it cannot work -- so both are the "too permissive to
    be correct" evidence §8 demotes on. A guard refusal executed nothing and a
    timeout was killed before it finished, and neither says anything about the
    program; they are excluded. The body exiting non-zero is not in this test on
    purpose: the postconditions are the program's own statement of done, and
    spec §8 demotes on a postcondition miss, not on an exit code. A transient
    timeout demoting a correct program would remove it permanently and shrink
    coverage -- the variable the comparison is matched on.
    """
    if replayed.refused or replayed.timed_out:
        return False
    if replayed.unbound_parameter:
        return True
    return replayed.postconditions is not None and not replayed.postconditions.ok


def _learn_from_solution(
    result: _ArmResult,
    signature: TaskSignature,
    box: Sandbox,
    library: Library,
    fault_type: str,
    seed: int,
    occurrence: int,
    accounting: _AccountingProvider,
) -> None:
    """Compile the episode's solution into a candidate and gate it, in place.

    The decision to compile is read from the result, not from the arm: an episode
    that solved a task and owns a library is compilable, a replay is not (no model
    ran), and arm 1's solve is not (arm 1 has no library). `_run_arm` sets that
    flag where the episode's shape is known, so this function needs no arm branch
    — §4 keeps per-arm logic inside `dispatch.py`, and a fourth arm must not
    require auditing here.

    Only a fallback reaches here, so the compile — and every token it spends —
    belongs to the episode that needed it. `box` has already been destroyed:
    `compile_program` reads the signature and the transcript, and only uses the
    environment for its name, so a throwaway target is honest. Building the
    program is `compile_program`'s job; deciding whether it may be dispatched is
    `admit`'s, and this function only stores the verdict. A program that fails the
    gate is kept as a `candidate` — §8: a rejected program is data, not rubbish —
    and its reason is recorded on the row rather than lost with the traceback a
    raise would produce.

    The program is stored under an id derived from the episode (`_program_id`),
    and its provenance names the fault this episode injected, so the family its
    `variant` is scoreable against is recorded by the caller rather than the
    model (issues #69, #80).
    """
    if not result.compilable or result.transcript is None:
        # `compilable` is set only where a transcript exists; the second test is
        # what lets the type checker see that, without a branch on the arm.
        return

    episode_id = _episode_id(fault_type, seed, occurrence)
    intent = _intent_for(fault_type)
    try:
        compiled = compile_program(
            signature,
            box,
            result.transcript,
            accounting,
            fault=fault_type,
            variant_ids=[variant.id for variant in intent.variants],
        )
    except Exception as exc:
        _record_compile_failure(result, f"compile raised {type(exc).__name__}: {exc}")
        return

    if not compiled.ok or compiled.program is None:
        _record_compile_failure(result, compiled.reason or "the compile returned no program")
        return

    # The stored id is derived from this episode's identity, not taken from the
    # model: a later episode reusing a slug must not lose its program to the
    # library's correct refusal to overwrite (issue #80).
    program = compiled.program.model_copy(
        update={"id": _program_id(fault_type, occurrence, compiled.program.id)}
    )
    admitted, gate_reason = admit(program, fault_type, seeds=[seed])
    try:
        library.add(program)
    except ProgramIdCollisionError as exc:
        # Reachable only when one episode compiles twice into one library (a
        # re-run at the same occurrence). It is a naming collision, not a reply
        # that failed to parse or a gate rejection, and the row must say so.
        _record_compile_failure(result, f"program id collision: {exc}")
        return
    except ValueError as exc:
        # The library never overwrites, so a refused add is reported. The episode
        # keeps the cost of the compile that produced it.
        _record_compile_failure(result, str(exc))
        return
    if admitted:
        library.set_status(program.id, ProgramStatus.ADMITTED, episode_id=episode_id)
    else:
        _record_compile_failure(result, gate_reason)

    if result.program_id is None:
        result.program_id = program.id
    if result.admitted is None:
        result.admitted = admitted


def _record_compile_failure(result: _ArmResult, reason: str) -> None:
    """Attach a failed compile or admission to the row without overwriting facts.

    `admitted` is only filled in when the arm has not already established it (a
    fired program was admitted by definition); `compile_failure_reason` keeps the
    first reason recorded. It never touches `refusal_reason`: that field is the
    guard's alone, and writing a malformed reply into it would put a compile
    failure into the guard refusal rate (issue #60).
    """
    if result.admitted is None:
        result.admitted = False
    if result.compile_failure_reason is None:
        result.compile_failure_reason = reason


def _after_fallback(agent_outcome: EpisodeOutcome) -> EpisodeOutcome:
    """The episode's outcome once the agent has taken over.

    A fallback that the agent completes is `FALLBACK`: no stored program applied,
    or the one that fired did not work, and the episode's cost is the agent's.
    If the agent itself failed — a provider error, or a step budget exhausted —
    the outcome is `FAIL`, because an episode that ended in failure must not be
    averaged in as an expected fallback.
    """
    return (
        EpisodeOutcome.FALLBACK if agent_outcome is EpisodeOutcome.SUCCESS else EpisodeOutcome.FAIL
    )


def _intent_for(fault_type: str) -> IntentSpec:
    """The ambiguous intent that makes `fault_type` measurable, or a loud refusal."""
    if fault_type in EXCLUDED_FROM_BENCHMARK:
        raise ValueError(f"fault {fault_type!r} is {_EXCLUDED_NOTICE}")
    measured = {intent.fault: intent for intent in ambiguous_intents()}
    intent = measured.get(fault_type)
    if intent is None:
        raise ValueError(
            f"fault {fault_type!r} has no registered ambiguous intent, so it cannot be "
            f"measured; measurable faults: {sorted(measured)}"
        )
    return intent


def _require_measurable(faults: list[str]) -> None:
    """Refuse a request naming an unmeasurable fault, before any episode runs."""
    for fault_type in faults:
        _intent_for(fault_type)


def _require_empty_library(root: Path, arm: Arm) -> None:
    """Each arm starts from empty, so a stale run cannot be mistaken for one.

    A library left behind by an earlier run would silently preload programs and
    change what the arm replays, so this refuses rather than merging the two.
    """
    if root.exists() and Library(root).load_all():
        raise ValueError(
            f"{root} already holds programs, but arm {arm.value!r} must start from an "
            f"empty library; remove it or choose a fresh output directory"
        )


def _episode_id(fault_type: str, seed: int, occurrence: int) -> str:
    return f"{fault_type}/seed-{seed}/occurrence-{occurrence}"


def _program_id(fault_type: str, occurrence: int, proposed: str) -> str:
    """The id a compiled program is stored under: unique to its episode.

    The model's `id` is a readability hint, not a key. Two episodes can emit the
    same slug, and `Library.add` refuses a duplicate rather than overwriting, so
    the later episode's program would be paid for and dropped -- a library whose
    growth depends on how the model happened to name things (issue #80). The
    episode's `(fault, occurrence)` pair is unique within a run -- one compile per
    episode -- so prefixing it makes the stored id unique by construction.
    `occurrence` rather than `seed` because it is the episode's identity in the
    ledger and is stable across a re-seeded run.

    The model's slug is kept as a suffix so a directory still says what it does.
    It is sanitised because it is model output used as a path component:
    `Library.add` rejects anything that is not a single component, and letting a
    stray `/` decide whether the program is stored would be the same defect in
    another form. A collision can then still occur only if one episode compiles
    twice into one library, which the runner records as a collision.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", proposed.lower()).strip("-") or "program"
    return f"{fault_type}-occ{occurrence}-{slug}"


def _invalid_record(
    arm: Arm,
    task_id: str,
    fault_type: str,
    seed: int,
    occurrence: int,
    role: OccurrenceRole,
    model: str,
    started: float,
    reason: str,
    *,
    accounting: _AccountingProvider,
    library_hash: str,
    threshold: float,
) -> EpisodeRecord:
    """The row for an episode that could not run.

    `ground_truth_ok` stays `None` — "not checked" is passed deliberately, since
    the episode never reached a state the checker could grade. The row carries
    whatever `accounting` has already seen, because an episode can become invalid
    *after* the arm ran: a `fault.check` failure happens with the solve already
    paid for, and hardcoding zero there would drop real spend from the ledger
    (spec §7, item 9: invalid episodes are "excluded from denominators but never
    hidden"). It is recorded so it appears in the denominator's own invalid rate
    rather than vanishing.

    The reason goes to `invalid_reason`, not `refusal_reason`: a sandbox that
    would not build is not a guard refusal, and putting it in the refusal field
    would inflate the safety metric (issue #60).

    The role is written even here. It is a property of the plan's seed sequence,
    knowable before any sandbox exists, so an episode that never ran still has
    one -- and leaving it off would make the row unreadable by a report that
    groups by role, which is the report's only defence against counting a repeat
    as an independent observation.
    """
    return EpisodeRecord(
        arm=arm,
        task_id=task_id,
        fault_type=fault_type,
        occurrence_index=occurrence,
        occurrence_role=role,
        seed=seed,
        tokens_in=accounting.tokens_in,
        tokens_out=accounting.tokens_out,
        cached_tokens_in=accounting.cached_tokens_in,
        llm_calls=accounting.llm_calls,
        wall_clock_s=time.monotonic() - started,
        outcome=EpisodeOutcome.INVALID,
        correct_variant=None,
        ground_truth_ok=None,
        similarity_threshold=threshold,
        library_hash=library_hash,
        invalid_reason=reason,
        model=model,
    )
