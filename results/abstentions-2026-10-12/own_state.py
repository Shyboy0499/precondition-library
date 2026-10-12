"""Do each admitted program's preconditions hold on the state it was learned on?

Admission's positive side replays a program (body and postconditions) on its learning state but
does not evaluate its preconditions there, so a program whose preconditions never hold can be
admitted. This checks every admitted program in the three committed libraries. No model call.

Usage, from the repository root: `python results/abstentions-2026-10-12/own_state.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

from precondition_library.library import Library
from precondition_library.program import ProgramStatus
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.tasks.faults import build_sandbox

RUNS = Path(__file__).resolve().parents[1] / "replicates-2026-10-05"


def main() -> None:
    for run in (11, 12, 13):
        library = Library(RUNS / f"run-{run}" / "library-two-sided")
        for program in library.load_all():
            if program.status is not ProgramStatus.ADMITTED:
                continue
            match = re.search(r"seed-(\d+)-", program.provenance.episode_id)
            assert match, f"no learning seed in {program.provenance.episode_id!r}"
            seed, fault = int(match.group(1)), program.provenance.fault
            box = build_sandbox(seed, [fault])
            try:
                held = evaluate_preconditions(program, box)
            finally:
                box.destroy()
            failed = ", ".join(p.name for p in held.predicates if not p.ok) or "-"
            print(
                f"run-{run}\t{program.id}\t{fault}\tseed {seed}\t{program.variant}\t"
                f"{'holds' if held.ok else 'DOES NOT HOLD'}\t{failed}"
            )


if __name__ == "__main__":
    main()
