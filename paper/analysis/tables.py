"""The report's tables, as LaTeX, from committed result files; nothing typed in.

    python paper/analysis/tables.py --out paper/tables

Each table is recomputed from the per-pair, per-case or per-program records and then checked
against the headline figure the run itself committed (Figure 1's matched points, stage B's
report), so a table that disagreed with its run would stop the script rather than be printed.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPLICATES = ROOT / "results" / "replicates-2026-10-05"
HYBRID = ROOT / "results" / "hybrid-2026-10-11"
CONSEQUENCES = ROOT / "results" / "consequences-2026-10-21"
STAGE_B = ROOT / "results" / "real-merges-2026-10-26" / "stage-B"
RUNS = ("run-11", "run-12", "run-13")
SCORE_TOLERANCE = 1e-6
"""The hybrid run recomputed the reranker's scores, which agree with the rescore's to about
3e-7; a pair exactly at the matched threshold needs this much slack to be counted as the rescore
counted it. The nearest pair genuinely below a threshold is 5e-5 away."""
FAULTS = {
    "follow_renamed_upstream_branch": "branch\\_renamed",
    "keep_uncommitted_work_and_sync": "dirty\\_tree",
    "sync_fork_with_upstream": "diverged",
    "sync_through_a_conflicting_lockfile": "lockfile\\_conflict",
    "restore_submodule_state": "submodule\\_moved",
}


def _matched(primary: Path) -> tuple[float, int, int, int, int]:
    """The run's own matched point: arm 2's threshold, fires and wrong; arm 3's fires and
    wrong."""
    text = primary.read_text("utf-8")
    arm3 = re.search(r"coverage (\d+)/400, mismatch (\d+)/\d+", text)
    arm2 = re.search(r"threshold ([0-9.]+)\) has mismatch (\d+)/(\d+)", text)
    assert arm3 is not None and arm2 is not None, primary
    return (
        float(arm2.group(1)),
        int(arm2.group(3)),
        int(arm2.group(2)),
        int(arm3.group(1)),
        int(arm3.group(2)),
    )


def _pairs(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def per_fault() -> str:
    """Arm 3, lexical and reranker arm 2 at their matched thresholds, by intent, summed over the
    three libraries; each library's totals checked against its committed Figure 1."""
    cells: dict[tuple[str, str, str], list[int]] = {}
    for run in RUNS:
        for scorer, primary in (
            ("lexical", REPLICATES / run / "primary" / "primary.txt"),
            (
                "cross-encoder",
                REPLICATES / run / "rescore-cross-encoder" / "primary" / "primary.txt",
            ),
        ):
            threshold, fires2, wrong2, fires3, wrong3 = _matched(primary)
            totals = Counter()
            for row in _pairs(HYBRID / run / scorer / "pairs.jsonl"):
                pair = row["pair"]
                kind = "positive" if row["environment"] != "fault-free" else "negative"
                acceptable = set(pair["acceptable_variants"])
                variant = {p["id"]: p["variant"] for p in row["ranked"]}
                assert pair["intent"] in FAULTS, pair["intent"]
                key = (pair["intent"], kind)
                if scorer == "lexical":
                    fired = variant[row["accepted"][0]] if row["accepted"] else None
                    if fired is not None:
                        wrong = fired not in acceptable
                        cells.setdefault((*key, "arm3"), [0, 0])
                        cells[(*key, "arm3")][0] += 1
                        cells[(*key, "arm3")][1] += wrong
                        totals["f3"] += 1
                        totals["w3"] += wrong
                top = row["ranked"][0] if row["ranked"] else None
                if top is not None and top["score"] >= threshold - SCORE_TOLERANCE:
                    wrong = top["variant"] not in acceptable
                    cells.setdefault((*key, scorer), [0, 0])
                    cells[(*key, scorer)][0] += 1
                    cells[(*key, scorer)][1] += wrong
                    totals["f2"] += 1
                    totals["w2"] += wrong
            assert (totals["f2"], totals["w2"]) == (fires2, wrong2), (run, scorer, totals)
            if scorer == "lexical":
                assert (totals["f3"], totals["w3"]) == (fires3, wrong3), (run, totals)

    def cell(key: tuple[str, str, str]) -> str:
        fires, wrong = cells.get(key, [0, 0])
        return f"{fires}, {wrong}"

    lines = [
        "\\begin{tabular}{llccc}",
        "\\toprule",
        "intent's fault & pairs & precondition & lexical & cross-encoder \\\\",
        "\\midrule",
    ]
    for intent, fault in FAULTS.items():
        for kind, label in (("positive", "faulted"), ("negative", "fault-free")):
            lines.append(
                f"{fault if kind == 'positive' else ''} & {label} (120) & "
                f"{cell((intent, kind, 'arm3'))} & {cell((intent, kind, 'lexical'))} & "
                f"{cell((intent, kind, 'cross-encoder'))} \\\\"
            )
    total = {
        name: [
            sum(v[0] for k, v in cells.items() if k[2] == name),
            sum(v[1] for k, v in cells.items() if k[2] == name),
        ]
        for name in ("arm3", "lexical", "cross-encoder")
    }
    lines += [
        "\\midrule",
        "all & 1{,}200 & "
        + " & ".join(f"{total[n][0]}, {total[n][1]}" for n in ("arm3", "lexical", "cross-encoder"))
        + " \\\\",
        "\\bottomrule",
        "\\end{tabular}",
    ]
    return "\n".join(lines) + "\n"


