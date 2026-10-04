"""Learn a program on an existing checkout: solve a copy, confirm, compile, admit (#188).

ADR-0026 is the design; this is its implementation, step by step:

1. **Solve a disposable copy.** The checkout is opened (`checkout.open_checkout`, with
   the trusted pre-fetch) and copied (`checkout.snapshot`). The ReAct agent solves the
   copy, its git screened, confined and redirected so no real remote is reachable
   (#196). The checkout itself is never the solve's working directory.
2. **Confirm.** If the agent declared the task done, the caller is shown what the solve
   did to the copy -- the commits it added, the working tree it left, which parts of the
   repository moved -- and must confirm it is what they wanted. Nothing is compiled
   without that.
3. **Compile.** `agents.compile.compile_program` turns the solve into a candidate, as in
   the harness, told the family's declared resolutions.
4. **Fire where it was learned.** On a fresh copy of the checkout, as it was before the
   solve, every precondition must hold and replaying the program must satisfy its
   postconditions.
5. **Pass the harness gate unchanged.** `agents.compile.admit`, two-sided, on harness
   sandboxes of the named family, at a seed whose injected state is the program's own
   resolution -- the positive side the harness gives a program compiled there.
6. **Store it, marked.** The program is written to the caller's library as admitted,
   with `Provenance.learned_on = "checkout"`, which keeps it out of any measured run.

Each step that stops says why in `LearnOutcome.stopped`; nothing after it runs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from .agents.compile import admit, compile_program
from .agents.react import solve
from .checkout import open_checkout, snapshot
from .library import Library, ProgramIdCollisionError
from .program import EpisodeOutcome, Program, ProgramStatus
from .provider import Provider
from .runtime.probes import evaluate_preconditions, sandbox_state
from .runtime.replay import replay
from .sandbox import Sandbox, run_git
from .signatures import StateFingerprint, TaskSignature
from .tasks.faults import FAULTS
from .tasks.registry import ambiguous_intents

SOLVE_COPY = "solve"
"""The scratch copy the agent solves in."""
HERE_COPY = "fires-here"
"""The fresh copy, as the checkout was before the solve, that the program must fire on."""
ADMIT_SEED_SEARCH = 200
"""How many harness seeds are searched for one whose state is the program's resolution."""


class SolveEffect(BaseModel):
    """What the agent's solve did to its copy of the checkout -- what the user confirms."""

    head_before: str
    head_after: str
    commits: list[str]
    """`git log --oneline` of what the solve added to HEAD, newest first."""
    status: str
    """`git status --short` after the solve: what it left uncommitted."""
    changed: list[str]
    """Which parts of the repository moved (`runtime.probes.sandbox_state`'s parts)."""


class LearnOutcome(BaseModel):
    fault: str
    request: str
    solve: str
    """The agent's outcome (`EpisodeOutcome`); only `success` -- it declared done -- goes on."""
    tool_calls: int
    effect: SolveEffect | None = None
    confirmed: bool = False
    program_id: str | None = None
    variant: str | None = None
    gate_reason: str | None = None
    admitted: bool = False
    stopped: str | None = None
    """Why learning stopped before storing a program; `None` when one was admitted."""


Confirm = Callable[[SolveEffect], bool]
"""Shown the solve's effect on the copy; returns whether it is what the user wanted."""


def _intent_names(fault: str) -> list[str]:
    for intent in ambiguous_intents():
        if intent.fault == fault:
            return [variant.id for variant in intent.variants]
    families = sorted(intent.fault for intent in ambiguous_intents())
    raise ValueError(f"unknown family {fault!r}; a program can be learned for one of {families}")


def _head(work: Path) -> str:
    return run_git(("rev-parse", "HEAD"), cwd=work).stdout.strip()


def _effect(copy: Sandbox, before: dict[str, str], head_before: str) -> SolveEffect:
    after = sandbox_state(copy)
    head_after = _head(copy.work)
    commits = run_git(
        ("log", "--oneline", f"{head_before}..{head_after}"), cwd=copy.work, check=False
    ).stdout.splitlines()
    return SolveEffect(
        head_before=head_before,
        head_after=head_after,
        commits=commits,
        status=run_git(("status", "--short"), cwd=copy.work).stdout,
        changed=[name for name in before if before[name] != after.get(name)],
    )


def _tool_calls(transcript: list[dict]) -> int:
    return sum(1 for e in transcript if e.get("role") == "tool" and not e.get("not_run"))


def admission_seed(fault: str, variant: str | None) -> int | None:
    """The first harness seed whose injected state is `variant`'s, or `None` if none is.

    The harness admits a compiled program at the seed it was compiled from. A program
    learned on a checkout has no seed, so it is given the first one whose state is its own
    resolution -- the same positive side, at the state the program claims to fix.
    """
    spec = FAULTS[fault]
    for seed in range(ADMIT_SEED_SEARCH):
        if variant is not None and spec.variant_for_seed(seed) == variant:
            return seed
    return None


