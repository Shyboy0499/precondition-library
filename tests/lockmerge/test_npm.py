"""lockmerge on package-lock.json: what it merges, what it refuses, and that npm accepts it."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import lockmerge
from lockmerge import Declined, Merged
from lockmerge._merge import merge_value

BASE: dict[str, Any] = {
    "name": "app",
    "version": "1.0.0",
    "lockfileVersion": 3,
    "requires": True,
    "packages": {
        "": {"name": "app", "version": "1.0.0", "dependencies": {"left-pad": "^1.0.0"}},
        "node_modules/left-pad": {"version": "1.1.0", "license": "MIT"},
    },
}


def _text(lock: dict[str, Any], indent: int | str = 2) -> str:
    return json.dumps(lock, indent=indent) + "\n"


def _add(lock: dict[str, Any], name: str, version: str, wanted: str, **extra: Any) -> None:
    """Add a dependency as npm would, keeping both maps sorted."""
    root = lock["packages"][""]
    root["dependencies"] = dict(sorted({**root["dependencies"], name: wanted}.items()))
    lock["packages"][f"node_modules/{name}"] = {"version": version, **extra}
    lock["packages"] = {"": root, **dict(sorted((k, v) for k, v in lock["packages"].items() if k))}


def _merge(base: dict, ours: dict, theirs: dict) -> lockmerge.Outcome:
    return lockmerge.merge("package-lock.json", _text(base), _text(ours), _text(theirs))


def test_the_three_way_rule() -> None:
    assert merge_value(1, 1, 2) == (2, False)
    assert merge_value(1, 2, 1) == (2, False)
    assert merge_value(1, 2, 2) == (2, False)
    assert merge_value(1, 2, 3) == (2, True)


def test_each_side_adding_a_different_package_merges_sorted() -> None:
    ours, theirs = copy.deepcopy(BASE), copy.deepcopy(BASE)
    _add(ours, "zod", "3.22.0", "^3.22.0")
    _add(theirs, "chalk", "5.3.0", "^5.3.0")
    outcome = _merge(BASE, ours, theirs)
    assert isinstance(outcome, Merged)
    merged = json.loads(outcome.text)
    assert list(merged["packages"]) == [
        "",
        "node_modules/chalk",
        "node_modules/left-pad",
        "node_modules/zod",
    ]
    assert list(merged["packages"][""]["dependencies"]) == ["chalk", "left-pad", "zod"]


def test_one_package_moved_to_two_versions_is_refused_and_named() -> None:
    ours, theirs = copy.deepcopy(BASE), copy.deepcopy(BASE)
    ours["packages"]["node_modules/left-pad"]["version"] = "1.2.0"
    theirs["packages"]["node_modules/left-pad"]["version"] = "1.3.0"
    outcome = _merge(BASE, ours, theirs)
    assert isinstance(outcome, Declined) and outcome.diverged
    assert outcome.reasons == ["left-pad: base 1.1.0, ours 1.2.0, theirs 1.3.0"]


def test_the_same_change_on_both_sides_is_no_conflict() -> None:
    ours, theirs = copy.deepcopy(BASE), copy.deepcopy(BASE)
    for side in (ours, theirs):
        side["packages"]["node_modules/left-pad"]["version"] = "1.3.0"
    outcome = _merge(BASE, ours, theirs)
    assert isinstance(outcome, Merged)
    assert json.loads(outcome.text) == ours


def test_removed_on_one_side_and_changed_on_the_other_is_refused() -> None:
    ours, theirs = copy.deepcopy(BASE), copy.deepcopy(BASE)
    del ours["packages"]["node_modules/left-pad"]
    del ours["packages"][""]["dependencies"]["left-pad"]
    theirs["packages"]["node_modules/left-pad"]["version"] = "1.3.0"
    outcome = _merge(BASE, ours, theirs)
    assert isinstance(outcome, Declined) and outcome.diverged


def test_a_record_is_never_stitched_from_both_sides() -> None:
    """Ours changes left-pad's license field, theirs its version: one record, two edits. A
    field-by-field merge would invent a record neither side resolved."""
    ours, theirs = copy.deepcopy(BASE), copy.deepcopy(BASE)
    ours["packages"]["node_modules/left-pad"]["license"] = "ISC"
    theirs["packages"]["node_modules/left-pad"]["version"] = "1.3.0"
    assert isinstance(_merge(BASE, ours, theirs), Declined)


def test_a_merge_that_breaks_a_requirement_neither_side_broke_is_refused() -> None:
    """Ours upgrades a shared dependency; theirs adds a package that needs the old version.
    No record diverges, but the merged tree cannot be installed as locked."""
    base = copy.deepcopy(BASE)
    ours, theirs = copy.deepcopy(base), copy.deepcopy(base)
    ours["packages"]["node_modules/left-pad"]["version"] = "2.0.0"
    ours["packages"][""]["dependencies"]["left-pad"] = "^2.0.0"
    _add(theirs, "padder", "1.0.0", "^1.0.0", dependencies={"left-pad": "^1.0.0"})
    outcome = _merge(base, ours, theirs)
    assert isinstance(outcome, Declined) and outcome.inconsistent
    assert any("padder -> left-pad@^1.0.0 (found 2.0.0)" in r for r in outcome.reasons)


def test_a_requirement_already_broken_on_one_side_does_not_block() -> None:
    base = copy.deepcopy(BASE)
    base["packages"]["node_modules/left-pad"]["dependencies"] = {"ghost": "^1.0.0"}
    ours, theirs = copy.deepcopy(base), copy.deepcopy(base)
    _add(theirs, "chalk", "5.3.0", "^5.3.0")
    assert isinstance(_merge(base, ours, theirs), Merged)


def test_different_lockfile_formats_are_refused() -> None:
    ours, theirs = copy.deepcopy(BASE), copy.deepcopy(BASE)
    theirs["lockfileVersion"] = 2
    outcome = _merge(BASE, ours, theirs)
    assert isinstance(outcome, Declined)
    assert "different lockfile formats" in outcome.reasons[0]


def test_format_1_merges_by_top_level_dependency() -> None:
    base = {
        "name": "app",
        "lockfileVersion": 1,
        "requires": True,
        "dependencies": {"left-pad": {"version": "1.1.0"}},
    }
    ours, theirs = copy.deepcopy(base), copy.deepcopy(base)
    ours["dependencies"]["zod"] = {"version": "3.22.0"}
    theirs["dependencies"] = {"chalk": {"version": "5.3.0"}, **theirs["dependencies"]}
    outcome = _merge(base, ours, theirs)
    assert isinstance(outcome, Merged)
    assert list(json.loads(outcome.text)["dependencies"]) == ["chalk", "left-pad", "zod"]


def test_indentation_and_final_newline_follow_ours() -> None:
    ours, theirs = copy.deepcopy(BASE), copy.deepcopy(BASE)
    _add(theirs, "chalk", "5.3.0", "^5.3.0")
    outcome = lockmerge.merge(
        "package-lock.json", _text(BASE, "\t"), _text(ours, "\t"), _text(theirs, "\t")
    )
    assert isinstance(outcome, Merged)
    assert outcome.text.startswith('{\n\t"name"') and outcome.text.endswith("}\n")


def test_unreadable_input_is_refused_not_guessed() -> None:
    outcome = lockmerge.merge("package-lock.json", "{}", "{ not json", "{}")
    assert isinstance(outcome, Declined) and "not JSON" in outcome.reasons[0]


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not installed (#385)")
def test_npm_accepts_the_merged_lock_file(tmp_path: Path) -> None:
    """`npm ls --package-lock-only` reads package.json and the lock file without installing or
    reaching a registry, and exits non-zero on a lock that does not satisfy package.json."""
    ours, theirs = copy.deepcopy(BASE), copy.deepcopy(BASE)
    _add(ours, "zod", "3.22.0", "^3.22.0")
    _add(theirs, "chalk", "5.3.0", "^5.3.0")
    outcome = _merge(BASE, ours, theirs)
    assert isinstance(outcome, Merged)
    root = json.loads(outcome.text)["packages"][""]
    manifest = {"name": "app", "version": "1.0.0", "dependencies": root["dependencies"]}
    (tmp_path / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "package-lock.json").write_text(outcome.text, encoding="utf-8")
    done = subprocess.run(
        ["npm", "ls", "--package-lock-only", "--all", "--offline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "chalk@5.3.0" in done.stdout and "zod@3.22.0" in done.stdout
