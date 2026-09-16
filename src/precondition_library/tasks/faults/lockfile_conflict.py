"""Fault: both sides changed a generated dependency file, so a sync conflicts.

The most interesting fault for the mismatch metric. The right resolution for a
conflict in a generated dependency file is to *regenerate* it with the
ecosystem's own tool, never to hand-edit conflict markers -- and a program that
hand-edits markers still *reports success*, which is the silent-wrong-action
failure arm 3 exists to catch.

## Lock-shaped, not a real ecosystem lockfile

This is a deliberate simplification, and it must not be described as more than
it is. Regeneration needs a package manager, which a sandbox does not have, and
grading a regenerated lockfile would require running one; neither is in scope
here. So the injector creates a small generated file of its own -- a version
field and a list of package entries -- commits it on both sides, and changes
both sides so a sync conflicts in it. The file is **lock-shaped, not a real
ecosystem lockfile**, and no claim that it is one should be made from it. A real
lockfile is a later change.

What survives the simplification is the failure mode that matters, because the
checker grades the outcome structurally rather than the bytes of a regenerated
file:

1. upstream's tip is contained in the local branch;
2. no conflict markers remain anywhere in the working tree -- a sync left
   half-resolved must fail;
3. the locally-added dependency is still present *and* the upstream-added one
   is too. This is the clause that punishes the plausible wrong answer: deleting
   the markers by hand "succeeds" as a command while silently dropping a
   dependency, and a real regeneration would keep both.

This fault is real but not yet measurable: it has no `IntentSpec`, so the
request text still names the fault and it stays excluded from any dispatch
measurement (issue #25).
"""

from __future__ import annotations

from ...sandbox import Sandbox, git_out, record_base, run_git, store_blob, tip_contained
from ..intent import sample_index
from ..spec import FaultSpec, GroundTruth

# The generated file the sandbox itself creates. Lock-shaped: a version field
# and a package list, not the format of any real package manager.
LOCK_PATH = "deps.lock"
_HEADER = "# lock-shaped dependency file (generated; not a real ecosystem lockfile)\n"
_BASE_PACKAGE = "corelib"

# Package names are split into halves so the local and upstream entries can
# never coincide: the local side draws from the first half and upstream from the
# second, whatever the seed. Appending a name would change which name an existing
# seed injects, so add names deliberately.
_PACKAGE_NAMES = ("alder", "birch", "cedar", "dogwood", "elder", "fir", "gum", "hazel")
_HALF = len(_PACKAGE_NAMES) // 2

# Versions the two sides move to. The upstream index is offset from the local
# one by at least 1, so the two sides always change the version line to
# different values -- which is what guarantees the sync conflicts rather than
# auto-merging. The base versions are a disjoint pool, so the injected file's
# starting version differs from both.
VERSIONS = ("1.2.0", "2.0.1", "3.4.0", "0.9.5")
_BASE_VERSIONS = ("0.1.0", "0.2.0")

_PACKAGE_SALT = "lockfile_conflict:package"
_VERSION_SALT = "lockfile_conflict:version"

# Ground truth lives under refs/sandbox/, where a branch rewrite cannot drop it
# and the checker can read it with `git cat-file` rather than re-deriving it
# from a seed the checker is never given.
_LOCAL_TIP_REF = "refs/sandbox/lock-local-tip"
_LOCAL_DEPENDENCY_REF = "refs/sandbox/lock-local-dependency"
_UPSTREAM_DEPENDENCY_REF = "refs/sandbox/lock-upstream-dependency"

# A conflict marker starts a line: `<<<<<<<`, `=======` (separator), `>>>>>>>`
# (end) or `|||||||` (diff3 base).
_MARKER_PATTERN = r"^(<{7}|={7}|>{7}|\|{7})"


def local_package_for_seed(seed: int) -> str:
    """The package the local side adds. Deterministic, and never upstream's."""
    index = sample_index(seed, f"{_PACKAGE_SALT}:local", _HALF)
    return _PACKAGE_NAMES[index]


def upstream_package_for_seed(seed: int) -> str:
    """The package the upstream side adds. Deterministic, and never local's."""
    index = _HALF + sample_index(seed, f"{_PACKAGE_SALT}:upstream", len(_PACKAGE_NAMES) - _HALF)
    return _PACKAGE_NAMES[index]


def _versions_for_seed(seed: int) -> tuple[str, str]:
    """(local version, upstream version), guaranteed distinct."""
    local_index = sample_index(seed, f"{_VERSION_SALT}:local", len(VERSIONS))
    offset = 1 + sample_index(seed, f"{_VERSION_SALT}:upstream", len(VERSIONS) - 1)
    return VERSIONS[local_index], VERSIONS[(local_index + offset) % len(VERSIONS)]


def base_version_for_seed(seed: int) -> str:
    """The version the injected file starts at, before either side changes it."""
    return _BASE_VERSIONS[sample_index(seed, f"{_VERSION_SALT}:base", len(_BASE_VERSIONS))]


def local_dependency_for_seed(seed: int) -> str:
    """The entry line the local side adds, e.g. `birch 0.9.5`."""
    return f"{local_package_for_seed(seed)} {_versions_for_seed(seed)[0]}"


def upstream_dependency_for_seed(seed: int) -> str:
    """The entry line the upstream side adds, e.g. `elder 1.2.0`."""
    return f"{upstream_package_for_seed(seed)} {_versions_for_seed(seed)[1]}"


def _base_lock_text(seed: int) -> str:
    version = base_version_for_seed(seed)
    return (
        _HEADER
        + f"version = {version}\n"
        + "packages = [\n"
        + f'    "{_BASE_PACKAGE} {version}",\n'
        + "]\n"
    )


