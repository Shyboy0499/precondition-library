"""Measurements that may run only under a committed pre-registration (#298).

A pre-registration fixes a study's hypotheses, unit, metric, test, sample and exclusions before
any of its data is seen. Its commit is its timestamp, so it is only worth anything if the code
that measures cannot run against a registration that was edited afterwards, or never committed.

Each registered study pins its document's SHA-256 here. `require` refuses to return unless the
document exists, hashes to the pinned value, is tracked by git and has no uncommitted change. An
amendment made before measuring is a new commit that changes the document *and* the pin, so it
shows in review; one made after measuring is a deviation, reported in the study's results rather
than written into the registration.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]

REGISTRATIONS: dict[str, str] = {
    "real-merges": "77bc2f861f117bbe7d97b58fb777f1e8e70cc4b92800904f7b1e06efa4e13d30",
    "refusal-population": "45674a886d36679bc3842600f38a40fc1836e519a9fcbc0641db9f1b01caee8c",
}
"""Each registered study's document, by name, and the SHA-256 of its bytes."""


class UnregisteredError(RuntimeError):
    """A measurement was asked for without the committed registration it is bound to."""


def document(name: str, root: Path = REPOSITORY) -> Path:
    return root / "docs" / "preregistration" / f"{name}.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(name: str, root: Path = REPOSITORY) -> Path:
    """The registration `name` is bound to, or `UnregisteredError` saying why it does not hold."""
    if name not in REGISTRATIONS:
        raise UnregisteredError(f"no study named {name!r} is registered")
    path = document(name, root)
    if not path.is_file():
        raise UnregisteredError(f"{path} does not exist; the study is not registered")
    if digest(path) != REGISTRATIONS[name]:
        raise UnregisteredError(
            f"{path} differs from the registered text; an amendment before measuring changes "
            "the pin in the same commit, and one after measuring is a deviation in the results"
        )
    relative = path.relative_to(root).as_posix()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative], cwd=root, capture_output=True
    )
    if tracked.returncode != 0:
        raise UnregisteredError(f"{relative} is not committed; its commit is its timestamp")
    changed = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative], cwd=root, capture_output=True
    )
    if changed.returncode != 0:
        raise UnregisteredError(f"{relative} has uncommitted changes")
    return path
