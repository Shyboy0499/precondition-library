"""Lazy dispatch's probe bill (issue #265): the walks' arithmetic, and that they decide as priced.

Most tests use hand-built records, because a lazy walk is arithmetic over a pair's accepted set and
text ranking. One prices the gold library's real record from the hybrid stage, end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import gold_programs

from precondition_library.bench.hybrid import run_hybrid
from precondition_library.bench.library_pairs import LibraryPair, RankedProgram
from precondition_library.bench.live import LivePlan
from precondition_library.bench.pairs import LabelledPair
from precondition_library.bench.probe_cost import cost_table, read_pairs, write
from precondition_library.library import Library
from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.similarity import lexical_similarity
from precondition_library.tasks.state_grid import declared_state


def _program(program_id: str, variant: str, checks: int) -> Program:
    return Program(
        id=program_id,
        intent="sync my fork",
        preconditions=[
            Predicate(name=f"p{i}", description="holds", probe="true") for i in range(checks)
        ],
        body="true",
        postconditions=[Predicate(name="q", description="holds", probe="true")],
        variant=variant,
        status=ProgramStatus.ADMITTED,
        provenance=Provenance(
            compiled_from_task="a test",
            model="none",
            compiler_version="0.0.0",
            episode_id="test",
            fault="diverged",
        ),
    )


PROGRAMS = [_program("a", "rebase", 3), _program("b", "merge", 2), _program("c", "discard", 1)]
"""Specificity order is a (3 checks), b (2), c (1); arm 3's every-program bill is 6."""


def _pair(accepted: tuple[str, ...], ranked: tuple[str, ...], correct: str | None) -> LibraryPair:
    return LibraryPair(
        pair=LabelledPair(
            intent="sync_fork_with_upstream",
            seed=0,
            state=declared_state(),
            correct_variant=correct,
            acceptable_variants=(correct,) if correct else (),
            task_text="bring my branch up to date",
            ambiguous=True,
            informed=False,
        ),
        environment="diverged" if correct else "fault-free",
        accepted=accepted,
        ranked=tuple(
            RankedProgram(id=i, variant=next(p.variant for p in PROGRAMS if p.id == i), score=1.0)
            for i in ranked
        ),
    )


def test_each_walk_pays_for_what_it_reaches_and_fires_what_it_stands_for() -> None:
    pairs = [
        _pair(
            ("c",), ("c", "a", "b"), "discard"
        ),  # text finds c first; specificity reaches it last
        _pair((), ("a", "b", "c"), None),  # a negative: every walk pays for all it reached
    ]
    rows = {(row.dispatcher, row.k): row for row in cost_table(pairs, PROGRAMS, ks=(1, None))}

    every = rows[("arm 3, every program", None)]
    assert (every.fires, every.wrong, every.predicates_per_pair) == (1, 0, 6.0)
    lazy3 = rows[("arm 3, lazy (specificity order)", None)]
    assert (lazy3.fires, lazy3.predicates_per_pair) == (1, 6.0), "a, b, c on both pairs"
    k1 = rows[("lazy hybrid (text order)", 1)]
    assert (k1.fires, k1.predicates_per_pair) == (1, (1 + 3) / 2)
    assert k1.saved_vs_every_program == pytest.approx(1 - 2 / 6)
    whole = rows[("lazy hybrid (text order)", None)]
    assert (whole.fires, whole.predicates_per_pair) == (1, (1 + 6) / 2)


def test_a_cap_that_stops_before_the_accepted_program_loses_the_fire_not_the_bill() -> None:
    pairs = [_pair(("b",), ("a", "b", "c"), "merge")]
    rows = {(row.dispatcher, row.k): row for row in cost_table(pairs, PROGRAMS, ks=(1,))}
    k1 = rows[("lazy hybrid (text order)", 1)]
    assert (k1.fires, k1.programs_per_pair, k1.predicates_per_pair) == (0, 1.0, 3.0)


def test_lazy_arm_3_fires_exactly_what_arm_3_fires() -> None:
    """Arm 3 fires `accepted[0]`, the most specific program that held; the lazy walk must too."""
    pairs = [_pair(("a", "c"), ("c", "a", "b"), "rebase")]
    rows = {(row.dispatcher, row.k): row for row in cost_table(pairs, PROGRAMS, ks=())}
    assert rows[("arm 3, lazy (specificity order)", None)].wrong == 0
    assert rows[("arm 3, lazy (specificity order)", None)].predicates_per_pair == 3.0


def test_an_empty_record_is_refused_and_the_csv_is_written_fresh(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no pairs"):
        cost_table([], PROGRAMS)
    rows = cost_table([_pair(("a",), ("a",), "rebase")], PROGRAMS, ks=(1,))
    out = tmp_path / "cost.csv"
    write(rows, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(rows) + 1 and lines[0].startswith("dispatcher,k,")
    with pytest.raises(ValueError, match="fresh file"):
        write(rows, out)


def test_the_gold_librarys_real_record_prices_without_a_disagreement(tmp_path: Path) -> None:
    """End to end: the hybrid stage's saved record, priced; every walk's decision is checked."""
    library = Library(tmp_path / "gold", evaluate_preconditions=evaluate_preconditions)
    for program in gold_programs():
        library.add(program.model_copy(update={"status": ProgramStatus.CANDIDATE}))
        library.set_status(program.id, ProgramStatus.ADMITTED)
    out = tmp_path / "hybrid"
    run_hybrid(
        library.root,
        out,
        similarity=lexical_similarity,
        scorer_id={"scorer": "lexical"},
        source="a gold library",
        plan=LivePlan(episodes=False, online=False, faults=["diverged"], pair_seeds=[2000]),
        ks=(1, None),
        plot=False,
    )
    rows = cost_table(read_pairs(out / "pairs.jsonl"), library.load_all(), ks=(1, None))
    every = rows[0]
    lazy3 = rows[1]
    assert lazy3.fires == every.fires and lazy3.wrong == every.wrong
    assert lazy3.predicates_per_pair <= every.predicates_per_pair
    assert all(row.predicates_per_pair <= every.predicates_per_pair for row in rows)
