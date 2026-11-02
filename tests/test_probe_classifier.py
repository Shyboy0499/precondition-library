"""A tree over only a library's precondition verdicts (#295 item 3, `bench.probe_classifier`)."""

from __future__ import annotations

from dataclasses import dataclass

from precondition_library.bench import probe_classifier as pc
from precondition_library.bench.preregistration import REPOSITORY
from precondition_library.bench.real_merges import LIBRARIES
from precondition_library.library import Library
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.tasks.faults import build_sandbox


def _view() -> pc.ProbeView:
    return pc.ProbeView(REPOSITORY / LIBRARIES[0])


def test_each_distinct_precondition_is_one_feature() -> None:
    view = _view()
    every = [p for program in view.programs for p in program.preconditions]
    assert view.programs and len(view.predicates) <= len(every)
    assert set(view.predicates) == {pc.key(p) for p in every}
    first = every[0]
    renamed = first.model_copy(update={"name": "another name", "description": "other words"})
    assert pc.key(renamed) == pc.key(first), "a precondition is what it runs, not what it is called"


def test_arm3_is_the_most_specific_program_whose_preconditions_all_hold() -> None:
    view = _view()
    everything = dict.fromkeys(view.predicates, True)
    expected = sorted(view.programs, key=lambda p: (-len(p.preconditions), p.id))[0]
    assert view.arm3(everything) == expected.variant
    assert len(expected.preconditions) == max(len(p.preconditions) for p in view.programs)
    assert view.arm3(dict.fromkeys(view.predicates, False)) is None or any(
        not p.preconditions for p in view.programs
    )


def test_arm3_from_verdicts_is_the_librarys_own_matcher() -> None:
    view = _view()
    library = Library(view.root, evaluate_preconditions=evaluate_preconditions)
    box = build_sandbox(2000, ["dirty_tree"])
    try:
        accepted = library.match_preconditions(box)
        assert view.arm3(view.verdicts(box)) == (accepted[0].variant if accepted else None)
    finally:
        box.destroy()


@dataclass
class _Variant:
    id: str


@dataclass
class _Intent:
    """Stands in for an `IntentSpec`: its rule fires `fix` when probes a and b both hold."""

    name: str = "intent"

    def correct_variant(self, state: dict[str, bool]) -> _Variant | None:
        return _Variant("fix") if state["a"] and state["b"] else None


def test_the_trees_learn_a_rule_over_the_verdicts() -> None:
    grid = [{"a": a, "b": b, "c": c} for a in (False, True) for b in (False, True) for c in (0, 1)]
    trees = pc.ProbeTrees([_Intent()]).fit([(v, v) for v in grid])  # type: ignore[list-item]
    intent = _Intent()
    for verdicts in grid:
        fired, probability = trees.decide(intent, verdicts)  # type: ignore[arg-type]
        assert fired == ("fix" if verdicts["a"] and verdicts["b"] else None)
        assert probability == 1.0
    assert trees.depths() == {"intent": 2}


def test_a_tree_never_fires_a_variant_its_library_holds_no_program_for() -> None:
    grid = [{"a": a, "b": b} for a in (False, True) for b in (False, True)]
    trees = pc.ProbeTrees([_Intent()], allowed={"other"}).fit([(v, v) for v in grid])  # type: ignore[list-item]
    assert all(trees.decide(_Intent(), v)[0] is None for v in grid)  # type: ignore[arg-type]
