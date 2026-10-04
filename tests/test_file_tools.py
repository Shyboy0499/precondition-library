"""The agent's file reader and writer, and what confines them to the working tree.

The fourth live smoke run's agent could not resolve a lock-file conflict with git alone:
it failed every lockfile solve but one, which wrote its blob through `git notes`, and
another set a `!sed` alias (now refused). These tests pin that `read_file` and
`write_file` work inside the tree, refuse every way out of it -- an absolute path, `..`,
`.git`, a symbolic link -- and, end to end, that a scripted agent now resolves the real
lockfile state the way a person would: merge, read the conflict, write the file, commit.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path

import pytest
from conftest import FakeProvider

from precondition_library.agents.file_tools import MAX_FILE_BYTES, read_file, write_file
from precondition_library.agents.memory import successful_commands
from precondition_library.agents.react import FINISH_TOOL, solve
from precondition_library.program import EpisodeOutcome
from precondition_library.provider import Completion, TokenUsage
from precondition_library.sandbox import run_git
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults.lockfile_conflict import SPEC

ADDITIONS_ONLY = 0
"""The lockfile seed whose state is `additions_only`, as `tests/test_lockfile_intent.py`
pins."""

_IDS = itertools.count(1)
_USAGE = TokenUsage(tokens_in=10, tokens_out=5, uncached_tokens_in=10)


def _call(name: str, **arguments: str) -> dict:
    return {
        "id": f"call_{next(_IDS)}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _turn(*calls: dict) -> Completion:
    return Completion(tool_calls=list(calls), usage=_USAGE, model="fake")


def test_a_write_is_read_back_and_creates_its_directories(tmp_path: Path) -> None:
    result, ok = write_file("notes/new/today.txt", "one\ntwo\n", tmp_path)
    assert ok and result == "wrote notes/new/today.txt (8 bytes)"
    assert read_file("notes/new/today.txt", tmp_path) == ("one\ntwo\n", True)
    if sys.platform != "win32":
        assert (tmp_path / "notes/new/today.txt").stat().st_mode & 0o777 == 0o644


def test_a_write_replaces_the_whole_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("old and long\n", encoding="utf-8")
    write_file("a.txt", "new\n", tmp_path)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new\n"


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("", "a path is required"),
        ("/etc/passwd", "is absolute"),
        ("../outside.txt", "climbs out"),
        ("docs/../../outside.txt", "climbs out"),
        (".git/config", "inside .git"),
        (".git/hooks/post-merge", "inside .git"),
        (".GIT/config", "inside .git"),
        ("vendor/libcore/.git/config", "inside .git"),
    ],
)
def test_a_path_out_of_the_tree_is_refused(tmp_path: Path, path: str, reason: str) -> None:
    for result, ok in (write_file(path, "x", tmp_path), read_file(path, tmp_path)):
        assert not ok and result.startswith("refused:") and reason in result, result
    assert not (tmp_path.parent / "outside.txt").exists()


def test_a_symbolic_link_is_never_followed(tmp_path: Path) -> None:
    """POSIX symbolic links; the Windows CI job runs only the portability tests."""
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("keep\n", encoding="utf-8")
    os.symlink(outside, work / "linked-dir")
    os.symlink(outside / "secret.txt", work / "linked-file")
    for path in ("linked-dir/secret.txt", "linked-file"):
        result, ok = write_file(path, "overwritten\n", work)
        assert not ok and "symbolic link" in result, result
        assert not read_file(path, work)[1]
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "keep\n"


def test_size_and_kind_are_checked(tmp_path: Path) -> None:
    too_big = "x" * (MAX_FILE_BYTES + 1)
    assert "the limit is" in write_file("big.txt", too_big, tmp_path)[0]
    (tmp_path / "big.txt").write_text(too_big, encoding="utf-8")
    assert "the limit is" in read_file("big.txt", tmp_path)[0]
    (tmp_path / "docs").mkdir()
    assert "is a directory" in write_file("docs", "x", tmp_path)[0]
    assert read_file("missing.txt", tmp_path) == ("no such file: missing.txt", False)


def _resolved_lock(work: Path) -> str:
    """Upstream's lock with the local side's added entries inserted: `take_upstream`."""

    def show(rev: str) -> list[str]:
        return run_git(("show", f"{rev}:deps.lock"), cwd=work).stdout.splitlines()

    base = run_git(("merge-base", "HEAD", "upstream/main"), cwd=work).stdout.strip()
    added = [line for line in show("HEAD") if line not in show(base) and line.startswith("    ")]
    theirs = show("upstream/main")
    at = theirs.index("packages = [") + 1
    return "\n".join([*theirs[:at], *added, *theirs[at:]]) + "\n"


def test_the_agent_resolves_a_lockfile_conflict_with_the_file_tools(make_sandbox) -> None:
    box = make_sandbox(ADDITIONS_ONLY, ["lockfile_conflict"])
    signature = TaskSignature(
        intent=SPEC.task_text(ADDITIONS_ONLY),
        fingerprint=StateFingerprint.observe(box),
        target=str(box.work),
    )
    provider = FakeProvider(
        _turn(_call("run_git", command="git merge --no-edit upstream/main")),
        _turn(_call("read_file", path="deps.lock")),
        _turn(_call("write_file", path="deps.lock", content=_resolved_lock(box.work))),
        _turn(_call("run_git", command="git add deps.lock")),
        _turn(_call("run_git", command="git commit -q --no-edit")),
        _turn(_call(FINISH_TOOL, summary="merged upstream and rebuilt the lock")),
    )
    outcome, transcript = solve(signature, box, provider)

    assert outcome is EpisodeOutcome.SUCCESS
    tools = [entry for entry in transcript if entry["role"] == "tool"]
    assert "<<<<<<<" in tools[1]["content"], "read_file shows the conflict as it is on disk"
    assert tools[2]["command"] == "write_file deps.lock" and tools[2]["ok"]
    verdict = SPEC.check(box)
    assert verdict.ok, verdict.detail
    assert "write_file deps.lock" in successful_commands(transcript), "arm 1b remembers it"


def test_a_write_without_content_and_an_unknown_tool_are_refused(make_sandbox) -> None:
    box = make_sandbox(ADDITIONS_ONLY, ["lockfile_conflict"])
    signature = TaskSignature(
        intent="sync", fingerprint=StateFingerprint.observe(box), target=str(box.work)
    )
    provider = FakeProvider(
        _turn(_call("write_file", path="deps.lock")),
        _turn(_call("delete_file", path="deps.lock")),
        _turn(_call(FINISH_TOOL, summary="gave up")),
    )
    _, transcript = solve(signature, box, provider)
    missing, unknown = [entry for entry in transcript if entry["role"] == "tool"]
    assert not missing["ok"] and "needs 'content'" in missing["content"]
    assert not unknown["ok"] and "'read_file', 'write_file'" in unknown["content"]
    assert (box.work / "deps.lock").is_file(), "nothing was written or removed"
