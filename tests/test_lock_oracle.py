"""The lock-file oracle study (lock-oracle §3-§9), on a history built here with known answers.

Each merge's sides change `Cargo.lock` package by package, and its maintainer commits a known
resolution:

* `unified`: both sides move `libc` within 0.2, and each adds a crate; the maintainer keeps
  the higher `libc` and both crates, what `three_way_unified` gives and plain `three_way` does
  not;
* `took-local`: the maintainer keeps the local file whole;
* `regenerated`: the maintainer's file holds a version neither side had, so nothing reproduces it;
* `markers`: the maintainer committed the file with its conflict markers, so it is passed over;
* `clean`: both sides change the file without conflict, which is no case for this study.
"""

from __future__ import annotations

import itertools
import math
import os
import statistics
import subprocess
from pathlib import Path

import pytest

from precondition_library.bench import lock_oracle as lo
from precondition_library.bench import preregistration
from precondition_library.bench import real_merges as rm
from precondition_library.bench.report import Interval

_CLOCK = itertools.count(1_700_000_000, 60)

BASE = {"anyhow": "1.0.0", "libc": "0.2.150", "log": "0.4.0"}


def _git(repo: Path, *argv: str, check: bool = True) -> str:
    when = f"{next(_CLOCK)} +0000"
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *argv],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when},
    ).stdout.strip()


def _lock(packages: dict[str, str]) -> str:
    blocks = [
        f'[[package]]\nname = "{name}"\nversion = "{version}"\n'
        for name, version in sorted(packages.items())
    ]
    return "version = 3\n\n" + "\n".join(blocks)


def _commit(repo: Path, message: str, lock: str | None = None) -> str:
    if lock is not None:
        (repo / "Cargo.lock").write_text(lock, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _scenario(repo: Path, name: str, local: str, upstream: str, resolved: str) -> str:
    _git(repo, "checkout", "-q", "main")
    _commit(repo, f"{name}: reset", _lock(BASE))
    _git(repo, "checkout", "-q", "-b", f"{name}-up", "main")
    _commit(repo, f"{name}: upstream", upstream)
    _git(repo, "checkout", "-q", "-b", f"{name}-local", "main")
    _commit(repo, f"{name}: local", local)
    _git(repo, "merge", "-q", f"{name}-up", check=False)
    merge = _commit(repo, f"{name}: merge upstream", resolved)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", f"{name}: fold", f"{name}-local")
    return merge


@pytest.fixture(scope="module")
def history(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    repo = tmp_path_factory.mktemp("oracle") / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    _commit(repo, "base", _lock(BASE))
    local = _lock({**BASE, "libc": "0.2.155", "rand": "0.8.0"})
    upstream = _lock({**BASE, "libc": "0.2.161", "serde": "1.0.0"})
    unified = {**BASE, "libc": "0.2.161", "rand": "0.8.0", "serde": "1.0.0"}
    merges = {
        "unified": _scenario(repo, "unified", local, upstream, _lock(unified)),
        "took-local": _scenario(repo, "took-local", local, upstream, local),
        "regenerated": _scenario(
            repo, "regenerated", local, upstream, _lock({**BASE, "libc": "0.2.170"})
        ),
        "markers": _scenario(
            repo, "markers", local, upstream, "<<<<<<< HEAD\n" + local + ">>>>>>> up\n"
        ),
    }
    # A clean merge: the sides change different packages, far apart in the file.
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "clean: reset", _lock(BASE))
    _git(repo, "checkout", "-q", "-b", "clean-up", "main")
    _commit(repo, "clean: upstream", _lock({**BASE, "log": "0.4.1"}))
    _git(repo, "checkout", "-q", "-b", "clean-local", "main")
    _commit(repo, "clean: local", _lock({**BASE, "anyhow": "1.0.1"}))
    _git(repo, "merge", "-q", "-m", "clean", "clean-up")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "clean: fold", "clean-local")

    cache = repo.parent / "cache.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(cache)], check=True)
    tip = _git(repo, "rev-parse", "main")
    _, mined, _ = rm.mine("example/repo", cache, "main", tip)
    return {"cache": cache, "merges": merges, "mined": mined}


def _labelled(history: dict[str, object], cap: int = lo.PER_REPOSITORY):  # type: ignore[no-untyped-def]
    cache = history["cache"]
    mined = history["mined"]
    assert isinstance(cache, Path) and isinstance(mined, list)
    return lo.label_repository(mined, cache, cap)


def _by_merge(history: dict[str, object]) -> dict[str, lo.CaseLabel]:
    merges = history["merges"]
    assert isinstance(merges, dict)
    labelled, _ = _labelled(history)
    names = {merge: name for name, merge in merges.items()}
    return {names[case.merge]: found for case, found in labelled}


def test_each_merge_is_labelled_by_the_action_that_reproduces_it(
    history: dict[str, object],
) -> None:
    found = _by_merge(history)
    assert set(found) == {"unified", "took-local", "regenerated"}
    assert [a for a, ok in found["unified"].reproduces.items() if ok] == ["three_way_unified"]
    assert found["unified"].jaccard["three_way_unified"] == 1.0
    assert found["unified"].jaccard["three_way"] == pytest.approx(5 / 6)
    assert [a for a, ok in found["took-local"].reproduces.items() if ok] == ["take_local"]
    assert not found["regenerated"].covered
    assert all(row.only_locks_conflicted for row in found.values())
    assert not any(f.line_union for row in found.values() for f in row.files)


def test_an_unreadable_merged_file_is_passed_over_and_recorded(
    history: dict[str, object],
) -> None:
    merges = history["merges"]
    assert isinstance(merges, dict)
    _, excluded = _labelled(history)
    assert [(e.merge, e.reason) for e in excluded] == [
        (merges["markers"], "merged lock file unread")
    ]


