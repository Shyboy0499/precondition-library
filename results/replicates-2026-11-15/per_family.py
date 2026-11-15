"""Per-family rows for runs 14 and 15 (ADR-0061 decision 2), recomputed from each frozen library.

    PYTHONPATH=src python results/replicates-2026-11-15/per_family.py > per_family.txt

For each run it rebuilds the run's 480 labelled pairs with `bench.library_pairs` -- the code that
made the run's Figure 1, so the totals must equal `summary.txt`'s -- and splits arm 3's and the
lexical arm 2's fires by the family of the pair's intent. Arm 2 is read at the run's matched
threshold, parsed from `summary.txt`. A program admission refused stays in the library directory
as a candidate, so programs are counted both ways. No model is called.
"""

import json
import re
from collections import Counter
from pathlib import Path

from precondition_library.bench.library_pairs import library_pair_outcomes
from precondition_library.library import Library
from precondition_library.program import ProgramStatus
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.tasks.registry import INTENTS

HERE = Path(__file__).resolve().parent
FAMILY = {spec.name: spec.fault for spec in INTENTS.values()}


def fires(outcome, threshold):
    if outcome.fired_variant is None:
        return False
    return threshold is None or (outcome.score is not None and outcome.score >= threshold)


def main() -> None:
    for run in ("run-14", "run-15"):
        d = HERE / run
        plan = json.loads((d / "plan.json").read_text("utf-8"))["plan"]
        summary = (d / "summary.txt").read_text("utf-8")
        threshold = float(
            re.search(r"at matched coverage arm 2 \(threshold ([0-9.e-]+)\)", summary)[1]
        )
        library = Library(d / "library-two-sided", evaluate_preconditions=evaluate_preconditions)
        programs = library.load_all()
        stored = Counter(p.provenance.fault for p in programs)
        admitted = Counter(
            p.provenance.fault for p in programs if p.status is ProgramStatus.ADMITTED
        )
        out = library_pair_outcomes(library, plan["faults"], plan["pair_seeds"])
        rows: dict[str, Counter] = {}
        for pair, a3, a2 in zip(out.pairs, out.arm3, out.arm2, strict=True):
            fam = FAMILY[pair.pair.intent]
            c = rows.setdefault(fam, Counter())
            c["pairs"] += 1
            c["positive"] += pair.pair.correct_variant is not None
            if fires(a3, None):
                c["arm3_fires"] += 1
                c["arm3_wrong"] += not a3.fire_is_right(a3.fired_variant)
            if fires(a2, threshold):
                c["arm2_fires"] += 1
                c["arm2_wrong"] += not a2.fire_is_right(a2.fired_variant)
        print(
            f"{run} ({json.loads((d / 'summary.json').read_text('utf-8'))['model']}), "
            f"library {out.library_hash[:12]}, arm 2 at threshold {threshold:.4f}"
        )
        header = ["family", "admitted/stored", "pairs (positive)", "arm 3 wrong/fires"]
        print("  " + " | ".join([*header, "lexical arm 2 wrong/fires"]))
        total: Counter = Counter()
        for fam in [*sorted(rows), "all"]:
            if fam == "all":
                c, kept, held = total, sum(admitted.values()), sum(stored.values())
            else:
                c, kept, held = rows[fam], admitted.get(fam, 0), stored.get(fam, 0)
                total.update(c)
            cells = [
                fam,
                f"{kept}/{held}",
                f"{c['pairs']} ({c['positive']})",
                f"{c['arm3_wrong']}/{c['arm3_fires']}",
                f"{c['arm2_wrong']}/{c['arm2_fires']}",
            ]
            print("  " + " | ".join(cells))


if __name__ == "__main__":
    main()
