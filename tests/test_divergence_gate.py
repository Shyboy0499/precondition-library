"""Study 5 (`bench.divergence_gate`, divergence-gate §4-§9): divergence, the figures and the rules,
by hand and on a history built here with known answers."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from precondition_library.bench import divergence_gate as dg
from precondition_library.bench import ecosystem_unify as eu
from precondition_library.bench import lock_oracle as lo
from precondition_library.bench import preregistration
from precondition_library.bench import real_merges as rm


def _set(*pairs: str) -> set[tuple[str, str]]:
    return {tuple(p.split("@")) for p in pairs}  # type: ignore[misc]


def test_a_package_diverges_only_when_both_sides_change_it_differently() -> None:
    base = _set("a@1", "b@1", "c@1", "d@1")
    local = _set("a@2", "b@2", "c@1", "d@1", "e@1")
    upstream = _set("a@3", "b@2", "c@2", "e@2")
    # a: both changed, differently -> diverges; b: both changed, the same way -> convergent;
    # c: only upstream; d: only upstream removed it; e: both added, different versions -> diverges.
    assert dg.divergent(base, local, upstream) == 2
    assert dg.divergent(base, base, base) == 0
    assert dg.divergent(base, local, local) == 0


def test_npm_copies_count_as_one_package_with_a_set_of_versions() -> None:
    base = _set("ms@2.0.0")
    local = _set("ms@2.0.0", "ms@2.1.3")
    upstream = _set("ms@2.1.3", "ms@2.0.0")
    assert dg.divergent(base, local, upstream) == 0, "the same copies on both sides"
    assert dg.divergent(base, local, _set("ms@2.1.2")) == 1


def _gate(repo: str, *, diverges: bool, right: bool, one_version: bool = True) -> dg.GateCase:
    path = "composer.lock" if one_version else "package-lock.json"
    return dg.GateCase(
        index=0,
        repo=repo,
        files=[
            dg.GateFile(
                path=path,
                family=eu.family(path),
                divergent=int(diverges),
                predicted_reproduces=right,
            )
        ],
        diverges=diverges,
        predicted_reproduces=right,
        one_version=one_version,
    )


def test_each_repository_gives_m_always_and_m_gate_where_the_gate_fires() -> None:
    rows = [
        _gate("r1", diverges=False, right=True),
        _gate("r1", diverges=False, right=False),
        _gate("r1", diverges=True, right=False),
        _gate("r1", diverges=True, right=False),
        _gate("r2", diverges=True, right=True),  # the gate never fires in r2
    ]
    assert dg.mismatches(rows) == {"r1": (0.75, 0.5)}


def test_the_mantel_haenszel_difference_by_hand() -> None:
    r1 = [_gate("r1", diverges=False, right=True)] * 3 + [_gate("r1", diverges=True, right=False)]
    r2 = [_gate("r2", diverges=False, right=True), _gate("r2", diverges=False, right=False)] + [
        _gate("r2", diverges=True, right=True)
    ] * 2
    npm_only = [_gate("r3", diverges=False, right=True, one_version=False)]
    # r1: 3 calm, 1 split, difference 1 - 0 = 1, weight 3/4; r2: 2 and 2, 0.5 - 1, weight 1.
    expected = (0.75 * 1.0 + 1.0 * -0.5) / 1.75
    assert dg.mantel_haenszel([r1, r2, npm_only]) == pytest.approx(expected)
    assert dg.mantel_haenszel([npm_only]) is None


def test_the_bootstrap_is_fixed_by_its_seed_and_contains_its_estimate() -> None:
    rows = []
    for i in range(8):
        rows += [_gate(f"r{i}", diverges=False, right=True)] * 3
        rows += [_gate(f"r{i}", diverges=True, right=i % 3 == 0)] * 2
    first, second = dg.bootstrap(rows, resamples=300), dg.bootstrap(rows, resamples=300)
    assert first == second
    assert first is not None and first.interval is not None
    assert first.interval.low <= first.statistic <= first.interval.high


def _labels(rows: list[dg.GateCase]) -> list[lo.CaseLabel]:
    from precondition_library.bench.lock_actions import COMPUTED

    return [
        lo.CaseLabel(
            index=i,
            repo=row.repo,
            merge="m",
            only_locks_conflicted=True,
            files=[],
            reproduces=dict.fromkeys(COMPUTED, row.predicted_reproduces),
            jaccard=dict.fromkeys(COMPUTED, 1.0),
            covered=row.predicted_reproduces,
        )
        for i, row in enumerate(rows)
    ]


def test_the_rules() -> None:
    def world(m_gate_wrong: int) -> list[dg.GateCase]:
        rows = []
        for i in range(16):
            rows += [_gate(f"r{i}", diverges=False, right=k >= m_gate_wrong) for k in range(10)]
            rows += [_gate(f"r{i}", diverges=True, right=False)] * 5
        return rows

    bad = world(3)  # the gate is wrong on 3 of 10 everywhere: m_gate 0.3, gain 0.2
    found = dg.report(bad, _labels(bad), [])
    assert found.h1.outcome == "supported" and found.h2.outcome == "supported"
    good = world(0)  # the gate never misses: rarely wrong, and H1 is contradicted
    found = dg.report(good, _labels(good), [])
    assert found.h1.outcome == "not supported: the gate makes the merge rarely wrong"
    assert found.h2.outcome == "supported"
    few = dg.report(bad[:30], _labels(bad[:30]), [])
    assert few.underpowered
    assert (
        few.h1.outcome
        == few.h2.outcome
        == few.h3.outcome
        == ("not decided: the study is underpowered")
    )


def test_the_descriptive_figures() -> None:
    rows = [
        _gate("r1", diverges=False, right=True),
        _gate("r1", diverges=True, right=False),
        _gate("r1", diverges=True, right=True, one_version=False),
    ]
    found = dg.report(rows, _labels(rows), [], min_repositories=1)
    assert (found.always.fires, found.always.wrong) == (3, 1)
    assert (found.gate.fires, found.gate.wrong) == (1, 0)
    assert found.gate_fire_share == pytest.approx(1 / 3)
    assert found.files_by_family["one-version"] == {
        "none diverges": [1, 1],
        "some diverges": [1, 0],
    }
    assert found.files_by_family["npm"]["some diverges"] == [1, 1]
    assert "H1" in dg.text(found)


# --- on a real history ------------------------------------------------------------------------


def _git(cwd: Path, *argv: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    return subprocess.run(
        ["git", *argv], cwd=cwd, env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(repo: Path, packages: dict[str, str], message: str) -> str:
    data = {"packages": [{"name": n, "version": v} for n, v in sorted(packages.items())]}
    (repo / "composer.lock").write_text(json.dumps(data, indent=4) + "\n")
    _git(repo, "add", "composer.lock")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_gate_case_reads_the_sides_from_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    base = _commit(repo, {"a/x": "1.0.0", "b/y": "1.0.0"}, "base")
    _git(repo, "checkout", "-q", "-b", "side")
    upstream = _commit(repo, {"a/x": "1.2.0", "b/y": "1.0.0"}, "upstream bumps a/x to 1.2")
    _git(repo, "checkout", "-q", "main")
    local = _commit(repo, {"a/x": "1.1.0", "b/y": "1.1.0"}, "local bumps both")
    # The maintainer keeps the higher a/x and local's b/y: what the unified merge gives.
    merge = _commit(repo, {"a/x": "1.2.0", "b/y": "1.1.0"}, "merge")
    case = rm.Case(
        index=0,
        repo="o/r",
        kind="positive",
        merge=merge,
        first=local,
        second=upstream,
        base=base,
        conflicted=["composer.lock"],
    )
    label = lo.label_case(case, repo)
    assert label is not None
    found = dg.gate_case(case, label, repo)
    assert found.files[0].divergent == 1, "a/x: 1.1 against 1.2"
    assert found.diverges and found.one_version
    assert found.predicted_reproduces, "the unified merge keeps 1.2 and local's b/y"


# --- the registration --------------------------------------------------------------------------


def test_the_study_refuses_without_its_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(preregistration.REGISTRATIONS, dg.REGISTRATION, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError):
        dg.run(tmp_path / "out", repositories=())
    assert not (tmp_path / "out").exists()


def test_the_repository_list_is_the_registered_one() -> None:
    text = preregistration.document(dg.REGISTRATION).read_text(encoding="utf-8")
    section = text.split("### 3.1", 1)[1].split("###", 1)[0]
    listed = re.findall(r"^\| \d+ \| `([^`]+)`", section, re.MULTILINE)
    assert tuple(listed) == dg.REPOSITORIES
    assert len(dg.REPOSITORIES) >= dg.MIN_REPOSITORIES


def test_no_repository_was_studied_or_counted_before() -> None:
    from precondition_library.bench import refusal_set, refusal_study

    seen = {*rm.PILOT, *rm.CONFIRMATORY, *refusal_set.ADMISSION, *refusal_study.EVALUATION}
    seen |= set(lo.REPOSITORIES) | set(eu.REPOSITORIES)
    for name in ("lock-oracle-feasibility.jsonl", "ecosystem-unify-feasibility.jsonl"):
        counted = preregistration.REPOSITORY / "docs/preregistration" / name
        seen |= {json.loads(line)["repo"] for line in counted.read_text().splitlines()}
    assert not {s.lower() for s in seen} & {r.lower() for r in dg.REPOSITORIES}
