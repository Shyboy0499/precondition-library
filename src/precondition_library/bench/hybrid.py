"""The hybrid arm: retrieve by text, gate by preconditions (issue #265).

Arm 3 fires on about 47% of pairs (187/400) and falls back on the rest -- that is the price of its
zero mis-fires. The production gate in the prior work runs the other way round: semantic recall
first, then an executability gate that prunes. This module measures that cascade:

1. rank the library's admitted programs by the seam's text scorer, **unthresholded**;
2. keep those with score at or above a retrieval floor and within the top `k`;
3. fire the **best-ranked one whose preconditions all hold** in the environment;
4. if none holds, fire nothing and fall back -- arm 3's refusal, inherited.

Two properties are what make this a third arm rather than a tuning of the other two. It **cannot
fire on a negative pair**, because the gate is applied per candidate and a fault-free sandbox
accepts nothing, so its mis-fires come from positives only. And it fires by **text rank, not arm 3's
specificity rank**, so it can fire the wrong one of several accepting programs where arm 3 would
have fired the right one -- which is exactly the trade-off the issue asks about.

**No sandbox is built here.** The decisions are derived from an existing pair pass:
`bench.library_pairs.library_pair_outcomes` records each environment's accepted program ids and each
request's complete text ranking, and a hybrid decision at any `(k, floor)` is a walk down that
record. So the whole grid costs one pass, and the grid itself is arithmetic.

**The family is not a curve, and that matters for what may be claimed.** With two knobs and a few
hundred points over 400 pairs, the *best* point is a maximum over many draws and is optimistically
biased. The claimable comparison is the point **nearest arm 3's coverage**, chosen by the
pre-registered rule (ADR-0008: nearest, a tie to the lower coverage); the family is reported whole;
and the natural "how much coverage does the gate recover at zero mis-fires" reading is reported as a
**description of these pairs** -- the widest zero-mismatch point per `k`, with the Wilson upper
limit of the mis-fires it did not have -- never as an unbiased estimate of the rate at a threshold
that was picked because it looked good (issue #265, ADR-0035).
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..library import Library
from ..program import ProgramStatus
from ..runtime.probes import evaluate_preconditions
from ..similarity import Similarity
from .coverage import (
    Interval,
    MatchedComparison,
    OperatingPoint,
    PairOutcome,
    detectable_difference,
    matched_comparison,
    operating_point,
    sweep,
)
from .library_pairs import LibraryPair, LibraryPairOutcomes, library_pair_outcomes
from .live import LivePlan
from .primary import Dispatcher, PrimaryReport, _plot
from .rescore import scorer

KS: tuple[int | None, ...] = (1, 2, 3, 5, 10, None)
"""The registered `k` grid: how many of the ranking's best programs the gate may consider.

`None` is the whole ranking. The grid is a pre-registration value: it fixes which points exist, so a
reader can tell a measured point from one chosen after seeing the curve.
"""

NO_FLOOR = float("-inf")
"""The retrieval floor that admits every program: no floor at all."""

WORDING_LIMIT = (
    "the family is a maximum over a grid of (k, retrieval floor) points on one set of pairs, so a "
    "single best point is optimistically biased; the claimable comparison is the point nearest arm "
    "3's coverage, and the widest zero-mismatch points describe these pairs within their own "
    "Wilson "
    "upper limits"
)


class HybridPoint(BaseModel):
    """One operating point of the family: the knobs, and what they decided."""

    k: int | None
    threshold: float
    point: OperatingPoint
    """Coverage and mismatch at this `(k, floor)`.

    Its `threshold` is the **retrieval floor** the point was computed at, not a score the
    dispatcher thresholded: the hybrid's decision is already inside `fired_variant`, so the
    arithmetic is `operating_point`'s with no further filtering. Labelling it here is what lets the
    CSV and the figure say which point each row is."""

    @property
    def no_floor(self) -> bool:
        return self.threshold == NO_FLOOR


class ZeroMismatch(BaseModel):
    """The widest point at which this `k` mis-fired on nothing, as a description of these pairs."""

    k: int | None
    threshold: float
    fires: int
    coverage: float | None
    mismatch_upper: float | None
    """The 95% Wilson upper limit of the mis-fires it did not have: what bounds the description."""


class MatchedArm(BaseModel):
    """One arm's numbers at the matched comparison, with the knobs that produced them."""

    coverage: float | None
    fires: int
    mismatch: float | None
    wrong: int
    pairs: int | None = None
    k: int | None = None
    retrieval_floor: float | None = None
    mismatch_interval: Interval | None = None


