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
   dependency, and a real regeneration would keep both;
4. a dependency one side removed stays removed -- re-adding it is the mirror of
   dropping one, and a regeneration from the side that still lists it does exactly
   that;
5. the file is still lock-shaped: exactly one `version` line. A union merge keeps
   both sides' version lines, which no real lockfile could hold.

Each seed selects one of three live states (#191), chosen so that different fixed
resolutions are right in different states, by this checker:

* ``additions_only`` -- each side adds one dependency and bumps the version;
* ``upstream_removed`` -- as well, upstream drops a dependency the local side kept;
* ``local_removed`` -- as well, the local side drops one upstream kept.

The fault is measured (ADR-0029): `INTENT` is registered in `tasks.registry`, so the
request is one of its phrasings and `variant_for_seed` labels every seed with the
resolution its state needs.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...sandbox import Sandbox, git_out, record_base, run_git, tip_contained
from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant, sample_index
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

# The three live states a seed selects between, and the salt that chooses them.
# Appending a state would change which state an existing seed injects, so add
# states deliberately.
INJECTED_STATES = ("additions_only", "upstream_removed", "local_removed")
_STATE_SALT = "lockfile_conflict:state"

# A dependency the base lists and one side may drop. Never a drawn package name, so
# it cannot coincide with either side's addition.
_REMOVABLE_PACKAGE = "zlib"

# Ground truth lives in `Sandbox.recorded`, which the harness holds outside the
# clone: no branch rewrite can drop it, the graded code cannot read it, and the
# checker need not re-derive it from a seed it is never given (#103, #161).

# A conflict marker starts a line: `<<<<<<<`, `=======` (separator), `>>>>>>>`
# (end) or `|||||||` (diff3 base).
_MARKER_PATTERN = r"^(<{7}|={7}|>{7}|\|{7})"


def state_for_seed(seed: int) -> str:
    """Which live state this seed injects. Deterministic.

    One definition shared by `inject` and the tests, so a test cannot disagree with the
    injected environment.
    """
    return INJECTED_STATES[sample_index(seed, _STATE_SALT, len(INJECTED_STATES))]


def removable_dependency_for_seed(seed: int) -> str:
    """The base entry a side may drop, e.g. `zlib 0.1.0`."""
    return f"{_REMOVABLE_PACKAGE} {base_version_for_seed(seed)}"


# --- the intent (#191), registered in `tasks.registry` (ADR-0029) ---------------
#
# Its acceptable sets are pinned against `check` by replay
# (`tests/test_lockfile_intent.py`).

STATE_VARIANT = {
    "additions_only": "take_upstream",
    "upstream_removed": "take_upstream",
    "local_removed": "keep_local",
}
"""Which resolution each injected state is labelled with; what `INTENT`'s rules decide."""


def sync_conflicts_in_a_shared_file(state: StateFingerprint) -> bool:
    """The family's situation: both sides committed, and a merge would conflict.

    `StateFingerprint.sync_would_conflict` is the shared test; every other family that
    syncs commits refuses it (#191).
    """
    return state.sync_would_conflict


VARIANTS = [
    ResolutionVariant(
        id="take_upstream",
        decided_by=lambda s: sync_conflicts_in_a_shared_file(s) and not s.local_dropped_lines,
        accepted_by=lambda s: sync_conflicts_in_a_shared_file(s) and not s.local_dropped_lines,
        rationale=(
            "Upstream's file is the reference, and the local side removed nothing from it, "
            "so rebuilding from upstream's file plus the local side's additions loses nothing."
        ),
    ),
    ResolutionVariant(
        id="keep_local",
        decided_by=lambda s: (
            sync_conflicts_in_a_shared_file(s)
            and bool(s.local_dropped_lines)
            and not s.upstream_dropped_lines
        ),
        accepted_by=lambda s: sync_conflicts_in_a_shared_file(s) and not s.upstream_dropped_lines,
        rationale=(
            "The local side removed a dependency upstream still lists, so the local file is "
            "the one to rebuild from, adding upstream's new entries to it."
        ),
    ),
]

INTENT = IntentSpec(
    name="sync_through_a_conflicting_lockfile",
    fault="lockfile_conflict",
    phrasings=[
        "Bring this branch up to date with upstream. Both of us changed our dependencies.",
        "Syncing with upstream stopped on a conflict. Get it through without losing any "
        "dependency either side meant to have.",
        "Merge upstream's latest in here and leave the dependency file consistent.",
        "Upstream and I both moved our dependencies on. Catch my branch up properly.",
        "The sync conflicts. Resolve it the way this project expects.",
        "Get my fork current with upstream; our dependency changes collided.",
        "Update this branch from upstream and make sure the dependency list still makes sense.",
        "Catch up with upstream without losing what either side added, or reviving what "
        "either side removed.",
    ],
    naming_markers=["lockfile", "lock file"],
    variants=VARIANTS,
    variant_phrasings={
        "take_upstream": ["upstream's dependency list is the one to start from; I only added"],
        "keep_local": ["I dropped a dependency on purpose, and upstream still lists it"],
    },
)


# --- Tier 1 instance axes (ADR-0005) ---------------------------------------------
#
# Each side's package -- the versions follow from the pair -- plus `removal`, which
# side (if either) dropped the removable dependency. `removal` separates the two
# states `take_upstream` covers; `keep_local` has one state, so it does not vary there.
# No draw moves an edit between sides, so no draw can relabel a state.

AXES: Mapping[str, tuple[str, ...]] = {
    "local_package": _PACKAGE_NAMES[:_HALF],
    "upstream_package": _PACKAGE_NAMES[_HALF:],
    "removal": ("none", "upstream"),
}
"""The Tier 1 axes this fault draws, with the values each may take. The versions are
derived from the package pair (`_versions_for_seed`), so they are not axes of their own."""

AXES_BY_RESOLUTION: Mapping[str, tuple[str, ...]] = {
    "take_upstream": ("local_package", "upstream_package", "removal"),
    "keep_local": ("local_package", "upstream_package"),
}
"""Which axes may vary for each resolution."""


def drawn_axes(seed: int) -> dict[str, str]:
    """Every axis's drawn value at `seed`; one definition for identity and the axes."""
    state = state_for_seed(seed)
    return {
        "local_package": local_package_for_seed(seed),
        "upstream_package": upstream_package_for_seed(seed),
        "removal": state.removesuffix("_removed") if state != "additions_only" else "none",
    }


def local_package_for_seed(seed: int) -> str:
    """The package the local side adds. Deterministic, and never upstream's."""
    return _PACKAGE_NAMES[_package_indices(seed)[0]]


def upstream_package_for_seed(seed: int) -> str:
    """The package the upstream side adds. Deterministic, and never local's."""
    return _PACKAGE_NAMES[_HALF + _package_indices(seed)[1]]


def _package_indices(seed: int) -> tuple[int, int]:
    """(local, upstream) indices into each half of `_PACKAGE_NAMES`."""
    return (
        sample_index(seed, f"{_PACKAGE_SALT}:local", _HALF),
        sample_index(seed, f"{_PACKAGE_SALT}:upstream", len(_PACKAGE_NAMES) - _HALF),
    )


def _versions_for_seed(seed: int) -> tuple[str, str]:
    """(local version, upstream version), guaranteed distinct.

    Derived from the drawn package pair rather than drawn on their own (ADR-0029): an
    independent version draw multiplied the instance space until no seed set ever
    repeated an instance, and the cost curve is read from repeats.
    """
    local, upstream = _package_indices(seed)
    offset = 1 + upstream % (len(VERSIONS) - 1)
    return VERSIONS[local], VERSIONS[(local + offset) % len(VERSIONS)]


def base_version_for_seed(seed: int) -> str:
    """The version the injected file starts at, before either side changes it.

    Derived from the drawn upstream package, for the reason `_versions_for_seed` gives.
    """
    return _BASE_VERSIONS[_package_indices(seed)[1] % len(_BASE_VERSIONS)]


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
        + f'    "{removable_dependency_for_seed(seed)}",\n'
        + "]\n"
    )