def _floor(summary: Path) -> dict:
    return json.loads(summary.read_text("utf-8"))["arm2_floor"]


def scorers() -> str:
    """Each text scorer's floor and matched point, per library."""
    rows = []
    for name, folder in (
        ("lexical", None),
        ("bi-encoder", "rescore-embedding"),
        ("cross-encoder", "rescore-cross-encoder"),
    ):
        cells = []
        for run in RUNS:
            base = REPLICATES / run if folder is None else REPLICATES / run / folder
            floor = _floor(base / "summary.json")
            _, fires2, wrong2, fires3, wrong3 = _matched(base / "primary" / "primary.txt")
            usable = (
                f"{floor['decided']}/{floor['decidable']} ({floor['lower_bound']:.3f})"
                if floor.get("usable")
                else "not usable"
            )
            difference = wrong2 / fires2 - wrong3 / fires3
            cells.append(f"{usable} & {wrong2}/{fires2} & $+${difference:.2f}")
        rows.append(f"{name} & " + " & ".join(cells) + " \\\\")
    return (
        "\\begin{tabular}{l" + "ccc" * 3 + "}\n\\toprule\n"
        "& \\multicolumn{3}{c}{library 1} & \\multicolumn{3}{c}{library 2} & "
        "\\multicolumn{3}{c}{library 3} \\\\\n"
        "\\cmidrule(lr){2-4}\\cmidrule(lr){5-7}\\cmidrule(lr){8-10}\n"
        "scorer"
        + " & floor & wrong & $\\Delta$" * 3
        + " \\\\\n\\midrule\n"
        + "\n".join(rows)
        + "\n\\bottomrule\n\\end{tabular}\n"
    )


def libraries() -> str:
    """What each build produced and spent."""
    rows = []
    for run in RUNS:
        root = REPLICATES / run / "library-two-sided"
        programs = [
            yaml.safe_load(path.read_text("utf-8")) for path in sorted(root.glob("*/program.yaml"))
        ]
        admitted = [p for p in programs if p.get("status") == "admitted"]
        resolutions = len({(p["id"].split("-occ")[0], p["variant"]) for p in admitted})
        preconditions = sum(len(p["preconditions"]) for p in admitted)
        ledger = _pairs(REPLICATES / run / "build.jsonl")
        tokens = Counter()
        for row in ledger:
            for key in ("uncached_tokens_in", "cached_tokens_in", "tokens_out", "llm_calls"):
                tokens[key] += row.get(key) or 0
        rows.append(
            f"library {int(run[-2:]) - 10} & {len(ledger)} & {len(programs)} & {len(admitted)} & "
            f"{resolutions} & {preconditions / len(admitted):.1f} & {tokens['llm_calls']} & "
            f"{tokens['uncached_tokens_in'] / 1000:.0f}k & "
            f"{tokens['cached_tokens_in'] / 1000:.0f}k & "
            f"{tokens['tokens_out'] / 1000:.0f}k \\\\"
        )
    return (
        "\\begin{tabular}{lccccccccc}\n\\toprule\n"
        "& episodes & compiled & admitted & resolutions & checks/program & calls & "
        "uncached in & cached in & out \\\\\n\\midrule\n"
        + "\n".join(rows)
        + "\n\\bottomrule\n\\end{tabular}\n"
    )


