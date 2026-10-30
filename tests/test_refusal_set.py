"""Study 2's refusal set R (refusal-population §3.3), mined and checked on study 1's fixture.

`test_real_merges`' small history has two inexpressible conflicts: one the maintainer resolved
by taking upstream's file whole, which neither resolution produces, and one that also conflicted
in the README. The other two conflicts are expressible, so R never holds them.
"""

from __future__ import annotations

import gzip
import re
import shutil
from pathlib import Path

import pytest
from test_episode_runner import _discard_program
from test_real_merges import _case, history  # noqa: F401  (the module-scoped fixture)

from precondition_library.bench import preregistration
from precondition_library.bench import refusal_set as rs
from precondition_library.program import Predicate


def test_the_repositories_and_sizes_are_the_registered_ones() -> None:
    text = preregistration.document(rs.REGISTRATION).read_text(encoding="utf-8")
    section = text.split("**Admission (A): the refusal set's source.**", 1)[1]
    section = section.split("**Evaluation (E), in order:**", 1)[0]
    assert list(rs.ADMISSION) == re.findall(r"^\d+\. \[`([^`]+)`\]", section, flags=re.MULTILINE)
    assert "at most 10 per repository" in text and "until there are 40" in text
    assert (rs.PER_REPOSITORY, rs.SIZE) == (10, 40)


def test_the_inexpressible_conflicts_most_recent_first(history: dict[str, object]) -> None:  # noqa: F811
    part = rs.select(
        "example/repo", history["cache"], "main", history["tip"], limit=10, first_index=5
    )  # type: ignore[arg-type]
    merges = history["merges"]
    assert isinstance(merges, dict)
    assert [case.merge for case in part.cases] == [
        merges["also-readme"]["merge"],
        merges["took-upstream"]["merge"],
    ], "the two inexpressible conflicts, the later one first"
    assert [case.index for case in part.cases] == [5, 6]
    assert [lab.acceptable for lab in part.labels] == [[], []]
    assert all(state.sync_would_conflict for state in part.states)
    assert (part.repository.positives, part.repository.negatives) == (2, 0)


def test_a_repository_gives_no_more_than_its_limit(history: dict[str, object]) -> None:  # noqa: F811
    part = rs.select("example/repo", history["cache"], "main", history["tip"], 1, 0)  # type: ignore[arg-type]
    assert [case.merge for case in part.cases] == [_case(history, "also-readme").merge]


@pytest.fixture
def mined(
    history: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """R mined from two listed repositories that are both the fixture, with `SIZE` 3."""
    fetched: list[str] = []

    def fetch(host: object) -> Path:
        fetched.append(str(host))
        copy = tmp_path / f"cache-{len(fetched)}.git"
        shutil.copytree(history["cache"], copy)  # type: ignore[arg-type]
        return copy

    monkeypatch.setattr(rs, "ADMISSION", ("example/one", "example/two"))
    monkeypatch.setattr(rs, "SIZE", 3)
    monkeypatch.setattr(rs, "PER_REPOSITORY", 2)
    monkeypatch.setattr(rs, "pin", lambda repo: ("main", history["tip"]))
    monkeypatch.setattr(rs, "fetch_real_host", fetch)
    out = tmp_path / "R"
    refusals = rs.mine_refusal_set(out)
    return {"out": out, "refusals": refusals, "fetched": fetched}


def test_mining_stops_at_the_size_and_writes_the_frozen_set(mined: dict[str, object]) -> None:
    refusals = mined["refusals"]
    assert isinstance(refusals, rs.RefusalSet)
    assert [(c.repo, c.index) for c in refusals.cases] == [
        ("example/one", 0),
        ("example/one", 1),
        ("example/two", 2),
    ], "two from the first, then only the one still needed from the second"
    out = mined["out"]
    assert isinstance(out, Path)
    loaded, states = rs.load(out)
    assert loaded == refusals
    assert len(states) == 3 and all(state.sync_would_conflict for state in states)
    assert rs.digest(out) == rs.digest(out)


def test_a_frozen_set_is_never_mined_again(mined: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="frozen"):
        rs.mine_refusal_set(mined["out"])  # type: ignore[arg-type]


def test_mining_resumes_from_the_repositories_written(mined: dict[str, object]) -> None:
    out = mined["out"]
    assert isinstance(out, Path)
    before = rs.digest(out)
    (out / rs.MANIFEST).unlink()
    (out / rs.STATES).unlink()
    fetched = mined["fetched"]
    assert isinstance(fetched, list)
    count = len(fetched)
    rs.mine_refusal_set(out)
    assert len(fetched) == count, "nothing fetched again"
    assert rs.digest(out) == before, "the same bytes, so the same digest"


def test_mining_refuses_without_the_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(preregistration.REGISTRATIONS, rs.REGISTRATION, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError, match="differs"):
        rs.mine_refusal_set(tmp_path / "R")
    assert not (tmp_path / "R").exists()


def _with_precondition(probe: str):  # type: ignore[no-untyped-def]
    return _discard_program(
        preconditions=[
            Predicate(name="under_test", description="the probe under test", probe=probe)
        ]
    )


def test_the_gate_names_every_refusal_state_a_program_accepts(mined: dict[str, object]) -> None:
    states = rs.RefusalStates(mined["out"])  # type: ignore[arg-type]
    assert len(states) == 3
    accepted, error = states.accepted_by(_with_precondition("true"))
    assert error is None
    refusals = mined["refusals"]
    assert isinstance(refusals, rs.RefusalSet)
    assert [name for name, _ in accepted] == [
        f"{case.repo}@{case.merge[:12]}" for case in refusals.cases
    ]
    assert [state for _, state in accepted] == states.states
    assert states.accepted_by(_with_precondition("false")) == ([], None)


def test_a_probe_reading_the_conflict_tells_the_states_apart(mined: dict[str, object]) -> None:
    """A real probe on the rebuilt state: each case is a checkout of its first parent, so the
    lock file is there, and upstream is ahead."""
    states = rs.RefusalStates(mined["out"])  # type: ignore[arg-type]
    probe = (
        "test -f Cargo.lock && "
        'test "$(git rev-list --count HEAD..{upstream_remote}/{upstream_branch})" -gt 0'
    )
    accepted, error = states.accepted_by(_with_precondition(probe))
    assert error is None and len(accepted) == 3


def test_a_precondition_that_cannot_run_is_an_error(mined: dict[str, object]) -> None:
    states = rs.RefusalStates(mined["out"])  # type: ignore[arg-type]
    accepted, error = states.accepted_by(_with_precondition("test -n '{no_such_parameter}'"))
    assert accepted == [] and error is not None and "no_such_parameter" in error


def test_a_state_that_no_longer_rebuilds_stops_the_build(mined: dict[str, object]) -> None:
    out = mined["out"]
    assert isinstance(out, Path)
    lines = gzip.decompress((out / rs.STATES).read_bytes()).decode("utf-8").splitlines()
    first = rs.ObservedRefusal.model_validate_json(lines[0])
    changed = first.state.model_copy(update={"upstream_ahead": first.state.upstream_ahead + 1})
    lines[0] = first.model_copy(update={"state": changed}).model_dump_json()
    (out / rs.STATES).write_bytes(gzip.compress(("\n".join(lines) + "\n").encode("utf-8")))
    with pytest.raises(RuntimeError, match="no longer rebuilds as it was frozen"):
        rs.RefusalStates(out).accepted_by(_with_precondition("false"))
