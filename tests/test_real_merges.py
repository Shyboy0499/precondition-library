"""Mining, labelling and building real lock-file merges (#296), on a repository built here.

The fixture is a small history whose merges have known answers, so each step of
`bench.real_merges` can be checked without the network:

* a lock-file conflict the maintainer resolved by taking upstream's file;
* one resolved as `take_upstream` produces -- upstream's lines plus the local additions -- where
  the local side removed a line, so `keep_local` produces something else;
* one resolved as `keep_local` produces;
* one whose conflict also includes a file that is not a lock file;
* a clean merge where both sides changed the lock file, the negative; and
* a merge that conflicts only in the README, which is no case at all.
"""

from __future__ import annotations

import itertools
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from precondition_library.bench import preregistration
from precondition_library.bench import real_merges as rm
from precondition_library.sandbox import git_out, run_git

BASE = ["[[package]]", 'name = "alpha"', 'name = "beta"', 'version = "1"', "", "# end"]


_CLOCK = itertools.count(1_700_000_000, 60)
"""Each git call a minute after the last, so "most recent" is never a tie between commits."""


def _git(repo: Path, *argv: str) -> str:
    when = f"{next(_CLOCK)} +0000"
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *argv],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when},
    ).stdout.strip()


def _write(repo: Path, lines: list[str], name: str = "Cargo.lock") -> None:
    (repo / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _side(version: str, added: str, *, drop_beta: bool = False) -> list[str]:
    lines = [line for line in BASE if not (drop_beta and line == 'name = "beta"')]
    return [added if line == "[[package]]" else line for line in lines[:1]] + [
        "[[package]]",
        *[f'version = "{version}"' if line.startswith("version") else line for line in lines[1:]],
    ]


def _scenario(
    repo: Path,
    name: str,
    local: list[str],
    upstream: list[str],
    resolved: list[str] | None,
    *,
    readme: tuple[str, str] | None = None,
) -> dict[str, str]:
    """Branch both sides from main, merge upstream into local as `resolved`, then fold into main."""
    _reset(repo, name)
    _git(repo, "checkout", "-q", "-b", f"{name}-up", "main")
    _write(repo, upstream)
    if readme:
        _write(repo, [readme[1]], "README")
    second = _commit(repo, f"{name}: upstream")
    _git(repo, "checkout", "-q", "-b", f"{name}-local", "main")
    _write(repo, local)
    if readme:
        _write(repo, [readme[0]], "README")
    first = _commit(repo, f"{name}: local")
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "merge", "-q", f"{name}-up"],
        cwd=repo,
        capture_output=True,
    )
    if resolved is not None:
        _write(repo, resolved)
    if readme:
        _write(repo, ["resolved"], "README")
    merge = _commit(repo, f"{name}: merge upstream")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", f"{name}: fold", f"{name}-local")
    return {"merge": merge, "first": first, "second": second}


def _reset(repo: Path, name: str) -> None:
    """Put main's files back to the base, so each scenario's sides diverge from the same file."""
    _git(repo, "checkout", "-q", "main")
    _write(repo, BASE)
    _write(repo, ["readme"], "README")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"{name}: reset")


def _multiset(lines: list[str]) -> Counter[str]:
    return Counter(lines)