def consequences() -> str:
    """What each replayed fire left, from each run's summary."""
    rows = []
    for run in RUNS:
        text = (CONSEQUENCES / run / "summary.txt").read_text("utf-8")

        def counts(label: str) -> dict[str, int]:
            line = re.search(rf"{label}: (\d+) fires -- (.*)", text)
            if line is None:
                return {"fires": 0}
            found = {"fires": int(line.group(1))}
            for amount, outcome in re.findall(r"(?:^|, )?(\w[\w ]*?) (\d+)", line.group(2)):
                found[amount] = int(outcome)
            return found

        arm3 = counts("arm3/correct")
        right = counts("arm2/correct")
        wrong = counts("arm2/wrong")
        rows.append(
            f"library {int(run[-2:]) - 10} & {arm3['fires']} & {arm3.get('fixed', 0)} & "
            f"{arm3.get('not fixed', 0)} & {right['fires']} & {right.get('fixed', 0)} & "
            f"{wrong['fires']} & {wrong.get('fixed', 0)} & {wrong.get('not fixed', 0)} & "
            f"{wrong.get('nothing ran', 0)} & {wrong.get('unchanged', 0)} \\\\"
        )
    return (
        "\\begin{tabular}{l" + "c" * 10 + "}\n\\toprule\n"
        "& \\multicolumn{3}{c}{precondition, right choices} & "
        "\\multicolumn{2}{c}{lexical, right} & \\multicolumn{5}{c}{lexical, wrong choices} \\\\\n"
        "\\cmidrule(lr){2-4}\\cmidrule(lr){5-6}\\cmidrule(lr){7-11}\n"
        "& fires & fixed & not & fires & fixed & fires & fixed & not & nothing ran & "
        "unchanged \\\\\n"
        "\\midrule\n" + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n"
    )


def probe_cost() -> str:
    """Checks evaluated per request, by how programs are tried."""
    import csv

    labels = (
        ("arm 3, every program", "all", "lexical", "every program"),
        ("arm 3, lazy (specificity order)", "all", "lexical", "lazy, most specific first"),
        ("lazy hybrid (text order)", "all", "lexical", "lazy, lexical order"),
        ("lazy hybrid (text order)", "all", "cross-encoder", "lazy, reranker order"),
        ("lazy hybrid (text order)", "3", "cross-encoder", "reranker order, $k=3$"),
    )
    rows = []
    for dispatcher, k, scorer, label in labels:
        cells = []
        for run in RUNS:
            with (HYBRID / run / scorer / "probe_cost.csv").open(encoding="utf-8") as handle:
                row = next(
                    r
                    for r in csv.DictReader(handle)
                    if r["dispatcher"] == dispatcher and r["k"] == k
                )
            saved = float(row["saved_vs_every_program"])
            cells.append(
                f"{float(row['predicates_per_pair']):.1f} & {row['fires']}, {row['wrong']} & "
                f"{saved:.0%}".replace("%", "\\%")
            )
        rows.append(f"{label} & " + " & ".join(cells) + " \\\\")
    return (
        "\\begin{tabular}{l" + "ccc" * 3 + "}\n\\toprule\n"
        "& \\multicolumn{3}{c}{library 1} & \\multicolumn{3}{c}{library 2} & "
        "\\multicolumn{3}{c}{library 3} \\\\\n"
        "\\cmidrule(lr){2-4}\\cmidrule(lr){5-7}\\cmidrule(lr){8-10}\n"
        "programs tried"
        + " & checks & fires, wrong & saved" * 3
        + " \\\\\n\\midrule\n"
        + "\n".join(rows)
        + "\n\\bottomrule\n\\end{tabular}\n"
    )


