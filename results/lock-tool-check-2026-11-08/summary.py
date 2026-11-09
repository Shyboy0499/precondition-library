"""The agreement tables of `check.py`'s output (#297).

    python -I results/lock-tool-check-2026-11-08/summary.py results/lock-tool-check-2026-11-08

For each tool:

- **the control**: the tool's verdict on the maintainer's merged lock file;
- **agreement**: on each side's lock file (study 3's `take_local` and `take_upstream`), the tool's
  verdict against the maintainer's oracle (is it the maintainer's package set?). Files where the
  tool failed for another reason are counted apart.
"""

import json
import sys
from collections import Counter
from pathlib import Path

STUDIES = ("study-3", "study-4", "study-5")


def kind(verdict: str) -> str:
    if verdict == "consistent":
        return "consistent"
    return "inconsistent" if verdict.startswith("inconsistent") else "error"


def main() -> None:
    folder = Path(sys.argv[1])
    rows = []
    for study in STUDIES:
        path = folder / f"{study}.jsonl"
        if path.exists():
            for line in path.read_text("utf-8").splitlines():
                rows.append({"study": study, **json.loads(line)})
    for tool in ("npm", "pnpm", "composer"):
        mine = [r for r in rows if r["tool"] == tool]
        if not mine:
            continue
        print(f"## {tool}: {len(mine)} conflicted lock files")
        control = Counter(kind(r["check"]["merge"]["verdict"]) for r in mine)
        print("control, the maintainer's merged file:", dict(sorted(control.items())))
        if tool == "composer":
            stale = Counter(r["check"]["merge"].get("hash") for r in mine)
            print("  its content-hash:", dict(sorted(stale.items())))
        errors = Counter(
            r["check"]["merge"]["verdict"]
            for r in mine
            if kind(r["check"]["merge"]["verdict"]) == "error"
        )
        for verdict, n in errors.most_common():
            print(f"  {n} x {verdict}")
        cells: Counter = Counter()
        side_errors: Counter = Counter()
        for r in mine:
            for side in ("first", "second"):
                verdict = r["check"][side]["verdict"]
                same = r["maintainer_set"][side]
                if kind(verdict) == "error":
                    side_errors[verdict] += 1
                    continue
                cells[(same, kind(verdict))] += 1
        print("sides (2 per file): maintainer's set x tool's verdict")
        print("| | tool: consistent | tool: inconsistent |")
        print("| --- | ---: | ---: |")
        for same, label in ((True, "is the maintainer's set"), (False, "is not")):
            print(f"| {label} | {cells[(same, 'consistent')]} | {cells[(same, 'inconsistent')]} |")
        settings = sum(
            r["check"][side]["verdict"] == "inconsistent: settings"
            for r in mine
            for side in ("first", "second")
        )
        if settings:
            print(f"  of the inconsistent sides, {settings} for settings, not manifests")
        rejected = [
            (r, side)
            for r in mine
            for side in ("first", "second")
            if r["maintainer_set"][side] and kind(r["check"][side]["verdict"]) == "inconsistent"
        ]
        if rejected:
            also = sum(kind(r["check"]["merge"]["verdict"]) == "inconsistent" for r, _ in rejected)
            print(
                f"  the tool rejects {len(rejected)} sides that are the maintainer's set;"
                f" for {also} of them it rejects the maintainer's own merged file too"
            )
        one = [
            r
            for r in mine
            if sorted(kind(r["check"][side]["verdict"]) for side in ("first", "second"))
            == ["consistent", "inconsistent"]
        ]
        picked = sum(
            r["maintainer_set"][
                "first" if kind(r["check"]["first"]["verdict"]) == "consistent" else "second"
            ]
            for r in one
        )
        some = sum(r["maintainer_set"]["first"] or r["maintainer_set"]["second"] for r in one)
        print(
            f"files where exactly one side passes: {len(one)}; that side is the maintainer's set"
            f" in {picked} (and some side is, in {some})"
        )
        print("sides where the tool failed:", sum(side_errors.values()))
        for verdict, n in side_errors.most_common(6):
            print(f"  {n} x {verdict}")
        if tool == "composer":
            hashes: Counter = Counter()
            for r in mine:
                for side in ("first", "second"):
                    hash_ = r["check"][side].get("hash")
                    if hash_:
                        hashes[(r["maintainer_set"][side], hash_)] += 1
            print("sides: content-hash, by whether the side is the maintainer's set")
            for same, label in ((True, "is the maintainer's set"), (False, "is not")):
                print(
                    f"  {label}: hash consistent {hashes[(same, 'consistent')]}, "
                    f"inconsistent {hashes[(same, 'inconsistent')]}"
                )
        print()


if __name__ == "__main__":
    main()
