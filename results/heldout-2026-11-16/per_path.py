"""Arm 3's fires and wrong fires on the held-out lock-file states, by the lock file's path.

    PYTHONPATH=src python results/heldout-2026-11-16/per_path.py > per_path.json

The held-out stage reports each library's fires and wrong fires; this splits them by the four
held-out paths, so a library that never fired on a spaced path cannot pass for one that fired
there correctly. Each of the 40 held-out states (seeds 3000-3039) is built once and decided by
every library through its own matcher, as the stage decides it, and a fire is wrong when it is
not among the state's acceptable resolutions. No model is called. Each library's totals must
equal its `summary.txt`.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from precondition_library.library import Library
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.faults.lockfile_conflict import lock_path_for_seed
from precondition_library.tasks.registry import INTENTS

ROOT = Path(__file__).resolve().parents[2]
RUNS = [
    "results/replicates-2026-11-15/run-14",
    "results/replicates-2026-11-15/run-15",
    *(f"results/refusal-population-2026-11-15/builds/{c}-{i}" for c in "0R" for i in range(10)),
]


def main() -> None:
    libraries = {
        Path(run).name: Library(
            ROOT / run / "library-two-sided", evaluate_preconditions=evaluate_preconditions
        )
        for run in RUNS
    }
    intent = next(i for i in INTENTS.values() if i.fault == "lockfile_conflict")
    tally: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for seed in range(3000, 3040):
        box = build_sandbox(seed, ["lockfile_conflict"])
        try:
            acceptable = intent.acceptable_variants(StateFingerprint.observe(box))
            path = lock_path_for_seed(seed)
            for name, library in libraries.items():
                accepted = library.match_preconditions(box)
                if accepted:
                    tally[name][path][0] += 1
                    tally[name][path][1] += int(accepted[0].variant not in acceptable)
        finally:
            box.destroy()
        print(seed, path, file=sys.stderr, flush=True)
    rows = {
        name: {path: {"fires": f, "wrong": w} for path, (f, w) in sorted(by.items())}
        for name, by in sorted(tally.items())
    }
    print(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
