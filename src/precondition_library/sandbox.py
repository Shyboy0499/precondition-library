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

**The dependency points one way: `tasks/faults/*` imports this module, and this
module imports no fault and no registry.** `create` therefore builds a sandbox
and stops; injecting a fault is the caller's step (`tasks.faults.build_sandbox`).
An earlier version imported `FAULTS` inside `create` to inject on the caller's
behalf, which reversed the declared direction (spec §4) and made
`{sandbox, tasks.faults, signatures, tasks.intent, *}` a single import cycle, so
`runtime.probes`, `runtime.replay` and `library` could all reach every fault
injector and the task registry. Injection still happens *after* the environment
exists, in the same order, through `build_sandbox`; only the direction changed.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import warnings
from collections.abc import Callable, Sequence
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
        # Explicit rather than the machine locale: git's output is compared and
        # asserted on, so its decoding should not depend on the console code page.
        encoding="utf-8",
        errors="replace",
        input=stdin,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result


def git_out(*args: str, cwd: Path) -> str:
    """Run git under the pinned environment and return its stripped stdout."""
    return run_git(args, cwd=cwd).stdout.strip()


def store_blob(work: Path, ref: str, content: str) -> None:
    """Write `content` as a blob and point `ref` at it.

    A ref rather than a side file keeps the recorded ground truth inside git,
    where a checker reads it with `git cat-file` and a branch rewrite cannot
    silently drop it.
    """
    sha = run_git(("hash-object", "-w", "--stdin"), cwd=work, stdin=content).stdout.strip()
    run_git(("update-ref", ref, sha), cwd=work)


def _force_writable(path: str) -> None:
    """Add the owner write bit, leaving every other bit alone.

    The recipe usually quoted for this is `os.chmod(path, stat.S_IWRITE)`, and it
    is wrong on POSIX for the same reason the naive `rmtree` is wrong on Windows:
    it *replaces* the mode rather than adding to it, so a directory that tripped
    this handler would come back as owner-write-only, losing the execute bit that
    makes it traversable. OR-ing the bit in is what both platforms actually want
    -- Windows maps the owner write bit onto `FILE_ATTRIBUTE_READONLY`, so the
    same call clears the attribute there.
    """
    os.chmod(path, os.lstat(path).st_mode | stat.S_IWUSR)


def _clear_readonly(func: Callable[..., object], path: str, _exc: BaseException) -> None:
    """Clear the write protection and retry, for a caller that must not fail.

    A `onexc` handler for `shutil.rmtree`. Git for Windows marks every loose
    object `FILE_ATTRIBUTE_READONLY`; POSIX `unlink` only needs the containing
    directory writable, but Windows `DeleteFile` refuses a read-only file
    outright. A bare `shutil.rmtree` therefore deletes a Linux sandbox and
    necessarily fails on a Windows one.

    Anything the retry does not fix re-raises, so a genuine failure surfaces at
    the call site that caused it rather than being deferred.
    """
    _force_writable(path)
    func(path)


def _clear_readonly_quiet(func: Callable[..., object], path: str, exc: BaseException) -> None:
    """`_clear_readonly` for a caller that must not raise: record instead.

    Used by `Sandbox.destroy()`, whose contract is idempotence: an already-absent
    root stays silent. Every other failure is *recorded* rather than swallowed.
    Silently discarding it leaves `.sandboxes/` residue that blows up later, in
    the next `create()`, inside whichever unrelated test happens to run then --
    an error naming neither the residue nor this call. That is the same
    report-success-while-doing-nothing shape the library exists to catch.
    """
    if isinstance(exc, FileNotFoundError):
        # The root (or a path inside it) is already gone. Idempotence, not a fault.
        return
    try:
        _clear_readonly(func, path, exc)
    except OSError as retry_exc:
        warnings.warn(
            f"left residue at {path}: {retry_exc}. A later create() may fail on it; "
            f"clear .sandboxes/ before the next run.",
            RuntimeWarning,
            stacklevel=2,
        )


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
        shutil.rmtree(self.root, onexc=_clear_readonly_quiet)
        # Leave no empty `.sandboxes/` behind when the last sandbox goes; rmdir
        # fails harmlessly while another one is still there.
        if self.root.parent == _SANDBOX_DIR:
            try:
                _SANDBOX_DIR.rmdir()
            except OSError:
                pass


