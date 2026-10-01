"""The committed gold resolutions, loaded as the oracle floor's programs (issue #7).

The hand-written gold scripts in the repository's ``bench/gold/`` directory are
the zero-token oracle: for each measurable fault they give the correct
resolution for every state the fault can inject, written and checked by a human
before any agent result was believed (the spec's gold-first rule). Issue #7 adds
an arm that runs them -- consulting ground truth to pick which one -- so the
benchmark has a floor that bounds success from above and cost from below.

This module is the one place package code reads those files. It is kept separate
from `bench.run` so the loader can be tested on its own and so the oracle arm
receives its programs the way arm 2 receives its `similarity` seam and the run
receives its `provider`: injected, not reached for. The files live at the
repository root rather than inside the installed package because they are
research fixtures shared with the tests (`tests/conftest.py` reads the same
directory); this repository is run from its source tree, as its own CI does.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..program import Program

GOLD_DIR = Path(__file__).resolve().parents[3] / "bench" / "gold"
"""The repository's hand-written resolutions. `parents[3]` is the repository root
(`bench/gold.py` -> `bench` -> `precondition_library` -> `src` -> root), the same
root `sandbox.py` reaches for `.sandboxes/`."""


def _load_file(path: Path) -> list[Program]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Program.model_validate(entry) for entry in document["programs"]]


def load_gold_programs(directory: Path = GOLD_DIR) -> dict[str, dict[str, Program]]:
    """Every committed gold resolution, indexed by ``fault`` then ``variant``.

    The fault is read from each program's `provenance.fault` and the variant from
    `Program.variant`, so the index matches how the benchmark selects: a run names
    a `fault_type` and ground truth names a variant. A gold file is keyed by its
    intent, but the oracle dispatches on the fault, so the fault is the outer key.

    Raises if two gold programs share a (fault, variant) -- the oracle must have
    exactly one resolution for each -- or if a gold program declares no variant,
    which an intent with two or more resolutions forbids anyway. A missing
    directory raises `FileNotFoundError` rather than returning an empty index: an
    oracle with no programs is a configuration error, not an empty result.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"no gold directory at {directory}")
    index: dict[str, dict[str, Program]] = {}
    for path in sorted(directory.glob("*.yaml")):
        for program in _load_file(path):
            if program.variant is None:
                raise ValueError(
                    f"gold program {program.id!r} in {path.name} declares no variant, so the "
                    f"oracle cannot key it; every gold resolution must name its variant"
                )
            fault = program.provenance.fault
            by_variant = index.setdefault(fault, {})
            if program.variant in by_variant:
                raise ValueError(
                    f"two gold programs for fault {fault!r} variant {program.variant!r} "
                    f"({by_variant[program.variant].id!r} and {program.id!r}); the oracle "
                    f"needs exactly one resolution per (fault, variant)"
                )
            by_variant[program.variant] = program
    return index