def _edited_lock_text(seed: int, side: str) -> str:
    """The file after one side edits it: new version, one new entry at the top.

    Both sides rewrite the version line and insert immediately after
    `packages = [`, so the two edits occupy the same region and a merge of them
    conflicts. Which side is built is decided by the caller, not by the seed, so
    the same seed still yields byte-identical content for each commit.
    """
    local_version, upstream_version = _versions_for_seed(seed)
    if side == "local":
        version = local_version
        entry = local_dependency_for_seed(seed)
    else:
        version = upstream_version
        entry = upstream_dependency_for_seed(seed)
    return (
        _HEADER
        + f"version = {version}\n"
        + "packages = [\n"
        + f'    "{entry}",\n'
        + f'    "{_BASE_PACKAGE} {base_version_for_seed(seed)}",\n'
        + "]\n"
    )


class LockfileConflictFault(FaultSpec):
    name = "lockfile_conflict"
    description = "Upstream moved dependencies, conflicting inside a lock-shaped dependency file"

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Give both sides a different edit of the lock-shaped file.

        A common-ancestor commit adds the file and is pushed, so both sides start
        from the same content. The local side then commits its edit (kept local),
        and upstream commits a different edit from the same ancestor and pushes
        it. The local branch is restored to its own commit last, so the sandbox
        presents diverged sides whose edits overlap -- the sync conflicts.

        Deterministic in the seed: `sample_index` chooses the package names and
        the versions, and the sandbox's fixed identities and dates fix the SHAs.
        """
        work = sandbox.work
        record_base(sandbox, fault="lockfile_conflict")

        # The shared ancestor: both sides edit this version of the file.
        (work / LOCK_PATH).write_text(_base_lock_text(seed), encoding="utf-8")
        run_git(("add", "-A"), cwd=work)
        run_git(("commit", "-q", "-m", "chore: add generated dependency lock"), cwd=work)
        common = git_out("rev-parse", "HEAD", cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # The local-only edit.
        (work / LOCK_PATH).write_text(_edited_lock_text(seed, "local"), encoding="utf-8")
        run_git(("add", "-A"), cwd=work)
        run_git(("commit", "-q", "-m", "feat: add local dependency"), cwd=work)
        local_tip = git_out("rev-parse", "HEAD", cwd=work)
        run_git(("update-ref", _LOCAL_TIP_REF, local_tip), cwd=work)

        # Upstream's edit, built from the same ancestor and published.
        run_git(("reset", "--hard", common), cwd=work)
        (work / LOCK_PATH).write_text(_edited_lock_text(seed, "upstream"), encoding="utf-8")
        run_git(("add", "-A"), cwd=work)
        run_git(("commit", "-q", "-m", "feat: upstream adds a dependency"), cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # Back to the local branch, and record the ground truth the checker uses.
        run_git(("reset", "--hard", _LOCAL_TIP_REF), cwd=work)
        store_blob(work, _LOCAL_DEPENDENCY_REF, local_dependency_for_seed(seed))
        store_blob(work, _UPSTREAM_DEPENDENCY_REF, upstream_dependency_for_seed(seed))

        # Leave the remote-tracking ref current so observe() can read it without
        # fetching (observe must not mutate the environment).
        run_git(("fetch", "-q", "upstream"), cwd=work)

    def task_text(self, seed: int) -> str:
        return (
            "The sync hit a conflict in the lockfile. Resolve it the way this project "
            "expects, and leave dependency state consistent."
        )

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome, not the method, in three clauses.

        First, upstream's tip must be contained in the local branch. Second, no
        conflict marker may remain anywhere in the working tree, so a sync left
        half-resolved fails. Third, both added dependency entries must still be
        in the lock-shaped file: the local one and the upstream one.

        The third clause is the point. Hand-deleting the markers while keeping
        one side "succeeds" as a command and satisfies the first two clauses, but
        it silently drops a dependency; a real regeneration would keep both.
        """
        work = sandbox.work
        upstream_tip = git_out("rev-parse", "refs/heads/main", cwd=sandbox.upstream)
        if not tip_contained(work, upstream_tip):
            return GroundTruth(
                ok=False,
                detail=f"upstream tip {upstream_tip[:12]} is not contained in the local branch",
            )

        markers = run_git(
            ("grep", "-n", "-I", "--untracked", "-E", _MARKER_PATTERN), cwd=work, check=False
        )
        if markers.stdout.strip():
            first = markers.stdout.splitlines()[0]
            return GroundTruth(
                ok=False,
                detail=f"conflict markers remain in the working tree: {first}",
            )

        lock = work / LOCK_PATH
        if not lock.exists():
            return GroundTruth(ok=False, detail=f"{LOCK_PATH} is missing after the sync")
        text = lock.read_text(encoding="utf-8")

        local_entry = git_out("cat-file", "-p", _LOCAL_DEPENDENCY_REF, cwd=work)
        upstream_entry = git_out("cat-file", "-p", _UPSTREAM_DEPENDENCY_REF, cwd=work)
        if local_entry not in text:
            return GroundTruth(
                ok=False,
                detail=f"the locally-added dependency is missing from {LOCK_PATH}",
            )
        if upstream_entry not in text:
            return GroundTruth(
                ok=False,
                detail=f"the upstream-added dependency is missing from {LOCK_PATH}",
            )

        return GroundTruth(
            ok=True,
            detail=(
                "upstream tip is contained, no conflict markers remain, and both sides' "
                "dependencies are present"
            ),
        )


SPEC = LockfileConflictFault()