def _edited_lock_text(seed: int, side: str) -> str:
    """The file after one side edits it: new version, one new entry at the top.

    Both sides rewrite the version line and insert immediately after
    `packages = [`, so the two edits occupy the same region and a merge of them
    conflicts. Which side is built is decided by the caller, not by the seed, so
    the same seed still yields byte-identical content for each commit. The side the
    state names as the remover leaves the removable entry out; the other keeps it.
    """
    local_version, upstream_version = _versions_for_seed(seed)
    if side == "local":
        version = local_version
        entry = local_dependency_for_seed(seed)
    else:
        version = upstream_version
        entry = upstream_dependency_for_seed(seed)
    removes = state_for_seed(seed) == f"{side}_removed"
    kept = "" if removes else f'    "{removable_dependency_for_seed(seed)}",\n'
    return (
        _HEADER
        + f"version = {version}\n"
        + "packages = [\n"
        + f'    "{entry}",\n'
        + f'    "{_BASE_PACKAGE} {base_version_for_seed(seed)}",\n'
        + kept
        + "]\n"
    )


class LockfileConflictFault(FaultSpec):
    name = "lockfile_conflict"
    # The lock-shaped file both sides edit and a correct regeneration rewrites.
    change_surface = (LOCK_PATH,)
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
        sandbox.recorded["local-tip"] = local_tip

        # Upstream's edit, built from the same ancestor and published.
        run_git(("reset", "--hard", common), cwd=work)
        (work / LOCK_PATH).write_text(_edited_lock_text(seed, "upstream"), encoding="utf-8")
        run_git(("add", "-A"), cwd=work)
        run_git(("commit", "-q", "-m", "feat: upstream adds a dependency"), cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # Back to the local branch, and record the ground truth the checker uses.
        run_git(("reset", "--hard", local_tip), cwd=work)
        sandbox.recorded["local-dependency"] = local_dependency_for_seed(seed)
        sandbox.recorded["upstream-dependency"] = upstream_dependency_for_seed(seed)
        if state_for_seed(seed) != "additions_only":
            sandbox.recorded["removed-dependency"] = removable_dependency_for_seed(seed)

        # Leave the remote-tracking ref current so observe() can read it without
        # fetching (observe must not mutate the environment).
        run_git(("fetch", "-q", "upstream"), cwd=work)

    def task_text(self, seed: int) -> str:
        return INTENT.task_text(seed)

    def state_for_seed(self, seed: int) -> str:
        return state_for_seed(seed)

    def variant_for_seed(self, seed: int) -> str:
        """The resolution `state_for_seed` makes correct at `seed` (`STATE_VARIANT`)."""
        return STATE_VARIANT[state_for_seed(seed)]

    def instance_for_seed(self, seed: int) -> str:
        """The instance identity: resolution plus every drawn axis value, in axis order."""
        resolution = self.variant_for_seed(seed)
        drawn = self.drawn_axes_for_seed(seed)
        return "/".join(
            ["lockfile_conflict", resolution, *(f"{axis}={value}" for axis, value in drawn.items())]
        )

    def axes_for_resolution(self, resolution: str) -> Mapping[str, tuple[str, ...]]:
        """The axes `resolution` may vary along, with their value pools (ADR-0005)."""
        if resolution not in AXES_BY_RESOLUTION:
            raise KeyError(f"lockfile_conflict declares no resolution {resolution!r}")
        return {name: AXES[name] for name in AXES_BY_RESOLUTION[resolution]}

    def drawn_axes_for_seed(self, seed: int) -> Mapping[str, str]:
        """The drawn value of each declared axis at `seed` (ADR-0005 decision 2)."""
        drawn = drawn_axes(seed)
        return {axis: drawn[axis] for axis in AXES_BY_RESOLUTION[self.variant_for_seed(seed)]}

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome, not the method, in five clauses.

        First, upstream's tip must be contained in the local branch. Second, no
        conflict marker may remain anywhere in the working tree, so a sync left
        half-resolved fails. Third, both added dependency entries must still be
        in the lock-shaped file: the local one and the upstream one. Fourth, a
        dependency one side removed must stay removed. Fifth, the file must have
        exactly one `version` line.

        The third clause is the point. Hand-deleting the markers while keeping
        one side "succeeds" as a command and satisfies the first two clauses, but
        it silently drops a dependency; a real regeneration would keep both. The
        fourth is its mirror: rebuilding from the side that still lists a removed
        dependency resurrects it. The fifth refuses a union merge, which keeps both
        sides' lines and so both sides' versions.
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

        local_entry = sandbox.recorded["local-dependency"]
        upstream_entry = sandbox.recorded["upstream-dependency"]
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

        removed = sandbox.recorded.get("removed-dependency")
        if removed is not None and removed in text:
            return GroundTruth(
                ok=False,
                detail=f"a dependency one side removed is back in {LOCK_PATH}: {removed}",
            )
        versions = [line for line in text.splitlines() if line.startswith("version = ")]
        if len(versions) != 1:
            return GroundTruth(
                ok=False,
                detail=f"{LOCK_PATH} has {len(versions)} version lines, not one",
            )

        return GroundTruth(
            ok=True,
            detail=(
                "upstream tip is contained, no conflict markers remain, both sides' "
                "additions are present and nothing removed came back"
            ),
        )


SPEC = LockfileConflictFault()