def test_the_cap_keeps_the_most_recent_readable_cases(history: dict[str, object]) -> None:
    merges = history["merges"]
    assert isinstance(merges, dict)
    labelled, excluded = _labelled(history, cap=1)
    # The most recent conflicted merge is `markers`, passed over; the next is `regenerated`.
    assert [case.merge for case, _ in labelled] == [merges["regenerated"]]
    assert len(excluded) == 1


def _row(repo: str, covered: str | None, merge: float, local: float, upstream: float):  # type: ignore[no-untyped-def]
    reproduces = {a: a == covered for a in lo.COMPUTED}
    jaccard = {
        "take_local": local,
        "take_upstream": upstream,
        "three_way": merge,
        "three_way_unified": merge,
    }
    return lo.CaseLabel(
        index=0,
        repo=repo,
        merge="m",
        only_locks_conflicted=True,
        files=[lo.FileLabel(path="Cargo.lock", results=[], line_union=False)],
        reproduces=reproduces,
        jaccard=jaccard,
        covered=covered is not None,
    )


def test_the_figures_by_hand() -> None:
    rows = [
        _row("a", "three_way_unified", 1.0, 0.8, 0.9),
        _row("a", None, 0.9, 0.9, 0.5),
        _row("b", "take_local", 0.9, 1.0, 0.6),
        _row("b", None, 0.5, 0.4, 0.4),
    ]
    found = lo.report(rows, [], targets=(4, 2))
    assert found.coverage.statistic == 0.5
    assert found.merge_minus_local.statistic == pytest.approx((0.2 + 0 - 0.1 + 0.1) / 4)
    assert found.merge_minus_upstream.statistic == pytest.approx((0.1 + 0.4 + 0.3 + 0.1) / 4)
    assert found.action_share["three_way_unified"] == 0.25
    assert found.action_share["take_local"] == 0.25
    assert found.per_repository == {"a": 2, "b": 2}
    assert not found.underpowered
    # Two repositories, each with coverage 0.5: no spread between them, so no width.
    assert found.coverage.interval == Interval(low=0.5, high=0.5)
    assert [d.rule for d in found.decisions] == ["1 power", "2 H1", "3 H2"]
    assert found.decisions[1].outcome.startswith("supported")
    assert found.decisions[2].outcome.startswith("not supported"), "merge minus local can be < 0"


def test_an_underpowered_study_reports_and_decides_nothing() -> None:
    rows = [_row("a", "three_way_unified", 1.0, 0.8, 0.9)]
    found = lo.report(rows, [])
    assert found.underpowered
    assert found.underpowered_because == [
        f"1 cases, below {lo.TARGET_CASES}",
        f"1 repositories, below {lo.MIN_REPOSITORIES}",
    ]
    assert [d.rule for d in found.decisions] == ["1 power"]
    assert "1 power: underpowered" in lo.text(found)


def test_h1_needs_the_lower_end_above_the_bound() -> None:
    def estimate(low: float) -> lo.Estimate:
        return lo.Estimate(statistic=0.3, interval=Interval(low=low, high=0.5))

    positive = estimate(0.01)
    assert lo.BOUND == 0.10
    assert lo.decide(estimate(0.11), positive, positive, [])[1].outcome.startswith("supported")
    assert lo.decide(estimate(0.10), positive, positive, [])[1].outcome.startswith("not")
    assert lo.decide(estimate(0.2), positive, estimate(-0.01), [])[2].outcome.startswith("not")


def test_the_interval_is_a_t_interval_over_repository_means() -> None:
    rows = [
        _row("a", "take_local", 1, 1, 1),
        _row("a", None, 1, 1, 1),
        _row("a", None, 1, 1, 1),
        _row("b", "take_local", 1, 1, 1),
        _row("c", None, 1, 1, 1),
    ]
    means = [1 / 3, 1.0, 0.0]
    found = lo.estimate(rows, lo.covered)
    assert found.statistic == pytest.approx(sum(means) / 3), "each repository counts once"
    half = 4.303 * statistics.stdev(means) / math.sqrt(3)
    assert found.interval == Interval(low=found.statistic - half, high=found.statistic + half)
    assert lo.estimate(rows[:3], lo.covered).interval is None, "one repository gives no interval"
    assert lo.report(rows, [], targets=(1, 1)).pooled_coverage == 0.4


def test_the_t_table() -> None:
    stats = pytest.importorskip("scipy.stats")
    for df in range(1, 31):
        assert lo.t_975(df) == pytest.approx(stats.t.ppf(0.975, df), abs=6e-4)
    assert lo.t_975(45) > stats.t.ppf(0.975, 45), "past the table, wider than exact"


def test_the_study_refuses_without_its_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(preregistration.REGISTRATIONS, lo.REGISTRATION, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError):
        lo.run(tmp_path / "out", repositories=())
    assert not (tmp_path / "out").exists()


def test_the_repository_list_is_the_registered_one() -> None:
    text = preregistration.document(lo.REGISTRATION).read_text(encoding="utf-8")
    section = text.split("### 3.1", 1)[1].split("###", 1)[0]
    listed = [line.split("`")[1] for line in section.splitlines() if line.startswith("| `")]
    assert tuple(listed) == lo.REPOSITORIES
    assert len(lo.REPOSITORIES) >= lo.MIN_REPOSITORIES


def test_no_repository_was_studied_before() -> None:
    from precondition_library.bench import refusal_set, refusal_study

    seen = {*rm.PILOT, *rm.CONFIRMATORY, *refusal_set.ADMISSION, *refusal_study.EVALUATION}
    assert not seen & set(lo.REPOSITORIES)
