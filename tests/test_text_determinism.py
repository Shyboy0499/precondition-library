"""A reported episode must be reproducible from its seed alone.

Sampling the request text is the one place this project introduces randomness, so
it is the one place a run could differ from its own record.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from precondition_library.tasks.intent import IntentSpec, ResolutionVariant, sample_index


def test_sample_index_is_stable_and_in_range() -> None:
    for seed in range(50):
        value = sample_index(seed, "salt", 7)
        assert 0 <= value < 7
        assert value == sample_index(seed, "salt", 7)


def test_sample_index_rejects_empty_range() -> None:
    with pytest.raises(ValueError, match="n must be positive"):
        sample_index(1, "salt", 0)


@pytest.mark.skip(reason="the intent registry lands in Task 7; un-skipped there")
def test_same_seed_same_text() -> None:
    from precondition_library.tasks.registry import ambiguous_intents

    for intent in ambiguous_intents():
        assert intent.task_text(11) == intent.task_text(11)


@pytest.mark.skip(reason="the intent registry lands in Task 7; un-skipped there")
def test_text_does_not_depend_on_process_hash_seed() -> None:
    """CPython salts `hash()` for strings per process.

    If the sampler used `hash()`, the same seed would produce different task text
    in a different run and a reported episode would not be reproducible. This runs
    the sampler in two subprocesses with different hash seeds and compares.
    """
    code = (
        "from precondition_library.tasks.registry import ambiguous_intents;"
        "print([i.task_text(7) for i in ambiguous_intents()])"
    )
    runs = [
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            check=True,
        ).stdout
        for seed in ("0", "1")
    ]
    assert runs[0] == runs[1]


def test_intent_rejects_duplicate_variant_ids() -> None:
    variant = ResolutionVariant(id="only", decided_by=lambda state: True, rationale="test fixture")
    with pytest.raises(ValueError, match="duplicate variant ids"):
        IntentSpec(
            name="dupe",
            fault="diverged",
            phrasings=["do the thing"],
            naming_markers=[],
            variants=[variant, variant],
        )


def test_intent_rejects_missing_parts() -> None:
    variant = ResolutionVariant(id="v", decided_by=lambda state: True, rationale="r")
    with pytest.raises(ValueError, match="needs at least one phrasing"):
        IntentSpec(name="x", fault="f", phrasings=[], naming_markers=[], variants=[variant])
    with pytest.raises(ValueError, match="needs at least one resolution variant"):
        IntentSpec(name="x", fault="f", phrasings=["p"], naming_markers=[], variants=[])
