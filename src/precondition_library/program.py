"""The unit of reuse: a Program.

A Program is what the agent compiles a one-off LLM solution into. Its
preconditions are the load-bearing part of this project's claim: they are
*executable probes* over the target environment, not prose descriptions, so
deciding whether a stored program applies costs zero LLM calls and is
checkable by anyone reading the probe.

Nothing in this module may import a provider or perform I/O.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)


class Step(BaseModel):
    """One invocation of an allowlisted argv template (issue #10).

    The safe alternative to a line of a shell `body`: `template` names an entry
    in `runtime.templates.TEMPLATES`, and `args` supplies that template's
    literal arguments (e.g. a commit `message`). The bound parameters a template
    reads -- `upstream_remote`, `submodule_path` -- come from the sandbox at run
    time, not from here, and the executor builds an argv array from both and
    runs it without a shell, so no value in a step can become code. A program
    carries either `steps` or a `body`, never both.
    """

    template: str
    args: dict[str, str] = Field(default_factory=dict)


class Predicate(BaseModel):
    """An executable check over an environment.

    Used for both preconditions (may this program fire?) and postconditions
    (did it work?). Deliberately a shell probe rather than a Python callable:
    probes survive serialization into the committed library, are readable in a
    diff, and can be run by the runtime without importing program code.
    """

    name: str
    description: str
    probe: str
    """Shell command run in the environment root. Expected to be side-effect free."""
    expect_exit: int = 0
    expect_pattern: str | None = None
    """Optional regex the probe's stdout must match, read by `runtime.probes.pattern_for`:
    its `{placeholders}` are bound (regex-escaped) and POSIX classes are understood."""


class Provenance(BaseModel):
    """Where a Program came from. Required for auditing demoted programs."""

    compiled_from_task: str
    model: str
    compiler_version: str
    episode_id: str
    fault: str
    """The `FaultSpec.name` whose states this program serves.

    The load-time variant check keys on this, not on `intent`
    (`Library._reject_undeclared_variant`). `intent` is free text -- the compile
    prompt asks the model for a natural-language task, so a compiled program's
    intent is prose that matches no registry key -- while a `variant` is only
    scoreable against the intent family the fault selects. Admission is handed the
    fault by its caller; storing it on the program is what lets a load re-check
    the invariant for a `program.yaml` that never went through admission (issue
    #69)."""
    learned_on: Literal["checkout"] | None = None
    """`"checkout"` for a program learned on a user's existing repository (#188,
    ADR-0026); `None` for one compiled in the harness, which every measured program is.

    **Omitted from the serialized form when `None`** (`_omit_unset_learned_on`), so a
    harness program's canonical content -- and with it every library hash already
    recorded in a ledger -- is byte-identical to what it was before the field
    existed. A measured run refuses a frozen library holding a checkout-learned
    program (`bench.run`), because its admission was judged partly by a person rather
    than wholly by the harness."""

    @model_serializer(mode="wrap")
    def _omit_unset_learned_on(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if data.get("learned_on") is None:
            data.pop("learned_on", None)
        return data


class ProgramStatus(StrEnum):
    """Lifecycle of a stored program.

    CANDIDATE    compiled, not yet admitted to the usable library
    ADMITTED     passed the two-sided admission gate: postconditions hold on a
                 faulty sandbox and preconditions reject every negative sandbox.
                 Deliberately not called "verified" -- this project's own gate is
                 not external validation, and the word would imply an assurance
                 the gate cannot confer.
    DEMOTED      fired on a real episode and could not work: the body ran and its
                 postconditions failed, or the body named a declared parameter
                 the environment could not bind, so it never ran at all
    QUARANTINED  withdrawn from dispatch; retained for analysis, never replayed.
                 Reached by a load-time variant violation, or by two recorded
                 mismatches (spec §8)
    """

    CANDIDATE = "candidate"
    ADMITTED = "admitted"
    DEMOTED = "demoted"
    QUARANTINED = "quarantined"


class Program(BaseModel):
    """A reusable solution with an executable applicability condition."""

    id: str
    intent: str
    """Free-text statement of what this program does, e.g. 'sync the fork with upstream'.

    Prose is what the compile prompt asks for, and the hand-written gold artifacts
    happen to use the registered intent name instead; neither is load-bearing. The
    task family this program belongs to -- and therefore which `variant` ids are
    scoreable for it -- is `provenance.fault`, which is what the load-time variant
    check reads (issue #69). `_program_text` still uses this string as arm 2's
    request-side text, which is why its readability matters even though the check
    does not key on it."""
    parameters: list[str] = Field(default_factory=list)
    """Names of environment-bound values, so one program serves many repos."""
    preconditions: list[Predicate]
    body: str | None = None
    """Shell program source, for the model-compiled path. Executed by
    runtime.replay behind the guard; never executed by the compile step. A
    program carries exactly one of `body` or `steps` -- the shell path, or the
    argv-template path below."""
    steps: list[Step] | None = None
    """An argv-template program (issue #10): a list of allowlisted operations the
    runtime runs as argv arrays, without a shell. The safe alternative to a free
    shell `body` for resolutions a fixed catalogue can express; exactly one of the
    two is set."""
    postconditions: list[Predicate]
    variant: str | None = None
    """Which resolution of its intent's ambiguity this program implements.

    Required for intents with two or more resolutions: a dispatch error can only
    be defined relative to the state's correct variant, so a program that does
    not declare its variant cannot be scored. None is legitimate for intents that
    have only one resolution.
    """
    provenance: Provenance
    status: ProgramStatus = ProgramStatus.CANDIDATE

    @model_validator(mode="after")
    def _exactly_one_representation(self) -> Program:
        """A program is executed one way, so it declares one.

        Both set would let the two disagree about what the program does (and let
        a `steps` program smuggle an unscreened shell body past the runtime);
        neither set is a program with nothing to run. The runtime dispatches on
        which one is present, so the choice has to be unambiguous here."""
        has_body = self.body is not None and self.body.strip() != ""
        has_steps = bool(self.steps)
        if has_body and has_steps:
            raise ValueError("a program sets either body or steps, not both")
        if not has_body and not has_steps:
            raise ValueError("a program must set a body or steps")
        return self


class PredicateResult(BaseModel):
    """One predicate's verdict, kept individually so a failure is diagnosable."""

    name: str
    ok: bool
    observed: str = ""
    refused: bool = False
    """The probe was refused rather than evaluated -- by the guard, or because running it
    changed the sandbox (issue #10). A refused probe is reported as not holding, which is
    the shape dispatch needs; this flag keeps the two apart so a refusal can be counted
    instead of reading as an ordinary non-match."""


class GroundTruthResult(BaseModel):
    """The combined verdict of a predicate set, with no model involved."""

    ok: bool
    detail: str = ""
    predicates: list[PredicateResult] = Field(default_factory=list)

    @property
    def refusals(self) -> int:
        """How many of the predicates were refused rather than evaluated."""
        return sum(result.refused for result in self.predicates)


class EpisodeOutcome(StrEnum):
    """How the arm's mechanism completed. NOT whether the episode was correct.

    Those are different questions, and conflating them hides the failure this
    project exists to reduce: a program can fire wrongly and the episode still end
    successfully, because the wrong fire falls back to the agent. So correctness is
    recorded as facts (`EpisodeRecord.correct_variant`, `.fired_variant`,
    `.ground_truth_ok`) and the verdicts are *derived* from them -- a stored
    `mismatch` outcome could not sit in the same row as a stored success without
    the two disagreeing.

    FAIL, FALLBACK and REFUSAL all count in the metric denominators, carrying their
    token spend: an episode that crashed after 4,000 tokens still cost 4,000
    tokens, and dropping it would make amortization look better than it is. INVALID
    is the exception -- the episode never ran, so it is recorded and counted
    separately rather than averaged in (see the design spec, §7).
    """

    SUCCESS = "success"
    FAIL = "fail"
    FALLBACK = "fallback"
    """No program applicable, or the fired one failed and the agent took over.
    Expected, not a failure."""
    REFUSAL = "refusal"
    """The guard refused the generated body, so nothing executed. Kept distinct
    from FALLBACK because a high refusal rate is a safety finding, not a cost."""
    INVALID = "invalid"
    """The episode could not be graded (sandbox, checker or infrastructure
    failure). Excluded from metric denominators, reported as its own rate.

    It is not a claim that nothing was spent: a checker that raises after the arm
    ran leaves an episode that cost tokens and cannot be graded, and the row
    carries that spend rather than hiding it."""


def accepts(correct: str | None, acceptable: tuple[str, ...], fired: str) -> bool:
    """Whether firing `fired` is right: one of the acceptable resolutions (ADR-0023).

    The one rule every scorer shares -- the pair metric, the soft-vote tuning, the
    episode ledger and admission -- so they cannot disagree about what a mismatch is.
    A negative (`correct is None`) accepts nothing. An empty `acceptable` with a label
    is a record from before ADR-0023, and accepts the label alone.
    """
    if correct is None:
        return False
    return fired in acceptable if acceptable else fired == correct
