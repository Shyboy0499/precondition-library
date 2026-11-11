"""Rule D as a resolver at merge time could run it (#297; exploratory, after study 6).

    cd results/manifest-leak-2026-11-11 && python -I analyze.py > summary.txt

`audit.py` puts every checked lock file in a class (`inputs.jsonl`):
- **same:** every file the check reads is git's own merge;
- **conflicted:** git could not merge one of them;
- **edited:** git merged them, and the maintainer committed something else.

The registered rule D judges each side in the merge's tree, as committed (tool-precondition §4).
Only where a file is "same" is that the verdict a resolver would get before resolving anything
else. So this compares:
- **C** and **D** as recorded;
- **C'** and **D'**, which use the check only on "same" files and refuse it elsewhere. The
  gate's step is unchanged: it reads only the three lock files.

Mismatch is wrong fires over fires, with a Wilson interval, pooled over files. For study 6 the
per-repository mean of D' is also given, as study 6's H2 computes it: a description, not a
test. Imports nothing from the project.
"""

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECKED = ROOT / "results" / "lock-tool-check-2026-11-08"
ANATOMY = ROOT / "results" / "lock-anatomy-2026-11-04"
GATES = ROOT / "results" / "divergence-gate-2026-11-08" / "gates.jsonl"
STUDY_6 = ROOT / "results" / "tool-precondition-2026-11-09" / "files.jsonl"
STUDIES = ("study-6", "study-3", "study-4", "study-5")


def kind(check: dict) -> str:
    v = check["verdict"]
    if v == "consistent":
        return "consistent"
    return "inconsistent" if v.startswith("inconsistent") else "error"


def accepted(check: dict) -> str | None:
    kinds = {s: kind(check[s]) for s in ("first", "second")}
    passes = [s for s, k in kinds.items() if k == "consistent"]
    return passes[0] if len(passes) == 1 and "error" not in kinds.values() else None


def wilson(k: int, n: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):
        return 1 - betainc(b, a, 1 - x)
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
    c, d, f = 1.0, 0.0, 1.0
    for i in range(400):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1 + num * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + num / (c if abs(c) > 1e-300 else 1e-300)
        f *= c * d
        if abs(1 - c * d) < 1e-15:
            break
    return front * (f - 1) / a


def t_975(df: int) -> float:
    low, high = 0.0, 50.0
    for _ in range(200):
        mid = (low + high) / 2
        below = 1 - 0.5 * betainc(df / 2, 0.5, df / (df + mid * mid)) < 0.975
        low, high = (mid, high) if below else (low, mid)
    return (low + high) / 2


def files() -> list[dict]:
    """Every checked file: study, repository, tool, divergence, labels, the side the check
    accepts and its class."""
    classes = {}
    for line in (HERE / "inputs.jsonl").read_text("utf-8").splitlines():
        r = json.loads(line)
        classes[(r["study"], r["index"], r["path"])] = r["class"]
    found = []
    for line in STUDY_6.read_text("utf-8").splitlines():
        r = json.loads(line)
        found.append(
            {
                "study": "study-6",
                "repo": r["repo"],
                "tool": r["tool"],
                "diverges": r["divergent"] > 0,
                "merge_right": r["predicted_reproduces"],
                "first_right": r["local_reproduces"],
                "right": {"first": r["local_reproduces"], "second": r["upstream_reproduces"]},
                "accepted": accepted(r["check"]),
                "class": classes[("study-6", r["index"], r["path"])],
            }
        )
    gates = {}
    for study in ("study-3", "study-4"):
        for line in (ANATOMY / f"{study}.jsonl").read_text("utf-8").splitlines():
            f = json.loads(line)
            gates[(study, f["index"], f["path"])] = (
                f["kinds"].get("divergent", 0) > 0,
                f["predicted_reproduces"],
            )
    for line in GATES.read_text("utf-8").splitlines():
        case = json.loads(line)
        for f in case["files"]:
            gates[("study-5", case["index"], f["path"])] = (
                f["divergent"] > 0,
                f["predicted_reproduces"],
            )
    for study in ("study-3", "study-4", "study-5"):
        for line in (CHECKED / f"{study}.jsonl").read_text("utf-8").splitlines():
            r = json.loads(line)
            diverges, merge_right = gates[(study, r["index"], r["path"])]
            found.append(
                {
                    "study": study,
                    "repo": r["repo"],
                    "tool": r["tool"],
                    "diverges": diverges,
                    "merge_right": merge_right,
                    "first_right": r["maintainer_set"]["first"],
                    "right": r["maintainer_set"],
                    "accepted": accepted(r["check"]),
                    "class": classes[(study, r["index"], r["path"])],
                }
            )
    return found


