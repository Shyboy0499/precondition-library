# Intent-Underdetermined Instances Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project's primary claim testable by removing the flaw that task text is a perfect class label — so that a text-only dispatcher has nothing to go on and a state-only dispatcher has something to prove.

**Architecture:** An **intent** becomes a task family with one request distribution and ≥2 correct resolutions, where the correct one is decided *only* by observable state. A **labelled-pair generator** turns (state, intent) into per-decision ground truth, which is the raw material the spec's primary metric needs. A **text-only control classifier** measures whether the request text leaks the answer, and is itself validated by a positive control that must detect a deliberately leaky intent.

**Tech Stack:** Python 3.12, uv, pydantic v2, pytest, ruff (line-length 100), mypy. No new dependencies — the control classifier is implemented in pure Python, because a control that needs a new dependency to run is a control that gets skipped.

---

## Why this is first, and what it deliberately does not include

The method review found a fatal flaw: `FaultSpec.task_text()` returns **one fixed sentence per fault**, so the task text *is* the ground-truth label, embedding dispatch cannot mis-fire by construction, and the primary claim has no experimental surface. Everything in issues #4–#10 sits on top of this.

### Decision 1: the labelled-pair seam belongs here, not in issue #5

Issue #3's own acceptance criteria require (a) a text-only classifier AUC and (b) mismatch scored **on the ambiguous subset, with the denominator reported**. Neither is expressible without a per-instance label tied to (state, resolution). Issue #5 adds the threshold sweep, coverage curves, and Wilson intervals *on top of* this seam; it should not also have to define what a wrong answer is. Freezing the label definition now also satisfies issue #9's requirement that ground truth be frozen before any arm is built — a label defined after seeing dispatch results can be tuned into existence.

### Decision 2: states are declarative fingerprints, not live git sandboxes

`StateFingerprint` is exactly what the dispatch-level benchmark consumes, its fields are all observable from git, and constructing one costs nothing — whereas `sandbox.create()` is a phase-1 stub belonging to issues #4/#5. Pulling live git into this change would turn a design fix into a mega-PR and couple the label definition to sandbox plumbing.

**Residual risk, recorded rather than hidden:** the decision rules below must be computable from git probes alone. They are, by construction — every discriminator is a `git rev-list` count or a `git diff --name-only` intersection. If a later phase finds a discriminator that cannot actually be probed, the correct response is to **redesign the variant**, not to relax the label. That failure mode is why each variant carries a `rationale` and each decision is a named function rather than an inline lambda over a mystery field.

### Decision 3: the ≥2 resolutions are hand-written fixtures

Issue #3 asks for "≥2 admitted programs sharing one intent". Admission runs through the compile step, which is issue #4. So this plan ships the resolutions as **hand-written gold programs** under `bench/gold/`, which the spec's gold-first rule requires anyway. The ambiguity is then real for labelling purposes; the compile path adds generated programs later and must clear the same gate.

### Out of scope, explicitly

