"""Run A against run B: how far the judge repeats itself (spec revision 156).

    python -I results/judge-2026-11-15/verification/agreement.py

For each library, the two runs asked the same prompts, so their caches share keys. Reads both
caches and reports, per library and pooled:
- calls whose score vectors are identical;
- calls with the same top-scored candidate, and with a tie at the top in either run;
- the mean absolute difference between the two runs' scores.

It then reads each run's `summary.txt` for arm 3's point, the matched arm 2 point and the floor.
Imports nothing from the project.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def cache(path: Path) -> dict[str, list[float]]:
    found = {}
    for line in path.read_text("utf-8").splitlines():
        record = json.loads(line)
        found[record["key"]] = record["scores"]
    return found


def top(scores: list[float]) -> tuple[int, ...]:
    best = max(scores)
    return tuple(i for i, s in enumerate(scores) if s == best)


def main() -> None:
    pooled = {"keys": 0, "same": 0, "same_top": 0, "tie": 0, "diff": 0.0, "scores": 0}
    for run in sorted(HERE.glob("run-*")):
        a, b = cache(run / "A" / "cache.jsonl"), cache(run / "B" / "cache.jsonl")
        keys = sorted(set(a) & set(b))
        same = sum(a[k] == b[k] for k in keys)
        same_top = sum(top(a[k]) == top(b[k]) for k in keys)
        tie = sum(len(top(a[k])) > 1 or len(top(b[k])) > 1 for k in keys)
        diff = sum(abs(x - y) for k in keys for x, y in zip(a[k], b[k], strict=True))
        scores = sum(len(a[k]) for k in keys)
        print(
            f"{run.name}: {len(keys)} shared calls (A {len(a)}, B {len(b)}); identical scores "
            f"{same}; same top {same_top}; a tie at the top in either run {tie}; "
            f"mean |A-B| per score {diff / scores:.4f}"
        )
        for name, value in (
            ("keys", len(keys)),
            ("same", same),
            ("same_top", same_top),
            ("tie", tie),
            ("diff", diff),
            ("scores", scores),
        ):
            pooled[name] += value
        for rep in ("A", "B"):
            text = (run / rep / "rescore" / "summary.txt").read_text("utf-8")
            point = next(x for x in text.splitlines() if "at matched coverage arm 2" in x)
            arm3 = next(x for x in text.splitlines() if "arm 3 (pre-registered" in x)
            floor = next(x for x in text.splitlines() if x.startswith("arm 2 baseline floor"))
            print(f"  {rep}: {arm3.strip()}; {point.strip()}")
            print(f"     {floor.strip()}")
    print(
        f"pooled: {pooled['keys']} calls; identical {pooled['same']} "
        f"({pooled['same'] / pooled['keys']:.3f}); same top {pooled['same_top']} "
        f"({pooled['same_top'] / pooled['keys']:.3f}); mean |A-B| per score "
        f"{pooled['diff'] / pooled['scores']:.4f}"
    )


if __name__ == "__main__":
    main()
