"""The blind labelling kit (#299 step 3, `bench.human_labels`): cards, the private key, scoring."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from precondition_library.bench import human_labels as hl
from precondition_library.bench.library_pairs import _measured_intents


def test_every_measured_resolution_has_neutral_wording() -> None:
    from precondition_library.bench.heldout import HELD_OUT_FAULTS

    for intent in _measured_intents(HELD_OUT_FAULTS):
        assert set(hl.ACTIONS[intent.name]) == {v.id for v in intent.variants}
        for variant in intent.variants:
            wording = hl.ACTIONS[intent.name][variant.id]
            assert variant.rationale not in wording, "an option must not say why it is right"


def test_kappa_by_hand() -> None:
    assert hl.kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    # Observed 0.5; each rater says a half the time, so expected agreement is 0.5 too.
    assert hl.kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert hl.kappa(["a", "a"], ["a", "a"]) is None, "one category throughout: undefined"
    with pytest.raises(ValueError):
        hl.kappa(["a"], [])


def _kit(tmp_path: Path, salt: str = "test-salt") -> tuple[Path, Path, list[hl.Card]]:
    cards, key = tmp_path / "cards", tmp_path / "private" / "key.json"
    made = hl.make(cards, key, salt, faulted=1, fault_free=1, faults=("dirty_tree",), seeds=(2000,))
    return cards, key, made


def test_a_kit_is_blind(tmp_path: Path) -> None:
    cards, key, made = _kit(tmp_path)
    assert len(made) == 2 and key.is_file()
    assert sorted(p.name for p in cards.iterdir()) == sorted(
        [f"{c.id}.md" for c in made] + ["answers.csv"]
    )
    for card in made:
        text = (cards / f"{card.id}.md").read_text()
        assert card.intent not in text and card.environment not in text
        assert "Answer with one letter" in text
        assert set(card.options.values()) == {"stash", "commit", "aside", hl.NOTHING, hl.UNSAFE}
    labels = {c.environment: c.label for c in made}
    assert labels["fault-free"] == hl.NOTHING and labels["dirty_tree"] != hl.NOTHING


def test_ids_and_order_depend_on_the_salt(tmp_path: Path) -> None:
    _, _, first = _kit(tmp_path / "a", "one salt")
    _, _, second = _kit(tmp_path / "b", "another salt")
    assert {c.id for c in first}.isdisjoint({c.id for c in second})


def test_a_kit_refuses_without_a_salt_or_with_the_key_among_the_cards(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="salt"):
        hl.make(tmp_path / "c", tmp_path / "k.json", "", faulted=1, fault_free=1)
    with pytest.raises(ValueError, match="key"):
        hl.make(tmp_path / "c", tmp_path / "c" / "k.json", "s", faulted=1, fault_free=1)


def _key(tmp_path: Path) -> Path:
    cards = [
        hl.Card(
            id=f"c{i}",
            intent="sync_fork_with_upstream",
            environment="x",
            seed=i,
            label=label,
            acceptable=acceptable,
            options={"A": "rebase", "B": "merge", "C": hl.NOTHING, "D": hl.UNSAFE},
        )
        for i, (label, acceptable) in enumerate(
            [("rebase", ["rebase", "merge"]), ("merge", ["merge"]), (hl.NOTHING, [hl.NOTHING])]
        )
    ]
    path = tmp_path / "key.json"
    path.write_text(json.dumps([c.model_dump() for c in cards]))
    return path


def _sheet(tmp_path: Path, name: str, answers: dict[str, str]) -> Path:
    path = tmp_path / f"{name}.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["card", "answer"])
        writer.writerows(answers.items())
    return path


def test_scoring(tmp_path: Path) -> None:
    key = _key(tmp_path)
    ann = _sheet(tmp_path, "ann", {"c0": "B", "c1": "B", "c2": "c"})
    bob = _sheet(tmp_path, "bob", {"c0": "A", "c1": "D", "c2": ""})
    scores = hl.score(key, [ann, bob])
    by = {r.rater: r for r in scores.raters}
    assert (by["ann"].answered, by["ann"].agrees_with_rules) == (3, 3), "merge is acceptable on c0"
    assert (by["bob"].answered, by["bob"].agrees_with_rules) == (2, 1), "a blank is left out"
    assert by["bob"].disagreements == [
        {"card": "c1", "intent": "sync_fork_with_upstream", "answered": hl.UNSAFE, "rules": "merge"}
    ]
    assert scores.pairwise_kappa["ann ~ bob"] == hl.kappa(["merge", "merge"], ["rebase", hl.UNSAFE])
    with pytest.raises(ValueError, match="not an option"):
        hl.score(key, [_sheet(tmp_path, "eve", {"c0": "Z"})])
