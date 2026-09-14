"""Throwaway environments for episodes.

Every episode runs against a sandbox built here — a working clone plus a bare
"upstream" repo — and is destroyed afterwards. Phase 1 never touches a real
fork: replayed programs execute unattended, so the only safe target is a
repository that can be deleted without consequence.

The environment is pinned so that one seed produces byte-identical *content*,
commit SHAs included: fixed author and committer dates, fixed identities, no
system or user git config, and `init.defaultBranch=main`. Without that, a
re-run of the same episode would silently face a different repository, and a
difference between arms could be the developer's git config rather than the
mechanism under test.

`run_git` and `git_env` are the single definition of that pinned environment.
They are module-level rather than underscore-private because fault injectors
(`tasks/faults/*`) and the state probes (`signatures.StateFingerprint.observe`)
must mutate and read the sandbox with the same settings; a second copy in each
caller is how one fault's commits drift from another's.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_SANDBOX_DIR = Path(__file__).resolve().parents[2] / ".sandboxes"

# Fixed so that the same seed yields the same SHAs. Real-world ordering is not
# needed; reproducibility is.
_GIT_DATE = "2026-01-01T00:00:00+00:00"
_GIT_NAME = "precondition-library sandbox"
_GIT_EMAIL = "sandbox@precondition-library.invalid"


def git_env() -> dict[str, str]:
    """The environment every git call in a sandbox runs under.

    `GIT_CONFIG_NOSYSTEM` and `GIT_CONFIG_GLOBAL=/dev/null` make a developer's
    own config unable to change the result; identity comes from the environment
    so no per-machine `user.name` is required (and none is written globally).
    """
    env = dict(os.environ)
    # A developer shell that has GIT_DIR/GIT_WORK_TREE exported would retarget
    # these commands at their own repository; drop them.
    for leaked in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(leaked, None)
    env.update(
        {
            "GIT_AUTHOR_NAME": _GIT_NAME,
            "GIT_AUTHOR_EMAIL": _GIT_EMAIL,
            "GIT_COMMITTER_NAME": _GIT_NAME,
            "GIT_COMMITTER_EMAIL": _GIT_EMAIL,
            "GIT_AUTHOR_DATE": _GIT_DATE,
            "GIT_COMMITTER_DATE": _GIT_DATE,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
    )
    return env


def run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run git with the sandbox environment; raise on failure unless `check=False`.

    Returns the completed process so callers can read stdout or inspect a
    non-zero exit for a probe whose failure is information (an ancestor test,
    for example) rather than an error.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=git_env(),
        capture_output=True,
        text=True,
        input=stdin,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result


@dataclass(frozen=True)
class Sandbox:
    """A disposable environment and the handles needed to inspect it."""

    root: Path
    work: Path
    """Working clone the agent operates on."""
    upstream: Path
    """Bare repo standing in for a real upstream."""

    def destroy(self) -> None:
        """Remove the sandbox from disk. Idempotent: a missing root is fine."""
        shutil.rmtree(self.root, ignore_errors=True)
        # Leave no empty `.sandboxes/` behind when the last sandbox goes; rmdir
        # fails harmlessly while another one is still there.
        if self.root.parent == _SANDBOX_DIR:
            try:
                _SANDBOX_DIR.rmdir()
            except OSError:
                pass


_BASE_FILES = {
    "app.py": (
        "def greet(name):\n"
        '    return f"hello {name}"\n'
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        '    print(greet("world"))\n'
    ),
    "docs/readme.md": "# readme\n\nSome notes.\n",
}


def _seed_base(work: Path) -> None:
    """Write the base tree, commit it, and publish it as upstream's `main`."""
    for relative, content in _BASE_FILES.items():
        path = work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    run_git(("add", "-A"), cwd=work)
    run_git(("commit", "-q", "-m", "chore: initial commit"), cwd=work)
    run_git(("push", "-q", "-u", "upstream", "main"), cwd=work)


def create_submodule_origin(root: Path, name: str) -> Path:
    """Create an empty local repository for a submodule fault to point at.

    A submodule needs a third repository behind its URL. A local path is a valid
    submodule URL, so one can be built here with no network and still
    deterministically: the origin is created under the same pinned environment as
    the rest of the sandbox (`run_git`), so its commit SHAs reproduce, and it
    lives inside the sandbox root so `Sandbox.destroy` removes it with everything
    else. The caller writes and commits the content it wants; `git submodule add`
    needs the origin to have at least one commit before it can clone it.
    """
    origin = root / name
    origin.mkdir(parents=True)
    run_git(("-c", "init.defaultBranch=main", "init", "-q", str(origin)), cwd=root)
    # Identity is per-repo, never global.
    run_git(("config", "user.name", _GIT_NAME), cwd=origin)
    run_git(("config", "user.email", _GIT_EMAIL), cwd=origin)
    return origin


def create(seed: int, faults: list[str]) -> Sandbox:
    """Build a sandbox with the named faults injected, deterministically.

    Determinism is required for the ablation: both arms must face byte-identical
    environments, and a re-run of the same seed must reproduce the same episode.

    The root is a function of `(seed, faults)`, so calling `create` twice for the
    same pair *replaces* the first sandbox rather than failing. That is safe for
    a throwaway environment and keeps leftover state from a crashed run from
    poisoning the next one; callers that need two live sandboxes must use two
    seeds, or destroy the first before rebuilding.
    """
    from .tasks.faults import FAULTS

    unknown = sorted(set(faults) - set(FAULTS))
    if unknown:
        raise ValueError(f"unknown faults {unknown}; known: {sorted(FAULTS)}")

    slug = "-".join(sorted(faults)) or "base"
    root = _SANDBOX_DIR / f"seed-{seed}-{slug}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    upstream = root / "upstream.git"
    work = root / "work"
    run_git(("-c", "init.defaultBranch=main", "init", "--bare", str(upstream)), cwd=root)
    run_git(("clone", "-o", "upstream", str(upstream), str(work)), cwd=root)
    # Identity is per-repo, never global.
    run_git(("config", "user.name", _GIT_NAME), cwd=work)
    run_git(("config", "user.email", _GIT_EMAIL), cwd=work)
    _seed_base(work)

    sandbox = Sandbox(root=root, work=work, upstream=upstream)
    for name in faults:
        FAULTS[name].inject(seed, sandbox)
    return sandbox