class MatchedRecord(BaseModel):
    """The hybrid at arm 3's coverage, arm 3 itself, and the difference between them."""

    hybrid: MatchedArm
    arm3: MatchedArm
    coverage_gap: float
    mismatch_difference: float | None


class HybridSummary(BaseModel):
    """The stage's record: which library, which grid, and what may be read off it."""

    source: str
    library_root: str
    library_hash_before: str
    library_hash_after: str
    scorer: dict[str, str]
    pairs: int
    positives: int
    grid_points: int
    fired_points: int
    """How many of the grid's points fired on at least one pair.

    The CSV follows `figure1.csv`'s convention and lists only those, because a point that fires
    nothing has no mismatch to report. Both counts are recorded so a reader can see how much of the
    grid is in the table rather than inferring it from the row count."""
    thresholds: int
    ks: list[int | None]
    programs: int
    admitted: int
    arm3_fires: int
    arm3_mismatch: str
    matched: MatchedRecord
    smallest_detectable_difference: float | None
    widest_zero_mismatch: list[ZeroMismatch]
    wording: str
    artifacts: dict[str, str] = {}


def hybrid_decision(pair: LibraryPair, *, k: int | None, threshold: float) -> str | None:
    """The variant the hybrid fires on this pair, or `None` when the gate refuses everything.

    The ranking is best-first, so the walk can stop at the first score below the floor; `k` stops it
    earlier. The first candidate the environment accepts wins -- the gate prunes, it does not
    re-rank, which is what makes this the cascade a practitioner deploys rather than arm 3 with a
    request filter bolted on.
    """
    accepted = set(pair.accepted)
    for rank, candidate in enumerate(pair.ranked, start=1):
        if k is not None and rank > k:
            break
        if candidate.score < threshold:
            break
        if candidate.id in accepted:
            return candidate.variant
    return None


def hybrid_outcomes(
    pairs: Sequence[LibraryPair], *, k: int | None, threshold: float
) -> list[PairOutcome]:
    """One `PairOutcome` per pair at this `(k, floor)`, in the pairs' order."""
    return [
        PairOutcome(
            correct_variant=pair.pair.correct_variant,
            acceptable_variants=pair.pair.acceptable_variants,
            fired_variant=hybrid_decision(pair, k=k, threshold=threshold),
            score=None,
            informed=pair.pair.informed,
        )
        for pair in pairs
    ]


def threshold_grid(pairs: Sequence[LibraryPair]) -> list[float]:
    """Every distinct retrieval score, strictest first, plus no floor.

    ADR-0008's rule for a sweep: every achievable operating point and no interpolated one. The rule
    is pre-registered; the values come from the data, as they do for arm 2's own curve.
    """
    scores = {candidate.score for pair in pairs for candidate in pair.ranked}
    return sorted(scores, reverse=True) + [NO_FLOOR]


def hybrid_points(
    pairs: Sequence[LibraryPair],
    *,
    ks: Sequence[int | None] = KS,
    thresholds: Sequence[float] | None = None,
) -> list[HybridPoint]:
    """The whole family: one point per `(k, floor)` in the registered grids."""
    grid = list(thresholds) if thresholds is not None else threshold_grid(pairs)
    points: list[HybridPoint] = []
    for k in ks:
        for threshold in grid:
            decided = operating_point(hybrid_outcomes(pairs, k=k, threshold=threshold))
            points.append(
                HybridPoint(
                    k=k,
                    threshold=threshold,
                    point=decided.model_copy(update={"threshold": threshold}),
                )
            )
    return points


