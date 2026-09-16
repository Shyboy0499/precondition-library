"""The compile step: a solved task becomes a reusable Program.

This is where the LLM writes code that will later run unattended, so it is also
the project's main safety surface. Two defences live here:

* The compile step never executes what it generates. Execution is `runtime`'s
  job, on a throwaway sandbox, behind `runtime.guard`. `compile_program` only
  reads the task, the solution transcript and the state observations, and its
  whole output is data.
* Admission is a two-sided test, not a happy path. A program must satisfy its
  postconditions on a freshly faulted sandbox *and* have its preconditions
  reject negative sandboxes. Preconditions that accept everything are treated
  as a defect — such a program would fire on unrelated states, which is exactly
  the mismatch failure this project measures.

A malformed reply is a failed compile, recorded as a `CompileResult`, not an
exception: the reply cost tokens, and losing the episode's cost to a traceback
would corrupt the ledger's denominator.
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from .. import __version__
from ..program import Program, ProgramStatus, Provenance
from ..provider import Provider, TokenUsage
from ..runtime.probes import evaluate_preconditions
from ..runtime.replay import replay
from ..sandbox import create
from ..tasks.faults import FAULTS
from ..tasks.registry import ambiguous_intents
from ..tasks.spec import FaultSpec

SYSTEM_PROMPT = """\
You compile a solved git maintenance task into a reusable program.

You are given the user's request, the observable state of the repository when
the request arrived, and a transcript of how an agent solved it. Turn that
one-off solution into a program that can be replayed later on a different
repository without any model call.

Reply with a single YAML document and nothing else. It must have exactly these
keys:

id: a short lowercase slug, dashes not spaces
intent: the natural-language task this program implements
variant: __VARIANT_RULE__
parameters: the environment-bound names used in `{placeholders}`; the runtime
  supplies work_dir, upstream_remote, upstream_branch and submodule_path.
  submodule_path is bound only where the repository declares a submodule; on a
  repository with none, a precondition that uses it does not hold rather than
  failing loudly, so it is safe to write one that needs it.
preconditions: executable shell probes that are ALL run before the program may
  fire. Each has name, description, probe, and optionally expect_exit and
  expect_pattern. A precondition must be SPECIFIC: one that accepts every
  possible repository state is a defect, not a convenience, because the program
  would then fire on unrelated states. Never return an empty precondition list.
body: the shell commands that do the work, using the `{placeholders}`
postconditions: executable shell probes that must hold after the body runs

Rules:
- Write probes and commands for `bash -c`, run in the repository root.
- `{name}` is substituted with a bound value; a placeholder with no binding
  makes the program unreplayable, so use only the parameters above.
- Your output is data. Do not try to run it, and do not include `provenance` or
  `status`: the caller sets both.
"""

_VARIANT_RULE_SINGLE = "which resolution of the request it implements, or null if there is only one"
_VARIANT_RULE_MULTI = (
    "which resolution of the request it implements. This intent has more than one "
    "correct resolution and the request text does not say which; it must be exactly "
    "one of these ids: {ids}"
)


def _system_prompt(variant_ids: list[str] | None) -> str:
    """The compile prompt, told which variant ids this intent will accept.

    A model that emits `variant: null` for an ambiguous intent produces a program
    that cannot be scored (`Program.variant`) and, before admission checked this,
    could fire wrongly while the ledger recorded no fire at all. Naming the ids
    in the prompt is the cheap half of that fix; `admit` is the enforcing half.
    """
    rule = (
        _VARIANT_RULE_MULTI.format(ids=", ".join(variant_ids))
        if variant_ids
        else _VARIANT_RULE_SINGLE
    )
    return SYSTEM_PROMPT.replace("__VARIANT_RULE__", rule)


_EMPTY_PRECONDITIONS = (
    "the reply had an empty precondition list; a program whose preconditions accept "
    "every state is a defect, and admission's negative side must reject it"
)

_NEGATIVE_SEED = 0
"""The one seed each unrelated fault is injected at for the negative side.

