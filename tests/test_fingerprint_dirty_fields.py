"""The fingerprint observes uncommitted work and untracked collisions, and arm 2 sees both.

#189 gives the dirty-tree fault an intent whose rules must read two facts the
fingerprint did not have: which tracked files carry uncommitted changes, and which
untracked files sit at a path upstream's tree holds. These tests pin:

* both are observed from git on a repository built by hand to have each;
* both are empty where there is nothing uncommitted;
* **both reach `as_text`**, arm 2's whole view of state, now that the intent is
  registered (ADR-0027): a field the rules decide on and arm 2 cannot read would make
  arm 2 blind by construction rather than by its mechanism.
"""

from __future__ import annotations

from precondition_library.sandbox import run_git
from precondition_library.signatures import _NOT_YET_RENDERED, StateFingerprint
from precondition_library.tasks.state_grid import DIRTY_TREE_STATES


def _git(cwd, *args: str) -> str:
    return run_git(args, cwd=cwd).stdout.strip()


def test_uncommitted_files_and_untracked_collisions_are_observed(make_sandbox) -> None:
    box = make_sandbox(0, [])
    work = box.work
    # Upstream starts tracking notes/tracked.txt; the local branch is rewound before it.
    (work / "notes").mkdir()
    (work / "notes" / "tracked.txt").write_text("upstream's\n", encoding="utf-8")
    _git(work, "add", "notes/tracked.txt")
    _git(work, "commit", "-q", "-m", "upstream tracks a note")
    _git(work, "push", "-q", "upstream", "main")
    _git(work, "reset", "-q", "--hard", "HEAD~1")
    # Local work: an untracked file at upstream's new path, a free one, a staged edit
    # and an unstaged one.
    (work / "notes").mkdir(exist_ok=True)
    (work / "notes" / "tracked.txt").write_text("mine\n", encoding="utf-8")
    (work / "notes" / "free.txt").write_text("mine too\n", encoding="utf-8")
    with (work / "app.py").open("a", encoding="utf-8") as handle:
        handle.write("# staged\n")
    _git(work, "add", "app.py")
    with (work / "docs" / "readme.md").open("a", encoding="utf-8") as handle:
        handle.write("unstaged\n")

    state = StateFingerprint.observe(box)
    assert state.dirty_files == ["app.py", "docs/readme.md"], "staged and unstaged alike"
    assert state.untracked_upstream_collisions == ["notes/tracked.txt"]
    assert state.upstream_ahead == 1


def test_a_clean_tree_has_neither(make_sandbox) -> None:
    state = StateFingerprint.observe(make_sandbox(0, []))
    assert state.dirty_files == [] and state.untracked_upstream_collisions == []


def test_arm_2_sees_them_now_the_intent_is_registered() -> None:
    seen = StateFingerprint(
        dirty_worktree=True,
        branch="main",
        upstream_ahead=1,
        upstream_behind=0,
        has_locked_branch=False,
        has_submodule_reference=False,
        dirty_files=["app.py"],
        untracked_upstream_collisions=["notes/tracked.txt"],
    )
    lines = seen.as_text().splitlines()
    rendered = [name for name in StateFingerprint.model_fields if name not in _NOT_YET_RENDERED]
    assert [line.split(":", 1)[0] for line in lines] == rendered
    assert lines[-2:] == ["dirty_files: app.py", "untracked_upstream_collisions: notes/tracked.txt"]


def test_every_dirty_tree_state_renders_what_decides_it() -> None:
    """The fields the intent's rules read are in each declared state's text."""
    collision = DIRTY_TREE_STATES["collision"].as_text()
    assert "untracked_upstream_collisions: notes/scratch.txt" in collision
    assert "dirty_files: app.py" in DIRTY_TREE_STATES["same_file"].as_text()
    assert "dirty_files: docs/readme.md" in DIRTY_TREE_STATES["disjoint"].as_text()
    assert "untracked_upstream_collisions: (none)" in DIRTY_TREE_STATES["disjoint"].as_text()
