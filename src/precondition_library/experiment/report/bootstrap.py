"""The instance-clustered bootstrap over replicate ledgers."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from precondition_library.experiment.ledger import Arm, EpisodeRecord, OccurrenceRole, read
from precondition_library.experiment.report.stats import Interval, Rate
from precondition_library.experiment.report.tables import _graded

BOOTSTRAP_RESAMPLES = 2000


"""Cluster-bootstrap resamples. Enough that the 2.5th/97.5th percentiles are stable to
about a point; the RNG is seeded, so the interval reproduces exactly."""


BOOTSTRAP_SEED = 0


"""The bootstrap's RNG seed: fixed, so a rerun of the report gives the same interval."""


class ClusterBootstrap(BaseModel):
    """Arm 2 minus arm 3 per-fire mismatch, with an instance-clustered interval.

    Issue #6's seed-level uncertainty, computed by resampling instances rather than by
    fitting a mixed model (ADR-0012). Every count the numbers rest on is carried, so a
    reader can see how many instances -- not rows -- the interval stands on.
    """

    clusters: int
    """Instances (fault + drawn identity) contributing at least one row: the unit resampled."""
    rows: int
    replicates: int
    arm2_mismatch: Rate
    arm3_mismatch: Rate
    difference: float | None
    """Arm 2's per-fire mismatch minus arm 3's; positive means arm 3 mis-fires less."""
    interval: Interval | None
    resamples: int
    skipped: int
    """Resamples in which an arm fired nothing, so the difference was undefined."""
    note: str


def read_replicates(ledgers: Iterable[Path]) -> list[EpisodeRecord]:
    """Every row of every replicate's ledger (`bench.run.run_replicates`), in order."""
    return [record for ledger in ledgers for record in read(ledger)]


def _instance_key(record: EpisodeRecord) -> tuple[str, str]:
    """The environment a row ran in: the unit of analysis since ADR-0005."""
    from precondition_library.tasks.faults import FAULTS

    spec = FAULTS.get(record.fault_type)
    identity = spec.instance_for_seed(record.seed) if spec is not None else None
    return record.fault_type, identity if identity is not None else f"seed-{record.seed}"


def _per_fire(records: Iterable[EpisodeRecord]) -> Rate:
    fires = [record for record in records if record.fired_variant is not None]
    return Rate(numerator=sum(record.misfired for record in fires), denominator=len(fires))


def cluster_bootstrap(
    records: Iterable[EpisodeRecord],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.95,
) -> ClusterBootstrap:
    """Arm 2 vs arm 3 per-fire mismatch with an interval clustered on the instance.

    Issue #6 asks for seed-level uncertainty; ADR-0012 computes it by **resampling whole
    instances with replacement**, each carrying all its rows across every replicate, and
    taking the percentile interval of the difference. Rows of one instance -- the two
    arms, and every replicate of each -- move together, so repeats can never be counted
    as independent observations, which is the pseudo-replication #6 exists to prevent.

    Over graded variant rows of the two dispatch arms, as `mismatch_comparison` is:
    a replay re-asks a state an earlier occurrence introduced. A resample in which an arm
    fired nothing has no per-fire mismatch; it is skipped and counted, never scored 0.
    """
    if resamples < 1:
        raise ValueError(f"resamples must be at least 1, got {resamples}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    rows = [
        record
        for record in _graded(records)
        if record.arm in (Arm.SEMANTIC, Arm.PRECONDITION)
        and record.occurrence_role is OccurrenceRole.VARIANT
    ]
    clusters: dict[tuple[str, str], list[EpisodeRecord]] = {}
    for record in rows:
        clusters.setdefault(_instance_key(record), []).append(record)
    keys = sorted(clusters)

    def difference(sample: list[tuple[str, str]]) -> float | None:
        chosen = [record for key in sample for record in clusters[key]]
        arm2 = _per_fire(r for r in chosen if r.arm is Arm.SEMANTIC).value
        arm3 = _per_fire(r for r in chosen if r.arm is Arm.PRECONDITION).value
        return None if arm2 is None or arm3 is None else arm2 - arm3

    rng = random.Random(seed)
    draws: list[float] = []
    skipped = 0
    if keys:
        for _ in range(resamples):
            value = difference([rng.choice(keys) for _ in keys])
            if value is None:
                skipped += 1
            else:
                draws.append(value)
    draws.sort()
    interval: Interval | None = None
    if draws:
        tail = (1.0 - confidence) / 2.0
        low = draws[int(math.floor(tail * len(draws)))]
        high = draws[min(len(draws) - 1, int(math.ceil((1.0 - tail) * len(draws))) - 1)]
        interval = Interval(low=low, high=high)

    return ClusterBootstrap(
        clusters=len(keys),
        rows=len(rows),
        replicates=len({record.replicate for record in rows}),
        arm2_mismatch=_per_fire(r for r in rows if r.arm is Arm.SEMANTIC),
        arm3_mismatch=_per_fire(r for r in rows if r.arm is Arm.PRECONDITION),
        difference=difference(keys),
        interval=interval,
        resamples=resamples,
        skipped=skipped,
        note=(
            f"{confidence:.0%} percentile interval from {resamples} resamples of "
            f"{len(keys)} instance(s), each with all its replicates (ADR-0012); per-fire "
            f"mismatch (ADR-0008). The episode loop is underpowered and is not the "
            f"pre-registered primary comparison."
        ),
    )