Fixed rather than sampled so the gate's verdict is reproducible: a gate whose
verdict flickers would make every downstream comparison meaningless.
"""


class CompileResult(BaseModel):
    """The outcome of one compile, including its cost whether or not it parsed.

    `ok=False` is a recorded failure, not a traceback: the caller still gets the
    token usage and the reason, because an episode whose compile failed still
    spent what it spent. `program` is set only when `ok`.
    """

    ok: bool
    program: Program | None = None
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)
    """Defects that did not stop the parse. An empty precondition list lands here
    rather than in `reason`: the reply is a valid `Program`, but one admission's
    negative side exists to reject."""
    usage: TokenUsage


def compile_program(
    signature,
    env,
    transcript: list[dict],
    provider: Provider,
    *,
    variant_ids: list[str] | None = None,
) -> CompileResult:
    """Ask the model for intent, parameters, preconditions, body, postconditions.

    The return is a CANDIDATE on success; nothing becomes replayable until
    `admit` passes. The model never sees a command's result from here: the prompt
    carries the transcript of the *solution* episode, already executed, and this
    function runs nothing itself.

    `variant_ids` is the ambiguous intent's declared resolution ids, when the
    caller knows them. They are put in the prompt so the model is told what it
    must emit; a caller that omits them (an intent with one resolution) gets the
    generic rule.

    A reply that is not a valid `Program` becomes `CompileResult(ok=False)`. The
    caller can record the episode's cost and reason either way.
    """
    payload = {
        "task": signature.intent,
        "state_at_arrival": signature.fingerprint.model_dump(mode="json"),
        "environment": signature.target,
        "solution_transcript": transcript,
    }
    completion = provider.complete(
        system=_system_prompt(variant_ids),
        messages=[{"role": "user", "content": json.dumps(payload, indent=2, default=str)}],
    )

    document = _parse_document(completion.text)
    if document is None:
        return CompileResult(
            ok=False,
            reason="the reply was not a YAML mapping, so it is not a Program",
            usage=completion.usage,
        )

    # Authoritative provenance and status replace anything the model sent: a
    # model-authored `status: admitted` would claim a gate result that never ran,
    # and the audit trail has to name the model and episode that really produced
    # this program.
    document.pop("provenance", None)
    document["status"] = ProgramStatus.CANDIDATE.value
    document["provenance"] = Provenance(
        compiled_from_task=signature.intent,
        model=completion.model,
        compiler_version=__version__,
        episode_id=f"{signature.intent}/{env.root.name}",
    ).model_dump(mode="json")

    try:
        program = Program.model_validate(document)
    except ValidationError as exc:
        return CompileResult(
            ok=False,
            reason=f"the reply did not validate as a Program: {exc.error_count()} error(s), "
            f"first: {exc.errors()[0]['loc']}: {exc.errors()[0]['msg']}",
            usage=completion.usage,
        )

    warnings = [_EMPTY_PRECONDITIONS] if not program.preconditions else []
    return CompileResult(ok=True, program=program, warnings=warnings, usage=completion.usage)


def admit(program: Program, fault: FaultSpec | str, *, seeds: list[int]) -> tuple[bool, str]:
    """Two-sided admission gate.

    Positive side: the program must fix the fault on fresh sandboxes. Each seed
    in `seeds` builds a sandbox injected with `fault`, the body is replayed, and
    the program's own postconditions must hold. Failure means not admitted.

    Negative side: on sandboxes in unrelated states the preconditions must
    reject the program. The unrelated states come from the *other* faults'
    injectors -- that is what they exist for -- at one fixed seed each, so the
    verdict is reproducible. A program whose preconditions accept an unrelated
    state is not admitted, because it would fire there for real.

    A program is also rejected before any sandbox runs unless its `variant` is
    one of the ambiguous intent's declared ids. The ledger's `misfired` is
    `fired_variant is not None and fired_variant != correct_variant`, so a
    program that fires with `variant: null` records `fired_variant=None` -- which
    the ledger documents as "none fired" -- and counts as no miss. A program the
    model mislabels under a declared id would likewise be scored against the
    wrong resolution. Requiring a declared id is what makes the invariant
    `fired_variant is not None` imply a real variant, and the ledger's mismatch
    numerator rests on it. An intent with a single resolution has no declared
    ambiguity to check, so its programs are not constrained here.

    Returns `(admitted, reason)` so a rejection is reported rather than silently
    dropped — rejected programs are data for the mismatch analysis.
    """
    name = fault.name if isinstance(fault, FaultSpec) else fault
    if name not in FAULTS:
        raise ValueError(f"unknown fault {name!r}; known: {sorted(FAULTS)}")
    if not seeds:
        raise ValueError(
            "admission needs at least one positive seed; with none the positive side "
            "would pass vacuously and admit an unexecuted program"
        )

    declared = _declared_variant_ids(name)
    if declared is not None and program.variant not in declared:
        return False, (
            f"rejected before any sandbox: the intent for {name!r} is ambiguous and "
            f"declares variant id(s) {sorted(declared)}, but the program declares "
            f"{program.variant!r}; without a declared variant a wrong fire would be "
            f"recorded as no fire at all"
        )

    for seed in seeds:
        box = create(seed, [name])
        try:
            result = replay(program, box)
        except KeyError as exc:
            # A body or postcondition naming a parameter the sandbox cannot bind
            # is a compile defect, not a crash: report it as a rejection.
            return False, f"positive side failed: unbound placeholder in the program ({exc})"
        finally:
            box.destroy()
        if not result.ok:
            detail = result.reason or "the replay did not satisfy its contract"
            return False, f"positive side failed on {name} seed {seed}: {detail}"

    unrelated = sorted(set(FAULTS) - {name})
    if not unrelated:
        raise ValueError(f"no unrelated faults exist to test {name!r} against")

    for other in unrelated:
        box = create(_NEGATIVE_SEED, [other])
        try:
            accepted = _preconditions_hold(program, box)
        except KeyError as exc:
            return False, f"negative side failed: preconditions could not be evaluated ({exc})"
        finally:
            box.destroy()
        if accepted:
            return False, (
                f"negative side failed: preconditions accepted an unrelated state "
                f"({other} seed {_NEGATIVE_SEED}); a precondition set that accepts "
                f"unrelated states is a defect"
            )

    return True, (
        f"admitted: postconditions held on {len(seeds)} freshly faulted sandbox(es); "
        f"preconditions rejected {len(unrelated)} unrelated state(s)"
    )


def _declared_variant_ids(fault_name: str) -> set[str] | None:
    """The variant ids an ambiguous intent declares for `fault_name`, else None.

    None means "no ambiguous intent is registered for this fault", so there is no
    declared set to validate against; it is not the same as an empty set, which
    would reject every program. The registry is the one place that decides which
    intents are ambiguous, so admission reads it rather than re-deriving the list.
    """
    intent = next((item for item in ambiguous_intents() if item.fault == fault_name), None)
    return None if intent is None else {variant.id for variant in intent.variants}


def _preconditions_hold(program: Program, env) -> bool:
    """Whether every precondition accepts `env`. Runs probes only, no model.

    Delegates to `runtime.probes.evaluate_preconditions`, which is also what arm
    3's matcher calls, so admission and dispatch cannot disagree about what "the
    preconditions held" means. Only the boolean is used here; the `detail` and
    per-predicate results belong to a dispatch rejection.
    """
    return evaluate_preconditions(program, env).ok


def _parse_document(text: str) -> dict[str, Any] | None:
    """The YAML mapping in `text`, or None when there is not one.

    Fenced replies are unwrapped because a model asked for "a YAML document"
    often wraps it in a markdown fence anyway. Any parse error or non-mapping
    top level returns None so the caller records a failed compile rather than
    raising.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines)
    try:
        document = yaml.safe_load(stripped)
    except yaml.YAMLError:
        return None
    return document if isinstance(document, dict) else None
