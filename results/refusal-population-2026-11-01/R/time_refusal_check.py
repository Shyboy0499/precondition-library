"""How long configuration R's refusal check takes, measured on the frozen R (ADR-0054 item 3).

Each admitted program of one committed library (replicate 2, `run-12`) is put through
`RefusalStates.accepted_by`, the check a configuration R build runs on every candidate that
passes the two-sided gate. The time per program is what a build pays per such candidate.

    python results/refusal-population-2026-11-01/R/time_refusal_check.py

Writes `timing.json` beside this script. Which programs R accepts is recorded too, as a
description of these old programs; it decides nothing, and study 2's builds are new ones.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from precondition_library.bench.preregistration import REPOSITORY
from precondition_library.bench.refusal_set import RefusalStates
from precondition_library.library import Library
from precondition_library.program import ProgramStatus

HERE = Path(__file__).resolve().parent
LIBRARY = REPOSITORY / "results" / "replicates-2026-10-05" / "run-12" / "library-two-sided"


def main() -> None:
    states = RefusalStates(HERE)
    programs = [p for p in Library(LIBRARY).load_all() if p.status is ProgramStatus.ADMITTED]
    rows = []
    for program in programs:
        started = time.perf_counter()
        accepted, error = states.accepted_by(program)
        seconds = time.perf_counter() - started
        rows.append(
            {
                "program": program.id,
                "variant": program.variant,
                "seconds": round(seconds, 1),
                "accepted": [name for name, _ in accepted],
                "error": error,
            }
        )
        print(f"{seconds:7.1f}s  {len(accepted):2d} accepted  {program.id}", flush=True)
    seconds = [row["seconds"] for row in rows]
    summary = {
        "refusal_set": states.digest,
        "states": len(states),
        "library": str(LIBRARY.relative_to(REPOSITORY)),
        "programs": len(rows),
        "seconds_per_program": {
            "mean": round(sum(seconds) / len(seconds), 1),
            "min": min(seconds),
            "max": max(seconds),
        },
        "programs_refusing_every_state": sum(
            not row["accepted"] and not row["error"] for row in rows
        ),
        "rows": rows,
    }
    (HERE / "timing.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
