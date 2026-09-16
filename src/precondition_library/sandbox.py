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

It is also **scrubbed**, not inherited. `git_env` builds from a short allowlist
of ambient variables rather than `dict(os.environ)`, so an API key the operator
exported cannot be read by model-authored code (spec §9). `HOME` is not
ambient: every caller that runs a command passes the sandbox root, so `~`
resolves inside a throwaway repository.

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


_ALLOWLISTED_ENV_VARS = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
"""The only ambient variables a git call or a shell probe may inherit.

Everything else in the caller's environment is dropped rather than copied, which
is what makes the spec's "the environment is scrubbed" (§9) true: a
`dict(os.environ)` spread handed any exported API key -- and the operator's
whole environment -- to model-authored code. A variable belongs here only when a
call fails without it: `PATH` finds `git` and the probe's tools, the locale
keeps git's output deterministic, and `TMPDIR` is where tools scratch. `HOME` is
deliberately absent; callers redirect it into the sandbox (`git_env(home=...)`).
"""


def git_env(home: Path | None = None) -> dict[str, str]:
    """The environment every git call in a sandbox runs under.

    `GIT_CONFIG_NOSYSTEM` and `GIT_CONFIG_GLOBAL=/dev/null` make a developer's
    own config unable to change the result; identity comes from the environment
    so no per-machine `user.name` is required (and none is written globally).

    Only `_ALLOWLISTED_ENV_VARS` is inherited, so a leaked `GIT_DIR` /
    `GIT_WORK_TREE` / `GIT_INDEX_FILE` cannot retarget these commands at the
    caller's own repository. `home`, when given, becomes `HOME` so a command
    that expands `~` lands inside the sandbox; a caller with no sandbox to
    redirect into leaves `HOME` unset rather than inheriting the operator's.
    """
    env = {name: os.environ[name] for name in _ALLOWLISTED_ENV_VARS if name in os.environ}
    if home is not None:
        env["HOME"] = str(home)
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
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run git with the sandbox environment; raise on failure unless `check=False`.

    Returns the completed process so callers can read stdout or inspect a
    non-zero exit for a probe whose failure is information (an ancestor test,
    for example) rather than an error.

    `timeout` bounds the call in seconds. On expiry `subprocess.TimeoutExpired`
    propagates rather than being converted to a failed exit: a caller must decide
    whether a killed command is an error (a probe) or information for whoever
    issued it (the ReAct tool, which reports it back to the model). `None` keeps
    the previous unbounded behaviour.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=git_env(home=cwd),
        capture_output=True,
        text=True,
        input=stdin,
        timeout=timeout,
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


_RECORDED_SUBMODULE_PATH_REF = "refs/sandbox/submodule-path"
"""Where a fault injector records the submodule path it injected, as a blob.

A fault's ground truth lives under `refs/sandbox/` so a branch rewrite cannot
drop it. This one has a second reason: the path is the *input* to the task, and
a correct removal deletes the `.gitmodules` entry that would otherwise carry it,
so the recorded value is what still names it in the state a program must bind.

The `submodule_moved` injector writes this ref and its checker reads it back;
the runtime needs the same name to bind `{submodule_path}` there, so the literal
is repeated here beside its reader. `tasks/faults/submodule_moved.py` holds the
other copy and the two are one convention -- the sandbox cannot import it
because the faults import the sandbox.
"""


def _recorded_submodule_path(work: Path) -> str | None:
    """The submodule path a fault injector recorded, or None when none is."""
    result = run_git(("cat-file", "-p", _RECORDED_SUBMODULE_PATH_REF), cwd=work, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def submodule_path(work: Path) -> str | None:
    """The submodule's path: recorded injection first, `.gitmodules` second.

    The order is the point, not an accident. `.gitmodules` is how a repository
    that was never faulted reports its submodule, so a program compiled against a
    real repository still resolves `{submodule_path}` from it. But one resolution
    of `submodule_moved` is *removing* the submodule, and a correct removal
    deletes the `.gitmodules` entry -- the evidence of what the path was. Reading
    it first would leave the program that did the right thing unable to bind the
    postcondition that says so. The injector records the path under
    `refs/sandbox/submodule-path`, which survives the removal, so it wins.

    Lives here rather than in `signatures` because it is a git read under the
    pinned environment, which this module owns, and because both the observed
    fingerprint and the runtime's parameter bindings need it; one reader means
    the two cannot disagree about where the submodule is. One submodule is all
    the grid models, so the first declared path is returned.
    """
    recorded = _recorded_submodule_path(work)
    if recorded is not None:
        return recorded
    result = run_git(
        ("config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"),
        cwd=work,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[-1]


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
