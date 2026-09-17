"""The episode ledger: one JSONL line per episode, the raw material of the result.

Every number in the write-up is a grouping over this file, so it records more
than the headline metric. In particular `cached_tokens_in` is kept separate
from `tokens_in` because provider-side prompt caching can make the ReAct
baseline look cheaper than the work it performed, and that would quietly
flatter whichever arm benefits most. Dispatch-tuning parameters are recorded
per episode too, so a reviewer can tell a tuned comparison from an untuned one.

Nothing in this module computes results; that is `bench.report`'s job.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ..program import EpisodeOutcome


class Arm(StrEnum):
    """The three conditions. Each builds its own library from an empty start."""

    REACT = "react"
    SEMANTIC = "semantic"
    PRECONDITION = "precondition"


class EpisodeRecord(BaseModel):
    """One episode. Fields are flat on purpose: the ledger must stay greppable."""

    arm: Arm
    task_id: str
    fault_type: str
    occurrence_index: int
    """1 for the first time this fault type is seen, 2 for the second, and so on.
    Grouping by this field is what produces the cost-vs-repeat curve."""
    seed: int

    tokens_in: int
    tokens_out: int
    cached_tokens_in: int = 0
    llm_calls: int
    wall_clock_s: float

    outcome: EpisodeOutcome
    """How the arm's mechanism completed. See `EpisodeOutcome`: this is not
    whether the episode was correct, which is derived from the facts below."""

    correct_variant: str | None
    """Ground truth: the resolution this state requires, or None if it is benign.
    Defined by the intent's decision rules, in separate code from the programs'
    probe strings, so a wrong precondition cannot make its own program look right.

    Required, with no default, because None is a meaningful answer ("this state
    needs nothing done"). A defaulted field could be forgotten and silently read
    as a benign state, which would turn a missing fact into a wrong one."""
    fired_variant: str | None = None
    """The resolution the program that actually ran implements; None if none fired."""
    ground_truth_ok: bool | None
    """Whether the environment reached the expected state, checked by git alone.
    None means it was not checked, which happens only for INVALID episodes.
    Also required: "not checked" must be passed deliberately, never inherited."""

    program_id: str | None = None
    dispatch_score: float | None = None
    """Similarity score for arm 2; None for the other arms."""
    similarity_threshold: float | None = None
    """Arm 2's inclusive similarity floor as configured for this episode.

    Recorded per row so an untuned run is distinguishable from a tuned one: the
    pre-registration has the threshold calibrated on the held-out tune set, and a
    reader can see from the ledger alone whether that calibration happened rather
    than inferring it from the code's default."""
    library_hash: str | None = None
    """The digest of the arm's library as this episode found it (`Library.library_hash`).

    Each arm grows its own library, so an arm-2-versus-arm-3 difference is
    confounded with a library difference. Recording the digest per row makes that
    confound visible rather than silent; removing it is a harness change tracked
    separately (issue #4)."""
    admitted: bool | None = None
    refusal_reason: str | None = None
    """Why the guard refused the generated body. Set only when `outcome` is
    `EpisodeOutcome.REFUSAL`; every other degradation has its own field below.

    Kept apart from compile failures because `refusal` is a safety signal
    (spec §7 reports the guard refusal rate as a secondary metric): a rate read
    off this field alone must not pick up a malformed model reply that no guard
    ever saw. Issue #60 found a merged-run row with `outcome: fallback` and a
    `refusal_reason` holding "the reply was not a YAML mapping" -- a compile
    failure wearing the safety metric's name."""
    compile_failure_reason: str | None = None
    """Why a compile or admission produced no usable program: a malformed reply,
    a validation failure, a rejected gate, a duplicate id.

    Set on a row where the arm had to solve and no program came out of it, and
    never on a row whose only degradation is a guard refusal. It is a
    compile-quality signal, not a safety one."""
    invalid_reason: str | None = None
    """Why the episode could not be graded (a sandbox, checker or other
    infrastructure failure). Set only when `outcome` is `EpisodeOutcome.INVALID`,
    so the invalid rate is a grouping over that outcome rather than over a text
    field shared with refusals."""
    replay_failure_reason: str | None = None
    """Why a program that fired could not be run at all (issue #76).

    Today the one cause is a body naming a declared parameter this environment
    cannot bind, so no command executed and there is no postcondition evidence.
    Distinct from a body that ran and failed its postconditions, which leaves the
    demotion and the postcondition results rather than this field, and distinct
    from a guard refusal, which has `refusal_reason`. The guard refusal rate is a
    grouping over that field alone, so a replay failure must not be written
    there — the defect issue #60 fixed."""
    timed_out: bool = False
    """Set when a replay exceeded its timeout. Kept beside `outcome` rather than
    folded into it, since a timeout is a failure mode of the runtime while
    `outcome` describes how the episode ended."""

    model: str
    """Exact model identifier used for this episode. Provider-side model drift
    mid-experiment silently invalidates a comparison, so it is recorded per
    episode and a version change invalidates the affected run."""

    @property
    def misfired(self) -> bool:
        """A program fired that was not the ground-truth resolution.

        Deliberately independent of final state, and of `outcome`: a wrong fire
        often ends in a successful episode because the arm falls back to the agent.
        That quadrant -- misfired and successful -- is the one the primary metric
        exists to count, and a single `outcome` value could not express it.
        """
        return self.fired_variant is not None and self.fired_variant != self.correct_variant

    @property
    def succeeded(self) -> bool:
        """Whether the episode reached the expected state. Separate from `misfired`."""
        return self.ground_truth_ok is True


class LedgerCorruptError(ValueError):
    """A ledger line could not be parsed back into an episode.

    Dedicated so a caller can tell a corrupt ledger from a missing file: a
    missing ledger raises `FileNotFoundError`, this raises for a ledger that
    exists but has a line that is not a record. It is never raised for a *skip*;
    the alternative -- dropping the line and returning the rest -- would remove
    an episode from every denominator silently, which is the accounting this
    module exists to keep intact.
    """


def append(path: Path, record: EpisodeRecord) -> None:
    """Append one episode. Must be crash-safe: a killed run should still leave
    every completed episode on disk, since episodes are expensive to reproduce.

    Serialisation is pydantic's own (`model_dump_json`), so enums and `None`
    round-trip and the line stays flat and greppable. The line is written and
    flushed to the operating system before this returns: a write still sitting
    in Python's buffer when the process dies would lose an episode that was
    reported as recorded, which is the one failure this file cannot absorb.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json())
        handle.write("\n")
        handle.flush()


def read(path: Path) -> list[EpisodeRecord]:
    """Read the ledger back. Malformed trailing lines are reported, not skipped.

    A missing file is left to raise `FileNotFoundError`. Any line that is not a
    record raises `LedgerCorruptError`, naming the line number and its content:
    the realistic cause is a crash mid-write, which tears only the last line and
    leaves every complete record above it intact. The list is returned whole or
    not at all -- a partial list would silently shrink the denominators.
    """
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        # The file ends with a newline, so the final split element is the
        # empty string after it, not a line.
        lines.pop()
    records: list[EpisodeRecord] = []
    for number, line in enumerate(lines, start=1):
        try:
            records.append(EpisodeRecord.model_validate_json(line))
        except (ValidationError, json.JSONDecodeError) as error:
            raise LedgerCorruptError(
                f"{path}: line {number} is not a valid episode record, so the ledger "
                f"is torn at that point. This is what a crash mid-write leaves behind: "
                f"the {number - 1} complete record(s) above it are intact and readable. "
                f"Line content: {line!r}"
            ) from error
    return records
