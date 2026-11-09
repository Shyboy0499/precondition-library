"""Descriptive figures for study 6's README, none of them registered, from `files.jsonl` and
`manifest.json`. Imports nothing from the project; it reuses `recompute.py`'s t quantile.

    python -I results/tool-precondition-<date>/verification/describe.py

- the per-repository table: cases, files, the check's rejections, g (H1), rule D (H2), tie-break
  files (H3);
- how fragile H1's decision is: per-repository signs, each repository left out in turn, and the
  pnpm "settings" verdicts counted as errors rather than as rejections;
- the errors, by message;
- where the tie-break's one reverse and its wins lie.
"""

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recompute import accepted, kind, right, rule_d, t_975  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
OWN = ("first", "second", "base")


def settings_as_error(verdict: dict) -> str:
    if verdict["verdict"] == "inconsistent: settings":
        return "error"
    return kind(verdict)


def gaps(rows: list[dict], judge=kind) -> dict[str, float]:
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_repo[row["repo"]].append(row)
    found = {}
    for repo, files in by_repo.items():
        merged = [k for k in (judge(r["check"]["merge"]) for r in files) if k != "error"]
        ordinary = [k for k in (judge(r["own"][s]) for r in files for s in OWN) if k != "error"]
        if merged and ordinary:
            found[repo] = merged.count("inconsistent") / len(merged) - ordinary.count(
                "inconsistent"
            ) / len(ordinary)
    return found


def interval(values: list[float]) -> str:
    centre = statistics.fmean(values)
    half = t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return f"{centre:.3f} [{centre - half:.3f}, {centre + half:.3f}]"


def lower(values: list[float]) -> float:
    centre = statistics.fmean(values)
    return centre - t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))


def main() -> None:
    rows = [json.loads(line) for line in (HERE / "files.jsonl").read_text("utf-8").splitlines()]
    manifest = json.loads((HERE / "manifest.json").read_text("utf-8"))
    cases = Counter(c["repo"] for c in manifest["cases"])
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_repo[row["repo"]].append(row)
    g = gaps(rows)

    print("## By repository\n")
    print(
        "| repository | cases | files (composer / npm / pnpm) | merged: rejected / judged "
        "| ordinary: rejected / judged | g | rule D: wrong / fires | m_D | tie-break files |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for entry in manifest["repositories"]:
        repo = entry["repo"]
        files = by_repo[repo]
        tools = Counter(r["tool"] for r in files)
        merged = [kind(r["check"]["merge"]) for r in files]
        ordinary = [kind(r["own"][s]) for r in files for s in OWN]
        fires = [ok for fire, ok in map(rule_d, files) if fire]
        ties = sum(r["divergent"] > 0 and accepted(r) is not None for r in files)
        print(
            f"| `{repo}` | {cases[repo]} "
            f"| {len(files)} ({tools['composer']} / {tools['npm']} / {tools['pnpm']}) "
            f"| {merged.count('inconsistent')} / {sum(k != 'error' for k in merged)} "
            f"| {ordinary.count('inconsistent')} / {sum(k != 'error' for k in ordinary)} "
            f"| {f'{g[repo]:+.3f}' if repo in g else '—'} "
            f"| {sum(not ok for ok in fires)} / {len(fires)} "
            f"| {f'{sum(not ok for ok in fires) / len(fires):.2f}' if fires else '—'} | {ties} |"
        )

    print("\n## How fragile H1's decision is\n")
    values = list(g.values())
    print(f"as registered, over {len(values)} repositories: {interval(values)}")
    print(
        f"g above 0 in {sum(v > 0 for v in values)}, below 0 in {sum(v < 0 for v in values)}, "
        f"exactly 0 in {sum(v == 0 for v in values)}"
    )
    left_out = sorted((lower([v for r, v in g.items() if r != repo]), repo) for repo in g)
    print(
        f"each repository left out in turn: the lower end stays above 0 in "
        f"{sum(low > 0 for low, _ in left_out)} of {len(left_out)}; lowest "
        f"{left_out[0][0]:.3f}, without {left_out[0][1]}"
    )
    for low, repo in left_out:
        if low <= 0:
            print(f"    {low:.3f} without {repo}")
    settings = gaps(rows, settings_as_error)
    print(
        f'pnpm "settings" verdicts counted as errors: {len(settings)} repositories, '
        f"{interval(list(settings.values()))}"
    )
    pooled = {
        name: [kind(r[where][s]) for r in rows for s in sides]
        for name, where, sides in (("merged", "check", ("merge",)), ("ordinary", "own", OWN))
    }
    for name, kinds in pooled.items():
        judged = sum(k != "error" for k in kinds)
        print(
            f"pooled {name}: {kinds.count('inconsistent')} of {judged} judged rejected "
            f"({kinds.count('inconsistent') / judged:.3f}); {kinds.count('error')} errors"
        )

    print("\n## Verdicts and errors\n")
    for name, where, sides in (
        ("merged files", "check", ("merge",)),
        ("parents' files in the merge's tree", "check", ("first", "second")),
        ("ordinary checks", "own", OWN),
    ):
        verdicts = Counter(r[where][s]["verdict"] for r in rows for s in sides)
        found = Counter()
        for verdict, n in verdicts.items():
            found[verdict if not verdict.startswith("error") else "error"] += n
        print(f"{name}: {dict(sorted(found.items()))}")
    errors = Counter()
    for r in rows:
        for where, sides in (("check", ("merge", "first", "second")), ("own", OWN)):
            for s in sides:
                if kind(r[where][s]) == "error":
                    errors[(r["tool"], r[where][s]["verdict"][:60])] += 1
    print("\nerrors by tool and message (first 60 characters), all checks:")
    for (tool, message), n in errors.most_common():
        print(f"  {n:4} {tool:8} {message!r}")
    every = Counter(
        (r["repo"], kind(r[w][s]) == "error")
        for r in rows
        for w, sides in (("check", ("merge",)), ("own", OWN))
        for s in sides
    )
    for repo in by_repo:
        if every[(repo, False)] == 0:
            print(f"every check errored in {repo}")

    print("\n## The tie-break\n")
    ties = [r for r in rows if r["divergent"] > 0 and accepted(r) is not None]
    print("tie-break files by repository:", dict(Counter(r["repo"] for r in ties).most_common()))
    for r in ties:
        side = accepted(r) or "first"
        if r["local_reproduces"] and not right(r, side):
            print(f"reverse: {r['repo']}, case {r['index']}, {r['path']}, accepted {side}")
    wins = Counter(
        r["repo"] for r in ties if right(r, accepted(r) or "first") and not r["local_reproduces"]
    )
    print("wins over the first parent's file, by repository:", dict(wins.most_common()))


if __name__ == "__main__":
    main()
