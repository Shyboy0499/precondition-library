"""A sandbox can start from a pinned real repository's history (ADR-0043).

The real-host stage changes one thing about a state: the history it starts from. These tests
pin, offline, with a local repository standing in for a public host:

* inside `real_host_bases`, a sandbox's upstream and clone start from the host's pinned commit
  and the commits before it, with the generator's base committed on top; outside it, or for a
  seed the resolver maps to None, nothing moves;
* the host is fetched once into the cache, and a commit the host does not have is refused;
* nothing in the clone names the host -- only the harness's own record does;
* every fault the stage measures builds over a host whose `.gitignore` ignores `vendor`, with
  its label kept (the label check runs inside `build_sandbox`);
* the registered pins and the seed-to-host mapping are what ADR-0043 says, and the committed
  results are the blocks on disk.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from precondition_library import sandbox as sandbox_module
from precondition_library.bench.heldout import HELD_OUT_FAULTS, HeldOutSummary
from precondition_library.bench.realhost import (
    REAL_HOST_SEEDS,
    REAL_HOSTS,
    host_for_seed,
    read_blocks,
    seeds_for_host,
    slug,
)
from precondition_library.bench.splits import EVAL_SEEDS
from precondition_library.sandbox import RealHost, fetch_real_host, git_out, real_host_bases
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.spec import HELD_OUT_SEED_BASE

_HOST_FILES = {
    ".gitignore": "vendor\nnode_modules/\n",
    "README.md": "# a real project\n",
    "src/core.py": "def core():\n    return 1\n",
    "docs/guide with space.md": "a path git quotes\n",
}


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2025-06-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2025-06-01T00:00:00+00:00",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    return subprocess.run(
        ["git", "-c", "user.name=host", "-c", "user.email=host@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


@pytest.fixture
def local_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RealHost:
    """A three-commit repository served over `file://`, and a cache of its own."""
    monkeypatch.setattr(sandbox_module, "_REAL_HOSTS", tmp_path / "cache")
    repo = tmp_path / "host"
    repo.mkdir()
    _git(repo, "-c", "init.defaultBranch=trunk", "init", "-q")
    for index, (relative, content) in enumerate(_HOST_FILES.items()):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(repo, "add", "-A")
        if index:
            _git(repo, "commit", "-q", "-m", f"host commit {index}")
    commit = _git(repo, "rev-parse", "HEAD")
    return RealHost("example/host", repo.as_uri(), commit)


def test_a_sandbox_starts_from_the_pinned_history(local_host: RealHost) -> None:
    with real_host_bases(lambda seed: local_host):
        box = sandbox_module.create(0, [])
    try:
        assert git_out("rev-parse", "HEAD^", cwd=box.work) == local_host.commit
        assert git_out("rev-parse", "main", cwd=box.upstream) == git_out(
            "rev-parse", "HEAD", cwd=box.work
        )
        assert git_out("rev-list", "--count", "HEAD", cwd=box.work) == "4"
        for relative in [*_HOST_FILES, "app.py", "docs/readme.md"]:
            assert (box.work / relative).is_file(), relative
        assert box.recorded["real-host"] == f"example/host@{local_host.commit}"
    finally:
        box.destroy()


def test_nothing_in_the_clone_names_the_host(local_host: RealHost) -> None:
    with real_host_bases(lambda seed: local_host):
        box = sandbox_module.create(0, [])
    try:
        assert git_out("remote", cwd=box.work) == "upstream"
        refs = git_out("for-each-ref", "--format=%(refname)", cwd=box.work)
        assert "host" not in refs and "FETCH_HEAD" not in os.listdir(box.upstream)
        assert local_host.url not in (box.work / ".git" / "config").read_text(encoding="utf-8")
    finally:
        box.destroy()


@pytest.mark.parametrize("fault", ["diverged", "dirty_tree"])
def test_outside_the_block_or_for_an_unmapped_seed_nothing_moves(fault: str) -> None:
    def head(box) -> str:
        try:
            return git_out("rev-parse", "HEAD", cwd=box.work)
        finally:
            box.destroy()

    plain = head(build_sandbox(0, [fault]))
    with real_host_bases(lambda seed: None):
        assert head(build_sandbox(0, [fault])) == plain


def test_the_host_is_fetched_once(local_host: RealHost, tmp_path: Path) -> None:
    cache = fetch_real_host(local_host)
    (tmp_path / "host").rename(tmp_path / "moved")
    assert fetch_real_host(local_host) == cache, "a second fetch would need the host"
    with real_host_bases(lambda seed: local_host):
        box = sandbox_module.create(0, [])
    box.destroy()


def test_a_commit_the_host_does_not_have_is_refused(local_host: RealHost) -> None:
    missing = RealHost(local_host.name, local_host.url, "0" * 40)
    with pytest.raises(subprocess.CalledProcessError):
        fetch_real_host(missing)


@pytest.mark.parametrize("fault", HELD_OUT_FAULTS)
@pytest.mark.parametrize("seed", [2000, 2001, 2002, 2003])
def test_every_fault_keeps_its_label_over_a_host_that_ignores_vendor(
    local_host: RealHost, fault: str, seed: int
) -> None:
    """`build_sandbox` refuses a mislabelled build, so building is the check."""
    with real_host_bases(lambda s: local_host):
        box = build_sandbox(seed, [fault])
    try:
        assert git_out("merge-base", "--is-ancestor", local_host.commit, "HEAD", cwd=box.work) == ""
        assert box.injected_state is not None
    finally:
        box.destroy()


def test_the_pins_are_exact_commits_on_public_hosts() -> None:
    assert len({host.name for host in REAL_HOSTS}) == len(REAL_HOSTS) == 4
    for host in REAL_HOSTS:
        assert re.fullmatch(r"[0-9a-f]{40}", host.commit), host
        assert host.url == f"https://github.com/{host.name}"
        assert host.depth == 50


def test_the_seeds_are_the_eval_block_split_evenly_with_no_held_out_axis() -> None:
    """Paired with Figure 1's states, and below the base, so no held-out value is drawn."""
    assert REAL_HOST_SEEDS == EVAL_SEEDS
    assert max(REAL_HOST_SEEDS) < HELD_OUT_SEED_BASE
    assert sorted(s for host in REAL_HOSTS for s in seeds_for_host(host)) == list(EVAL_SEEDS)
    assert {len(seeds_for_host(host)) for host in REAL_HOSTS} == {10}
    assert host_for_seed(2000) is REAL_HOSTS[0] and host_for_seed(2003) is REAL_HOSTS[3]


REAL_HOST_RESULTS = Path(__file__).resolve().parents[1] / "results" / "realhost-2026-10-20"


@pytest.mark.parametrize("run", ["run-11", "run-12", "run-13"])
def test_the_committed_counts_are_the_blocks_on_disk(run: str) -> None:
    """`realhost.json` is read back from the per-block summaries, every block measured the
    pins registered here, and no block moved the library it measured."""
    out = REAL_HOST_RESULTS / run
    recorded = json.loads((out / "realhost.json").read_text(encoding="utf-8"))
    assert recorded["blocks"] == [count.model_dump() for count in read_blocks(out)]
    assert len(recorded["blocks"]) == len(REAL_HOSTS) * len(HELD_OUT_FAULTS)
    assert [host["commit"] for host in recorded["hosts"]] == [h.commit for h in REAL_HOSTS]
    for path in out.glob("*/*/summary.json"):
        summary = HeldOutSummary.model_validate_json(path.read_text(encoding="utf-8"))
        assert summary.library_hash_before == summary.library_hash_after, path
        assert summary.source == f"results/replicates-2026-10-05/{run}"
        host = next(h for h in REAL_HOSTS if slug(h) == path.parent.parent.name)
        assert summary.seeds == list(seeds_for_host(host)), path