@pytest.fixture(scope="module")
def history(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    repo = tmp_path_factory.mktemp("history") / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, BASE)
    _write(repo, ["readme"], "README")
    (repo / "LICENSE").write_text("MIT License\n\nCopyright\n", encoding="utf-8")
    _commit(repo, "base")

    local = _side("2", 'name = "xi"', drop_beta=True)
    upstream = _side("3", 'name = "ypsilon"')
    b, lo, up = _multiset(BASE), _multiset(local), _multiset(upstream)
    take_upstream = list((up + (lo - b)).elements())
    keep_local = list((lo + (up - b)).elements())
    assert Counter(take_upstream) != Counter(keep_local), "the local removal separates the two"

    merges = {
        "took-upstream": _scenario(repo, "took-upstream", local, upstream, upstream),
        "take-upstream": _scenario(repo, "take-upstream", local, upstream, take_upstream),
        "keep-local": _scenario(repo, "keep-local", local, upstream, keep_local),
        "also-readme": _scenario(
            repo, "also-readme", local, upstream, take_upstream, readme=("left", "right")
        ),
    }
    # A clean negative: the sides change the lock file far apart, so the merge auto-resolves.
    _reset(repo, "clean")
    _git(repo, "checkout", "-q", "-b", "clean-up", "main")
    _write(repo, [*BASE[:-1], "# upstream end"])
    _commit(repo, "clean: upstream")
    _git(repo, "checkout", "-q", "-b", "clean-local", "main")
    _write(repo, ["# local start", *BASE])
    _commit(repo, "clean: local")
    _git(repo, "merge", "-q", "-m", "clean: merge upstream", "clean-up")
    merges["clean"] = {"merge": _git(repo, "rev-parse", "HEAD")}
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "clean: fold", "clean-local")
    # A second clean merge, whose maintainer changed the lock file in the merge commit itself:
    # the tree is not the one the clean merge writes.
    _reset(repo, "evil")
    _git(repo, "checkout", "-q", "-b", "evil-up", "main")
    _write(repo, [*BASE[:-1], "# upstream end"])
    _commit(repo, "evil: upstream")
    _git(repo, "checkout", "-q", "-b", "evil-local", "main")
    _write(repo, ["# local start", *BASE])
    _commit(repo, "evil: local")
    _git(repo, "merge", "-q", "--no-commit", "evil-up")
    _write(repo, ["# local start", *BASE[:-1], "# upstream end", "# and the maintainer's own"])
    merges["evil"] = {"merge": _commit(repo, "evil: merge upstream, and edit")}
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "evil: fold", "evil-local")
    # No case: the conflict is only in the README.
    merges["readme-only"] = _scenario(repo, "readme-only", BASE, BASE, None, readme=("one", "two"))

    cache = repo.parent / "cache.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(cache)], check=True)
    tip = _git(repo, "rev-parse", "main")
    summary, cases, excluded = rm.mine("example/repo", cache, "main", tip)
    return {
        "cache": cache,
        "tip": tip,
        "merges": merges,
        "summary": summary,
        "cases": cases,
        "excluded": excluded,
    }


def _case(history: dict[str, object], name: str) -> rm.Case:
    merges = history["merges"]
    assert isinstance(merges, dict)
    cases = history["cases"]
    assert isinstance(cases, list)
    return next(case for case in cases if case.merge == merges[name]["merge"])


def test_mining_finds_the_positives_and_the_negative(history: dict[str, object]) -> None:
    cases = history["cases"]
    assert isinstance(cases, list)
    kinds = Counter(case.kind for case in cases)
    assert kinds == {"positive": 4, "negative": 2}
    merges = history["merges"]
    assert isinstance(merges, dict)
    found = {case.merge for case in cases}
    assert merges["readme-only"]["merge"] not in found, "a README-only conflict is no case"
    positive = _case(history, "take-upstream")
    assert (positive.first, positive.second) == (
        merges["take-upstream"]["first"],
        merges["take-upstream"]["second"],
    )
    assert positive.conflicted == ["Cargo.lock"]
    assert _case(history, "also-readme").conflicted == ["Cargo.lock", "README"]
    assert _case(history, "clean").kind == "negative"
    assert history["excluded"] == []


def test_the_repository_summary(history: dict[str, object]) -> None:
    summary = history["summary"]
    assert isinstance(summary, rm.Repository)
    assert (summary.positives, summary.negatives, summary.exclusions) == (4, 2, 0)
    assert summary.tip == history["tip"]
    assert summary.licence == "LICENSE: MIT"


