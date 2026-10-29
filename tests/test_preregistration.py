"""A pre-registered measurement refuses to run without its committed registration (#298)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from precondition_library.bench import preregistration as pr


@pytest.mark.parametrize("name", sorted(pr.REGISTRATIONS))
def test_the_committed_registration_holds(name: str) -> None:
    assert pr.require(name) == pr.document(name)


def test_every_pin_is_a_sha256() -> None:
    for name, pin in pr.REGISTRATIONS.items():
        assert len(pin) == 64 and set(pin) <= set("0123456789abcdef"), name
        assert pr.digest(pr.document(name)) == pin, name


def _repository(tmp_path: Path) -> Path:
    """A git repository holding the registration as committed."""
    root = tmp_path / "repo"
    target = pr.document("real-merges", root)
    target.parent.mkdir(parents=True)
    shutil.copyfile(pr.document("real-merges"), target)
    for argv in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "register"],
    ):
        subprocess.run(["git", *argv], cwd=root, check=True)
    return root


def test_it_holds_in_a_repository_that_committed_it(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    assert pr.require("real-merges", root) == pr.document("real-merges", root)


def test_an_unknown_study_is_refused() -> None:
    with pytest.raises(pr.UnregisteredError, match="no study"):
        pr.require("not-a-study")


def test_a_missing_registration_is_refused(tmp_path: Path) -> None:
    with pytest.raises(pr.UnregisteredError, match="does not exist"):
        pr.require("real-merges", tmp_path)


def test_an_edited_registration_is_refused(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    path = pr.document("real-merges", root)
    path.write_text(path.read_text(encoding="utf-8").replace("H1", "H0", 1), encoding="utf-8")
    with pytest.raises(pr.UnregisteredError, match="differs from the registered text"):
        pr.require("real-merges", root)


def test_an_uncommitted_registration_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = pr.document("real-merges", root)
    target.parent.mkdir(parents=True)
    shutil.copyfile(pr.document("real-merges"), target)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    with pytest.raises(pr.UnregisteredError, match="not committed"):
        pr.require("real-merges", root)


def test_a_registration_changed_since_its_commit_is_refused(tmp_path: Path) -> None:
    """Restoring the registered bytes over a different committed text is still refused."""
    root = _repository(tmp_path)
    path = pr.document("real-merges", root)
    registered = path.read_bytes()
    path.write_bytes(registered + b"\nedited\n")
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "edit"],
        cwd=root,
        check=True,
    )
    path.write_bytes(registered)
    with pytest.raises(pr.UnregisteredError, match="uncommitted changes"):
        pr.require("real-merges", root)
