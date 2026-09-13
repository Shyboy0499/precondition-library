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

from pydantic import BaseModel, Field


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
    """Optional regex the probe's stdout must match."""


class Provenance(BaseModel):
    """Where a Program came from. Required for auditing demoted programs."""

    compiled_from_task: str
    model: str
    compiler_version: str
    episode_id: str


class ProgramStatus(StrEnum):
    """Lifecycle of a stored program.

    CANDIDATE    compiled, not yet admitted to the usable library
    ADMITTED     passed the two-sided admission gate: postconditions hold on a
                 faulty sandbox and preconditions reject every negative sandbox.
                 Deliberately not called "verified" -- this project's own gate is
                 not external validation, and the word would imply an assurance
                 the gate cannot confer.
    DEMOTED      fired on a real episode and its postconditions failed
    QUARANTINED  withdrawn from dispatch; retained for analysis, never replayed
    """

    CANDIDATE = "candidate"
    ADMITTED = "admitted"
    DEMOTED = "demoted"
    QUARANTINED = "quarantined"


class Program(BaseModel):
    """A reusable solution with an executable applicability condition."""

    id: str
    intent: str
    """Natural-language statement of what this program does, e.g. 'sync fork with upstream'."""
    parameters: list[str] = Field(default_factory=list)
    """Names of environment-bound values, so one program serves many repos."""
    preconditions: list[Predicate]
    body: str
    """Program source. Executed by runtime.replay; never executed by the compile step."""
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

    def applicable(self, env) -> bool:
        """True when every precondition holds. Runs probes only, no LLM."""
        raise NotImplementedError("implemented per plan: phases 2-3")


class PredicateResult(BaseModel):
    """One predicate's verdict, kept individually so a failure is diagnosable."""

    name: str
    ok: bool
    observed: str = ""


class GroundTruthResult(BaseModel):
    """The combined verdict of a predicate set, with no model involved."""

    ok: bool
    detail: str = ""
    predicates: list[PredicateResult] = Field(default_factory=list)


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
    """The episode could not run (sandbox or infrastructure failure). Excluded
    from metric denominators, reported as its own rate."""