def test_a_licence_directory_is_read_one_level_down(tmp_path: Path) -> None:
    """nextcloud/server keeps REUSE's `LICENSES/`, a tree; reading it as a blob stopped stage B."""
    repo = tmp_path / "repo"
    (repo / "LICENSES" / "nested").mkdir(parents=True)
    (repo / "LICENSES" / "AGPL-3.0-or-later.txt").write_text(
        "GNU AFFERO GENERAL PUBLIC LICENSE\n", encoding="utf-8"
    )
    (repo / "LICENSES" / "MIT.txt").write_text("MIT License\n", encoding="utf-8")
    (repo / "LICENSES" / "nested" / "deeper.txt").write_text("BSD\n", encoding="utf-8")
    (repo / "COPYING").write_text("Apache License\n", encoding="utf-8")
    (repo / "README").write_text("not a licence\n", encoding="utf-8")
    run_git(("init", "-q"), cwd=repo)
    run_git(("add", "-A"), cwd=repo)
    run_git(("commit", "-q", "-m", "licences"), cwd=repo)
    tip = git_out("rev-parse", "HEAD", cwd=repo)

    assert rm.licence(repo, tip) == (
        "COPYING: Apache; LICENSES/AGPL-3.0-or-later.txt: AGPL; LICENSES/MIT.txt: MIT"
    )


@pytest.mark.parametrize(
    ("name", "acceptable", "descriptive"),
    [
        ("took-upstream", [], "took upstream"),
        ("take-upstream", ["take_upstream"], "matches take_upstream"),
        ("keep-local", ["keep_local"], "matches keep_local"),
        ("also-readme", [], "matches take_upstream"),
    ],
)
def test_the_maintainers_label(
    history: dict[str, object], name: str, acceptable: list[str], descriptive: str
) -> None:
    cache = history["cache"]
    assert isinstance(cache, Path)
    got = rm.label(_case(history, name), cache)
    assert got.acceptable == acceptable
    assert got.descriptive == descriptive


def test_a_clean_case_accepts_nothing_under_the_original_text(history: dict[str, object]) -> None:
    cache = history["cache"]
    assert isinstance(cache, Path)
    got = rm.label(_case(history, "clean"), cache, amendment=0)
    assert (got.acceptable, got.descriptive) == ([], None)


@pytest.mark.parametrize(
    ("name", "acceptable", "descriptive"),
    [("clean", ["merge"], "clean merge reproduced"), ("evil", [], "clean merge changed")],
)
def test_amendment_1_labels_a_clean_case_by_the_maintainers_tree(
    history: dict[str, object], name: str, acceptable: list[str], descriptive: str
) -> None:
    cache = history["cache"]
    assert isinstance(cache, Path)
    got = rm.label(_case(history, name), cache, amendment=1)
    assert (got.acceptable, got.descriptive) == (acceptable, descriptive)


def test_amendment_1_does_not_relabel_a_conflicted_case(history: dict[str, object]) -> None:
    cache = history["cache"]
    assert isinstance(cache, Path)
    for name in ("took-upstream", "take-upstream", "keep-local", "also-readme"):
        case = _case(history, name)
        assert rm.label(case, cache, amendment=1) == rm.label(case, cache, amendment=0)


def test_a_capped_repository_keeps_its_most_recent_cases_in_equal_number(
    history: dict[str, object],
) -> None:
    cache = history["cache"]
    cases = history["cases"]
    assert isinstance(cache, Path) and isinstance(cases, list)
    kept = rm._capped(cases, cache, 4)
    assert Counter(case.kind for case in kept) == {"positive": 2, "negative": 2}
    merges = history["merges"]
    assert isinstance(merges, dict)
    # The two most recent conflicted scenarios, and both clean ones.
    assert {case.merge for case in kept if case.kind == "positive"} == {
        merges["keep-local"]["merge"],
        merges["also-readme"]["merge"],
    }
    assert rm._capped(cases, cache, 99) == cases


def test_a_regenerated_file_is_told_apart() -> None:
    base, local, upstream = Counter(["a", "v1"]), Counter(["a", "v2"]), Counter(["a", "v3"])
    assert rm.produced("take_upstream", base, local, upstream) == Counter(["a", "v3", "v2"])
    assert rm.produced("keep_local", base, local, upstream) == Counter(["a", "v2", "v3"])
    with pytest.raises(ValueError, match="no such resolution"):
        rm.produced("merge", base, local, upstream)


