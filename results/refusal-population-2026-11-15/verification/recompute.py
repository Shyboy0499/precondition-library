"""Recompute every figure of study 2's report from its committed files, without the project.

The registration (`docs/preregistration/refusal-population.md`, §10) asks for an independent
recomputation by code that does not import the project. This script reads only the JSON files
beside it, using the standard library, and compares its numbers with `report.json`.

It re-derives:

- each case's kind (clean, inexpressible or other);
- every dispatcher's fire and right-fire;
- §2's statistics;
- §7's two-level bootstrap: 2000 resamples, seed 0, repositories and builds drawn with
  replacement, the 2.5th and 97.5th percentiles;
- each build's own figures and repository-clustered margin;
- the spread;
- §9's decisions.

Run from the repository root:

    python results/refusal-population-2026-11-15/verification/recompute.py

It prints every figure and ends with "every figure matches report.json", or lists each
mismatch and exits 1.
"""

import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RESAMPLES = 2000
SEED = 0
H4_MARGIN = 0.10
MIN_VALID_BUILDS = 8
TARGETS = {"inexpressible": 100, "clean": 60, "repositories": 6}


def read_jsonl(name):
    lines = (HERE / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
labels = {row["index"]: row for row in read_jsonl("labels.jsonl")}
rows = read_jsonl("decisions.jsonl")
builds = json.loads((HERE / "builds.json").read_text(encoding="utf-8"))
report = json.loads((HERE / "report.json").read_text(encoding="utf-8"))


def kind(case):
    """§3.4: a case without a conflict is clean; a conflict no resolution expresses is
    inexpressible; any other conflict is other."""
    if case["kind"] == "negative":
        return "clean"
    return "other" if labels[case["index"]]["acceptable"] else "inexpressible"


cases = [(c["index"], c["repo"], kind(c)) for c in manifest["cases"]]
assert sorted(labels) == sorted(c[0] for c in cases) == sorted(r["index"] for r in rows)


def fires(variants):
    """{case index: (fired, right)} for one dispatcher, `variants[i]` fired on rows[i]."""
    return {
        row["index"]: (v is not None, v is not None and v in labels[row["index"]]["acceptable"])
        for row, v in zip(rows, variants, strict=True)
    }


zero_n = sum(b["configuration"] == "0" for b in builds)
refusal_n = sum(b["configuration"] == "R" for b in builds)
zero = [fires([r["zero"][i] for r in rows]) for i in range(zero_n)]
refusal = [fires([r["refusal"][i] for r in rows]) for i in range(refusal_n)]
control_zero = fires([r["control_zero"][0] for r in rows])
control_refusal = fires([r["control_refusal"][0] for r in rows])


def rate(decided, drawn, which, column):
    pool = [i for i, _, k in drawn if k == which]
    return sum(decided[i][column] for i in pool) / len(pool) if pool else None


def f(decided, drawn):
    return rate(decided, drawn, "inexpressible", 0)


def right(decided, drawn):
    return rate(decided, drawn, "clean", 1)


def mean(values):
    if not values or any(v is None for v in values):
        return None
    return sum(values) / len(values)


def against(group, control, drawn):
    reference = f(control, drawn)
    if reference is None:
        return None
    return mean([None if f(b, drawn) is None else reference - f(b, drawn) for b in group])


def between(left, right_, drawn, measure):
    a = mean([measure(b, drawn) for b in left])
    b = mean([measure(b, drawn) for b in right_])
    return None if a is None or b is None else a - b


def bootstrap(groups, statistic):
    point = statistic(cases, groups)
    repos = sorted({repo for _, repo, _ in cases})
    by_repo = {repo: [c for c in cases if c[1] == repo] for repo in repos}
    rng = random.Random(SEED)
    values, skipped = [], 0
    for _ in range(RESAMPLES):
        drawn = [c for repo in rng.choices(repos, k=len(repos)) for c in by_repo[repo]]
        resampled = [rng.choices(list(g), k=len(g)) for g in groups]
        value = statistic(drawn, resampled)
        if value is None:
            skipped += 1
        else:
            values.append(value)
    if len(values) < RESAMPLES // 2:
        return point, None, len(values), skipped
    values.sort()
    low = values[math.floor(0.025 * (len(values) - 1))]
    high = values[math.ceil(0.975 * (len(values) - 1))]
    return point, (low, high), len(values), skipped


hypotheses = {
    "h1": bootstrap([refusal], lambda c, g: against(g[0], control_refusal, c)),
    "h2": bootstrap([zero], lambda c, g: against(g[0], control_zero, c)),
    "h3": bootstrap([zero, refusal], lambda c, g: between(g[0], g[1], c, f)),
    "h4": bootstrap([zero, refusal], lambda c, g: between(g[1], g[0], c, right)),
}

mismatches = []


def check(name, mine, theirs):
    close = (mine is None and theirs is None) or (
        mine is not None and theirs is not None and abs(mine - theirs) < 1e-12
    )
    if not close:
        mismatches.append(f"{name}: recomputed {mine}, report.json {theirs}")


counts = {k: sum(c[2] == k for c in cases) for k in ("inexpressible", "clean", "other")}
repositories = len({c[1] for c in cases})
print(f"cases: {counts}, from {repositories} repositories")
for k in counts:
    check(f"count {k}", counts[k], report["counts"][k])
check("repositories with a case", repositories, report["counts"]["repositories_with_a_case"])
print(f"valid builds: 0 {zero_n}, R {refusal_n}")

underpowered = (
    counts["inexpressible"] < TARGETS["inexpressible"]
    or counts["clean"] < TARGETS["clean"]
    or repositories < TARGETS["repositories"]
    or min(zero_n, refusal_n) < MIN_VALID_BUILDS
)
check("underpowered", underpowered, report["underpowered"])

for name, decided in (("Control-0", control_zero), ("Control-R", control_refusal)):
    key = "control_zero_fire_rate" if name == "Control-0" else "control_refusal_fire_rate"
    print(f"{name} fire rate on inexpressible conflicts: {f(decided, cases):.3f}")
    check(key, f(decided, cases), report[key])

for name, (point, interval, used, skipped) in hypotheses.items():
    shown = f"[{interval[0]:+.3f}, {interval[1]:+.3f}]" if interval else "undefined"
    print(f"{name.upper()}: {point:+.3f} {shown} ({used} resamples, {skipped} skipped)")
    theirs = report["hypotheses"][name]
    check(f"{name} statistic", point, theirs["statistic"])
    check(f"{name} low", interval and interval[0], theirs["interval"] and theirs["interval"]["low"])
    check(
        f"{name} high", interval and interval[1], theirs["interval"] and theirs["interval"]["high"]
    )
    check(f"{name} resamples", used, theirs["resamples"])

ordered = [b for b in builds if b["configuration"] == "0"] + [
    b for b in builds if b["configuration"] == "R"
]
decided_all = zero + refusal
controls = [control_zero] * zero_n + [control_refusal] * refusal_n
reported = {(b["configuration"], b["order"]): b for b in report["builds"]}
for build, decided, control in zip(ordered, decided_all, controls, strict=True):
    point, interval, _, _ = bootstrap([[decided]], lambda c, g, ctl=control: against(g[0], ctl, c))
    beats = interval is not None and interval[0] > 0
    label = f"{build['configuration']}-{build['order']}"
    print(
        f"build {label}: f {f(decided, cases):.3f}, clean right {right(decided, cases):.3f}, "
        f"fires on clean {rate(decided, cases, 'clean', 0):.3f}, margin {point:+.3f} "
        f"[{interval[0]:+.3f}, {interval[1]:+.3f}]{' beats its control' if beats else ''}"
    )
    theirs = reported[(build["configuration"], build["order"])]
    check(f"{label} f", f(decided, cases), theirs["fire_rate"])
    check(f"{label} clean right", right(decided, cases), theirs["clean_right_rate"])
    check(f"{label} margin", point, theirs["against_control"]["statistic"])
    check(f"{label} margin low", interval[0], theirs["against_control"]["interval"]["low"])
    check(f"{label} beats", beats, theirs["beats_control"])


def spread(rates):
    s = sorted(rates)
    n = len(s)
    m = sum(s) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in s) / (n - 1))

    def q(p):
        pos = p * (n - 1)
        lo, hi = math.floor(pos), math.ceil(pos)
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)

    return {"mean": m, "sd": sd, "min": s[0], "max": s[-1], "iqr": q(0.75) - q(0.25)}


for name, group in (("0", zero), ("R", refusal)):
    mine = spread([f(b, cases) for b in group])
    print(
        f"spread of f in configuration {name}: "
        + ", ".join(f"{k} {v:.3f}" for k, v in mine.items())
    )
    for key, value in mine.items():
        check(f"spread {name} {key}", value, report["spread"][name][key])

h1, h3, h4 = hypotheses["h1"], hypotheses["h3"], hypotheses["h4"]
print("§9:")
print("  1 power:", "underpowered" if underpowered else "powered")
print("  3 H1:", "supported" if h1[1] and h1[1][0] > 0 else "not supported")
print("  4 H2:", "supported" if hypotheses["h2"][1][0] > 0 else "not supported")
print("  5 H3:", "supported" if h3[1][0] > 0 else "not supported", end="; ")
print("H4:", "holds" if h4[1][0] > -H4_MARGIN else "not shown")

if mismatches:
    print("\nMISMATCHES:")
    print("\n".join(mismatches))
    sys.exit(1)
print("\nevery figure matches report.json")
