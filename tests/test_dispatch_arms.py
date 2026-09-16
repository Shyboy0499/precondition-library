"""The two dispatch arms: one shared record, and no logic of their own.

§4 of the design spec makes the arms differ in exactly one function. These tests
pin that at the seam where it is cheapest to violate: `dispatch_semantic` and
`dispatch_preconditions` must return what their matcher chose, unmodified, in one
shared record type. A re-rank, a filter or a score adjustment added to either
function fails here rather than silently confounding the ablation.

Everything runs offline against a `tmp_path` library. Arm 3 alone needs a real
sandbox, and that sandbox is throwaway; neither arm writes to the repository.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import get_type_hints

import pytest

from precondition_library.agents.dispatch import (
    Dispatch,
    dispatch_preconditions,
    dispatch_semantic,
)
from precondition_library.library import Library, ScoredProgram
from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.sandbox import Sandbox, create
from precondition_library.signatures import StateFingerprint, TaskSignature

INTENT = "reconcile local commits with upstream"


@pytest.fixture(autouse=True)
def _repository_is_untouched(repository_unchanged):
    """A dispatch reads the repository and never writes it.

    Both arms take a `tmp_path` library and (arm 3) a sandbox under the system
    temp dir, so the committed library must be byte-identical afterwards. The
    comparison itself is `repository_unchanged` in `tests/conftest.py`, shared
    rather than copied per test module: it asserts the working tree is unchanged
    since import, which passes for a contributor whose branch has uncommitted
    work and still catches a leak.
    """
    yield


@pytest.fixture
def make_sandbox():
    """Build faulted sandboxes and destroy them however the test ends."""
    live: list[Sandbox] = []

    def build(seed: int, faults: list[str]) -> Sandbox:
        box = create(seed, faults)
        live.append(box)
        return box

    yield build
    for box in live:
        box.destroy()


def _fingerprint() -> StateFingerprint:
    return StateFingerprint(
        dirty_worktree=False,
        branch="main",
        upstream_ahead=2,
        upstream_behind=3,
        has_locked_branch=False,
        has_submodule_reference=False,
        remotes=["origin", "upstream"],
        local_touched_files=["app.py"],
        upstream_touched_files=["app.py"],
    )


def _signature(intent: str = INTENT) -> TaskSignature:
    return TaskSignature(
        intent=intent, fingerprint=_fingerprint(), target="/tmp/dispatch-arms-test"
    )


def _predicate(name: str, probe: str) -> Predicate:
    return Predicate(name=name, description=name, probe=probe)


def _program(
    program_id: str,
    *,
    descriptions: list[str],
    probes: list[tuple[str, str]],
    intent: str = INTENT,
    status: ProgramStatus = ProgramStatus.ADMITTED,
) -> Program:
    """One precondition per (name, probe) pair, described by `descriptions`.

    `descriptions` is what arm 2 reads -- a `Predicate`'s description is its
    English -- so it is kept separate from the probe name, exactly as a compiled
    program's `library.py` text is. `descriptions` and `probes` are parallel.
    """
    return Program(
        id=program_id,
        intent=intent,
        variant=None,
        parameters=["work_dir", "upstream_remote", "upstream_branch"],
        preconditions=[
            Predicate(name=name, description=description, probe=probe)
            for (name, probe), description in zip(probes, descriptions, strict=True)
        ],
        body="true",
        postconditions=[_predicate("noop", "true")],
        provenance=Provenance(
            compiled_from_task="dispatch-arms test fixture",
            model="human",
            compiler_version="human",
            episode_id=f"test/{program_id}",
        ),
        status=status,
    )


def _store(tmp_path: Path, programs: list[Program]) -> Library:
    """A library holding `programs` at the statuses they declare.

    `Library.add` takes only a candidate, so each program is added as one and
    then moved through the real transition table.
    """
    library = Library(tmp_path)
    for program in programs:
        library.add(program.model_copy(update={"status": ProgramStatus.CANDIDATE}))
        if program.status is not ProgramStatus.CANDIDATE:
            library.set_status(program.id, program.status)
    return library


def _discriminating(tmp_path: Path) -> Library:
    """Two admitted programs the two arms rank in opposite orders.

    Both texts clear arm 2's default floor, but `a-general` is the closer text
    (lexical score 0.27 against 0.18, measured with the shipped similarity) while
    `b-specific` has two preconditions to `a-general`'s one. Both preconditions
    hold on a fault-free clone, so the only reason the arms disagree is which
    matcher is called -- not what the state looks like.
    """
    general = _program(
        "a-general",
        descriptions=["the dirty worktree has local commits ahead of upstream"],
        probes=[("has_checkout", "test -d .git")],
    )
    specific = _program(
        "b-specific",
        intent="reconcile submodule state",
        descriptions=["the submodule is initialised", "the submodule pin matches upstream"],
        probes=[("has_checkout", "test -d .git"), ("has_head", "test -f .git/HEAD")],
    )
    return _store(tmp_path, [general, specific])


class _CannedLibrary:
    """A library whose matchers return fixed objects, so identity is checkable.

    The real `Library` reloads its programs from disk on every match, so two
    calls never return the same Python object and `is` could not pin "returned
    unmodified". This fake returns sentinels instead, which makes the claim
    exact. It is not a `Library`, but the dispatch functions only call the two
    matchers and Python does not check the annotation at runtime.

    The canned orders are deliberately *not* the orders a re-rank or a filter
    would produce: arm 2's first element has the lower of the two scores, and arm
    3's first element is not the one whose id sorts first. A dispatch function
    that picked the best score, sorted, or dropped a candidate fails here.
    """

    def __init__(self, ranked: list[ScoredProgram], accepted: list[Program]) -> None:
        self._ranked = ranked
        self._accepted = accepted
        self.semantic_calls = 0
        self.precondition_calls = 0

    def match_semantic(self, signature: TaskSignature) -> list[ScoredProgram]:
        self.semantic_calls += 1
        return list(self._ranked)

    def match_preconditions(self, signature: TaskSignature, env: Sandbox) -> list[Program]:
        self.precondition_calls += 1
        return list(self._accepted)


def test_each_arm_returns_its_matchers_first_element_unmodified(make_sandbox) -> None:
    """The returned program is the matcher's own first element, by identity.

    This is the test that pins §4. `is` rather than equality, so a function that
    copied, re-ranked, filtered or rebuilt the choice fails even when the rebuilt
    program compares equal. Each arm's matcher is consulted once and only once,
    and never the other arm's: a dispatch that asked arm 3's question would be a
    different mechanism wearing arm 2's name.
    """
    box = make_sandbox(11, [])
    first = _program("a-first", descriptions=["first"], probes=[("p", "true")])
    second = _program("b-second", descriptions=["second"], probes=[("p", "true")])
    ranked = [ScoredProgram(program=first, score=0.25), ScoredProgram(program=second, score=0.5)]
    accepted = [second, first]
    library = _CannedLibrary(ranked, accepted)

    semantic = dispatch_semantic(_signature(), library)
    preconditions = dispatch_preconditions(_signature(), library, box)

    assert semantic.program is ranked[0].program, "must take the matcher's order, not re-rank"
    assert semantic.score == ranked[0].score
    assert preconditions.program is accepted[0], "must take the matcher's first, not the best id"
    assert preconditions.score is None
    assert library.semantic_calls == 1 and library.precondition_calls == 1


def test_both_arms_return_the_same_record_shape(make_sandbox, tmp_path) -> None:
    """One `Dispatch` type with one set of fields, for either arm.

    The runner must need no per-arm branch beyond which function it calls: the
    arms differ in *one* function, not in what they report. Two return types
    would put the difference somewhere other than dispatch, which is the confound
    §4 forbids. The annotations are checked as well as the instances, so a second
    record type cannot be introduced without failing here.
    """
    assert [field.name for field in fields(Dispatch)] == ["program", "score", "reason"]
    assert get_type_hints(dispatch_semantic)["return"] is Dispatch
    assert get_type_hints(dispatch_preconditions)["return"] is Dispatch

    box = make_sandbox(14, [])
    never = _program(
        "a-absent",
        intent="decorate a cake",
        descriptions=["frosting and sprinkles"],
        probes=[("absent", "test -f definitely-not-here")],
    )
    library = _store(tmp_path, [never])

    semantic = dispatch_semantic(_signature(intent="xyzzy plugh"), library)
    preconditions = dispatch_preconditions(_signature(intent="xyzzy plugh"), library, box)

    assert type(semantic) is type(preconditions) is Dispatch
    assert {field.name for field in fields(semantic)} == {
        field.name for field in fields(preconditions)
    }
    assert semantic.program is None and preconditions.program is None


def test_arm3_picks_by_specificity_arm2_by_score(make_sandbox, tmp_path) -> None:
    """The same library and query, chosen differently by the two mechanisms.

    This is the clearest evidence the arms are not the same mechanism wearing two
    names: `a-general` wins on text and `b-specific` wins on precondition count.
    """
    box = make_sandbox(11, [])
    library = _discriminating(tmp_path)
    signature = _signature()

    semantic = dispatch_semantic(signature, library)
    preconditions = dispatch_preconditions(signature, library, box)

    assert semantic.program is not None and preconditions.program is not None
    assert semantic.program.id == "a-general", "arm 2 must take the nearest text"
    assert preconditions.program.id == "b-specific", "arm 3 must take the most specific"
    assert semantic.program.id != preconditions.program.id
    assert len(preconditions.program.preconditions) > len(semantic.program.preconditions)


def test_no_admitted_program_reports_nothing_applies(make_sandbox, tmp_path) -> None:
    """A library with no admitted program yields `None`, not an exception.

    Both stored programs have a probe that would hold on this sandbox, so the
    emptiness comes from the shared `admitted` filter and not from the probes;
    that is what makes this a check on the arms' fallback path rather than on a
    program that simply did not apply.
    """
    box = make_sandbox(12, [])
    holds = [("has_checkout", "test -d .git")]
    candidate = _program(
        "a-candidate",
        descriptions=["the dirty worktree has local commits ahead of upstream"],
        probes=holds,
        status=ProgramStatus.CANDIDATE,
    )
    quarantined = _program(
        "b-quarantined",
        descriptions=["the dirty worktree has local commits ahead of upstream"],
        probes=holds,
        status=ProgramStatus.QUARANTINED,
    )
    library = _store(tmp_path, [candidate, quarantined])

    # Not vacuous: both are stored and either would apply if it were admitted.
    assert len(library.load_all()) == 2
    assert evaluate_preconditions(candidate, box).ok is True

    semantic = dispatch_semantic(_signature(), library)
    preconditions = dispatch_preconditions(_signature(), library, box)

    assert semantic.program is None and semantic.score is None
    assert preconditions.program is None and preconditions.score is None
    assert semantic.reason and preconditions.reason, "a miss must say why, in words"


def test_below_the_floor_or_rejected_reports_nothing_applies(make_sandbox, tmp_path) -> None:
    """A miss for arm 2's reason and a miss for arm 3's reason look the same.

    The one admitted program is textually unrelated (so `match_semantic` returns
    `[]` under its floor) and its probe fails (so `match_preconditions` returns
    `[]`). Each arm misses for its own mechanism, and both report `None` through
    the same record rather than raising.
    """
    box = make_sandbox(13, [])
    unrelated = _program(
        "a-unrelated",
        intent="decorate a cake",
        descriptions=["frosting and sprinkles"],
        probes=[("absent", "test -f definitely-not-here")],
    )
    library = _store(tmp_path, [unrelated])
    signature = _signature(intent="xyzzy plugh")

    # Not vacuous: each matcher really is empty, for the reason this test names.
    assert library.match_semantic(signature) == []
    assert evaluate_preconditions(unrelated, box).ok is False
    assert library.match_preconditions(signature, box) == []

    semantic = dispatch_semantic(signature, library)
    preconditions = dispatch_preconditions(signature, library, box)

    assert semantic.program is None and preconditions.program is None


def test_arm2_carries_the_score_arm3_does_not(make_sandbox, tmp_path) -> None:
    """`dispatch_score` belongs to arm 2, and only arm 2.

    `bench/ledger.py` defines the field as "Similarity score for arm 2; None for
    the other arms". A score on arm 3's record would tell a reader it selected on
    a number it never computed.
    """
    box = make_sandbox(11, [])
    library = _discriminating(tmp_path)
    signature = _signature()

    semantic = dispatch_semantic(signature, library)
    preconditions = dispatch_preconditions(signature, library, box)

    assert semantic.program is not None and preconditions.program is not None
    assert isinstance(semantic.score, float)
    assert preconditions.score is None, (
        "arm 3 selects on a predicate verdict; a score here would be inconsistent "
        "with the ledger's field definition"
    )


def test_dispatch_leaves_the_repository_clean(repository_unchanged, make_sandbox, tmp_path) -> None:
    """Both arms run without writing to the repository's own working tree.

    Neither arm writes: the library is under `tmp_path` and the sandbox is
    throwaway. The assertion is "the working tree is unchanged since import",
    performed by `repository_unchanged` after the body -- not "the working tree
    is empty". The weaker-looking check is the stronger one: an empty status can
    only pass on a pristine checkout, so a contributor running the suite on a
    branch fails it for reasons unrelated to their change, and a real leak would
    be indistinguishable from their own edits. "Unchanged" fails only for the
    one thing this test is about, on any checkout. `_repository_is_untouched`
    above enforces the same shared check for every test in this file.
    """
    box = make_sandbox(11, [])
    library = _discriminating(tmp_path)

    dispatch_semantic(_signature(), library)
    dispatch_preconditions(_signature(), library, box)