def test_the_built_state_is_the_first_parent_tracking_the_second(
    history: dict[str, object],
) -> None:
    cache = history["cache"]
    assert isinstance(cache, Path)
    case = _case(history, "take-upstream")
    box = rm.build_state(case, cache, "main")
    try:
        assert _git(box.work, "rev-parse", "HEAD") == case.first
        assert _git(box.work, "rev-parse", "upstream/main") == case.second
        assert _git(box.work, "rev-parse", "--abbrev-ref", "HEAD") == "main"
        assert _git(box.work, "rev-parse", "--abbrev-ref", "@{upstream}") == "upstream/main"
        assert not (box.upstream / "objects" / "pack").exists() or not any(
            (box.upstream / "objects" / "pack").iterdir()
        ), "upstream borrows the cache's objects instead of copying them"
        assert (box.work / ".git" / "objects" / "info" / "alternates").is_file(), (
            "the checkout borrows them too"
        )
        state = rm.StateFingerprint.observe(box)
        assert state.sync_would_conflict
        assert state.merge_conflicted_files == ["Cargo.lock"]
        assert state.local_dropped_lines == ['name = "beta"']
        # The lock-shaped intent refuses a conflicted Cargo.lock (#306): its line unions never
        # resolved a real one, and the real-format family decides it package by package.
        assert rm.INTENT.correct_variant(state) is None
    finally:
        box.destroy()
    assert not box.root.exists()


def test_merge_tree_reads_a_clean_merge(history: dict[str, object]) -> None:
    cache = history["cache"]
    assert isinstance(cache, Path)
    clean = _case(history, "clean")
    tree = rm.merge_tree(cache, clean.first, clean.second)
    assert (tree.clean, tree.conflicted, tree.submodule_or_binary) == (True, [], False)


def test_mining_refuses_without_the_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(preregistration.REGISTRATIONS, rm.REGISTRATION, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError, match="differs"):
        rm.mine_stage("A", rm.PILOT)
    with pytest.raises(preregistration.UnregisteredError, match="differs"):
        rm.run_pilot(Path("never-written"))
    assert not Path("never-written").exists()


def _registered_list(heading: str) -> list[str]:
    text = preregistration.document(rm.REGISTRATION).read_text(encoding="utf-8")
    section = text.split(heading, 1)[1].split("\n\n**", 1)[0].split("\n\nThe first", 1)[0]
    return re.findall(r"^\d+\. \[`([^`]+)`\]", section, flags=re.MULTILINE)


def test_the_repositories_are_the_registered_ones_in_order() -> None:
    assert list(rm.PILOT) == _registered_list("**Pilot (stage A):**")
    text = preregistration.document(rm.REGISTRATION).read_text(encoding="utf-8")
    amended = text.split("**A5.", 1)[1].split("**A6.", 1)[0]
    appended = re.findall(r"^\d+\. \[`([^`]+)`\]", amended, flags=re.MULTILINE)
    assert len(appended) == 8
    assert list(rm.CONFIRMATORY) == [
        *_registered_list("**Confirmatory (stage B), in order:**"),
        *appended,
    ]


def test_the_lock_files_are_the_registered_ones() -> None:
    text = preregistration.document(rm.REGISTRATION).read_text(encoding="utf-8")
    sentence = text.split("A **lock file** is a path whose final component is one of", 1)[1]
    sentence = sentence.split(".\n", 1)[0] if "`.\n" not in sentence else sentence
    named = re.findall(r"`([^`]+)`", sentence.split("\n\n", 1)[0])
    assert tuple(named) == rm.LOCK_FILES


def test_the_libraries_are_committed() -> None:
    for path in rm.LIBRARIES:
        assert (preregistration.REPOSITORY / path / "build.json").is_file(), path