def widest_zero_mismatch(points: Sequence[HybridPoint]) -> list[ZeroMismatch]:
    """Per `k`, the point with the most fires among those that mis-fired on nothing.

    A description of these pairs, not an estimate: the threshold that maximises coverage subject to
    zero observed mis-fires is chosen *because* it looked good on this data, so the interval is what
    bounds the statement and selection bias is what it cannot bound.
    """
    best: dict[int | None, ZeroMismatch] = {}
    for entry in points:
        if entry.point.mismatch.numerator != 0 or entry.point.coverage.numerator == 0:
            continue
        found = ZeroMismatch(
            k=entry.k,
            threshold=entry.threshold,
            fires=entry.point.coverage.numerator,
            coverage=entry.point.coverage.value,
            mismatch_upper=(
                entry.point.mismatch_interval.high if entry.point.mismatch_interval else None
            ),
        )
        current = best.get(entry.k)
        if current is None or found.fires > current.fires:
            best[entry.k] = found
    return [best[key] for key in sorted(best, key=lambda k: (k is None, k or 0))]


def _matched_record(matched: MatchedComparison, matched_k: int | None) -> MatchedRecord:
    """The comparison as a record, with the `k` the chosen point came from.

    `matched_comparison` hands back the `OperatingPoint` it chose -- one of the objects passed in --
    so the entry it belongs to is found by identity, which is exact, rather than by comparing the
    numbers back into the grid.
    """
    return MatchedRecord(
        hybrid=MatchedArm(
            coverage=matched.arm2.coverage.value,
            fires=matched.arm2.coverage.numerator,
            pairs=matched.arm2.coverage.denominator,
            mismatch=matched.arm2.mismatch.value,
            wrong=matched.arm2.mismatch.numerator,
            k=matched_k,
            retrieval_floor=matched.arm2.threshold,
            mismatch_interval=matched.arm2.mismatch_interval,
        ),
        arm3=MatchedArm(
            coverage=matched.arm3.coverage.value,
            fires=matched.arm3.coverage.numerator,
            mismatch=matched.arm3.mismatch.value,
            wrong=matched.arm3.mismatch.numerator,
        ),
        coverage_gap=matched.coverage_gap,
        mismatch_difference=matched.mismatch_difference,
    )


def _csv_rows(points: Sequence[HybridPoint], matched: MatchedComparison) -> list[list[object]]:
    rows: list[list[object]] = []
    for entry in points:
        interval = entry.point.mismatch_interval
        rows.append(
            [
                "" if entry.k is None else entry.k,
                "" if entry.no_floor else entry.threshold,
                entry.point.coverage.numerator,
                entry.point.coverage.denominator,
                "" if entry.point.coverage.value is None else round(entry.point.coverage.value, 6),
                entry.point.mismatch.numerator,
                "" if entry.point.mismatch.value is None else round(entry.point.mismatch.value, 6),
                "" if interval is None else round(interval.low, 6),
                "" if interval is None else round(interval.high, 6),
                entry.point is matched.arm2,
            ]
        )
    return rows


_CSV_HEADER = [
    "k",
    "retrieval_floor",
    "fires",
    "pairs",
    "coverage",
    "wrong",
    "mismatch",
    "wilson_low",
    "wilson_high",
    "matched_to_arm3_coverage",
]