Live git sandboxes and `inject()` (#4/#5) · the compile and admission pipeline (#4) · threshold sweeps, coverage curves, Wilson intervals (#5) · the baselines (#7) · the cost ledger (#8) · safety hardening (#10). None of those is touched, and none is claimed.

---

## File structure

| File | Responsibility |
| --- | --- |
| `src/precondition_library/signatures.py` | **Modify.** Add the observable discriminators the two ambiguous intents decide on, plus a `conflicting_files` derived property. |
| `src/precondition_library/program.py` | **Modify.** Add `Program.variant` so a dispatch error can be defined at all: a wrong answer is a program whose variant does not match the state's. |
| `src/precondition_library/tasks/intent.py` | **Create.** `ResolutionVariant`, `IntentSpec`, deterministic paraphrase sampling, and the unique-correct-variant rule. |
| `src/precondition_library/tasks/faults/diverged.py` | **Modify.** Add `INTENT` with three resolutions (discard / merge / rebase) and a paraphrase distribution; delegate `task_text` to it. |
| `src/precondition_library/tasks/faults/submodule_moved.py` | **Modify.** Add `INTENT` with three resolutions (init / repin / remove); delegate `task_text` to it. |
| `src/precondition_library/tasks/registry.py` | **Create.** `INTENTS` and `ambiguous_intents()` — the only intents with an experimental surface. |
| `src/precondition_library/bench/pairs.py` | **Create.** `LabelledPair`, `label`, `labelled_pairs`, `ambiguous_subset`, `decision_is_correct`, `denominator_report`. |
| `src/precondition_library/bench/textcontrol.py` | **Create.** Bag-of-words logistic regression, rank-based AUC, leakage verdict. |
| `tests/conftest.py` | **Create.** State grids and a `make_state` helper shared across tests. |
| `tests/test_intent_ambiguity.py` | **Create.** Variant count, partition of the state space, label invariance under wording. |
| `tests/test_task_text_is_not_a_label.py` | **Create.** The control, plus the positive control that proves the control works. |
| `tests/test_text_determinism.py` | **Create.** Same seed → same text, including across processes. |
| `tests/test_pairs.py` | **Create.** Pair labelling, negative pairs, denominators. |
| `tests/test_gold_programs.py` | **Create.** Gold fixtures parse, are well-formed, and cover ≥2 resolutions per intent. |
| `bench/gold/sync_fork_with_upstream.yaml` | **Create.** Three hand-written resolution programs. |
| `bench/gold/restore_submodule_state.yaml` | **Create.** Three hand-written resolution programs. |
| `tests/test_faults_deterministic.py` | **Modify.** Un-skip the parts that are pure functions now that they can really run. |
| `docs/superpowers/specs/2026-09-13-precondition-library-design.md` | **Modify.** §3 (task family), §5 (artifact), §10 (testing) reflect variants and the control. |
| `CHANGELOG.md` | **Modify.** Unreleased entry. |

---

### Task 1: Observable discriminators on the state fingerprint

**Files:**
- Modify: `src/precondition_library/signatures.py`
- Test: `tests/test_intent_ambiguity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intent_ambiguity.py`:

```python
"""The state space must carry enough information to decide a resolution.

If it does not, the ambiguity is not resolvable by any dispatcher and the
experiment measures nothing -- so the fields a decision rule reads are part of
the design, not an implementation detail.
"""

from __future__ import annotations

import pytest

from precondition_library.signatures import StateFingerprint


def test_conflicting_files_is_the_intersection(make_state) -> None:
    state = make_state(
        local_touched_files=["a.py", "b.py"],
        upstream_touched_files=["b.py", "c.py"],
    )
    assert state.conflicting_files == {"b.py"}


def test_conflicting_files_empty_when_disjoint(make_state) -> None:
    state = make_state(local_touched_files=["a.py"], upstream_touched_files=["z.py"])
    assert state.conflicting_files == set()


def test_has_local_only_commits_counts_not_flags(make_state) -> None:
    assert make_state(upstream_behind=0).has_local_only_commits is False
    assert make_state(upstream_behind=2).has_local_only_commits is True


def test_defaults_keep_existing_construction_valid() -> None:
    """Existing call sites construct fingerprints by keyword with the original
    fields; adding fields with defaults must not break them."""
    state = StateFingerprint(
        dirty_worktree=False,
        branch="main",
        upstream_ahead=1,
        upstream_behind=0,
        has_locked_branch=False,
        has_submodule_reference=False,
        remotes=[],
    )
    assert state.has_local_only_commits is False
    assert state.submodule_initialised is False
    assert state.local_touched_files == []
    assert state.submodule_pin_matches_upstream is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_intent_ambiguity.py -v`
Expected: FAIL — `fixture 'make_state' not found` (conftest lands in Task 2) and, once it exists, `TypeError: StateFingerprint.__init__() got an unexpected keyword argument 'local_touched_files'`.

To make this step's expectation exact, Task 2 creates the conftest first. If you are executing tasks out of order, run this file after Task 2.

- [ ] **Step 3: Write minimal implementation**

In `src/precondition_library/signatures.py`, replace the `StateFingerprint` body with:

```python
class StateFingerprint(BaseModel):
    """Observable git-level facts about an environment, gathered without an LLM.

    Every field must be obtainable from git alone, because arm 3 decides by
    running probes over exactly these values. A field that cannot be probed does
    not belong here: it would make a resolution undecidable and quietly turn the
    experiment into a comparison of two equally blind dispatchers.
    """

    dirty_worktree: bool
    branch: str
    upstream_ahead: int
    """Commits upstream has that HEAD lacks: `git rev-list --count HEAD..upstream/main`."""
    upstream_behind: int
    """Commits HEAD has that upstream lacks: `git rev-list --count upstream/main..HEAD`."""
    has_locked_branch: bool
    has_submodule_reference: bool
    remotes: list[str] = []

    # Discriminators for the ambiguous intents (see the intent model added in the next task).
    local_touched_files: list[str] = []
    """Files the local-only commits change: `git diff --name-only upstream/main...HEAD`."""
    upstream_touched_files: list[str] = []
    """Files upstream's new commits change: `git diff --name-only HEAD...upstream/main`."""
    submodule_initialised: bool = False
    """Whether the submodule directory has been initialised in this clone:
    `git submodule status` prefixes an uninitialised entry with `-`."""
    submodule_pin_matches_upstream: bool = True
    """Whether the recorded submodule commit equals the one upstream pins:
    `git diff --name-only upstream/main HEAD -- <submodule_path>` is empty when it does."""
    upstream_still_references_submodule: bool = True
    """Whether upstream's tree still contains the submodule path at all:
    `git ls-tree upstream/main -- <submodule_path>` is non-empty when it does."""

    @property
    def conflicting_files(self) -> set[str]:
        """Files both sides touched.

        The discriminator that decides merge versus rebase: if the two sides
        changed the same file, replaying local commits on top of upstream would
        discard a resolution someone already made.
        """
        return set(self.local_touched_files) & set(self.upstream_touched_files)

    @property
    def has_local_only_commits(self) -> bool:
        """Whether the local branch is ahead of upstream at all.

        Derived from `upstream_behind` rather than carried as its own field: the
        two are the same measurement, and having two names for one quantity is how
        a fingerprint ends up asserting two contradictory things at once. A count
        rather than a flag because the zero case is the *benign* state -- nothing
        to resolve, so every program must refuse to fire, and a dispatcher that
        always fires can only be caught by states that require refusal.
        """
        return self.upstream_behind > 0

    @classmethod
    def observe(cls, env) -> StateFingerprint:
        """Run the probes. Must not mutate the environment.

        Still unimplemented: the real probes belong with the live sandbox
        (issues #4/#5). Until then, fingerprints are constructed directly, which
        is sufficient for labelling dispatch decisions because the benchmark
        consumes states, not repositories.
        """
        raise NotImplementedError("implemented per plan: phase 1 (issues #4/#5)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_intent_ambiguity.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/precondition_library/signatures.py tests/test_intent_ambiguity.py
git commit -m "feat(state): add observable discriminators for the ambiguous intents"
```

---

### Task 2: Shared test fixtures

**Files:**
- Test: `tests/conftest.py`

- [ ] **Step 1: Write the fixtures**

Create `tests/conftest.py`:

```python
"""Shared test fixtures.

The state grids are the input to every ambiguity test: four states per intent,
covering each correct resolution plus one benign state where nothing should be
done. Benign states are included deliberately -- a dispatcher that always fires
has to be catchable, and it can only be caught by states that require refusal.
"""

from __future__ import annotations

import pytest

from precondition_library.signatures import StateFingerprint


# `upstream_ahead` is how many commits upstream has that HEAD lacks; `upstream_behind`
# is how many HEAD has that upstream lacks. They describe the same ref pair from
# opposite sides, so a state cannot be both without being incoherent.
def _make_state(**overrides) -> StateFingerprint:
    base = {
        "dirty_worktree": False,
        "branch": "main",
        "upstream_ahead": 3,
        "upstream_behind": 0,
        "has_locked_branch": False,
        "has_submodule_reference": False,
        "remotes": ["origin", "upstream"],
    }
    base.update(overrides)
    return StateFingerprint(**base)


@pytest.fixture
def make_state():
    """Build a fingerprint from a baseline, overriding only the fields a test cares about."""
    return _make_state


# sync_fork_with_upstream: three resolutions, plus the benign state.
DIVERGED_STATES = {
    "benign_nothing_local": _make_state(upstream_touched_files=["app.py"]),
    "empty_local_commits": _make_state(
        upstream_behind=2, local_touched_files=[], upstream_touched_files=["app.py"]
    ),
    "disjoint_files": _make_state(
        upstream_behind=2,
        local_touched_files=["docs/readme.md"],
        upstream_touched_files=["app.py"],
    ),
    "overlapping_files": _make_state(
        upstream_behind=2,
        local_touched_files=["app.py", "docs/readme.md"],
        upstream_touched_files=["app.py"],
    ),
}

# restore_submodule_state: three resolutions, plus the benign state.
SUBMODULE_STATES = {
    "benign_pin_matches": _make_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=True,
    ),
    "not_initialised": _make_state(
        has_submodule_reference=True,
        submodule_initialised=False,
        submodule_pin_matches_upstream=False,
    ),
    "pin_drifted": _make_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=False,
    ),
    "upstream_dropped_it": _make_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=False,
        upstream_still_references_submodule=False,
    ),
}

STATE_GRID: dict[str, dict[str, StateFingerprint]] = {
    "sync_fork_with_upstream": DIVERGED_STATES,
    "restore_submodule_state": SUBMODULE_STATES,
}


@pytest.fixture
def state_grid() -> dict[str, dict[str, StateFingerprint]]:
    return STATE_GRID
```

- [ ] **Step 2: Run the tests to verify nothing regressed**

Run: `uv run pytest -q`
Expected: PASS — `2 passed, 30 skipped` becomes `6 passed, 30 skipped` (the four new tests in Task 1 plus the pre-existing two).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared state fingerprints covering each resolution and one benign state"
```

---

### Task 3: The intent model and deterministic paraphrase sampling

**Files:**
- Create: `src/precondition_library/tasks/intent.py`
- Test: `tests/test_text_determinism.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_text_determinism.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_text_determinism.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'precondition_library.tasks.intent'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/precondition_library/tasks/intent.py`:

```python
"""Intents with more than one correct resolution.

The flaw this module removes: when a fault's request is a single fixed sentence,
the text *is* the class label, so a dispatcher that reads only the text cannot
mis-fire and the primary claim is untestable. 60 episodes would produce a number
that looks like a result while measuring nothing.

An `IntentSpec` separates three things that were previously one:

  the request      a paraphrase distribution sampled by seed. A reported fraction
                   of samples do not name the fault at all.
  the state        a `StateFingerprint`, produced by the environment, not the request.
  the resolution   which of >=2 bodies is correct, decided ONLY by the state.

Because the resolution depends on state and not on wording, a text-only dispatcher
has nothing to go on -- and any accuracy it appears to have can be *measured* as
leakage (see bench/textcontrol.py) rather than assumed away.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..signatures import StateFingerprint


def sample_index(seed: int, salt: str, n: int) -> int:
    """Deterministic index in [0, n) from (seed, salt).

    Uses sha256 rather than `hash()` because CPython salts `hash()` for strings
    per process, so the same seed would yield different task text in a different
    run -- and the point of a seed is that a reported episode can be reproduced
    exactly. `tests/test_text_determinism.py` pins this with two subprocesses.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    digest = hashlib.sha256(f"{salt}:{seed}".encode()).hexdigest()
    return int(digest, 16) % n


@dataclass(frozen=True)
class ResolutionVariant:
    """One correct way to resolve an intent, and the states it is correct in."""

    id: str
    """Stable identifier, e.g. 'rebase'. Also the value `Program.variant` carries."""

    decided_by: Callable[[StateFingerprint], bool]
    """Ground truth for this variant.

    Deliberately a Python callable over observable state, NOT the program's probe
    strings. Issue #9 requires ground truth and the artifact contract to be
    separate code, so that a wrong precondition cannot make its own program look
    correct -- the failure the whole project measures.
    """

    rationale: str
    """Why this resolution is right in those states, in one sentence.

    Required, not decorative: a variant whose rationale cannot be written in one
    sentence usually means the state does not actually determine the answer, and
    the variant should be redesigned rather than labelled.
    """

    def correct_in(self, state: StateFingerprint) -> bool:
        return self.decided_by(state)


@dataclass(frozen=True)
class IntentSpec:
    """A task family: one request distribution, one or more correct resolutions."""

    name: str
    fault: str
    """The `FaultSpec.name` that injects the states this intent appears in."""

    phrasings: list[str]
    """The paraphrase distribution. The fraction that names the fault is reported
    by `naming_fraction` and asserted below a ceiling."""

    naming_markers: list[str]
    """Substrings whose presence means a phrasing gives the fault away."""

    variants: list[ResolutionVariant]

    def __post_init__(self) -> None:
        if not self.phrasings:
            raise ValueError(f"{self.name}: needs at least one phrasing")
        if not self.variants:
            raise ValueError(f"{self.name}: needs at least one resolution variant")
        ids = [v.id for v in self.variants]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.name}: duplicate variant ids {ids}")

    @property
    def is_ambiguous(self) -> bool:
        """Ambiguity is the point.

        With two or more resolutions, the request text cannot be sufficient to
        choose, so a dispatch comparison has an experimental surface. With one,
        the intent is still a valid task but proves nothing about dispatch.
        """
        return len(self.variants) > 1

    def task_text(self, seed: int) -> str:
        return self.phrasings[sample_index(seed, f"{self.name}:text", len(self.phrasings))]

    def names_the_fault(self, text: str) -> bool:
        lowered = text.lower()
        return any(marker.lower() in lowered for marker in self.naming_markers)

    def naming_fraction(self, seeds: Iterable[int]) -> float:
        """Fraction of sampled requests that give the fault away.

        Reported and asserted below a ceiling: a distribution that nearly always
        names the fault would reintroduce the original flaw in a more expensive
        way, and it would be invisible without this number.
        """
        texts = [self.task_text(seed) for seed in seeds]
        if not texts:
            raise ValueError("need at least one seed")
        return sum(self.names_the_fault(text) for text in texts) / len(texts)

    def correct_variant(self, state: StateFingerprint) -> ResolutionVariant | None:
        """The unique variant correct in `state`, or None for a benign state.

        None is a labelled outcome, not an error: the environment needs nothing
        done, so every program must refuse to fire. Overlap *is* an error and
        raises, because silently picking the first match would hide a defect
        inside the label that everything downstream depends on.
        """
        matches = [v for v in self.variants if v.correct_in(state)]
        if len(matches) > 1:
            raise ValueError(
                f"{self.name}: state matched {len(matches)} variants "
                f"({[m.id for m in matches]}); decision rules must partition the states"
            )
        return matches[0] if matches else None
