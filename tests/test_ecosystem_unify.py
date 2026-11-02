"""Study 4 (`bench.ecosystem_unify`, ecosystem-unify §4-§9): its votes and rules by hand."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from precondition_library.bench import ecosystem_unify as eu
from precondition_library.bench import lock_oracle as lo
from precondition_library.bench import preregistration
from precondition_library.bench import real_merges as rm
from precondition_library.bench.lock_actions import COMPUTED, ActionResult


def _file(path: str, *, plain: bool, unified: bool) -> lo.FileLabel:
    done = {"take_local": False, "take_upstream": False, "three_way": plain}
    done["three_way_unified"] = unified
    return lo.FileLabel(
        path=path,
        results=[
            ActionResult(action=a, reproduces=done[a], reproduces_but_new=done[a], jaccard=1.0)
            for a in COMPUTED
        ],
        line_union=False,
    )


def _case(repo: str, *files: lo.FileLabel) -> lo.CaseLabel:
    reproduces = {
        a: all(next(r.reproduces for r in f.results if r.action == a) for f in files)
        for a in COMPUTED
    }
    return lo.CaseLabel(
        index=0,
        repo=repo,
        merge="m",
        only_locks_conflicted=True,
        files=list(files),
        reproduces=reproduces,
        jaccard=dict.fromkeys(COMPUTED, 1.0),
        covered=any(reproduces.values()),
    )


def test_every_counted_lock_file_is_in_exactly_one_family() -> None:
    assert set(eu.NPM_FAMILY) | set(eu.ONE_VERSION) == set(rm.LOCK_FILES)
    assert not set(eu.NPM_FAMILY) & set(eu.ONE_VERSION)
    assert eu.predicted("web/yarn.lock") == "three_way"
    assert eu.predicted("composer.lock") == "three_way_unified"
    with pytest.raises(ValueError):
        eu.family("requirements.txt")


def test_only_files_where_the_two_merges_disagree_count() -> None:
    row = _case(
        "a",
        _file("composer.lock", plain=False, unified=True),  # predicted (unified) wins
        _file("package-lock.json", plain=False, unified=True),  # predicted (plain) loses
        _file("Gemfile.lock", plain=True, unified=True),  # agree: not discordant
    )
    assert eu.discordant(row) == [("one-version", 1), ("npm", -1)]


def test_each_repository_votes_once_and_a_tie_casts_none() -> None:
    rows = [
        _case("a", _file("composer.lock", plain=False, unified=True)),
        _case("a", _file("composer.lock", plain=False, unified=True)),
        _case("a", _file("yarn.lock", plain=False, unified=True)),
        _case("b", _file("yarn.lock", plain=True, unified=False)),
        _case("c", _file("Cargo.lock", plain=True, unified=False)),
        _case("d", _file("poetry.lock", plain=False, unified=True)),
        _case("d", _file("pnpm-lock.yaml", plain=False, unified=True)),
    ]
    assert eu.votes(rows, ("one-version", "npm")) == {"a": 1, "b": 1, "c": -1}
    assert eu.votes(rows, ("one-version",)) == {"a": 1, "c": -1, "d": 1}
    assert eu.votes(rows, ("npm",)) == {"a": -1, "b": 1, "d": -1}


def test_the_sign_test() -> None:
    assert eu.sign_p(6, 0) == pytest.approx(2 / 64)
    assert eu.sign_p(5, 0) == pytest.approx(2 / 32)
    assert eu.sign_p(7, 1) == pytest.approx(2 * 9 / 256)
    assert eu.sign_p(0, 0) == 1.0
    assert eu.sign_p(3, 3) == 1.0


def _wins(n: int, *, against: int = 0) -> list[lo.CaseLabel]:
    rows = [_case(f"r{i}", _file("composer.lock", plain=False, unified=True)) for i in range(n)]
    rows += [
        _case(f"x{i}", _file("composer.lock", plain=True, unified=False)) for i in range(against)
    ]
    return rows


def test_the_rules() -> None:
    six = eu.report(_wins(6), [], min_repositories=1)
    assert six.tests["H1"].outcome == "supported" and six.tests["H2"].outcome == "supported"
    assert six.tests["H3"].outcome == "not decided: 0 votes, fewer than 6"
    assert (
        eu.report(_wins(5), [], min_repositories=1)
        .tests["H1"]
        .outcome.startswith("not decided: 5 votes")
    )
    assert eu.report(_wins(6, against=2), [], min_repositories=1).tests["H1"].outcome == (
        "not supported"
    )
    against = eu.report(_wins(0, against=8), [], min_repositories=1)
    assert against.tests["H1"].outcome == "not supported", "a significant loss supports nothing"
    small = eu.report(_wins(6), [])
    assert small.underpowered and all(
        t.outcome == "not decided: the study is underpowered" for t in small.tests.values()
    )
    assert small.h4 == "not decided: the study is underpowered"


def test_the_descriptive_counts() -> None:
    found = eu.report(_wins(6, against=2), [], min_repositories=1)
    h1 = found.tests["H1"]
    assert (h1.files_won, h1.files_lost, h1.votes_for, h1.votes_against, h1.ties) == (6, 2, 6, 2, 0)
    assert found.ecosystem_share == 6 / 8
    assert found.coverage.statistic == pytest.approx(1.0), "every case is reproduced by something"
    assert "H1" in eu.text(found)


def test_the_study_refuses_without_its_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(preregistration.REGISTRATIONS, eu.REGISTRATION, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError):
        eu.run(tmp_path / "out", repositories=())
    assert not (tmp_path / "out").exists()


def test_the_repository_list_is_the_registered_one() -> None:
    text = preregistration.document(eu.REGISTRATION).read_text(encoding="utf-8")
    section = text.split("### 3.1", 1)[1].split("###", 1)[0]
    listed = re.findall(r"^\| \d+ \| `([^`]+)`", section, re.MULTILINE)
    assert tuple(listed) == eu.REPOSITORIES
    assert len(eu.REPOSITORIES) >= eu.MIN_REPOSITORIES


def test_no_repository_was_studied_or_counted_before() -> None:
    from precondition_library.bench import lock_oracle, refusal_set, refusal_study

    seen = {*rm.PILOT, *rm.CONFIRMATORY, *refusal_set.ADMISSION, *refusal_study.EVALUATION}
    seen |= set(lock_oracle.REPOSITORIES)
    counted = preregistration.REPOSITORY / "docs/preregistration/lock-oracle-feasibility.jsonl"
    seen |= {json.loads(line)["repo"] for line in counted.read_text().splitlines()}
    assert not seen & set(eu.REPOSITORIES)