BASE_REF = "refs/sandbox/base"
"""Where a fault records the tip it injected on top of.

Ground truth lives under `refs/sandbox/` so a branch rewrite cannot drop it. A
fault's own state ref (such as `submodule_moved`'s) is a different name, so this
is only the shared "the sandbox was pristine at this commit" record.
"""


def require_uninjected(sandbox: Sandbox, *, fault: str, ref: str = BASE_REF) -> None:
    """Raise if this sandbox already has `fault` injected.

    Injecting a fault twice would build a state that is neither fault, so it is an
    error rather than a no-op. `ref` is the ref the fault records when it runs; a
    sandbox already holding it has been injected.
    """
    work = sandbox.work
    if run_git(("rev-parse", "--verify", ref), cwd=work, check=False).returncode == 0:
        raise RuntimeError(f"{work} already has a {fault} fault injected")


def record_base(sandbox: Sandbox, *, fault: str) -> str:
    """Guard against double injection, record the pre-injection tip, return it.

    The guard and the record belong together: an injector that recorded a base
    without checking would leave the first injection's ref behind and a second
    call's `HEAD` would be the already-injected state, not the base.
    """
    require_uninjected(sandbox, fault=fault)
    work = sandbox.work
    base = git_out("rev-parse", "HEAD", cwd=work)
    run_git(("update-ref", BASE_REF, base), cwd=work)
    return base


def tip_contained(work: Path, tip: str) -> bool:
    """Whether `tip` is an ancestor of (or equal to) `HEAD` in `work`.

    Several checkers grade the same first clause -- upstream's tip is contained in
    the local branch -- before their fault-specific clauses. This is only that
    test; each caller keeps its own failure `detail`, which names what the tip was.
    """
    return (
        run_git(("merge-base", "--is-ancestor", tip, "HEAD"), cwd=work, check=False).returncode == 0
    )


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
    """Build an *empty* sandbox for `(seed, faults)`, deterministically.

    `faults` names the faults the sandbox is destined to hold; it selects the
    root (`seed-{seed}-{sorted faults}`) and nothing else. Injecting is the
    caller's step, because the fault registry is above this module, not below it
    (see the module docstring): `tasks.faults.build_sandbox` validates the names,
    calls `create`, and only then applies each fault's `inject`. Splitting the two
    keeps this function free of the cycle an in-function import used to hide.

    Determinism is required for the ablation: both arms must face byte-identical
    environments, and a re-run of the same seed must reproduce the same episode.
    Every step here is under the pinned environment above, so one seed produces
    the same clone and the same commit SHAs before any fault runs.

    The root is a function of `(seed, faults)`, so calling `create` twice for the
    same pair *replaces* the first sandbox rather than failing. That is safe for
    a throwaway environment and keeps leftover state from a crashed run from
    poisoning the next one; callers that need two live sandboxes must use two
    seeds, or destroy the first before rebuilding.
    """
    slug = "-".join(sorted(faults)) or "base"
    root = _SANDBOX_DIR / f"seed-{seed}-{slug}"
    if root.exists():
        # Residue from a crashed run, including read-only git objects on Windows;
        # `_clear_readonly` retries past them and re-raises anything it cannot fix.
        shutil.rmtree(root, onexc=_clear_readonly)
    root.mkdir(parents=True)

    upstream = root / "upstream.git"
    work = root / "work"
    run_git(("-c", "init.defaultBranch=main", "init", "--bare", str(upstream)), cwd=root)
    run_git(("clone", "-o", "upstream", str(upstream), str(work)), cwd=root)
    # Identity is per-repo, never global.
    run_git(("config", "user.name", _GIT_NAME), cwd=work)
    run_git(("config", "user.email", _GIT_EMAIL), cwd=work)
    _seed_base(work)
    return Sandbox(root=root, work=work, upstream=upstream)