```

- [ ] **Step 4: Run the tests and confirm the two deferrals are skips, not errors**

Run: `uv run pytest tests/test_text_determinism.py -v`
Expected: the four real tests PASS; `test_same_seed_same_text` and `test_text_does_not_depend_on_process_hash_seed` are reported SKIPPED with the reason `the intent registry lands in Task 7; un-skipped there`.

The two registry-dependent tests are marked `@pytest.mark.skip`, not left failing, and neither imports `ambiguous_intents` at module level: `test_same_seed_same_text` imports it inside the function body, and `test_text_does_not_depend_on_process_hash_seed` reaches it only through the subprocess snippet it runs. A `ModuleNotFoundError` raised while importing the module is a *collection* error and fails the whole module, taking the four runnable tests down with it — so a module-level registry import would hide real results behind a Task 7 dependency. Skipping keeps the module importable and the four real tests honest. The repository's own convention (CONTRIBUTING.md rule 4) is that a skipped test names the phase that implements it, which the skip reason does.

- [ ] **Step 5: Commit**

```bash
git add src/precondition_library/tasks/intent.py tests/test_text_determinism.py
git commit -m "feat(tasks): add IntentSpec with deterministic paraphrase sampling"
```

---

### Task 4: Give `diverged` three resolutions

**Files:**
- Modify: `src/precondition_library/tasks/faults/diverged.py`
- Modify: `src/precondition_library/program.py`
- Test: `tests/test_intent_ambiguity.py`

- [ ] **Step 1: Write the failing test**

First extend the file's existing top import block with `pytest` and the
`diverged` intent. Both imports belong at the top, not next to the new tests:
ruff's `E402` (import not at top of file) and `I001` (unsorted imports) reject a
mid-file import.

```python
from __future__ import annotations

import pytest

from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.diverged import INTENT as DIVERGED
```

Then append:

```python
@pytest.mark.parametrize(
    ("state_name", "expected"),
    [
        ("benign_nothing_local", None),
        ("empty_local_commits", "discard"),
        ("disjoint_files", "rebase"),
        ("overlapping_files", "merge"),
    ],
)
def test_diverged_resolution_is_decided_by_state(state_grid, state_name, expected) -> None:
    variant = DIVERGED.correct_variant(state_grid["sync_fork_with_upstream"][state_name])
    assert (variant.id if variant else None) == expected


def test_diverged_has_three_distinct_resolutions() -> None:
    assert {v.id for v in DIVERGED.variants} == {"discard", "merge", "rebase"}
    assert DIVERGED.is_ambiguous


def test_diverged_phrasings_mostly_do_not_name_the_fault() -> None:
    assert DIVERGED.naming_fraction(range(50)) <= 0.35


def test_diverged_variants_each_explain_themselves() -> None:
    for variant in DIVERGED.variants:
        assert variant.rationale.strip(), f"{variant.id} needs a rationale"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_intent_ambiguity.py -v -k diverged`
Expected: FAIL — `ImportError: cannot import name 'INTENT' from 'precondition_library.tasks.faults.diverged'`.

- [ ] **Step 3: Write minimal implementation**

Replace the whole body of `src/precondition_library/tasks/faults/diverged.py`:

```python
"""Fault: local branch and upstream have diverged, both with unique commits.

Three resolutions, and the request text cannot tell them apart. Which is correct
depends on what the local-only commits actually contain:

  discard  the local commits are empty of file changes, so resetting to upstream
           loses no work.
  rebase   the local commits change files upstream did not, so replaying them on
           top of upstream is conflict-free and yields a linear history.
  merge    both sides changed the same file, so rewriting local history would
           discard a resolution someone already made.

The discriminators are all observable (`upstream_behind`,
`local_touched_files`, `upstream_touched_files`), which matters: arm 3 decides by
running probes, so a resolution that needed a *judgement* could not be decided by
either mechanism and the comparison would be between two blind dispatchers.
"""

from __future__ import annotations

from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant
from ..spec import FaultSpec, GroundTruth


def _is_empty_of_changes(state: StateFingerprint) -> bool:
    """Local commits exist but change no files."""
    return state.has_local_only_commits and not state.local_touched_files


def _overlaps_upstream(state: StateFingerprint) -> bool:
    """Both sides changed at least one of the same files."""
    return state.has_local_only_commits and bool(state.conflicting_files)


def _is_disjoint_from_upstream(state: StateFingerprint) -> bool:
    """Local commits change files, none of which upstream also changed."""
    return (
        state.has_local_only_commits
        and bool(state.local_touched_files)
        and not state.conflicting_files
    )


VARIANTS = [
    ResolutionVariant(
        id="discard",
        decided_by=_is_empty_of_changes,
        rationale="Local commits change no files, so resetting to upstream loses nothing.",
    ),
    ResolutionVariant(
        id="merge",
        decided_by=_overlaps_upstream,
        rationale=(
            "Both sides changed the same file, so replaying local commits would "
            "discard a resolution and risk re-conflicting; merge keeps both."
        ),
    ),
    ResolutionVariant(
        id="rebase",
        decided_by=_is_disjoint_from_upstream,
        rationale=(
            "Local commits touch only files upstream left alone, so replaying them "
            "on top of upstream is conflict-free and keeps history linear."
        ),
    ),
]

INTENT = IntentSpec(
    name="sync_fork_with_upstream",
    fault="diverged",
    phrasings=[
        "Get this fork back in sync with upstream without losing my commits.",
        "Upstream has moved on and so have I. Sort the branch out.",
        "This branch and upstream have both changed. Bring it back into line.",
        "My fork and upstream have both moved. Make them consistent.",
        "Upstream moved ahead of me. Get me back in line with it.",
        "Reconcile this branch with upstream.",
        "I have local work and upstream has new commits. Untangle it.",
        "Something is out of step between my branch and upstream. Fix it.",
    ],
    naming_markers=["diverged", "divergence"],
    variants=VARIANTS,
)