def run_hybrid(
    library_root: Path,
    out: Path,
    *,
    similarity: Similarity,
    scorer_id: dict[str, str],
    source: str,
    plan: LivePlan,
    ks: Sequence[int | None] = KS,
    thresholds: Sequence[float] | None = None,
    plot: bool = True,
) -> HybridSummary:
    """Measure the hybrid's family against the frozen library at `library_root`.

    `out` must not exist: like a live run, a rescore and the held-out stage, this writes a fresh
    directory so one library's family cannot be mixed with another's. The library is read, never
    written, and its digest is compared before and after.
    """
    if out.exists():
        raise ValueError(f"{out} already exists; the hybrid stage writes a fresh directory")
    if not plan.pair_seeds:
        raise ValueError("the plan names no pair seeds, so there are no pairs to measure")
    library = Library(
        library_root, similarity=similarity, evaluate_preconditions=evaluate_preconditions
    )
    programs = library.load_all()
    if not programs:
        raise ValueError(f"{library_root} holds no program; there is nothing to gate")
    before = library.library_hash()
    outcomes: LibraryPairOutcomes = library_pair_outcomes(
        library, list(plan.faults), list(plan.pair_seeds)
    )
    if library.library_hash() != before:
        raise RuntimeError(
            f"the hybrid stage changed the library it measured ({before} -> "
            f"{library.library_hash()}); a figure computed from a library that moved is not one"
        )
    after = library.library_hash()

    arm3 = operating_point(outcomes.arm3)
    arm2_curve = sweep(outcomes.arm2)
    points = hybrid_points(outcomes.pairs, ks=ks, thresholds=thresholds)
    fired_entries = [entry for entry in points if entry.point.coverage.numerator > 0]
    fired = [entry.point for entry in fired_entries]
    if not fired:
        raise ValueError("the hybrid fired on no pair at any (k, floor), so it has no comparison")
    matched = matched_comparison(fired, arm3)
    # The chosen point is one of the objects passed in, so its knobs are found by identity.
    matched_entry = next(entry for entry in points if entry.point is matched.arm2)
    difference = detectable_difference(
        matched.arm2.mismatch.denominator, matched.arm3.mismatch.denominator, base_rate=0.5
    )

    out.mkdir(parents=True)
    report = PrimaryReport(
        informed=False,
        pairs=len(outcomes.pairs),
        arm2=Dispatcher(
            name="hybrid (text top-k, gated by preconditions)", points=fired, scored=True
        ),
        arm3=arm3,
        vacuous=None,
        matched=matched,
        power=None,
        baselines=[Dispatcher(name="arm 2 (semantic)", points=arm2_curve, scored=True)],
    )
    if plot:
        _plot(report, out / "hybrid.png")
    with (out / "hybrid.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_CSV_HEADER)
        writer.writerows(_csv_rows(fired_entries, matched))

    summary = HybridSummary(
        source=source,
        library_root=str(library_root),
        library_hash_before=before,
        library_hash_after=after,
        scorer=scorer_id,
        pairs=len(outcomes.pairs),
        positives=sum(not pair.pair.is_negative for pair in outcomes.pairs),
        grid_points=len(points),
        fired_points=len(fired_entries),
        thresholds=len(threshold_grid(outcomes.pairs)),
        ks=list(ks),
        programs=len(programs),
        admitted=sum(program.status is ProgramStatus.ADMITTED for program in programs),
        arm3_fires=arm3.coverage.numerator,
        arm3_mismatch=f"{arm3.mismatch.numerator}/{arm3.mismatch.denominator}",
        matched=_matched_record(matched, matched_entry.k),
        smallest_detectable_difference=difference,
        widest_zero_mismatch=widest_zero_mismatch(points),
        wording=WORDING_LIMIT,
        artifacts={"hybrid.csv": "hybrid.csv"},
    )
    if plot:
        summary.artifacts["hybrid.png"] = "hybrid.png"
    (out / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    (out / "summary.txt").write_text(text(summary), encoding="utf-8")
    (out / "hybrid.json").write_text(
        json.dumps(
            {
                **scorer_id,
                "source": source,
                "library_hash": before,
                "pairs": summary.pairs,
                "ks": [("all" if k is None else k) for k in ks],
                "thresholds": "every distinct retrieval score, plus no floor",
                "matched": summary.matched.model_dump(),
                "smallest_detectable_difference": difference,
                "widest_zero_mismatch": [
                    entry.model_dump() for entry in summary.widest_zero_mismatch
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def text(summary: HybridSummary) -> str:
    """The stage's own summary: the family, the matched point, and what bounds the reading."""
    hybrid = summary.matched.hybrid
    arm3 = summary.matched.arm3
    difference = summary.matched.mismatch_difference
    lines = [
        f"Hybrid arm (issue #265): {summary.pairs} labelled pairs, {summary.positives} of them "
        f"positive, {summary.fired_points} of {summary.grid_points} grid point(s) firing, "
        f"over {summary.thresholds} retrieval floor(s)",
        f"  library {summary.library_root} ({summary.admitted} admitted of {summary.programs} "
        f"programs), hash {summary.library_hash_before}",
        f"  text scorer: {summary.scorer.get('scorer')}",
        f"  arm 3 alone: coverage {arm3.fires} of {summary.pairs}, mismatch "
        f"{arm3.wrong} of {arm3.fires}",
        f"  hybrid at arm 3's coverage: k={hybrid.k}, floor {hybrid.retrieval_floor}, fires "
        f"{hybrid.fires} (coverage {hybrid.coverage}), mismatch {hybrid.wrong} of {hybrid.fires}"
        + ("" if hybrid.mismatch is None else f" = {hybrid.mismatch:.4f}")
        + f", coverage gap {summary.matched.coverage_gap:+.3f}, "
        + "mismatch difference (hybrid - arm 3) "
        + ("undefined" if difference is None else f"{difference:+.4f}"),
        "  smallest detectable mismatch difference at a 50% base rate with these fire counts: "
        + (
            "undefined"
            if summary.smallest_detectable_difference is None
            else f"{summary.smallest_detectable_difference:.3f}"
        ),
        f"  wording: {summary.wording}",
    ]
    if summary.widest_zero_mismatch:
        lines.append("  widest zero-mismatch point per k (a description of these pairs):")
        for entry in summary.widest_zero_mismatch:
            k = "all" if entry.k is None else entry.k
            coverage = "n/a" if entry.coverage is None else f"{entry.coverage:.3f}"
            upper = "n/a" if entry.mismatch_upper is None else f"{entry.mismatch_upper:.4f}"
            lines.append(
                f"    k={k}: {entry.fires} fire(s), coverage {coverage}, mismatches 0 "
                f"(95% Wilson upper {upper})"
            )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.hybrid",
        description=(
            "Measure the hybrid arm -- retrieve by text, gate by preconditions -- against a "
            "committed frozen library (issue #265). No model call."
        ),
    )
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="a finished run directory holding library-two-sided/ and plan.json",
    )
    parser.add_argument("--out", type=Path, required=True, help="fresh output directory")
    parser.add_argument(
        "--scorer",
        choices=("lexical", "embedding", "cross-encoder"),
        default="lexical",
        help="the text scorer the ranking comes from; the reranker of #256 needs the extra",
    )
    parser.add_argument(
        "--ks",
        type=int,
        nargs="+",
        default=[k for k in KS if k is not None],
        help="the top-k grid (the registered grid also has the uncapped `all`, added too)",
    )
    parser.add_argument("--no-plot", action="store_true", help="skip hybrid.png")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    recorded = json.loads((args.run / "plan.json").read_text(encoding="utf-8"))
    plan = LivePlan.model_validate(recorded["plan"])
    similarity, identity = scorer(args.scorer)
    ks: list[int | None] = [*args.ks, None]
    summary = run_hybrid(
        args.run / "library-two-sided",
        args.out,
        similarity=similarity,
        scorer_id=identity,
        source=str(args.run),
        plan=plan,
        ks=ks,
        plot=not args.no_plot,
    )
    print(text(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