def repositories() -> str:
    """Stage B by repository: what maintainers did, and how precondition dispatch fared."""
    manifest = json.loads((STAGE_B / "manifest.json").read_text("utf-8"))
    labels = {row["index"]: row for row in _pairs(STAGE_B / "labels.jsonl")}
    decided = {row["index"]: row for row in _pairs(STAGE_B / "decisions.jsonl")}
    report = json.loads((STAGE_B / "report.json").read_text("utf-8"))
    rows = []
    check = Counter()
    for repository in manifest["repositories"]:
        cases = [c for c in manifest["cases"] if c["repo"] == repository["repo"]]
        if not cases:
            continue
        conflicted = [c for c in cases if c["kind"] == "positive"]
        clean = [c for c in cases if c["kind"] == "negative"]
        classes = Counter(labels[c["index"]]["descriptive"] for c in conflicted)
        upstream_like = sum(
            classes[name]
            for name in ("took upstream", "matches take_upstream", "matches keep_local")
        )
        fires_conflicted = [
            sum(decided[c["index"]]["arm3"][r] is not None for c in conflicted) for r in range(3)
        ]
        right_clean = [
            sum(decided[c["index"]]["arm3"][r] in labels[c["index"]]["acceptable"] for c in clean)
            for r in range(3)
        ]
        for r in range(3):
            check[("fires_conflicted", r)] += fires_conflicted[r]
            check[("right_clean", r)] += right_clean[r]
        rows.append(
            f"{repository['repo'].replace('_', chr(92) + '_')} & "
            f"{len(conflicted)} & {len(clean)} & "
            f"{classes['regenerated']} & {classes['other']} & {classes['took local']} & "
            f"{upstream_like} & "
            + " / ".join(str(x) for x in fires_conflicted)
            + " & "
            + " / ".join(str(x) for x in right_clean)
            + " \\\\"
        )
    for r, replicate in enumerate(report["figures"]["replicates"]):
        # The run's own counts: fires on conflicted cases, and wrong fires overall, which on
        # clean cases are the fires that were not right.
        assert check[("fires_conflicted", r)] == replicate["arm3_fires_on_positives"], check
        fired_clean = sum(
            decided[c["index"]]["arm3"][r] is not None
            for c in manifest["cases"]
            if c["kind"] == "negative"
        )
        right_conflicted = sum(
            decided[c["index"]]["arm3"][r] in labels[c["index"]]["acceptable"]
            for c in manifest["cases"]
            if c["kind"] == "positive"
        )
        wrong = (
            check[("fires_conflicted", r)]
            - right_conflicted
            + fired_clean
            - check[("right_clean", r)]
        )
        assert wrong == replicate["arm3"]["mismatch"]["numerator"], (wrong, replicate["arm3"])
    return (
        "\\begin{tabular}{lcccccccc}\n\\toprule\n"
        "& & & \\multicolumn{4}{c}{maintainer's resolution of the conflicts} & "
        "\\multicolumn{2}{c}{precondition dispatch, per library} \\\\\n"
        "\\cmidrule(lr){4-7}\\cmidrule(lr){8-9}\n"
        "repository & conflicted & clean & regenerated & other & took local & upstream-like & "
        "fires on conflicts & right on clean \\\\\n\\midrule\n"
        + "\n".join(rows)
        + "\n\\bottomrule\n\\end{tabular}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, build in (
        ("per-fault", per_fault),
        ("scorers", scorers),
        ("libraries", libraries),
        ("consequences", consequences),
        ("probe-cost", probe_cost),
        ("repositories", repositories),
    ):
        (args.out / f"{name}.tex").write_text(build(), encoding="utf-8")


if __name__ == "__main__":
    main()
