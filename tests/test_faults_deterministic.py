"""Same seed, same faulty environment.

The ablation compares arms on shared environments, so non-determinism in fault
injection would introduce variance that looks like a difference between arms.
Determinism is also what lets a reported episode be re-run and inspected later.

What can run today is the request text: it is a pure function of the seed, and
the two intents that own sampled wording are tested for real. The injected
*state* needs the live sandbox (issue #4), so those tests stay skipped, with the
phase that will implement them named rather than implied.

The three faults not yet converted to intents -- dirty_tree, branch_renamed and
lockfile_conflict -- still return one fixed sentence, so they remain outside
this file's subject until the issues that convert them land: no skip is added
for them, because a skip that cannot run is noise. All three now inject a real
state and each has its own sandbox test file covering determinism; none has an
`IntentSpec` yet, so they stay excluded from any dispatch measurement (issue
#25).
"""

from __future__ import annotations

import pytest

from precondition_library.tasks import ALL_FAULTS
from precondition_library.tasks.faults import FAULTS
from precondition_library.tasks.registry import INTENTS, ambiguous_intents

FAULTS_WITH_INTENTS: list[str] = sorted(intent.fault for intent in INTENTS.values())


@pytest.mark.parametrize("intent", [spec.name for spec in ambiguous_intents()])
def test_same_seed_same_task_text(intent: str) -> None:
    """Real, not skipped: `task_text` is pure, and it is the one place this
    project introduces randomness."""
    spec = INTENTS[intent]
    for seed in (0, 1, 5, 42):
        text = spec.task_text(seed)
        assert text == spec.task_text(seed)
        assert isinstance(text, str)


@pytest.mark.parametrize("fault_type", FAULTS_WITH_INTENTS)
def test_fault_task_text_delegates_to_its_intent(fault_type: str) -> None:
    """One source of truth for phrasing: a fault's request must be its intent's
    request, not a copy that can drift from it.

    The intent is found through its declared `fault` attribute rather than a
    hardcoded name, so this stays pinned if an intent is renamed.
    """
    intent = next(spec for spec in INTENTS.values() if spec.fault == fault_type)
    fault = FAULTS[fault_type]
    for seed in range(50):
        assert fault.task_text(seed) == intent.task_text(seed), (
            f"{fault_type}: fault text is not the intent's text at seed {seed}"
        )


@pytest.mark.parametrize("intent", [spec.name for spec in ambiguous_intents()])
def test_occurrences_are_not_clones(intent: str) -> None:
    """Occurrences must not be clones of each other, or `occurrence_index` would
    count repetitions of one scenario instead of recurrences of a task family.

    Asserted over a wide seed range because a paraphrase distribution with a
    dominant phrasing would silently collapse the recurrence structure -- and
    that would flatter the cost model without anyone noticing.
    """
    spec = INTENTS[intent]
    texts = {spec.task_text(seed) for seed in range(200)}
    assert len(texts) == len(spec.phrasings), (
        f"{intent}: {len(texts)} distinct texts over 200 seeds for "
        f"{len(spec.phrasings)} phrasings -- some phrasings are unreachable"
    )


@pytest.mark.skip(reason="fault injection needs the live sandbox; implemented per plan, issue #4")
@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_same_seed_same_state(fault_type: str) -> None:
    """Two sandboxes built from one seed must match on every probe the
    fingerprint records."""
    raise NotImplementedError


@pytest.mark.skip(reason="fault injection needs the live sandbox; implemented per plan, issue #4")
@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_injected_states_are_distinguishable(fault_type: str) -> None:
    """Different seeds must produce genuinely different states, not the same
    state with a different task text."""
    raise NotImplementedError
