"""Rule D for a resolver that merges the manifests key by key first (#297; exploratory).

    cd results/manifest-merge-2026-11-11 && python -I analyze.py > summary.txt

The check is usable on a lock file when the files it reads are what this resolver would have:
- **"same"** in `results/manifest-leak-2026-11-11/inputs.jsonl`: git's merge;
- **"recovered"** in `classes.jsonl`: git reported a conflict, and the key-level merge gives the
  maintainer's committed manifest.

Either way the recorded verdicts are the ones this resolver gets. Elsewhere it refuses the
check. The rules:
- **D'** (`manifest-leak`): the gate's merge; else the side the check accepts, on "same" files
  only; else refuse;
- **D''**: the same, on "same" and "recovered" files.

Reuses `manifest-leak-2026-11-11/analyze.py` for the records and the statistics. Imports
nothing from the project.
"""

import importlib.util
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEAK = HERE.parent / "manifest-leak-2026-11-11"


def _leak():
    spec = importlib.util.spec_from_file_location("leak_analyze", LEAK / "analyze.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    leak = _leak()
    every = leak.files()
    recovered = {
        (r["study"], r["index"], r["path"])
        for r in map(json.loads, (HERE / "classes.jsonl").read_text("utf-8").splitlines())
        if r["class"] == "recovered"
    }
    for f in every:
        if f["class"] == "conflicted" and (f["study"], f["index"], f["path"]) in recovered:
            f["class"] = "recovered"

    def usable(f: dict, rule: str) -> bool:
        return f["class"] == "same" or (rule == "D''" and f["class"] == "recovered")

    def decide(f: dict, rule: str) -> tuple[bool, bool]:
        if rule == "B":
            return not f["diverges"], f["merge_right"]
        if rule == "D":
            return leak.decide(f, "D")
        if not f["diverges"]:
            return True, f["merge_right"]
        side = f["accepted"]
        fire = side is not None and usable(f, rule)
        return fire, fire and f["right"][side]

    rules = (
        ("B", "B: the gate's merge, else refuse (no check)"),
        ("D", "D: the gate's merge; else the side the check accepts (as recorded)"),
        ("D'", "D': ... the check only where it reads git's merge"),
        ("D''", "D'': ... and where the key-level merge gives the maintainer's manifests"),
    )
    groups = (
        ("study-6", [f for f in every if f["study"] == "study-6"]),
        ("studies 3-5 (exploratory)", [f for f in every if f["study"] != "study-6"]),
    )
    for name, chosen in groups:
        print(f"## {name}: {len(chosen)} files, {len({f['repo'] for f in chosen})} repositories\n")
        print("classes:", dict(sorted(Counter(f["class"] for f in chosen).items())))
        wrong = defaultdict(list)
        for f in chosen:
            if f["accepted"] is not None:
                wrong[f["class"]].append(not f["right"][f["accepted"]])
        print(
            "where the check accepts one side, wrong:",
            ", ".join(f"{c} {sum(w)}/{len(w)}" for c, w in sorted(wrong.items())),
        )
        print("\n| rule | fires | coverage | wrong | mismatch [95% Wilson] |")
        print("| --- | ---: | ---: | ---: | --- |")
        for rule, text in rules:
            fired = [right for fire, right in (decide(f, rule) for f in chosen) if fire]
            bad = sum(not r for r in fired)
            low, high = leak.wilson(bad, len(fired))
            print(
                f"| {text} | {len(fired)} | {len(fired) / len(chosen):.2f} | {bad} "
                f"| {bad / len(fired):.3f} [{low:.3f}, {high:.3f}] |"
            )
        ties = [f for f in chosen if f["diverges"] and f["accepted"] is not None]
        for label, group in (
            ("all", ties),
            ("usable to D''", [f for f in ties if usable(f, "D''")]),
        ):
            better = sum(f["right"][f["accepted"]] and not f["first_right"] for f in group)
            worse = sum(f["first_right"] and not f["right"][f["accepted"]] for f in group)
            print(
                f"tie-break files ({label}): {len(group)}; the check's side right where the "
                f"first parent's is wrong {better}, the reverse {worse}"
            )
        print()
    six = [f for f in every if f["study"] == "study-6"]
    by_repo = defaultdict(list)
    for f in six:
        fire, right = decide(f, "D''")
        if fire:
            by_repo[f["repo"]].append(not right)
    values = [sum(w) / len(w) for w in by_repo.values()]
    centre = statistics.fmean(values)
    half = leak.t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    print(
        "study 6, D'''s mismatch, mean over repositories (H2's statistic): "
        f"{centre:.3f} [{centre - half:.3f}, {centre + half:.3f}] over {len(values)} repositories"
    )


if __name__ == "__main__":
    main()
