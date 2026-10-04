"""`StateFingerprint.observe` reads the environment's own upstream ref, not `upstream/main`.

The fingerprint compared everything against `upstream/main`, the harness's fixed
spelling of upstream. On an existing checkout (#181) upstream is whatever its remote
and default branch are -- a fork's `origin/trunk` -- so `observe` now asks
`sandbox.upstream_ref`. These tests pin:

* **parity**: every harness state, observed as a checkout, fingerprints exactly as the
  sandbox does, so nothing measured changes;
* on a checkout whose upstream is `origin/trunk`, the counts and touched files are read
  against `origin/trunk`;
* a checkout with no derivable upstream refuses to be fingerprinted rather than
  comparing against a ref that is not its upstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precondition_library.checkout import open_checkout
from precondition_library.sandbox import (
    HARNESS_UPSTREAM_REF,
    NoUpstreamError,
    run_git,
    upstream_ref,
)
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import FAULTS, build_sandbox
from precondition_library.tasks.registry import ambiguous_intents

MEASURED = sorted(intent.fault for intent in ambiguous_intents())


def _seeds_per_state(fault: str) -> list[int]:
    seeds: dict[str, int] = {}
    for seed in range(200):
        state = FAULTS[fault].variant_for_seed(seed)
        if state is not None:
            seeds.setdefault(state, seed)
    return sorted(seeds.values())


CASES = [([], 0)] + [([f], seed) for f in MEASURED for seed in _seeds_per_state(f)]


@pytest.mark.parametrize(("faults", "seed"), CASES)
def test_a_harness_state_seen_as_a_checkout_fingerprints_identically(
    faults, seed, tmp_path
) -> None:
    box = build_sandbox(seed, faults)
    try:
        env = open_checkout(box.work, fetch=False, scratch=tmp_path)
        try:
            assert upstream_ref(env) == HARNESS_UPSTREAM_REF
            assert StateFingerprint.observe(env) == StateFingerprint.observe(box)
        finally:
            env.destroy()
    finally:
        box.destroy()


def test_a_harness_sandbox_reads_upstream_main() -> None:
    box = build_sandbox(0, [])
    try:
        assert upstream_ref(box) == "upstream/main"
    finally:
        box.destroy()


def _git(cwd: Path, *args: str) -> str:
    return run_git(args, cwd=cwd).stdout.strip()


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)


def test_a_fork_of_origin_trunk_is_compared_against_origin_trunk(tmp_path) -> None:
    origin = tmp_path / "origin.git"
    run_git(("-c", "init.defaultBranch=trunk", "init", "-q", "--bare", str(origin)), cwd=tmp_path)
    seed = tmp_path / "seed"
    run_git(("clone", "-q", str(origin), str(seed)), cwd=tmp_path)
    _git(seed, "checkout", "-q", "-b", "trunk")
    _commit(seed, "base")
    _git(seed, "push", "-q", "origin", "trunk")

    work = tmp_path / "work"
    run_git(("clone", "-q", str(origin), str(work)), cwd=tmp_path)
    _commit(work, "local-only")
    _commit(seed, "upstream-only")
    _git(seed, "push", "-q", "origin", "trunk")

    env = open_checkout(work, scratch=tmp_path)  # the pre-fetch brings upstream-only down
    try:
        assert upstream_ref(env) == "origin/trunk"
        state = StateFingerprint.observe(env)
        assert (state.upstream_ahead, state.upstream_behind) == (1, 1)
        assert state.local_touched_files == ["local-only"]
        assert state.upstream_touched_files == ["upstream-only"]
    finally:
        env.destroy()


def test_a_checkout_with_no_upstream_is_not_fingerprinted(tmp_path) -> None:
    lonely = tmp_path / "lonely"
    run_git(("init", "-q", str(lonely)), cwd=tmp_path)
    _commit(lonely, "only")
    env = open_checkout(lonely, fetch=False, scratch=tmp_path)
    try:
        with pytest.raises(NoUpstreamError, match="no derivable upstream"):
            StateFingerprint.observe(env)
    finally:
        env.destroy()
