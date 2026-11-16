"""Arm 2's baseline floor (spec §7 item 11): can a scorer pick the right resolution at all?"""

from __future__ import annotations

from pydantic import BaseModel

from precondition_library.experiment.report.stats import wilson_interval

ARM2_CANDIDATES_PER_DECISION = 3


"""Candidate resolutions per ambiguous intent, so a random dispatcher's strict top-1 is 1/3.

Both measurable intents declare three variants. A tie counts as no decision
(`bench.similarity_probe.top1_accuracy`), so chance is at most 1/3, not above it.
"""


class BaselineFloor(BaseModel):
    """Whether arm 2's measured baseline clears the pre-registered floor (spec §7 item 11).

    Carries the counts and the bound it was judged on, because "usable" without them says
    nothing: 13/24 clears the floor and 12/24 does not, and a reader has to be able to see which.
    """

    decided: int
    decidable: int
    chance: float
    lower_bound: float | None
    usable: bool
    reason: str


def arm2_baseline_floor(
    decided: int, decidable: int, *, candidates: int = ARM2_CANDIDATES_PER_DECISION
) -> BaselineFloor:
    """Whether arm 2's strict top-1 is distinguishable from chance (issue #116, ADR-0007).

    The floor is the 95% Wilson interval's **lower bound** exceeding chance (`1/candidates`),
    not the point estimate exceeding it: at 24 decidable pairs a point estimate one pair above
    chance (9/24) is noise, and a comparison against it is a comparison against a coin flip.
    The counts are the informed regime's strict top-1 **on the tune set, against the library
    the eval dispatches with**, measured before any eval episode
    (`bench.similarity_probe.tune_baseline`).

    Below the floor, arm 2 is not a usable baseline, so a report may not say that precondition
    dispatch beats text similarity; it reports the comparison with the floor's verdict beside it
    rather than dropping it. No decidable pair at all is not usable either: there is nothing
    to have measured.
    """
    if candidates < 2:
        raise ValueError(f"a decision needs at least two candidates, got {candidates}")
    chance = 1.0 / candidates
    interval = wilson_interval(decided, decidable)
    if interval is None:
        return BaselineFloor(
            decided=decided,
            decidable=decidable,
            chance=chance,
            lower_bound=None,
            usable=False,
            reason="no decidable pair was measured, so there is no baseline to judge",
        )
    usable = interval.low > chance
    reason = (
        f"strict top-1 {decided}/{decidable}: the 95% Wilson lower bound {interval.low:.3f} "
        + (
            f"exceeds chance {chance:.3f}, so arm 2 is a usable baseline"
            if usable
            else f"does not exceed chance {chance:.3f}, so arm 2 is not a usable baseline and "
            f"a win over it is not a win over text similarity"
        )
    )
    return BaselineFloor(
        decided=decided,
        decidable=decidable,
        chance=chance,
        lower_bound=interval.low,
        usable=usable,
        reason=reason,
    )
