"""Same seed, same faulty environment.

The ablation compares arms on shared environments, so non-determinism in fault
injection would introduce variance that looks like a difference between arms.
Determinism is also what lets a reported episode be re-run and inspected later.

Two things are asserted here, both real. The request text is a pure function of
the seed, and the two intents that own sampled wording are tested for real. The
injected *state* is real too: every fault in `ALL_FAULTS` injects live git state
against a live sandbox (issues #36-#40), so `test_same_seed_same_state` and
`test_injected_states_are_distinguishable` build real sandboxes rather than
skipping. No skip remains in this file, because a skip that can run is a defect
(issue #4 is the phase that removed theirs; issue #25 governs the dispatch
measurement, not these determinism tests).

The three faults not yet converted to intents -- dirty_tree, branch_renamed and
lockfile_conflict -- still return one fixed sentence, so they remain outside the
*text* tests below: no skip is added for them, because a skip that cannot run is
noise. Their injected states are real, so the two sandbox tests cover them; none
has an `IntentSpec` yet, so none is eligible for a dispatch measurement (issue
#25).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precondition_library.sandbox import Sandbox, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks import ALL_FAULTS
from precondition_library.tasks.faults import FAULTS, lockfile_conflict
from precondition_library.tasks.registry import INTENTS, ambiguous_intents

FAULTS_WITH_INTENTS: list[str] = sorted(intent.fault for intent in INTENTS.values())

# The seed the state-determinism test builds twice. One seed per fault is enough
# here: the per-fault sandbox tests already sweep their own seeds, and this test
# is about the same seed reproducing, not about coverage across seeds.
DETERMINISM_SEED = 0

# Two seeds per fault that select different injected states, with what carries
# the difference named in `_seed_signal`. Seeds that select the same state are
# deliberately avoided: asserting "different seeds differ" on a pair that injects
# one state would be false, and picking a pair that does differ is the honest
# version of the claim. Each pair is verified by the test itself.
DISTINGUISHING_SEEDS: dict[str, tuple[int, int]] = {
    "diverged": (0, 1),  # overlapping_files vs empty_local_commits
    "dirty_tree": (0, 3),  # modified vs modified_with_untracked
    "branch_renamed": (0, 3),  # trunk vs develop
    "submodule_moved": (0, 4),  # remove vs init
    "lockfile_conflict": (0, 3),  # birch/elder vs dogwood/hazel
}


def _refs(repo: Path) -> tuple[str, ...]:
    """Every ref and the object it points at, sorted, for one repository.

    The objectname is the commit SHA for branch refs and the blob SHA for the
    `refs/sandbox/` ground-truth refs some faults record, so comparing this
    compares commit SHAs rather than only the working tree.
    """
    out = run_git(("for-each-ref", "--format=%(refname) %(objectname)"), cwd=repo).stdout
    return tuple(sorted(line for line in out.splitlines() if line))


def _status(repo: Path) -> tuple[str, ...]:
    """The porcelain status including untracked files, sorted.

    `StateFingerprint` has no untracked field, so this is the only observable
    that separates dirty_tree's two seeds.
    """
    out = run_git(("status", "--porcelain", "--untracked-files=all"), cwd=repo).stdout
    return tuple(sorted(line for line in out.splitlines() if line))


def _upstream_branch_names(box: Sandbox) -> tuple[str, ...]:
    """The branch names the upstream repository actually has.

    `StateFingerprint.branch` reads the clone's stale remote-tracking ref and is
    blind to a rename, so branch_renamed's seed-dependent name is visible only
    here.
    """
    out = run_git(
        ("for-each-ref", "--format=%(refname:short)", "refs/heads"), cwd=box.upstream
    ).stdout
    return tuple(sorted(out.split()))


def _observable_state(box: Sandbox) -> tuple[object, ...]:
    """Everything the two tests below observe about a sandbox, as one value.

    Three components, because no single one varies for every fault:

      * the `StateFingerprint` -- the probes arm 3 dispatches on;
      * every ref name and object id in the clone and the upstream repo -- this
        is where commit SHAs are compared, and where a rename (which creates no
        commit) still shows;
      * the porcelain status including untracked files -- the only component
        that distinguishes dirty_tree's seeds.
    """
    return (
        StateFingerprint.observe(box).model_dump(),
        _refs(box.work) + _refs(box.upstream),
        _status(box.work),
    )


def _seed_signal(fault_type: str, box: Sandbox) -> object:
    """The fault-specific observable the two seeds must differ on.

    This is the signal named in the distinguishability test's docstring; it is a
    subset of `_observable_state`'s purpose. Returning it separately means the
    assertion's failure names the field the fault was supposed to vary, rather
    than only reporting that two opaque digests differ.
    """
    if fault_type == "diverged":
        # The seed picks empty / disjoint / overlapping, which the fingerprint's
        # local and upstream touch lists carry.
        return StateFingerprint.observe(box).model_dump()
    if fault_type == "dirty_tree":
        # Both seeds dirty the same tracked file; only the untracked file varies.
        return _status(box.work)
    if fault_type == "branch_renamed":
        # The seed picks the new branch name; the fingerprint is blind to it.
        return _upstream_branch_names(box)
    if fault_type == "submodule_moved":
        # The seed picks init / repin / remove, carried by the submodule fields.
        return StateFingerprint.observe(box).model_dump()
    if fault_type == "lockfile_conflict":
        # The seed picks package names and versions, so the file bytes differ.
        return (box.work / lockfile_conflict.LOCK_PATH).read_text(encoding="utf-8")
    raise KeyError(f"no distinguishing signal defined for fault {fault_type!r}")


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


@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_same_seed_same_state(fault_type: str, make_sandbox) -> None:
    """Two sandboxes built from one seed must match on everything observed.

    `_observable_state` covers the fingerprint (the probes arm 3 dispatches on),
    every ref name and object id in the clone and upstream -- so commit SHAs are
    compared, not just the task text -- and the porcelain status including
    untracked files. A difference in any of them would be injection noise that
    could look like a difference between ablation arms.

    `create` derives the sandbox root from `(seed, faults)`, so the first
    sandbox is destroyed before the second is built; the fixture owns both and
    destroying twice is idempotent.
    """
    first = make_sandbox(DETERMINISM_SEED, [fault_type])
    state = _observable_state(first)
    first.destroy()

    second = make_sandbox(DETERMINISM_SEED, [fault_type])
    assert _observable_state(second) == state


@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_injected_states_are_distinguishable(fault_type: str, make_sandbox) -> None:
    """Different seeds must produce genuinely different states, not the same
    state with a different task text.

    Two seeds per fault are fixed in `DISTINGUISHING_SEEDS`; the test compares
    `_seed_signal` (the fault-specific observable below) and the whole
    `_observable_state` digest, so the claim is about the repositories rather
    than a single field. What varies, and why that is the right signal:

      diverged          the seed picks the injected variant -- empty, disjoint
                        or overlapping -- so the fingerprint's touch lists
                        differ. The fingerprint is the probe arm 3 dispatches
                        on, so it is the right signal here.
      dirty_tree        the seed picks whether an untracked file joins the
                        tracked edit. The fingerprint is identical between the
                        two (it has no untracked field), so the porcelain status
                        is the only honest signal.
      branch_renamed    the seed picks the new branch name: trunk or develop.
                        `StateFingerprint.branch` reads the stale remote-tracking
                        ref and is blind to the rename, so upstream's own branch
                        refs are the signal.
      submodule_moved   the seed picks init, repin or remove, which the
                        fingerprint's submodule discriminators carry.
      lockfile_conflict the seed picks the package names and versions, so the
                        lock-shaped file's bytes differ.

    Each pair was chosen to select different states for its fault; no pair that
    injects one state is asserted to differ. The digest comparison is kept
    because a fault could vary its signal while leaving the repository otherwise
    identical, and that would not be a genuinely different state.
    """
    seed_a, seed_b = DISTINGUISHING_SEEDS[fault_type]
    assert seed_a != seed_b, f"{fault_type}: the two seeds must differ"

    first = make_sandbox(seed_a, [fault_type])
    second = make_sandbox(seed_b, [fault_type])

    assert _seed_signal(fault_type, first) != _seed_signal(fault_type, second), (
        f"{fault_type}: seeds {seed_a} and {seed_b} share the state signal"
    )
    assert _observable_state(first) != _observable_state(second), (
        f"{fault_type}: seeds {seed_a} and {seed_b} produced identical repositories"
    )
