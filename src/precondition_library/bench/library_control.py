"""The library-scoped control on a finished real-merge stage: exploratory (ADR-0052).

Stage B's registered state-reading control decides with the lock-file intent's own tree, so it
can fire only that intent's resolutions, while arm 3 fires any program in the library. ADR-0052
reads H2's margin as that difference in scope. This module tests the reading on the same cases:
it puts `StateClassifier.decide_library` -- the same fitted trees, any intent's resolution -- in
the registered control's place and applies the registered tests unchanged.

It is exploratory, not a test of anything. Stage B's data had been seen when the control was
written, and the control was written because of what stage B showed. It reads the states that
`real_merges.observe_states` recorded, and refuses any that did not rebuild as they were.

    python -m precondition_library.bench.library_control STAGE_DIR --out OUT_DIR
"""

from __future__ import annotations

import argparse
import gzip
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from .coverage import OperatingPoint, matched_comparison, operating_point, sweep
from .real_merge_inference import Inference, matched_test, refusal_test
from .real_merges import (
    LIBRARIES,
    Decisions,
    Label,
    Manifest,
    ObservedState,
    _rows,
    control_classifier,
)


class Kinds(BaseModel):
    """One dispatcher's fires on one kind of case: how many, and how many right."""

    fires: int
    right: int


class Replicate(BaseModel):
    library: str
    arm3: OperatingPoint
    control_matched: OperatingPoint
    """The library-scoped control at the point of its curve nearest arm 3's coverage."""
    h2: Inference
    """The registered H2 test, with the library-scoped control in the control's place."""
    h3: Inference


class LibraryControlReport(BaseModel):
    cases: int
    control_clean: Kinds
    control_conflicted: Kinds
    """The library-scoped control at every fire, by kind of case."""
    registered_clean: Kinds
    registered_conflicted: Kinds
    """The registered (intent-scoped) control at every fire, for comparison."""
    fired: dict[str, int]
    """The library-scoped control's fires, by resolution."""
    replicates: list[Replicate]


def _state_lines(stage: Path) -> list[str]:
    """`states.jsonl` as `observe_states` writes it, or `states.jsonl.gz` as it is committed."""
    plain, packed = stage / "states.jsonl", stage / "states.jsonl.gz"
    if plain.exists():
        text = plain.read_text(encoding="utf-8")
    elif packed.exists():
        text = gzip.decompress(packed.read_bytes()).decode("utf-8")
    else:
        raise ValueError(f"{stage}: no recorded state for any case; run observe first")
    return [line for line in text.splitlines() if line.strip()]


def _read(stage: Path) -> tuple[Manifest, list[Label], list[Decisions], list[ObservedState]]:
    def rows(name: str) -> list[str]:
        return [
            line for line in (stage / name).read_text(encoding="utf-8").splitlines() if line.strip()
        ]

    manifest = Manifest.model_validate_json((stage / "manifest.json").read_text("utf-8"))
    labels = [Label.model_validate_json(line) for line in rows("labels.jsonl")]
    decided = [Decisions.model_validate_json(line) for line in rows("decisions.jsonl")]
    states = [ObservedState.model_validate_json(line) for line in _state_lines(stage)]
    return manifest, labels, decided, states


def _kinds(
    manifest: Manifest, labels: Sequence[Label], fired: dict[int, str | None]
) -> tuple[Kinds, Kinds]:
    by_index = {lab.index: lab for lab in labels}
    counts = {"negative": [0, 0], "positive": [0, 0]}
    for case in manifest.cases:
        variant = fired[case.index]
        if variant is None:
            continue
        counts[case.kind][0] += 1
        counts[case.kind][1] += variant in by_index[case.index].acceptable
    clean, conflicted = counts["negative"], counts["positive"]
    return Kinds(fires=clean[0], right=clean[1]), Kinds(fires=conflicted[0], right=conflicted[1])


def compare(stage: Path) -> LibraryControlReport:
    """The library-scoped control against arm 3 on `stage`'s recorded states."""
    manifest, labels, decided, states = _read(stage)
    observed = {row.index: row for row in states}
    missing = sorted({case.index for case in manifest.cases} - set(observed))
    if missing:
        raise ValueError(f"{stage}: no recorded state for cases {missing[:5]}; run observe first")
    differing = sorted(row.index for row in states if not row.control_matches)
    if differing:
        raise ValueError(f"{stage}: cases {differing[:5]} did not rebuild as they were")
    classifier = control_classifier()
    library = {index: classifier.decide_library(row.state) for index, row in observed.items()}
    swapped = [d.model_copy(update={"control": library[d.index]}) for d in decided]
    control_clean, control_conflicted = _kinds(
        manifest, labels, {i: fired for i, (fired, _) in library.items()}
    )
    registered_clean, registered_conflicted = _kinds(
        manifest, labels, {d.index: d.control[0] for d in decided}
    )
    fired: dict[str, int] = {}
    for variant, _ in library.values():
        if variant is not None:
            fired[variant] = fired.get(variant, 0) + 1
    replicates = []
    for replicate, path in enumerate(LIBRARIES):
        rows = _rows(manifest, labels, swapped, replicate, "control")
        point = operating_point([row.arm3 for row in rows])
        replicates.append(
            Replicate(
                library=str(path),
                arm3=point,
                control_matched=matched_comparison(sweep([row.other for row in rows]), point).arm2,
                h2=matched_test(rows),
                h3=refusal_test(rows),
            )
        )
    return LibraryControlReport(
        cases=len(manifest.cases),
        control_clean=control_clean,
        control_conflicted=control_conflicted,
        registered_clean=registered_clean,
        registered_conflicted=registered_conflicted,
        fired=dict(sorted(fired.items())),
        replicates=replicates,
    )


def text(report: LibraryControlReport) -> str:
    def kinds(name: str, clean: Kinds, conflicted: Kinds) -> str:
        return (
            f"  {name}: clean {clean.right}/{clean.fires} right, "
            f"conflicted {conflicted.right}/{conflicted.fires} right\n"
        )

    out = [
        "The library-scoped control on stage B (exploratory, ADR-0052)\n",
        f"  cases {report.cases}; library-scoped control fires {report.fired}\n",
        kinds("library-scoped control", report.control_clean, report.control_conflicted),
        kinds("registered control", report.registered_clean, report.registered_conflicted),
    ]
    for rep in report.replicates:
        a3, ctl = rep.arm3, rep.control_matched
        out.append(
            f"  {rep.library}: arm 3 {a3.mismatch.numerator}/{a3.mismatch.denominator} wrong; "
            f"control at {ctl.coverage.numerator}/{ctl.coverage.denominator} coverage, "
            f"{ctl.mismatch.numerator}/{ctl.mismatch.denominator} wrong\n"
        )
        for name, inference in (("H2", rep.h2), ("H3", rep.h3)):
            interval = inference.interval
            statistic = (
                "undefined" if inference.statistic is None else f"{inference.statistic:+.3f}"
            )
            bounds = (
                "no interval"
                if interval is None
                else f"[{interval.low:+.3f}, {interval.high:+.3f}]"
            )
            out.append(
                f"    {name} with this control: {statistic} {bounds}, "
                f"McNemar b/c {inference.discordant[0]}/{inference.discordant[1]}\n"
            )
    return "".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.library_control")
    parser.add_argument("stage", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit(f"{args.out} already exists; the comparison writes a fresh directory")
    report = compare(args.stage)
    args.out.mkdir(parents=True)
    (args.out / "report.json").write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    (args.out / "summary.txt").write_text(text(report), encoding="utf-8")
    print(text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