def decide(f: dict, rule: str) -> tuple[bool, bool]:
    """(fires, right) for one file."""
    if rule == "B":
        return not f["diverges"], f["merge_right"]
    side = f["accepted"]
    usable = side is not None and (rule in ("C", "D") or f["class"] == "same")
    if rule in ("C", "C'"):
        return usable, usable and f["right"][side]
    if not f["diverges"]:
        return True, f["merge_right"]
    return usable, usable and f["right"][side]


def line(name: str, chosen: list[dict], rule: str) -> str:
    fired = [right for fire, right in (decide(f, rule) for f in chosen) if fire]
    wrong = sum(not r for r in fired)
    if not fired:
        return f"| {name} | 0 | 0.00 | 0 | — |"
    low, high = wilson(wrong, len(fired))
    return (
        f"| {name} | {len(fired)} | {len(fired) / len(chosen):.2f} | {wrong} "
        f"| {wrong / len(fired):.3f} [{low:.3f}, {high:.3f}] |"
    )


RULES = (
    ("B", "B: the gate's merge, else refuse (no check)"),
    ("C", "C: the side the check accepts, else refuse (as recorded)"),
    ("C'", "C': the same, only where the check reads git's merge"),
    ("D", "D: the gate's merge; else C (as recorded)"),
    ("D'", "D': the gate's merge; else C'"),
)


def report(name: str, chosen: list[dict]) -> None:
    repos = len({f["repo"] for f in chosen})
    print(f"## {name}: {len(chosen)} files, {repos} repositories\n")
    classes = Counter(f["class"] for f in chosen)
    print("classes:", dict(sorted(classes.items())))
    fires = [f for f in chosen if f["accepted"] is not None]
    by_class = defaultdict(list)
    for f in fires:
        by_class[f["class"]].append(not f["right"][f["accepted"]])
    print(
        "where the check accepts one side:",
        ", ".join(
            f"{c} {sum(w)}/{len(w)} wrong ({sum(w) / len(w):.2f})"
            for c, w in sorted(by_class.items())
        ),
    )
    print("\n| rule | fires | coverage | wrong | mismatch [95% Wilson] |")
    print("| --- | ---: | ---: | ---: | --- |")
    for rule, text in RULES:
        print(line(text, chosen, rule))
    fired = [f for f in chosen if decide(f, "C'")[0]]
    print(
        f"on C''s {len(fired)} fires: the accepted side is wrong on "
        f"{sum(not f['right'][f['accepted']] for f in fired)}, the first parent's file on "
        f"{sum(not f['first_right'] for f in fired)}"
    )
    ties = [f for f in chosen if f["diverges"] and f["accepted"] is not None]
    for label, group in (("all", ties), ("same", [f for f in ties if f["class"] == "same"])):
        better = sum(f["right"][f["accepted"]] and not f["first_right"] for f in group)
        worse = sum(f["first_right"] and not f["right"][f["accepted"]] for f in group)
        print(
            f"tie-break files ({label}): {len(group)}; the check's side right where the first "
            f"parent's is wrong {better}, the reverse {worse}"
        )
    print()


def per_repository(chosen: list[dict], rule: str) -> str:
    by_repo = defaultdict(list)
    for f in chosen:
        fire, right = decide(f, rule)
        if fire:
            by_repo[f["repo"]].append(not right)
    values = [sum(w) / len(w) for w in by_repo.values()]
    centre = statistics.fmean(values)
    half = t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return (
        f"{centre:.3f} [{centre - half:.3f}, {centre + half:.3f}] over {len(values)} repositories"
    )


def main() -> None:
    every = files()
    for study in STUDIES:
        report(study, [f for f in every if f["study"] == study])
    report("studies 3-5 (exploratory)", [f for f in every if f["study"] != "study-6"])
    six = [f for f in every if f["study"] == "study-6"]
    print("study 6, rule D's mismatch, mean over repositories (H2's statistic):")
    print(f"  D as recorded: {per_repository(six, 'D')}")
    print(f"  D': {per_repository(six, chr(68) + chr(39))}")


if __name__ == "__main__":
    main()