def _store(library_root: Path, program: Program) -> str:
    """Write `program` to the caller's library as admitted, renaming it on an id collision."""
    library = Library(library_root)
    candidate = program.model_copy(update={"status": ProgramStatus.CANDIDATE})
    base, suffix = candidate.id, 1
    while True:
        try:
            library.add(candidate)
            break
        except ProgramIdCollisionError:
            suffix += 1
            candidate = candidate.model_copy(update={"id": f"{base}-{suffix}"})
    library.set_status(
        candidate.id, ProgramStatus.ADMITTED, episode_id=candidate.provenance.episode_id
    )
    return candidate.id


def learn(
    library_root: Path,
    work: Path,
    *,
    request: str,
    fault: str,
    provider: Provider,
    confirm: Confirm,
    fetch: bool = True,
    scratch: Path | None = None,
) -> LearnOutcome:
    """Learn a program for `request` on the checkout `work`, into `library_root` (ADR-0026)."""
    variant_ids = _intent_names(fault)
    env = open_checkout(work, fetch=fetch, scratch=scratch)
    try:
        copy = snapshot(env, SOLVE_COPY)
        signature = TaskSignature(
            intent=request, fingerprint=StateFingerprint.observe(copy), target=str(copy.work)
        )
        before, head_before = sandbox_state(copy), _head(copy.work)
        outcome, transcript = solve(signature, copy, provider)
        result = LearnOutcome(
            fault=fault, request=request, solve=outcome.value, tool_calls=_tool_calls(transcript)
        )
        if outcome is not EpisodeOutcome.SUCCESS:
            result.stopped = "the agent did not declare the task done, so there is nothing to learn"
            return result

        result.effect = _effect(copy, before, head_before)
        result.confirmed = confirm(result.effect)
        if not result.confirmed:
            result.stopped = (
                "not confirmed: the solve is not what was wanted, so nothing is learned"
            )
            return result

        compiled = compile_program(
            signature, copy, transcript, provider, fault=fault, variant_ids=variant_ids
        )
        if not compiled.ok or compiled.program is None:
            result.stopped = f"the compile failed: {compiled.reason}"
            return result
        provenance = compiled.program.provenance.model_copy(update={"learned_on": "checkout"})
        program = compiled.program.model_copy(update={"provenance": provenance})
        result.program_id, result.variant = program.id, program.variant

        here = snapshot(env, HERE_COPY)
        holds = evaluate_preconditions(program, here)
        if not holds.ok:
            result.stopped = (
                f"its preconditions do not hold on the checkout it was learned on: {holds.detail}"
            )
            return result
        replayed = replay(program, here)
        if not replayed.ok:
            result.stopped = (
                f"replaying it on a fresh copy of the checkout failed: {replayed.reason}"
            )
            return result

        seed = admission_seed(fault, program.variant)
        if seed is None:
            result.stopped = (
                f"the harness has no {fault} state whose resolution is {program.variant!r}, so "
                f"the gate has no positive side to run"
            )
            return result
        admitted, reason = admit(program, fault, seeds=[seed])
        result.gate_reason = reason
        if not admitted:
            result.stopped = f"the harness gate rejected it: {reason}"
            return result

        result.program_id = _store(library_root, program)
        result.admitted = True
        return result
    finally:
        env.destroy()


def render_effect(effect: SolveEffect) -> str:
    """The solve's effect as text a person reads before confirming it."""
    lines = [
        f"the agent's solve, on a copy: HEAD {effect.head_before[:12]} -> {effect.head_after[:12]}"
    ]
    lines += [f"  + {commit}" for commit in effect.commits]
    lines.append("  changed: " + (", ".join(effect.changed) if effect.changed else "nothing"))
    if effect.status.strip():
        lines.append("  left uncommitted:")
        lines += [f"    {line}" for line in effect.status.splitlines()]
    return "\n".join(lines) + "\n"


def render(outcome: LearnOutcome) -> str:
    """The outcome as text."""
    lines = [
        f"family: {outcome.fault}; request: {outcome.request}",
        f"solve: {outcome.solve} after {outcome.tool_calls} tool call(s)",
    ]
    if outcome.program_id:
        lines.append(f"program: {outcome.program_id} [{outcome.variant or '-'}]")
    if outcome.admitted:
        lines.append(
            f"ADMITTED into the library, marked learned on a checkout: {outcome.gate_reason}"
        )
    else:
        lines.append(f"not learned: {outcome.stopped}")
    return "\n".join(lines) + "\n"
