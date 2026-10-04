"""An existing checkout as an environment the runtime can probe and replay in (#181, item 2).

The owner chose the trusted pre-fetch: the tool runs one fixed `git fetch` of the
upstream remote with the user's own git, mirrors the result locally, and every
model-authored probe and body then runs as in the harness -- no network, hardened git,
`HOME` in scratch -- with git told to read the remote from the mirror. These tests pin:

* the checkout's parameters are derived from it, and probes and bodies bind them;
* a body's own `git fetch` succeeds from the mirror after the real remote is gone, and
  its `git push` reaches only the mirror;
* a replayed commit carries the user's identity and today's date, not the sandbox's;
* `destroy` removes the scratch root and never the checkout;
* a path that is not a working tree's top level is refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precondition_library.checkout import MIRROR_NAME, NotACheckoutError, open_checkout
from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.runtime.probes import bindings, evaluate_predicates
from precondition_library.runtime.replay import replay
from precondition_library.sandbox import run_git

USER = ("Repo Owner", "owner@example.invalid")


def _git(cwd: Path, *args: str) -> str:
    return run_git(args, cwd=cwd).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def behind(tmp_path) -> tuple[Path, Path, str]:
    """A clone of `origin` (default branch `trunk`) one commit behind it.

    Returns the clone, the origin, and origin's tip. The clone carries the user's
    identity in its own config, as a real repository's owner would have one.
    """
    origin = tmp_path / "origin.git"
    run_git(("-c", "init.defaultBranch=trunk", "init", "-q", "--bare", str(origin)), cwd=tmp_path)
    seed = tmp_path / "seed"
    run_git(("clone", "-q", str(origin), str(seed)), cwd=tmp_path)
    _git(seed, "checkout", "-q", "-b", "trunk")
    _commit(seed, "first")
    _git(seed, "push", "-q", "origin", "trunk")

    work = tmp_path / "work"
    run_git(("clone", "-q", str(origin), str(work)), cwd=tmp_path)
    _git(work, "config", "user.name", USER[0])
    _git(work, "config", "user.email", USER[1])

    tip = _commit(seed, "second")
    _git(seed, "push", "-q", "origin", "trunk")
    return work, origin, tip


def _program(body: str, *, parameters: list[str], preconditions=()) -> Program:
    return Program(
        id="checkout-under-test",
        intent="sync with upstream",
        variant="merge",
        parameters=parameters,
        preconditions=list(preconditions),
        body=body,
        postconditions=[],
        provenance=Provenance(
            compiled_from_task="t",
            model="m",
            compiler_version="v",
            episode_id="e",
            fault="diverged",
        ),
        status=ProgramStatus.ADMITTED,
    )


def test_the_checkout_binds_its_own_values_after_the_trusted_fetch(behind, tmp_path) -> None:
    work, origin, tip = behind
    env = open_checkout(work, scratch=tmp_path)
    try:
        assert env.work == work.resolve()
        assert bindings(env) == {
            "work_dir": str(work.resolve()),
            "upstream_remote": "origin",
            "upstream_branch": "trunk",
        }
        assert _git(work, "rev-parse", "refs/remotes/origin/trunk") == tip, "the pre-fetch ran"
        assert _git(env.upstream, "rev-parse", "refs/heads/trunk") == tip, "and was mirrored"
        assert env.checkout is not None
        assert env.checkout.redirects == ((str(env.root / MIRROR_NAME), str(origin)),)
        assert env.checkout.identity == USER
    finally:
        env.destroy()


def test_without_the_fetch_the_checkout_keeps_what_it_has(behind, tmp_path) -> None:
    work, _, tip = behind
    env = open_checkout(work, fetch=False, scratch=tmp_path)
    try:
        assert _git(work, "rev-parse", "refs/remotes/origin/trunk") != tip
    finally:
        env.destroy()


def test_a_body_fetches_from_the_mirror_with_the_real_remote_gone(behind, tmp_path) -> None:
    """The point of the pre-fetch: model-authored `git fetch` needs no network."""
    work, origin, tip = behind
    env = open_checkout(work, scratch=tmp_path)
    try:
        origin.rename(origin.with_name("moved-away.git"))  # the real remote is unreachable
        body = (
            "git fetch {upstream_remote}\ngit merge --ff-only {upstream_remote}/{upstream_branch}\n"
        )
        result = replay(_program(body, parameters=["upstream_remote", "upstream_branch"]), env)
        assert result.ok, result.reason + result.stderr
        assert _git(work, "rev-parse", "HEAD") == tip
    finally:
        env.destroy()


def test_a_body_push_reaches_only_the_mirror(behind, tmp_path) -> None:
    work, origin, _ = behind
    env = open_checkout(work, scratch=tmp_path)
    try:
        body = "git push {upstream_remote} HEAD:refs/heads/from-replay\n"
        result = replay(_program(body, parameters=["upstream_remote"]), env)
        assert result.ok, result.reason + result.stderr
        assert (
            run_git(
                ("rev-parse", "--verify", "--quiet", "refs/heads/from-replay"),
                cwd=origin,
                check=False,
            ).returncode
            != 0
        ), "nothing reached the real remote"
        assert _git(env.upstream, "rev-parse", "refs/heads/from-replay")
    finally:
        env.destroy()


def test_a_replayed_commit_is_the_users_and_dated_now(behind, tmp_path) -> None:
    work, _, _ = behind
    env = open_checkout(work, scratch=tmp_path)
    try:
        result = replay(_program("git commit -q --allow-empty -m replayed\n", parameters=[]), env)
        assert result.ok, result.reason + result.stderr
        author = _git(work, "log", "-1", "--format=%an|%ae|%cn|%ce|%ad", "--date=format:%Y")
        name, email, committer, committer_email, year = author.split("|")
        assert (name, email) == USER and (committer, committer_email) == USER
        assert int(year) >= 2025, "not the sandbox's pinned date"
    finally:
        env.destroy()


def test_probes_bind_the_checkout_and_a_writing_probe_is_refused_not_undone(
    behind, tmp_path
) -> None:
    """A probe reads the checkout; one that writes is refused -- but its write stays.

    On a harness sandbox that is harmless, because the sandbox is thrown away. On a
    checkout it is the user's repository, so the module states it and a dispatcher must
    probe a copy (#181's dispatch item). Pinned here so the limit cannot go unnoticed.
    """
    work, _, _ = behind
    env = open_checkout(work, scratch=tmp_path)
    try:
        behind_upstream = Predicate(
            name="behind",
            description="the checkout lacks upstream's tip",
            probe="! git merge-base --is-ancestor {upstream_remote}/{upstream_branch} HEAD",
        )
        writes = Predicate(name="writes", description="changes the tree", probe="touch new-file")
        result = evaluate_predicates([behind_upstream, writes], env, kind="pre")
        verdicts = {r.name: r for r in result.predicates}
        assert verdicts["behind"].ok, verdicts["behind"].observed
        assert not verdicts["writes"].ok and verdicts["writes"].refused
        assert (work / "new-file").exists(), "refused after the fact, not prevented or undone"
    finally:
        env.destroy()


def test_destroy_removes_the_scratch_root_and_never_the_checkout(behind, tmp_path) -> None:
    work, _, _ = behind
    env = open_checkout(work, scratch=tmp_path)
    env.destroy()
    assert not env.root.exists()
    assert (work / ".git").is_dir() and (work / "first").is_file()


def test_a_path_that_is_not_a_working_tree_top_level_is_refused(behind, tmp_path) -> None:
    work, _, _ = behind
    (work / "sub").mkdir()
    with pytest.raises(NotACheckoutError):
        open_checkout(work / "sub", scratch=tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(NotACheckoutError):
        open_checkout(plain, scratch=tmp_path)
