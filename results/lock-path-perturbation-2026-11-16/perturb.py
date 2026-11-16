"""Would a build-time check at unseen lock-file paths have refused build 0-4's merge program?

Builds `lockfile_conflict` states at shipped seeds, with the lock file moved to a path neither the
shipped seeds nor the held-out block uses. Then, in every committed two-sided library, runs every
admitted program's preconditions on each state, exactly as admission's negative side and arm 3
would. Admission's two-sided rule requires a program compiled for another fault to refuse the
state. So a program from another family that fires here is one that such a check would have
refused.

Run from the repository root (no model call, no network):

    PYTHONPATH=src python results/lock-path-perturbation-2026-11-16/perturb.py > perturb.json
"""

import json
import sys
from pathlib import Path

from precondition_library.library import Library
from precondition_library.program import ProgramStatus
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.tasks.faults import build_sandbox, lockfile_conflict

# Two kinds of unseen path. The first four keep the `.lock` suffix under a name no build saw
# (one of them non-ASCII, one in a directory with a space, one a dotfile); the last two drop it,
# which no shipped or held-out state does.
PATHS = (
    "lib/Zuordnung.lock",
    "lib/Übersicht.lock",
    "deps/.packages.lock",
    "tools/build cache/state.lock",
    "deps-lock.txt",
    "packages.lockfile",
)
# One shipped seed per live state of the fault (`lockfile_conflict.INJECTED_STATES`).
SEEDS_PER_STATE = 1


def seeds() -> list[int]:
    chosen: dict[str, int] = {}
    seed = 0
    while len(chosen) < len(lockfile_conflict.INJECTED_STATES):
        chosen.setdefault(lockfile_conflict.state_for_seed(seed), seed)
        seed += 1
    return sorted(chosen.values())


def libraries() -> list[Path]:
    roots = sorted(Path("results/refusal-population-2026-11-15/builds").glob("*/library-two-sided"))
    roots += sorted(Path("results/replicates-2026-11-15").glob("*/library-two-sided"))
    roots += sorted(Path("results/replicates-2026-10-05").glob("*/library-two-sided"))
    return [r for r in roots if r.is_dir()]


def main() -> None:
    loaded = []
    for root in libraries():
        library = Library(root, evaluate_preconditions=evaluate_preconditions)
        admitted = [p for p in library.load_all() if p.status is ProgramStatus.ADMITTED]
        loaded.append((root, library.library_hash(), admitted))

    shipped = lockfile_conflict.lock_path_for_seed
    rows = []
    try:
        for path in PATHS:
            lockfile_conflict.lock_path_for_seed = lambda seed, path=path: path
            for seed in seeds():
                box = build_sandbox(seed, ["lockfile_conflict"])
                try:
                    for root, _, admitted in loaded:
                        for program in admitted:
                            if evaluate_preconditions(program, box).ok:
                                rows.append(
                                    {
                                        "path": path,
                                        "seed": seed,
                                        "state": lockfile_conflict.state_for_seed(seed),
                                        "library": str(root),
                                        "program": program.id,
                                        "family": program.provenance.fault,
                                        "variant": program.variant,
                                    }
                                )
                finally:
                    box.destroy()
                print(f"{path} seed {seed}: done", file=sys.stderr, flush=True)
    finally:
        lockfile_conflict.lock_path_for_seed = shipped

    for root, digest, _ in loaded:
        assert Library(root).library_hash() == digest, f"{root} changed while it was read"
    json.dump(
        {
            "paths": PATHS,
            "seeds": seeds(),
            "libraries": [str(root) for root, _, _ in loaded],
            "fires": rows,
        },
        sys.stdout,
        indent=1,
        ensure_ascii=False,
    )
    print()


if __name__ == "__main__":
    main()
