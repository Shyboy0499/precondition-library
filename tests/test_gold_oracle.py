"""The gold oracle floor: the ground-truth variant replayed for zero tokens (issue #7).

`Arm.GOLD` is the zero-token oracle floor (ADR-0014). It is an oracle on purpose:
it reads the state's correct variant and replays that variant's hand-written gold
program, so its success bounds what any arm could reach and its cost bounds the
cheapest an arm could be. These tests pin the three facts that make it a floor
rather than a fourth dispatcher:

* it never consults the model -- a `FakeProvider` with an empty queue raises if
  it is called, so a hidden call fails the test;
* it fires the ground-truth variant on every state, so it cannot misfire; and
* a run is refused up front unless the gold set covers every measured variant,
  so a gap is a configuration error rather than a silent dent in the floor.

Everything here is offline: the sandboxes are real and fault-injected, the gold
programs are the committed ones, and no key is needed because no model runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeProvider

from precondition_library.bench.gold import load_gold_programs
from precondition_library.bench.ledger import Arm, OccurrenceRole, read
from precondition_library.bench.run import run_benchmark, run_episode
from precondition_library.library import Library
from precondition_library.program import EpisodeOutcome
from precondition_library.runtime.probes import evaluate_preconditions

# diverged seed -> the variant its injected state requires (conftest.GOLD_CASES).
_DIVERGED_STATES = {1: "discard", 2: "rebase", 0: "merge"}


def _empty_library(path: Path) -> Library:
    return Library(path, evaluate_preconditions=evaluate_preconditions)


def _silent_provider() -> FakeProvider:
    """A provider that fails the test if the oracle calls the model at all."""
    return FakeProvider(raises=AssertionError("the gold oracle must not call the model"))


def test_load_gold_programs_indexes_by_fault_then_variant() -> None:
    index = load_gold_programs()
    assert set(index["diverged"]) == {"discard", "rebase", "merge"}
    assert set(index["submodule_moved"]) == {"init", "repin", "remove"}
    # The index key is the provenance fault, and each entry is the gold program
    # for that (fault, variant) -- so the variant it names matches its own key.
    for by_variant in index.values():
        for variant, program in by_variant.items():
            assert program.variant == variant


def test_gold_replays_the_correct_variant_for_zero_tokens(tmp_path: Path) -> None:
    gold = load_gold_programs()["diverged"]
    provider = _silent_provider()

    record = run_episode(
        Arm.GOLD,
        "diverged",
        1,  # empty_local_commits -> discard
        1,
        role=OccurrenceRole.VARIANT,
        provider=provider,
        library=_empty_library(tmp_path / "lib"),
        model="fake",
        gold_variants=gold,
    )

    assert provider.calls == [], "the oracle consulted the model"
    assert record.llm_calls == 0
    assert record.tokens_in == 0 and record.tokens_out == 0
    assert record.outcome is EpisodeOutcome.SUCCESS
    assert record.succeeded is True
    # It fired the ground-truth variant, so it cannot be a misfire.
    assert record.correct_variant == "discard"
    assert record.fired_variant == "discard"
    assert record.misfired is False
    assert record.program_id == gold["discard"].id
    # It has no library and no score, exactly as arm 1 has none.
    assert record.dispatch_score is None
    assert record.admission_gate is None


@pytest.mark.parametrize("seed,variant", sorted(_DIVERGED_STATES.items()))
def test_gold_fires_the_ground_truth_variant_on_every_state(
    tmp_path: Path, seed: int, variant: str
) -> None:
    """Across all three diverged states the oracle fires the correct variant."""
    gold = load_gold_programs()["diverged"]

    record = run_episode(
        Arm.GOLD,
        "diverged",
        seed,
        1,
        role=OccurrenceRole.VARIANT,
        provider=_silent_provider(),
        library=_empty_library(tmp_path / f"lib-{seed}"),
        model="fake",
        gold_variants=gold,
    )

    assert record.correct_variant == variant
    assert record.fired_variant == variant
    assert record.misfired is False
    assert record.outcome is EpisodeOutcome.SUCCESS
    assert record.llm_calls == 0


def test_run_benchmark_refuses_a_gold_arm_with_an_incomplete_set(tmp_path: Path) -> None:
    """A gold set missing a variant the fault can require is refused before any episode."""
    gold = load_gold_programs()
    partial = {"diverged": {"discard": gold["diverged"]["discard"]}}  # drops rebase, merge

    with pytest.raises(ValueError, match="no resolution for fault 'diverged'"):
        run_benchmark(
            arms=[Arm.GOLD],
            faults=["diverged"],
            occurrences=1,
            seeds=[1],
            out=tmp_path / "ledger.jsonl",
            model="fake",
            provider=_silent_provider(),
            gold_programs=partial,
        )


def test_run_benchmark_writes_zero_token_oracle_rows(tmp_path: Path) -> None:
    """A whole gold-arm run over the diverged states writes only zero-token rows."""
    out = run_benchmark(
        arms=[Arm.GOLD],
        faults=["diverged"],
        occurrences=3,
        seeds=[1, 2, 0],  # discard, rebase, merge
        out=tmp_path / "ledger.jsonl",
        model="fake",
        provider=_silent_provider(),
    )

    rows = read(out)
    assert len(rows) == 3
    for row in rows:
        assert row.arm is Arm.GOLD
        assert row.llm_calls == 0
        assert row.tokens_in == 0 and row.tokens_out == 0
        assert row.misfired is False
        assert row.outcome is EpisodeOutcome.SUCCESS
        assert row.fired_variant == _DIVERGED_STATES[row.seed]
