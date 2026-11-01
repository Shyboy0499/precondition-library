"""Recompute study 2's report from its files, importing nothing from the project (§10).

Written before any of study 2's data existed, against the files `bench.refusal_study evaluate`
writes: `manifest.json`, `labels.jsonl`, `decisions.jsonl`, `builds.json` and `report.json`. It uses
the standard library only, and reads the registration's rules from its text as written here:

- a conflicted case with an empty acceptable set is *inexpressible*, a clean case is *clean*,
  and any other is *other*;
- `f` is fires over inexpressible cases, and the clean rate is right fires over clean cases;
- H1 = f(Control-R) − mean f(R's builds); H2 = f(Control-0) − mean f(0's builds);
  H3 = mean f(0) − mean f(R); H4 = mean right(R) − mean right(0);
- each interval is a 95% two-level bootstrap: repositories, then each configuration's builds,
  with replacement. This script draws its own resamples, so its ends are compared within a
  tolerance, never exactly;
- §9's rules in order, with Amendment 1's three outcomes for H4.

    python -I results/refusal-population-2026-11-01/verification/recompute.py <study directory>

`--targets I,C,R` replaces §3.4's targets (100 inexpressible, 60 clean, 6 repositories), for the
tests that run it on a small fixture; the study itself is checked with the registered ones.

It exits 1 if any figure disagrees, and prints each comparison.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

RESAMPLES = 2000
SEED = 20261101
"""Not the registered seed (0), on purpose: agreement must not depend on drawing the same
resamples."""
TOLERANCE = 0.03
MARGIN = 0.10
TARGETS = (100, 60, 6)
MIN_BUILDS = 8


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


class Check:
    def __init__(self) -> None:
        self.failures = 0

    def same(self, what: str, mine: object, theirs: object, tolerance: float = 1e-9) -> None:
        if isinstance(mine, float) and isinstance(theirs, float):
            ok = abs(mine - theirs) <= tolerance
        else:
            ok = mine == theirs
        self.failures += not ok
        print(f"{'ok      ' if ok else 'MISMATCH'} {what}: {mine!r} / {theirs!r}")


def rate(
    decisions: dict[int, str | None],
    cases: list[dict],
    kinds: dict[int, str],
    acceptable: dict[int, set],
    kind: str,
) -> float | None:
    pool = [c for c in cases if kinds[c["index"]] == kind]
    if not pool:
        return None
    if kind == "inexpressible":
        hits = sum(decisions[c["index"]] is not None for c in pool)
    else:
        hits = sum(decisions[c["index"]] in acceptable[c["index"]] for c in pool)
    return hits / len(pool)


def mean(values: list[float | None]) -> float | None:
    if not values or any(v is None for v in values):
        return None
    return sum(values) / len(values)  # type: ignore[arg-type]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("study", type=Path)
    parser.add_argument("--targets", default=",".join(map(str, TARGETS)))
    args = parser.parse_args()
    study = args.study
    targets = tuple(int(x) for x in args.targets.split(","))
    manifest = json.loads((study / "manifest.json").read_text("utf-8"))
    report = json.loads((study / "report.json").read_text("utf-8"))
    builds = json.loads((study / "builds.json").read_text("utf-8"))
    labels = {row["index"]: row for row in rows(study / "labels.jsonl")}
    decided = {row["index"]: row for row in rows(study / "decisions.jsonl")}
    cases = [c for c in manifest["cases"] if c["index"] in decided]
    acceptable = {i: set(row["acceptable"]) for i, row in labels.items()}
    kinds = {
        c["index"]: "clean"
        if c["kind"] == "negative"
        else ("other" if acceptable[c["index"]] else "inexpressible")
        for c in cases
    }
    check = Check()

    counts = report["counts"]
    for kind in ("inexpressible", "clean", "other"):
        check.same(f"{kind} cases", sum(k == kind for k in kinds.values()), counts[kind])
    repositories = len({c["repo"] for c in cases})
    check.same("repositories with a case", repositories, counts["repositories_with_a_case"])

    zero = [b for b in builds if b["configuration"] == "0"]
    refusal = [b for b in builds if b["configuration"] == "R"]
    check.same("valid builds", {"0": len(zero), "R": len(refusal)}, report["valid_builds"])

    def dispatcher(field: str, i: int | None) -> dict[int, str | None]:
        return {
            index: (row[field][i] if i is not None else row[field][0])
            for index, row in decided.items()
        }

    zero_d = [dispatcher("zero", i) for i in range(len(zero))]
    refusal_d = [dispatcher("refusal", i) for i in range(len(refusal))]
    control_zero = dispatcher("control_zero", None)
    control_refusal = dispatcher("control_refusal", None)

    def f(d: dict, pool: list[dict]) -> float | None:
        return rate(d, pool, kinds, acceptable, "inexpressible")

    def right(d: dict, pool: list[dict]) -> float | None:
        return rate(d, pool, kinds, acceptable, "clean")

    check.same("Control-0's f", f(control_zero, cases), report["control_zero_fire_rate"])
    check.same("Control-R's f", f(control_refusal, cases), report["control_refusal_fire_rate"])

    def diff(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else a - b

    statistics = {
        "h1": lambda pool, z, r: diff(f(control_refusal, pool), mean([f(d, pool) for d in r])),
        "h2": lambda pool, z, r: diff(f(control_zero, pool), mean([f(d, pool) for d in z])),
        "h3": lambda pool, z, r: diff(mean([f(d, pool) for d in z]), mean([f(d, pool) for d in r])),
        "h4": lambda pool, z, r: diff(
            mean([right(d, pool) for d in r]), mean([right(d, pool) for d in z])
        ),
    }
    names = sorted({c["repo"] for c in cases})
    by_repo = {name: [c for c in cases if c["repo"] == name] for name in names}
    rng = random.Random(SEED)
    intervals = {}
    for name, statistic in statistics.items():
        theirs = report["hypotheses"][name]
        point = statistic(cases, zero_d, refusal_d)
        check.same(f"{name} statistic", point, theirs["statistic"])
        values = []
        for _ in range(RESAMPLES):
            pool = [c for repo in rng.choices(names, k=len(names)) for c in by_repo[repo]]
            z = rng.choices(zero_d, k=len(zero_d)) if zero_d else []
            r = rng.choices(refusal_d, k=len(refusal_d)) if refusal_d else []
            value = statistic(pool, z, r)
            if value is not None:
                values.append(value)
        if len(values) < RESAMPLES // 2 or theirs["interval"] is None:
            check.same(
                f"{name} interval defined",
                len(values) >= RESAMPLES // 2,
                theirs["interval"] is not None,
            )
            intervals[name] = None
            continue
        values.sort()
        low = values[math.floor(0.025 * (len(values) - 1))]
        high = values[math.ceil(0.975 * (len(values) - 1))]
        check.same(f"{name} interval low", low, theirs["interval"]["low"], TOLERANCE)
        check.same(f"{name} interval high", high, theirs["interval"]["high"], TOLERANCE)
        intervals[name] = theirs["interval"]

    because = []
    found = (counts["inexpressible"], counts["clean"], counts["repositories_with_a_case"])
    if any(have < need for have, need in zip(found, targets, strict=True)):
        because.append("targets")
    because += [
        f"configuration {c}" for c, n in (("0", len(zero)), ("R", len(refusal))) if n < MIN_BUILDS
    ]
    check.same("underpowered", bool(because), report["underpowered"])
    check.same("underpowered reasons", len(because), len(report["underpowered_because"]))

    # §9 in order, from the report's own intervals so a borderline bound cannot flip on
    # resampling; the intervals themselves were checked above.
    def above(name: str, bound: float) -> bool:
        return intervals[name] is not None and intervals[name]["low"] > bound

    def silent(ds: list[dict]) -> bool:
        return not any(d[c["index"]] is not None for d in ds for c in cases)

    expected = ["1 power"]
    if not because:
        expected.append("2 applicability")
        expected.append(
            "3 H1:"
            + (
                "not tested"
                if silent(refusal_d)
                else "supported"
                if above("h1", 0)
                else "not supported"
            )
        )
        expected.append(
            "4 H2:"
            + (
                "not tested"
                if silent(zero_d)
                else "supported"
                if above("h2", 0)
                else "not supported"
            )
        )
        if silent(zero_d) or silent(refusal_d):
            expected.append("5 H3 and H4:not tested")
        else:
            h4 = (
                "holds"
                if above("h4", -MARGIN)
                else (
                    "cost"
                    if intervals["h4"] is not None and intervals["h4"]["high"] < -MARGIN
                    else "not shown"
                )
            )
            expected.append(
                f"5 H3 and H4:H3 {'supported' if above('h3', 0) else 'not supported'}, H4 {h4}"
            )

    def shape(decision: dict) -> str:
        """A decision's rule and verdict, without the sentence that explains it."""
        rule, outcome = decision["rule"], decision["outcome"]
        return rule if rule.startswith(("1", "2")) else f"{rule}:{outcome.split(':')[0]}"

    check.same("§9's decisions", expected, [shape(d) for d in report["decisions"]])

    for build, d in [(b, x) for b, x in zip(zero, zero_d, strict=True)] + [
        (b, x) for b, x in zip(refusal, refusal_d, strict=True)
    ]:
        mine = next(
            x
            for x in report["builds"]
            if x["configuration"] == build["configuration"] and x["order"] == build["order"]
        )
        label = f"build {build['configuration']}{build['order']}"
        check.same(f"{label} f", f(d, cases), mine["fire_rate"])
        check.same(f"{label} clean right", right(d, cases), mine["clean_right_rate"])
        control = control_refusal if build["configuration"] == "R" else control_zero
        check.same(
            f"{label} margin",
            diff(f(control, cases), f(d, cases)),
            mine["against_control"]["statistic"],
        )

    print(f"{check.failures} mismatch(es)")
    return 1 if check.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