class DivergedFault(FaultSpec):
    name = "diverged"
    description = "Local branch and upstream both have commits the other lacks"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1 (issue #4)")

    def task_text(self, seed: int) -> str:
        """Delegate to the intent so there is one source of truth for phrasing."""
        return INTENT.task_text(seed)

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1 (issue #9)")


SPEC = DivergedFault()
```

**Also in this step**, update `FaultSpec.task_text`'s docstring in `src/precondition_library/tasks/spec.py`. It currently promises "Varies by seed so that repeats are recognisably the same *kind* of task without being the same string", which was true of the implementation being replaced and is too weak a description of the new one. Replace it with:

```python
    def task_text(self, seed: int) -> str:
        """The request handed to the agent, sampled from the intent's paraphrase
        distribution.

        Delegates to the intent so there is one source of truth per family. The
        distribution must not name the fault in most samples: when the text
        identifies the answer, the text *is* the label and a dispatch comparison
        becomes vacuous. How far that holds is measured, not assumed -- see
        bench/textcontrol.py.
        """
        raise NotImplementedError("implemented per plan: phase 1 (issue #4)")
```

Leave `inject` and `check` untouched: they keep their own phase-1 stub message.

Add `variant` to `Program` in `src/precondition_library/program.py`, immediately after the `postconditions` field:

```python
    variant: str | None = None
    """Which resolution of its intent's ambiguity this program implements.

    Required for intents with two or more resolutions: a dispatch error can only
    be defined relative to the state's correct variant, so a program that does
    not declare its variant cannot be scored. None is legitimate for intents that
    have only one resolution.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_intent_ambiguity.py -v`
Expected: PASS, 11 tests (4 from Task 1, 7 from this task).

- [ ] **Step 5: Commit**

```bash
git add src/precondition_library/tasks/faults/diverged.py src/precondition_library/program.py tests/test_intent_ambiguity.py
git commit -m "feat(tasks): give diverged three state-decided resolutions"
```

---

### Task 5: Give `submodule_moved` three resolutions

**Files:**
- Modify: `src/precondition_library/tasks/faults/submodule_moved.py`
- Test: `tests/test_intent_ambiguity.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intent_ambiguity.py`:

```python
from precondition_library.tasks.faults.submodule_moved import INTENT as SUBMODULE


@pytest.mark.parametrize(
    ("state_name", "expected"),
    [
        ("benign_pin_matches", None),
        ("not_initialised", "init"),
        ("pin_drifted", "repin"),
        ("upstream_dropped_it", "remove"),
    ],
)
def test_submodule_resolution_is_decided_by_state(state_grid, state_name, expected) -> None:
    variant = SUBMODULE.correct_variant(state_grid["restore_submodule_state"][state_name])
    assert (variant.id if variant else None) == expected


def test_submodule_has_three_distinct_resolutions() -> None:
    assert {v.id for v in SUBMODULE.variants} == {"init", "repin", "remove"}
    assert SUBMODULE.is_ambiguous


def test_submodule_phrasings_mostly_do_not_name_the_fault() -> None:
    assert SUBMODULE.naming_fraction(range(50)) <= 0.35
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_intent_ambiguity.py -v -k submodule`
Expected: FAIL — `ImportError: cannot import name 'INTENT' from 'precondition_library.tasks.faults.submodule_moved'`.

- [ ] **Step 3: Write minimal implementation**

Replace the whole body of `src/precondition_library/tasks/faults/submodule_moved.py`:

```python
"""Fault: a submodule's recorded commit no longer matches what upstream expects.

Three resolutions, indistinguishable from the request text:

  init    the submodule directory was never initialised in this clone.
  repin   it is initialised, upstream still tracks it, and the recorded commit drifted.
  remove  upstream no longer references the submodule at all.

The third is the one that punishes a plausible wrong answer: re-pinning a
submodule upstream has dropped *looks* like it worked (the command succeeds) while
leaving the tree in a state the checker rejects. That is exactly the silent
wrong-program fire the primary claim is about, which is why this intent is worth
having even though the first two resolutions are less interesting.
"""

from __future__ import annotations

from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant
from ..spec import FaultSpec, GroundTruth


def _upstream_dropped_it(state: StateFingerprint) -> bool:
    return not state.upstream_still_references_submodule


def _not_initialised(state: StateFingerprint) -> bool:
    return state.upstream_still_references_submodule and not state.submodule_initialised


def _pin_drifted(state: StateFingerprint) -> bool:
    return (
        state.upstream_still_references_submodule
        and state.submodule_initialised
        and not state.submodule_pin_matches_upstream
    )


VARIANTS = [
    ResolutionVariant(
        id="remove",
        decided_by=_upstream_dropped_it,
        rationale="Upstream's tree no longer contains the submodule, so it must go.",
    ),
    ResolutionVariant(
        id="init",
        decided_by=_not_initialised,
        rationale="Upstream still tracks it but this clone never initialised it.",
    ),
    ResolutionVariant(
        id="repin",
        decided_by=_pin_drifted,
        rationale="Initialised and still tracked, but recording a commit upstream no longer pins.",
    ),
]

INTENT = IntentSpec(
    name="restore_submodule_state",
    fault="submodule_moved",
    phrasings=[
        "The submodule in this fork is out of step with upstream. Bring it back into line.",
        "Something is off with the submodule here. Put it right.",
        "Get the submodule in this repo consistent with upstream.",
        "The submodule state looks wrong. Resolve it.",
        "Upstream and this clone disagree about the submodule. Reconcile them.",
        "Sort out the submodule so it matches what upstream expects.",
        "This repository's submodule needs to be brought into line.",
    ],
    naming_markers=["submodule"],
    variants=VARIANTS,
)


class SubmoduleMovedFault(FaultSpec):
    name = "submodule_moved"
    description = "A tracked submodule's pinned commit drifted from upstream's"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1 (issue #4)")

    def task_text(self, seed: int) -> str:
        return INTENT.task_text(seed)

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1 (issue #9)")


SPEC = SubmoduleMovedFault()
```

**Note on the naming fraction.** `naming_markers=["submodule"]` and every phrasing above contains the word, so `naming_fraction` is 1.0 and Step 1's assertion fails. That is intentional — the assertion is the mechanism that forces the distribution to be fixed, and Step 4 below is where you fix it. Do **not** loosen the ceiling.

- [ ] **Step 4: Fix the distribution, then run the tests**

Every phrasing currently names the submodule, so the intent leaks. Rewrite the `phrasings` list so that at most a third name it — the rest must describe the *symptom* without the word, for example:

```text
    phrasings=[
        "The submodule in this fork is out of step with upstream. Bring it back into line.",
        "Something is off with the nested repository here. Put it right.",
        "Get this repo's nested dependency consistent with upstream.",
        "One of the nested checkouts looks wrong. Resolve it.",
        "Upstream and this clone disagree about a nested repository. Reconcile them.",
        "Sort out the nested checkout so it matches what upstream expects.",
        "A nested repository in this project needs bringing into line.",
    ],
    naming_markers=["submodule"],
```

Fenced as `text`, not `python`, on purpose: this is a **fragment** of an `IntentSpec(...)` call rather than a complete statement, and CI runs `ruff format --check` over Python code inside markdown files. A fragment in a `python` fence gets reformatted into something that is no longer a faithful excerpt of the file it replaces — which is exactly what happened on the first CI run of this plan.

Run: `uv run pytest tests/test_intent_ambiguity.py -v`
Expected: PASS, 15 tests. `naming_fraction` over 50 seeds is 1/7 ≈ 0.143, under the 0.35 ceiling.

- [ ] **Step 5: Commit**

```bash
git add src/precondition_library/tasks/faults/submodule_moved.py tests/test_intent_ambiguity.py
git commit -m "feat(tasks): give submodule_moved three state-decided resolutions"
```

---

### Task 6: Partition the state space, and pin label invariance

**Files:**
- Test: `tests/test_intent_ambiguity.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intent_ambiguity.py`:

```python
from precondition_library.tasks.registry import ambiguous_intents


def test_every_grid_state_is_labelable(state_grid) -> None:
    """No state in the grid may raise: overlap is a defect, and a grid state that
    matches nothing but is not benign is a hole in the decision rules."""
    for intent in ambiguous_intents():
        for name, state in state_grid[intent.name].items():
            intent.correct_variant(state)  # raises on overlap


def test_each_resolution_is_reachable(state_grid) -> None:
    """Every declared variant must be the answer for at least one grid state.

    Otherwise the variant is dead weight, and the ambiguity is smaller than the
    spec claims -- an unreachable variant makes the task family look harder than
    it is, which flatters whichever arm happens to be tested on it.
    """
    for intent in ambiguous_intents():
        seen = {
            intent.correct_variant(state).id
            for state in state_grid[intent.name].values()
            if intent.correct_variant(state) is not None
        }
        assert seen == {v.id for v in intent.variants}, f"{intent.name}: unreachable variants"


def test_at_least_one_benign_state_per_intent(state_grid) -> None:
    """A dispatcher that always fires must be catchable."""
    for intent in ambiguous_intents():
        benign = [
            state
            for state in state_grid[intent.name].values()
            if intent.correct_variant(state) is None
        ]
        assert benign, f"{intent.name}: no benign state, so never-refusing cannot be detected"


def test_label_does_not_depend_on_wording(state_grid) -> None:
    """The load-bearing property of this whole change.

    Holding the state fixed and varying the seed -- and therefore the request
    text -- must not change the correct resolution. If it did, the label would be
    a property of the phrasing and the comparison would be circular.
    """
    for intent in ambiguous_intents():
        for state in state_grid[intent.name].values():
            answers = {
                (intent.correct_variant(state).id if intent.correct_variant(state) else None)
                for _ in range(1)
            }
            for seed in range(30):
                intent.task_text(seed)  # vary the request
                resolved = intent.correct_variant(state)
                answers.add(resolved.id if resolved else None)
            assert len(answers) == 1, f"{intent.name}: label moved with the wording"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_intent_ambiguity.py -v -k "grid or reachable or benign or wording"`
Expected: FAIL — `ModuleNotFoundError: No module named 'precondition_library.tasks.registry'` (the registry is Task 7).

- [ ] **Step 3: Commit once Task 7 lands**

This task has no implementation of its own; it is the property suite that pins Task 7's registry. Leave it uncommitted until then.

---

### Task 7: The intent registry

**Files:**
- Create: `src/precondition_library/tasks/registry.py`
- Modify: `src/precondition_library/tasks/__init__.py`
- Test: `tests/test_intent_ambiguity.py` (from Task 6)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intent_ambiguity.py`:

```python
def test_registry_exposes_only_intents_with_a_surface() -> None:
    names = [intent.name for intent in ambiguous_intents()]
    assert names == ["restore_submodule_state", "sync_fork_with_upstream"]  # sorted


def test_registry_intents_name_a_real_fault() -> None:
    from precondition_library.tasks import ALL_FAULTS

    for intent in ambiguous_intents():
        assert intent.fault in ALL_FAULTS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_intent_ambiguity.py -v -k registry`
Expected: FAIL — `ModuleNotFoundError: No module named 'precondition_library.tasks.registry'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/precondition_library/tasks/registry.py`:

```python
"""Which task families are usable, and which have an experimental surface.

Only ambiguous intents -- two or more correct resolutions -- can support a claim
about dispatch. A single-resolution intent is still a legitimate task, but on it
both dispatchers have the same single answer available and the comparison says
nothing. Keeping the distinction in one place stops an unambiguous intent being
counted into a rate as if it were evidence.
"""

from __future__ import annotations

from .faults.diverged import INTENT as DIVERGED_INTENT
from .faults.submodule_moved import INTENT as SUBMODULE_INTENT
from .intent import IntentSpec

INTENTS: dict[str, IntentSpec] = {
    intent.name: intent for intent in (DIVERGED_INTENT, SUBMODULE_INTENT)
}


def ambiguous_intents() -> list[IntentSpec]:
    """Intents with at least two correct resolutions, sorted by name."""
    return sorted(
        (intent for intent in INTENTS.values() if intent.is_ambiguous),
        key=lambda intent: intent.name,
    )


__all__ = ["INTENTS", "ambiguous_intents"]
```

Update `src/precondition_library/tasks/__init__.py`:

```python
"""Task family: seeded, checkable, branchy git maintenance chores."""

from __future__ import annotations

from .faults import ALL as ALL_FAULTS
from .intent import IntentSpec, ResolutionVariant
from .registry import INTENTS, ambiguous_intents
from .spec import FaultSpec, GroundTruth

__all__ = [
    "ALL_FAULTS",
    "INTENTS",
    "FaultSpec",
    "GroundTruth",
    "IntentSpec",
    "ResolutionVariant",
    "ambiguous_intents",
]
```

Then remove the two `@pytest.mark.skip` decorators added in Task 3 to `tests/test_text_determinism.py` (`test_same_seed_same_text` and `test_text_does_not_depend_on_process_hash_seed`). With `tasks/registry.py` in place `ambiguous_intents` imports, so both become real tests; the second is the point where the process-hash-seed determinism check actually runs, proving the sampler does not depend on `hash()`'s per-process salt.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS — `tests/test_intent_ambiguity.py` and `tests/test_text_determinism.py` fully green, plus the pre-existing `2 passed, 30 skipped` from the rest.

- [ ] **Step 5: Commit**

```bash
git add src/precondition_library/tasks/registry.py src/precondition_library/tasks/__init__.py tests/test_intent_ambiguity.py
git commit -m "feat(tasks): register ambiguous intents and pin the label-invariance property"
```

---

### Task 8: The labelled-pair generator

**Files:**
- Create: `src/precondition_library/bench/pairs.py`
- Test: `tests/test_pairs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pairs.py`:

```python
"""The primary metric's raw material.

Every rate this repository reports has to come with its denominator, and the
label has to be a property of the state rather than of anybody's behaviour.
"""

from __future__ import annotations

import pytest

from precondition_library.bench.pairs import (
    decision_is_correct,
    denominator_report,
    label,
    labelled_pairs,
    positive_subset,
)
from precondition_library.tasks.registry import INTENTS, ambiguous_intents

SEEDS = list(range(12))


def test_label_is_a_property_of_state_not_wording(state_grid) -> None:
    intent = INTENTS["sync_fork_with_upstream"]
    states = list(state_grid["sync_fork_with_upstream"].values())
    pairs = labelled_pairs(intent, states, SEEDS)
    by_state: dict[int, set[str | None]] = {}
    for pair in pairs:
        by_state.setdefault(id(pair.state), set()).add(pair.correct_variant)
    assert all(len(answers) == 1 for answers in by_state.values())


def test_benign_states_produce_negative_pairs(state_grid) -> None:
    intent = INTENTS["sync_fork_with_upstream"]
    benign = [state_grid["sync_fork_with_upstream"]["benign_nothing_local"]]
    pairs = labelled_pairs(intent, benign, SEEDS)
    assert pairs, "the generator must not silently produce nothing"
    assert all(pair.is_negative for pair in pairs)
    assert all(pair.correct_variant is None for pair in pairs)


def test_firing_a_program_is_wrong_on_a_benign_state(state_grid) -> None:
    """The label a dispatcher is graded against: on a benign state, every
    program is the wrong program."""
    intent = INTENTS["sync_fork_with_upstream"]
    pair = label(
        intent, seed=1, state=state_grid["sync_fork_with_upstream"]["benign_nothing_local"]
    )
    assert decision_is_correct(pair, candidate_variant="rebase") is False
    assert decision_is_correct(pair, candidate_variant="discard") is False


def test_wrong_resolution_is_wrong_and_right_one_is_right(state_grid) -> None:
    intent = INTENTS["sync_fork_with_upstream"]
    state = state_grid["sync_fork_with_upstream"]["overlapping_files"]  # merge is correct
    pair = label(intent, seed=3, state=state)
    assert decision_is_correct(pair, candidate_variant="merge") is True
    assert decision_is_correct(pair, candidate_variant="rebase") is False
    assert decision_is_correct(pair, candidate_variant="discard") is False


def test_generator_rejects_empty_input(state_grid) -> None:
    intent = INTENTS["sync_fork_with_upstream"]
    with pytest.raises(ValueError, match="produced no pairs"):
        labelled_pairs(intent, [], SEEDS)
    with pytest.raises(ValueError, match="produced no pairs"):
        labelled_pairs(intent, list(state_grid["sync_fork_with_upstream"].values()), [])


def test_denominators_add_up(state_grid) -> None:
    pairs = []
    for intent in ambiguous_intents():
        pairs.extend(labelled_pairs(intent, list(state_grid[intent.name].values()), SEEDS))
    report = denominator_report(pairs)
    assert report["pairs"] == report["positive"] + report["negative"]
    assert report["ambiguous"] <= report["pairs"]
    assert report["positive"] == len(positive_subset(pairs))
    assert report["negative"] > 0, "a denominator report with no negatives hides half the test"


def test_every_ambiguous_intent_contributes_pairs(state_grid) -> None:
    for intent in ambiguous_intents():
        pairs = labelled_pairs(intent, list(state_grid[intent.name].values()), SEEDS)
        assert len(pairs) == len(state_grid[intent.name]) * len(SEEDS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pairs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'precondition_library.bench.pairs'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/precondition_library/bench/pairs.py`:

```python
"""Labelled (state, resolution) pairs -- the primary metric's raw material.

The spec moved the primary metric to a dispatch-level comparison at matched
coverage. That needs something an episode loop cannot provide: a label per
decision, independent of any agent's behaviour. This module derives those labels
from the intents' own decision rules, which are ground truth and deliberately NOT
the programs' probe strings (issue #9) -- a wrong precondition must not be able to
make its own program look correct.

Why this seam lives here rather than in the dispatch-level harness (issue #5):
issue #3 requires an AUC control and mismatch scored "on the ambiguous subset,
with the denominator reported". Neither exists without per-instance labels, and
the label definition must be frozen before any arm is built, or the comparison
can be tuned into existence. Issue #5 adds the threshold sweep and coverage
curves on top of this module; it should not also have to define what a wrong
answer is.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel

from ..signatures import StateFingerprint
from ..tasks.intent import IntentSpec


class LabelledPair(BaseModel):
    """One dispatch decision, with its answer."""

    intent: str
    seed: int
    state: StateFingerprint
    correct_variant: str | None
    """None means no resolution is correct: the environment needs nothing done, so
    every program must refuse to fire. Negative examples are half the point -- a
    dispatcher that always fires can only be caught by them."""
    task_text: str
    ambiguous: bool
    """True when the intent has two or more resolutions, so the text alone cannot decide."""

    @property
    def is_negative(self) -> bool:
        return self.correct_variant is None


def label(intent: IntentSpec, seed: int, state: StateFingerprint) -> LabelledPair:
    """Label one (intent, state) instance. Pure: no environment, no model."""
    resolved = intent.correct_variant(state)
    return LabelledPair(
        intent=intent.name,
        seed=seed,
        state=state,
        correct_variant=resolved.id if resolved is not None else None,
        task_text=intent.task_text(seed),
        ambiguous=intent.is_ambiguous,
    )


def labelled_pairs(
    intent: IntentSpec,
    states: Sequence[StateFingerprint],
    seeds: Sequence[int],
) -> list[LabelledPair]:
    """Cross the given states with the given seeds.

    Every state is paired with every seed, because the label must be invariant
    under the request's wording: if relabelling moved with the text, the label
    would be a property of the phrasing and the exercise would be circular.
    """
    pairs = [label(intent, seed, state) for state in states for seed in seeds]
    if not pairs:
        raise ValueError("produced no pairs; check states and seeds are non-empty")
    return pairs


def decision_is_correct(pair: LabelledPair, candidate_variant: str) -> bool:
    """Would replaying a program that implements `candidate_variant` be right?

    This is the grading function for a dispatch decision, and the reason
    `Program.variant` exists: without it a wrong answer is undefinable.
    """
    return pair.correct_variant is not None and candidate_variant == pair.correct_variant


def ambiguous_subset(pairs: Iterable[LabelledPair]) -> list[LabelledPair]:
    """Only the pairs on which a dispatcher comparison means anything."""
    return [pair for pair in pairs if pair.ambiguous]


def positive_subset(pairs: Iterable[LabelledPair]) -> list[LabelledPair]:
    """Pairs where some program should fire."""
    return [pair for pair in pairs if not pair.is_negative]


def denominator_report(pairs: Iterable[LabelledPair]) -> dict[str, int]:
    """Every rate this repository reports must come with its denominator."""
    materialised = list(pairs)
    positive = positive_subset(materialised)
    return {
        "pairs": len(materialised),
        "ambiguous": len(ambiguous_subset(materialised)),
        "positive": len(positive),
        "negative": len(materialised) - len(positive),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pairs.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/precondition_library/bench/pairs.py tests/test_pairs.py
git commit -m "feat(bench): add the labelled dispatch-pair generator"
```

---

### Task 9: The text-only control classifier

**Files:**
- Create: `src/precondition_library/bench/textcontrol.py`
- Test: `tests/test_task_text_is_not_a_label.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_text_is_not_a_label.py`:

```python
"""The control that detects the defect this change exists to remove.

A control that has never been seen to fire is not a control. So this file has two
halves: a positive control proving the detector fires on a leaky intent, and the
real assertion that the registered ambiguous intents do not leak.
"""

from __future__ import annotations

import pytest

from precondition_library.bench.pairs import labelled_pairs
from precondition_library.bench.textcontrol import (
    LEAKAGE_CEILING,
    TextOnlyClassifier,
    leakage_verdict,
    roc_auc,
)
from precondition_library.tasks.intent import IntentSpec, ResolutionVariant
from precondition_library.tasks.registry import ambiguous_intents

TRAIN_SEEDS = list(range(0, 40))
EVAL_SEEDS = list(range(100, 140))


def test_auc_is_one_for_a_perfect_ranking() -> None:
    assert roc_auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0


def test_auc_is_zero_for_a_perfectly_inverted_ranking() -> None:
    assert roc_auc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0


def test_auc_is_one_half_for_all_ties() -> None:
    assert roc_auc([0.5, 0.5, 0.5, 0.5], [True, True, False, False]) == 0.5


def test_auc_rejects_a_single_class() -> None:
    with pytest.raises(ValueError, match="only one class"):
        roc_auc([0.1, 0.2], [True, True])


def test_classifier_learns_a_separable_problem() -> None:
    """The classifier must be capable of learning a separation at all, or the
    real assertion below could pass merely because the model is broken.

    Asserted as a ranking rather than an exact label flip: gradient descent on a
    separable problem reaches a correct ranking well before every point crosses
    its decision boundary, and the control only ever consumes the score.
    """
    texts = ["alpha alpha alpha", "alpha alpha", "beta beta beta", "beta beta"]
    labels = ["alpha", "alpha", "beta", "beta"]
    model = TextOnlyClassifier.fit(texts, labels, epochs=600)
    scores = [model.predict_proba(text)["alpha"] for text in texts]
    assert roc_auc(scores, [True, True, False, False]) >= 0.99


def test_classifier_rejects_one_class() -> None:
    with pytest.raises(ValueError, match="at least two classes"):
        TextOnlyClassifier.fit(["a b", "c d"], ["same", "same"])


@pytest.fixture
def leaky_intent() -> IntentSpec:
    """Mirrors the flaw being fixed: one fixed sentence per resolution.

    The two resolutions are phrased so the text *does* determine the answer --
    which is exactly what the old `task_text()` did for every fault.
    """
    return IntentSpec(
        name="leaky_fixture",
        fault="diverged",
        phrasings=["reset this branch, discard my work"],
        naming_markers=["discard"],
        variants=[
            ResolutionVariant(id="discard", decided_by=lambda state: True, rationale="fixture"),
            ResolutionVariant(
                id="rebase_variant",
                decided_by=lambda state: False,
                rationale="fixture",
            ),
        ],
    )


def test_positive_control_the_detector_fires_on_a_leaky_intent(leaky_intent) -> None:
    """If this test ever passes silently as a no-op, the real assertion below is
    worthless. The detector must be shown to fire on a known-bad input."""
    from precondition_library.bench.pairs import label
    from precondition_library.signatures import StateFingerprint

    state = StateFingerprint(
        dirty_worktree=False,
        branch="main",
        upstream_ahead=3,
        upstream_behind=0,
        has_locked_branch=False,
        has_submodule_reference=False,
        upstream_behind=1,
        local_touched_files=["a.py"],
    )
    pairs = [label(leaky_intent, seed, state) for seed in TRAIN_SEEDS + EVAL_SEEDS]
    verdict = leakage_verdict(pairs, train_seeds=TRAIN_SEEDS, eval_seeds=EVAL_SEEDS)
    assert verdict.auc > LEAKAGE_CEILING
    assert verdict.leaks is True


def test_ambiguous_intents_do_not_leak_the_answer(state_grid) -> None:
    """The real assertion.

    Train on the request text of one seed set, evaluate on a disjoint one. A
    single fixed sentence per resolution would drive this to 1.0; the paraphrase
    distribution must keep it near chance on the ambiguous subset.
    """
    for intent in ambiguous_intents():
        pairs = labelled_pairs(
            intent, list(state_grid[intent.name].values()), TRAIN_SEEDS + EVAL_SEEDS
        )
        verdict = leakage_verdict(pairs, train_seeds=TRAIN_SEEDS, eval_seeds=EVAL_SEEDS)
        assert verdict.leaks is False, f"{intent.name}: {verdict.describe()}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_text_is_not_a_label.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'precondition_library.bench.textcontrol'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/precondition_library/bench/textcontrol.py`:

```python
"""A control that detects the defect this whole change exists to remove.

If a dispatcher needs only the request text to choose the right resolution, then
the text is a class label and any dispatch comparison is vacuous. That failure is
easy to miss by inspection, so it is measured: a deliberately simple
bag-of-words classifier is trained on the text alone and its AUC is reported.

Simple is the right choice. The question is whether the text *can* be sufficient,
not whether a sophisticated model could exploit it -- if even a linear model over
word counts separates the classes, the flaw is proven, and a stronger model would
only widen the separation. If the simple model cannot separate them, that is weak
evidence the text is uninformative at this sample size, and `describe()` says so
rather than claiming more.

`tests/test_task_text_is_not_a_label.py` pins both directions: a positive control
that the detector fires on a known-leaky intent, and the real assertion that the
registered intents do not leak.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .pairs import LabelledPair

LEAKAGE_CEILING = 0.65
"""AUC above which the control reports leakage. Declared here, not chosen after
seeing a number: a threshold picked post hoc is not a control."""


def _tokens(text: str) -> list[str]:
    return [token for token in "".join(c.lower() if c.isalnum() else " " for c in text).split()]


def _counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _tokens(text):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _softmax(scores: Sequence[float]) -> list[float]:
    top = max(scores)
    exps = [math.exp(score - top) for score in scores]
    total = sum(exps)
    return [value / total for value in exps]


@dataclass
class TextOnlyClassifier:
    """Bag-of-words logistic regression trained by full-batch-free gradient descent.

    Multinomial with mean-squared-free cross-entropy updates. Small enough to
    read in one sitting on purpose: the control's job is to be obviously not
    clever, so that a separation it finds is credible.
    """

    labels: list[str]
    weights: dict[str, list[float]]
    bias: list[float]

    @classmethod
    def fit(
        cls,
        texts: Sequence[str],
        labels: Sequence[str],
        *,
        learning_rate: float = 0.5,
        epochs: int = 400,
    ) -> TextOnlyClassifier:
        if len(texts) != len(labels):
            raise ValueError("texts and labels must be the same length")
        classes = sorted(set(labels))
        if len(classes) < 2:
            raise ValueError("need at least two classes to train a classifier")
        index = {label: position for position, label in enumerate(classes)}
        vocabulary = sorted({token for text in texts for token in _tokens(text)})
        weights = {token: [0.0] * len(classes) for token in vocabulary}
        bias = [0.0] * len(classes)

        for _ in range(epochs):
            for text, label in zip(texts, labels, strict=True):
                counts = _counts(text)
                scores = [
                    bias[k] + sum(weights[token][k] * n for token, n in counts.items())
                    for k in range(len(classes))
                ]
                probabilities = _softmax(scores)
                target = index[label]
                for k in range(len(classes)):
                    error = probabilities[k] - (1.0 if k == target else 0.0)
                    bias[k] -= learning_rate * error
                    for token, n in counts.items():
                        weights[token][k] -= learning_rate * error * n
        return cls(labels=classes, weights=weights, bias=bias)

    def predict_proba(self, text: str) -> dict[str, float]:
        counts = _counts(text)
        scores = [
            self.bias[k]
            + sum(
                self.weights.get(token, [0.0] * len(self.labels))[k] * n
                for token, n in counts.items()
            )
            for k in range(len(self.labels))
        ]
        return dict(zip(self.labels, _softmax(scores), strict=True))


def roc_auc(scores: Sequence[float], positives: Sequence[bool]) -> float:
    """Rank-based AUC with ties handled by average rank.

    Implemented rather than imported: scikit-learn is not a dependency of this
    project, and a control that needs a new dependency to run is a control that
    gets skipped.
    """
    if len(scores) != len(positives):
        raise ValueError("scores and positives must be the same length")
    positive_count = sum(positives)
    negative_count = len(positives) - positive_count
    if positive_count == 0 or negative_count == 0:
        raise ValueError("AUC is undefined with only one class present")

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1

    rank_sum = sum(rank for rank, is_positive in zip(ranks, positives, strict=True) if is_positive)
    return (rank_sum - positive_count * (positive_count + 1) / 2) / (
        positive_count * negative_count
    )


@dataclass(frozen=True)
class LeakageVerdict:
    auc: float
    ceiling: float
    classes: list[str]
    n_train: int
    n_eval: int

    @property
    def leaks(self) -> bool:
        return self.auc > self.ceiling

    def describe(self) -> str:
        return (
            f"text-only AUC {self.auc:.3f} over {len(self.classes)} classes "
            f"(train n={self.n_train}, eval n={self.n_eval}, ceiling {self.ceiling}); "
            + (
                "LEAKAGE -- the request text predicts the answer"
                if self.leaks
                else "no leakage detected at this sample size"
            )
        )


def leakage_verdict(
    pairs: Iterable[LabelledPair],
    *,
    train_seeds: Sequence[int],
    eval_seeds: Sequence[int],
    ceiling: float = LEAKAGE_CEILING,
) -> LeakageVerdict:
    """Train on the text from one seed set, evaluate on a disjoint one.

    Only positive pairs are used: a negative pair's "answer" is "fire nothing",
    which is not a resolution a text classifier could be said to get right or
    wrong, and including it would inflate or deflate AUC for reasons unrelated to
    leakage.

    One-vs-rest AUC is averaged over the eval classes. The label set is tiny and
    the control's only job is to detect a text that gives the answer away.
    """
    train_set = set(train_seeds)
    eval_set = set(eval_seeds)
    materialised = list(pairs)
    train = [p for p in materialised if p.seed in train_set and not p.is_negative]
    evaluation = [p for p in materialised if p.seed in eval_set and not p.is_negative]
    if not train or not evaluation:
        raise ValueError("need non-empty train and eval sets of positive pairs")

    model = TextOnlyClassifier.fit(
        [p.task_text for p in train],
        [p.correct_variant for p in train if p.correct_variant is not None],
    )

    classes = sorted({p.correct_variant for p in evaluation if p.correct_variant is not None})
    aucs: list[float] = []
    for cls in classes:
        scores = [model.predict_proba(p.task_text).get(cls, 0.0) for p in evaluation]
        positives = [p.correct_variant == cls for p in evaluation]
        if all(positives) or not any(positives):
            continue
        aucs.append(roc_auc(scores, positives))
    if not aucs:
        raise ValueError("every eval class is degenerate; AUC is undefined")

    return LeakageVerdict(
        auc=sum(aucs) / len(aucs),
        ceiling=ceiling,
        classes=classes,
        n_train=len(train),
        n_eval=len(evaluation),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_task_text_is_not_a_label.py -v`
Expected: PASS, 8 tests. The positive control fires (`leaks is True`) and both ambiguous intents show `leaks is False`.

If `test_ambiguous_intents_do_not_leak_the_answer` fails, the correct response is to **widen the paraphrase distribution**, not to raise `LEAKAGE_CEILING`. A failing control here means the intent still leaks, which is precisely the defect being fixed.

- [ ] **Step 5: Commit**

```bash
git add src/precondition_library/bench/textcontrol.py tests/test_task_text_is_not_a_label.py
git commit -m "test(bench): add the text-only leakage control with a positive control"
```

---

### Task 10: Hand-written gold resolutions

**Files:**
- Create: `bench/gold/sync_fork_with_upstream.yaml`
- Create: `bench/gold/restore_submodule_state.yaml`
- Test: `tests/test_gold_programs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gold_programs.py`:

```python
"""Gold resolutions must be well-formed, and must exist for every resolution.

These are the >=2 candidates issue #3 asks for, written by hand because the
compile step (issue #4) does not exist yet. Gold-first is a rule here, not a
convenience: a benchmark whose checkers are wrong reports plausible numbers that
mean nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from precondition_library.program import Program, ProgramStatus
from precondition_library.tasks.registry import ambiguous_intents

GOLD = Path(__file__).resolve().parents[1] / "bench" / "gold"


def load(intent_name: str) -> list[Program]:
    document = yaml.safe_load((GOLD / f"{intent_name}.yaml").read_text(encoding="utf-8"))
    return [Program.model_validate(entry) for entry in document["programs"]]


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_every_ambiguous_intent_has_gold_programs(intent: str) -> None:
    programs = load(intent)
    assert len(programs) >= 2, "an ambiguous intent needs at least two candidates"


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_gold_covers_every_declared_resolution(intent: str) -> None:
    declared = {v.id for spec in ambiguous_intents() if spec.name == intent for v in spec.variants}
    assert {program.variant for program in load(intent)} == declared


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_gold_programs_are_well_formed(intent: str) -> None:
    for program in load(intent):
        assert program.intent == intent
        assert program.status is ProgramStatus.CANDIDATE, "hand-written != admitted"
        assert program.preconditions, f"{program.id}: needs preconditions"
        assert program.postconditions, f"{program.id}: needs postconditions"
        assert program.body.strip(), f"{program.id}: needs a body"
        for predicate in program.preconditions + program.postconditions:
            assert predicate.probe.strip(), f"{program.id}: {predicate.name} has an empty probe"
            assert predicate.description.strip(), f"{program.id}: {predicate.name} undescribed"


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_gold_bodies_are_distinct(intent: str) -> None:
    """Two candidates that do the same thing are not two resolutions."""
    bodies = {p.body.strip() for p in load(intent)}
    assert len(bodies) == len(load(intent))


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_gold_provenance_says_hand_written(intent: str) -> None:
    for program in load(intent):
        assert "hand-written" in program.provenance.compiled_from_task
        assert program.provenance.compiler_version == "human"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gold_programs.py -v`
Expected: FAIL — `FileNotFoundError: .../bench/gold/sync_fork_with_upstream.yaml`.

- [ ] **Step 3: Write the gold files, and correct the gold README**

Create `bench/gold/sync_fork_with_upstream.yaml`:

```yaml
# Hand-written resolutions for the `sync_fork_with_upstream` intent.
#
# These exist because issue #3 requires at least two candidates under one intent,
# and the compile step that would generate them is issue #4. They are gold, not
# generated: the spec's gold-first rule requires hand-written solutions that must
# satisfy the checkers before any agent result is believed.
#
# Preconditions are probes, so they must agree with the intent's decision rule
# (decided_by in tasks/faults/diverged.py). They are written independently --
# agreeing by construction would defeat the point of having a check.
programs:
  - id: sync-fork-empty-local-commits
    intent: sync_fork_with_upstream
    variant: discard
    parameters: [work_dir, upstream_remote, upstream_branch]
    preconditions:
      - name: has_local_only_commits
        description: The local branch is ahead of upstream.
        probe: 'test "$(git rev-list --count {upstream_remote}/{upstream_branch}..HEAD)" -gt 0'
      - name: local_commits_change_nothing
        description: The local-only commits touch no files, so they carry no work.
        probe: 'test -z "$(git diff --name-only {upstream_remote}/{upstream_branch}...HEAD)"'
    body: |
      git fetch {upstream_remote}
      git reset --hard {upstream_remote}/{upstream_branch}
    postconditions:
      - name: matches_upstream
        description: The local branch is exactly upstream's commit.
        probe: 'test "$(git rev-parse HEAD)" = "$(git rev-parse {upstream_remote}/{upstream_branch})"'
    provenance:
      compiled_from_task: hand-written gold resolution for benchmarking
      model: human
      compiler_version: human
      episode_id: gold/sync_fork_with_upstream/discard
    status: candidate

  - id: sync-fork-disjoint-rebase
    intent: sync_fork_with_upstream
    variant: rebase
    parameters: [work_dir, upstream_remote, upstream_branch]
    preconditions:
      - name: has_local_only_commits
        description: The local branch is ahead of upstream.
        probe: 'test "$(git rev-list --count {upstream_remote}/{upstream_branch}..HEAD)" -gt 0'
      - name: local_commits_change_files
        description: The local-only commits do change files.
        probe: 'test -n "$(git diff --name-only {upstream_remote}/{upstream_branch}...HEAD)"'
    body: |
      git fetch {upstream_remote}
      git rebase {upstream_remote}/{upstream_branch}
    postconditions:
      - name: upstream_contained
        description: Upstream's tip is now an ancestor of the local branch.
        probe: 'git merge-base --is-ancestor {upstream_remote}/{upstream_branch} HEAD'
      - name: no_residual_changes
        description: The worktree is clean afterwards.
        probe: 'test -z "$(git status --porcelain)"'
    provenance:
      compiled_from_task: hand-written gold resolution for benchmarking
      model: human
      compiler_version: human
      episode_id: gold/sync_fork_with_upstream/rebase
    status: candidate

  - id: sync-fork-overlapping-merge
    intent: sync_fork_with_upstream
    variant: merge
    parameters: [work_dir, upstream_remote, upstream_branch]
    preconditions:
      - name: has_local_only_commits
        description: The local branch is ahead of upstream.
        probe: 'test "$(git rev-list --count {upstream_remote}/{upstream_branch}..HEAD)" -gt 0'
      - name: upstream_touched_a_local_file
        description: At least one file both sides changed, so rewriting local history would risk losing a resolution.
        probe: 'test -n "$(comm -12 <(git diff --name-only {upstream_remote}/{upstream_branch}...HEAD | sort) <(git diff --name-only HEAD...{upstream_remote}/{upstream_branch} | sort))"'
    body: |
      git fetch {upstream_remote}
      git merge --no-edit {upstream_remote}/{upstream_branch}
    postconditions:
      - name: upstream_contained
        description: Upstream's tip is reachable from the local branch.
        probe: 'git merge-base --is-ancestor {upstream_remote}/{upstream_branch} HEAD'
      - name: local_commits_survived
        description: The pre-merge local tip is still reachable, so no work was discarded.
        probe: 'git rev-parse --verify HEAD~1 >/dev/null 2>&1'
    provenance:
      compiled_from_task: hand-written gold resolution for benchmarking
      model: human
      compiler_version: human
      episode_id: gold/sync_fork_with_upstream/merge
    status: candidate
```

Create `bench/gold/restore_submodule_state.yaml`:

```yaml
# Hand-written resolutions for the `restore_submodule_state` intent.
# See the header of sync_fork_with_upstream.yaml for why these are hand-written.
programs:
  - id: submodule-init
    intent: restore_submodule_state
    variant: init
    parameters: [work_dir, submodule_path]
    preconditions:
      - name: submodule_declared
        description: The repository declares the submodule.
        probe: 'test -f .gitmodules && git config --file .gitmodules --get-regexp path >/dev/null'
      - name: submodule_not_initialised
        description: The submodule directory has never been initialised in this clone.
        probe: 'test -z "$(git submodule status -- {submodule_path} | grep -v "^-")"'
    body: |
      git submodule update --init -- {submodule_path}
    postconditions:
      - name: submodule_initialised
        description: No submodule is left uninitialised.
        probe: 'test -z "$(git submodule status | grep "^-")"'
    provenance:
      compiled_from_task: hand-written gold resolution for benchmarking
      model: human
      compiler_version: human
      episode_id: gold/restore_submodule_state/init
    status: candidate

  - id: submodule-repin
    intent: restore_submodule_state
    variant: repin
    parameters: [work_dir, submodule_path]
    preconditions:
      - name: submodule_initialised
        description: The submodule directory exists and has a checkout.
        probe: 'test -n "$(git submodule status -- {submodule_path} | grep -v "^-")"'
      - name: upstream_still_tracks_it
        description: Upstream's tree still contains the submodule path.
        probe: 'test -n "$(git ls-tree {upstream_remote}/{upstream_branch} -- {submodule_path})"'
    body: |
      git fetch {upstream_remote}
      git checkout {upstream_remote}/{upstream_branch} -- {submodule_path}
    postconditions:
      - name: pinned_to_upstream
        description: The recorded submodule commit is no longer drifted from upstream.
        probe: 'test -z "$(git diff --name-only {upstream_remote}/{upstream_branch} -- {submodule_path})"'
    provenance:
      compiled_from_task: hand-written gold resolution for benchmarking
      model: human
      compiler_version: human
      episode_id: gold/restore_submodule_state/repin
    status: candidate

  - id: submodule-remove
    intent: restore_submodule_state
    variant: remove
    parameters: [work_dir, submodule_path]
    preconditions:
      - name: upstream_dropped_it
        description: Upstream's tree no longer contains the submodule path.
        probe: 'test -z "$(git ls-tree {upstream_remote}/{upstream_branch} -- {submodule_path})"'
    body: |
      git rm --cached -- {submodule_path}
      git config --file .gitmodules --remove-section submodule.{submodule_path} || true
      git add .gitmodules
    postconditions:
      - name: no_longer_declared
        description: The submodule is no longer declared in the tree.
        probe: 'test -z "$(git ls-files --stage -- {submodule_path})"'
    provenance:
      compiled_from_task: hand-written gold resolution for benchmarking
      model: human
      compiler_version: human
      episode_id: gold/restore_submodule_state/remove
    status: candidate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_gold_programs.py -v`
Expected: PASS, 10 tests (5 parametrised tests × 2 intents).

**Also in this step:** `bench/gold/README.md` says the gold check "is skipped until phase 1" and that the directory contains only a README. This task makes both statements false. Replace that paragraph with:

```markdown
The check runs today for the two ambiguous intents: gold resolutions live in
`sync_fork_with_upstream.yaml` and `restore_submodule_state.yaml`, and
`tests/test_gold_programs.py` validates that they parse, are well-formed, cover
every declared resolution, and have distinct bodies. It is still skipped for the
faults whose injection needs a live sandbox (issue #4), because a checker cannot
be validated without a state to check.
```

Leaving a stale "not implemented yet" note in place after implementing it is the same class of defect as claiming a stub is done — `CONTRIBUTING.md` rule 4.

- [ ] **Step 5: Commit**

```bash
git add bench/gold/sync_fork_with_upstream.yaml bench/gold/restore_submodule_state.yaml tests/test_gold_programs.py
git commit -m "test(bench): add hand-written gold resolutions for both ambiguous intents"
```

---

### Task 11: Un-skip the determinism tests that can now really run

**Files:**
- Modify: `tests/test_faults_deterministic.py`

- [ ] **Step 1: Rewrite the file**

Replace the whole of `tests/test_faults_deterministic.py`:

```python
"""Same seed, same faulty environment.

The ablation compares arms on shared environments, so non-determinism in fault
injection would introduce variance that looks like a difference between arms.
Determinism is also what lets a reported episode be re-run and inspected later.

Split by what can run today: the request text is a pure function and is tested
for real; the injected *state* needs the live sandbox (issue #4) and stays
skipped, with the phase that will implement it named rather than implied.
"""

from __future__ import annotations

import pytest

from precondition_library.tasks import ALL_FAULTS
from precondition_library.tasks.registry import ambiguous_intents


@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_same_seed_same_task_text(fault_type: str) -> None:
    """Real, not skipped: `task_text` is pure, and it is the one place this
    project introduces randomness."""
    from precondition_library.tasks.faults import FAULTS

    fault = FAULTS[fault_type]
    assert fault.task_text(5) == fault.task_text(5)
    assert isinstance(fault.task_text(5), str)


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_occurrences_are_not_clones(intent: str) -> None:
    """Occurrences must not be clones of each other, or `occurrence_index` would
    count repetitions of one scenario instead of recurrences of a task family.

    Asserted over a wide seed range because a paraphrase distribution with a
    dominant phrasing would silently collapse the recurrence structure -- and
    that would flatter the cost model without anyone noticing.
    """
    from precondition_library.tasks.registry import INTENTS

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
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_faults_deterministic.py -v`
Expected: PASS — 7 tests pass (5 faults + 2 intents), 10 remain skipped.

If `test_occurrences_are_not_clones` fails with "some phrasings are unreachable", the sampler is skewed; the fix is to check `sample_index` distributes over the phrasing count, not to lower the assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/test_faults_deterministic.py
git commit -m "test(tasks): un-skip task-text determinism and prove phrasings are all reachable"
```

---

### Task 12: Documentation and the full-suite check

**Files:**
- Modify: `docs/superpowers/specs/2026-09-13-precondition-library-design.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update the spec's task-family section**

In `docs/superpowers/specs/2026-09-13-precondition-library-design.md`, find the `### The five faults` table in §3 and add immediately after it:

```markdown
### Intents and resolutions (§3, revised 2026-09-13)

A fault's request text used to be one fixed sentence, which made the text a
perfect class label and the primary claim untestable. The task family is now
described by **intents**, each carrying a paraphrase distribution and one or more
**resolutions** decided only by observable state:

| intent | resolutions | decided by |
| --- | --- | --- |
| `sync_fork_with_upstream` | discard / rebase / merge | whether local-only commits change files at all, and whether they touch files upstream also changed |
| `restore_submodule_state` | init / repin / remove | whether the submodule is initialised, whether upstream still references it, whether the recorded pin matches |

Only intents with two or more resolutions have an experimental surface, and
`tasks/registry.py` is the single place that distinction lives, so an
unambiguous intent cannot be counted into a dispatch rate as if it were evidence.
A resolution is `None` for a *benign* state — nothing to do — and such pairs are
labelled negatives, because a dispatcher that always fires can only be caught by
states that require refusal.

The request text is sampled deterministically from the paraphrase distribution
(`sha256` over the seed, never `hash()`, which CPython salts per process). Whether
the text still leaks the answer is **measured** rather than assumed:
`bench/textcontrol.py` trains a bag-of-words classifier on the text alone and
reports its AUC, with a positive control proving the detector fires on a leaky
intent.
```

- [ ] **Step 2: Update the spec's testing section**

In §10 (Testing strategy), add this line to the code block, after the `DETERMINISM` entry:

```
TEXT LEAKAGE    a bag-of-words classifier trained on the request text alone
                must not predict the resolution. Pinned by a positive control
                that fires on a deliberately leaky intent, so the control
                cannot pass by being a no-op.
```

- [ ] **Step 3: Update the changelog**

Add to `CHANGELOG.md` under `## [Unreleased]`, replacing the `### Changed` stub:

```markdown
### Added

- `IntentSpec` and `ResolutionVariant`: intents carry a paraphrase distribution
  and two or more resolutions decided only by observable state
  (`tasks/intent.py`, `tasks/registry.py`).
- Labelled (state, resolution) pair generator with denominators
  (`bench/pairs.py`) — the raw material the spec's primary metric needs.
- A text-only leakage control with a positive control that proves the detector
  fires (`bench/textcontrol.py`).
- Hand-written gold resolutions for both ambiguous intents (`bench/gold/`).
- `Program.variant`, so a wrong dispatch decision is definable at all.

### Changed

- `diverged` and `submodule_moved` now have three state-decided resolutions each,
  replacing the single fixed request sentence that made the task text a class
  label and the primary claim untestable (issue #3).
```

- [ ] **Step 4: Run the whole suite, lint, and types**

Run:
```bash
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pytest -q
```
Expected: format reports files unchanged after the first run; ruff `All checks passed!`; mypy `Success: no issues found`; pytest green with the newly-real tests included and only the sandbox-dependent ones skipped.

- [ ] **Step 5: Commit and open the PR**

```bash
git add docs/superpowers/specs/2026-09-13-precondition-library-design.md CHANGELOG.md
git commit -m "docs: record intents and resolutions in the design of record"
git push -u origin pr/NN-intent-underdetermined-instances
gh pr create --base main --title "feat(tasks): make the task text stop being the ground-truth label" \
  --body "Closes #3. <fill in the PR template>"
```

`main` is protected: the PR must link issue #3, pass CI, and be rebase-merged. See `CONTRIBUTING.md`.

---

## Self-review

**Spec coverage.** §3's task family gains variants and a rationale for each (Tasks 4–5) plus the spec text (Task 12). §7's primary metric needs per-decision labels at matched coverage — the label seam is Task 8 and the denominators it must report are Task 8's `denominator_report`. §10's testing strategy gains the leakage control (Tasks 9, 12). Issue #3's five acceptance criteria map to: ≥2 candidates per ambiguous intent (Task 10), paraphrase distribution with a documented non-naming fraction (Tasks 4–5, `naming_fraction`), text-only AUC control with a recorded seed protocol (Task 9, `TRAIN_SEEDS`/`EVAL_SEEDS` are disjoint constants), mismatch on the ambiguous subset with a denominator (Task 8), and determinism of both text and the state-determined resolution (Tasks 6, 11).

**Deliberately not covered**, and stated as such in the plan header: live git injection (#4), compile-and-admission (#4), threshold sweeps and coverage curves (#5), baselines (#7), ledger (#8), safety (#10).

**Type consistency.** `ResolutionVariant.decided_by` takes a `StateFingerprint` and returns `bool` everywhere (Tasks 3–5). `IntentSpec.correct_variant` returns `ResolutionVariant | None` — the `None` case is what `LabelledPair.is_negative` keys off (Tasks 3, 8). `sample_index(seed, salt, n)` is defined in Task 3 and called only by `IntentSpec.task_text` (Task 3) — Task 11 asserts its distribution without re-implementing it. `Program.variant` is added in Task 4 and read in Task 10's gold loader and Task 8's `decision_is_correct`. `LEAKAGE_CEILING` is defined in Task 9's module and imported by its test, never redefined. `roc_auc(scores, positives)` keeps that argument order in all five call sites.

**Three defects found during self-review and fixed inline rather than deferred.**

1. Two documentation statements would have gone stale the moment this plan was executed — `bench/gold/README.md`'s "contains only a README / skipped until phase 1", and `FaultSpec.task_text`'s "varies by seed" docstring. Both are now explicit steps (Tasks 4, 10), because leaving a stale "not implemented yet" note after implementing something is the same class of defect as claiming a stub is done.
2. `test_occurrences_are_not_clones` asserted that 30 sampled seeds cover every phrasing. Sampling without replacement across buckets makes that **~14% likely to fail on a correct implementation** — a flaky test that would be "fixed" by weakening the assertion. Now 200 seeds, which makes a missed phrasing a real signal.
3. The classifier sanity test asserted an exact label flip on four training points, which depends on convergence rather than on capability. Now asserts a correct *ranking*, which is what the control actually consumes.

**Deliberately still open, and deliberately not steps in this plan:** `StateFingerprint.observe()` remains a stub, so a fingerprint cannot yet be produced from a real repository. Everything here consumes fingerprints rather than repositories, which is what keeps this change to one PR — but it means the plan's correctness rests on the discriminators being genuinely probeable. Task 1's docstring names the probe for each field for exactly that reason, and if one turns out not to be observable from git, the **variant must be redesigned**, not the label relaxed.
