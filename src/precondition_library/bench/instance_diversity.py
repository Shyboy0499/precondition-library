"""How many independent environments the injectors actually produce.

Issue #86's measured finding, and the reason this module exists: the injectors
select among a small number of hand-authored state shapes, and the seed chooses
*which shape* rather than varying the shape's content. Two seeds that select the
same resolution therefore build the same environment, so the mismatch
comparison's unit of analysis -- the environment -- is fixed by the number of
shapes rather than by the number of seeds. This module measures that directly,
against real sandboxes built by `tasks.faults.build_sandbox` (never a mock),
over the seeds the pre-registration actually uses (`bench/splits.py`).

For each fault it groups the seeds by the resolution the injector makes correct
and reports, per group:

  * how many seeds select it (`seeds`);
  * how many **distinct environments** those seeds build (`instances`) -- the
    achieved instance count issue #86 asks the report to carry;
  * how many distinct environments remain when commit SHAs are also compared
    (`sha_instances`), so "identical" can be told from "identical except SHAs";
  * which of the axes #86 names vary inside the group and which are fixed.

**What "distinct environment" means here, stated so it can be checked.** Two
sandboxes are compared by `instance_signature`, a canonical text of the axes
below -- file *bodies* (sha256 of every working-tree file except `.git`), the
upstream tree's paths and blob ids, file names, file counts, commit counts,
conflict positions, submodule paths, branch names and branch tracking. Ref names
and object ids are deliberately **not** in the signature: issue #86's point is
that a difference in commit SHAs alone is not
a new environment, so a signature that changed only when a SHA did would let
cosmetic variation pass as diversity. `environment_manifest` adds every ref and
object id, and `sha_instances` counts by it, so the two comparisons can be
reported together: for the measurable faults today they agree at 1, which is the
statement that same-resolution seeds are byte-identical *including* their commit
SHAs.

**The axes are descriptive, not part of the digest.** `environment_axes` records
the axes issue #86 names -- file names, file counts, commit counts, conflict
positions, submodule paths, branch names -- plus a `file bodies` sha256 axis and
a `branch tracking` axis, so a reader can see *what* is fixed without
re-deriving it. They are reported beside the count rather than hashed separately,
because "the manifests differ" and "the branch name differs" are different
claims. `file bodies` is the one axis added to #86's list that is not structural,
and it is not redundant: `lockfile_conflict` varies its package names and
versions inside one file, which changes the environment while leaving every
structural axis #86 names fixed -- without this axis the table would say "nothing
varies" about a fault whose content does.

**Read-only with respect to the injectors.** This module builds and destroys
sandboxes and changes nothing about how a fault is injected: #86 is scoped, not
implemented. Run it with

    .venv/bin/python -m precondition_library.bench.instance_diversity

and it prints the table the ADR-0005 context is measured from.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..sandbox import Sandbox, run_git
from ..tasks.faults import FAULTS, build_sandbox
from .splits import EVAL_SEEDS, SMOKE_SEEDS, TUNE_SEEDS

PLAN_SEEDS: tuple[int, ...] = (*SMOKE_SEEDS, *TUNE_SEEDS, *EVAL_SEEDS)
"""Every seed the pre-registration uses: the smoke, tune and eval sets in order.

Issue #86 asks for the seed range the plans actually use, not seeds 0-3. These
are the three sets `bench/splits.py` freezes, so the measurement is over the
population the reported numbers would come from.
"""


def _refs(repo: Path) -> tuple[str, ...]:
    """Every ref and the object it points at, sorted, for one repository."""
    out = run_git(("for-each-ref", "--format=%(refname) %(objectname)"), cwd=repo).stdout
    return tuple(sorted(line for line in out.splitlines() if line))


def _status(repo: Path) -> tuple[str, ...]:
    """Porcelain status including untracked files, sorted."""
    out = run_git(("status", "--porcelain", "--untracked-files=all"), cwd=repo).stdout
    return tuple(sorted(line for line in out.splitlines() if line))


def work_files(box: Sandbox) -> tuple[str, ...]:
    """Every file path in the working tree, relative, excluding git metadata.

    The exclusion is `.git` by path *component*, which drops both the clone's own
    metadata directory and the submodule's `.git` gitdir pointer. That pointer
    holds an absolute path containing the sandbox root, and the root contains the
    seed -- so including it would make every seed "different" for a reason that
    is not part of the environment the graded code sees.
    """
    found: list[str] = []
    for path in sorted(box.work.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(box.work)
        if ".git" in relative.parts:
            continue
        found.append(str(relative))
    return tuple(found)


def _file_bodies(box: Sandbox) -> tuple[str, ...]:
    """`(path, sha256 of bytes)` for every working-tree file, excluding `.git`."""
    return tuple(
        f"{relative} {hashlib.sha256((box.work / relative).read_bytes()).hexdigest()}"
        for relative in work_files(box)
    )


def _merge_base(box: Sandbox) -> str:
    """The merge base of the local branch and the clone's `upstream/main`, or ""."""
    result = run_git(("merge-base", "HEAD", "upstream/main"), cwd=box.work, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _conflict_positions(box: Sandbox) -> tuple[str, ...]:
    """Where the local-only and upstream-only hunks sit, as `side:@@ ... @@` lines.

    The axis issue #86 calls "conflict positions": the line ranges two diverged
    sides edit. Computed against the merge base so both sides' hunks are visible,
    with `--unified=0` so the header names the exact region a sync would merge.
    """
    base = _merge_base(box)
    if not base:
        return ()
    positions: list[str] = []
    for side, rev in (("local", "HEAD"), ("upstream", "upstream/main")):
        out = run_git(("diff", "--unified=0", base, rev), cwd=box.work, check=False).stdout
        positions += [f"{side}:{line}" for line in out.splitlines() if line.startswith("@@")]
    return tuple(positions)


def _submodule_paths(box: Sandbox) -> tuple[str, ...]:
    """The submodule paths the environment declares: gitlinks plus `.gitmodules`."""
    found: set[str] = set()
    tree = run_git(("ls-tree", "-r", "HEAD"), cwd=box.work, check=False).stdout
    for line in tree.splitlines():
        if line.startswith("160000 "):
            found.add(line.split("\t", 1)[-1])
    declared = run_git(
        ("config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"),
        cwd=box.work,
        check=False,
    ).stdout
    for line in declared.splitlines():
        if line.split():
            found.add(line.split()[-1])
    return tuple(sorted(found))


def _branch_names(box: Sandbox) -> tuple[str, ...]:
    """The local branch and every branch name the upstream repo actually has.

    Upstream's own `refs/heads` rather than the clone's remote-tracking refs: a
    rename creates no commit and the clone keeps a stale remote ref, so upstream's
    branch list is the only place the new name is visible.
    """
    local = run_git(("rev-parse", "--abbrev-ref", "HEAD"), cwd=box.work, check=False).stdout.strip()
    upstream = run_git(
        ("for-each-ref", "--format=%(refname:short)", "refs/heads"), cwd=box.upstream, check=False
    ).stdout
    return tuple(["work:" + local, *[f"upstream:{name}" for name in sorted(upstream.split())]])


def _branch_tracking(box: Sandbox) -> tuple[str, ...]:
    """The clone's branch wiring: the symbolic HEAD and each branch's upstream ref.

    Part of the environment in its own right -- `branch_renamed` is entirely about
    a stale `branch.<name>.merge` -- and not visible in any other axis, because
    the config that holds it lives under `.git`.
    """
    head = run_git(("symbolic-ref", "-q", "HEAD"), cwd=box.work, check=False).stdout.strip()
    out = run_git(
        ("config", "--get-regexp", r"^branch\..*\.(remote|merge)$"), cwd=box.work, check=False
    ).stdout
    return tuple([f"HEAD {head}", *[line for line in sorted(out.splitlines()) if line]])


def _upstream_tree(box: Sandbox) -> tuple[str, ...]:
    """`git ls-tree -r HEAD` in the upstream repo: its paths and blob object ids.

    The upstream side's content in its own right. The clone's working tree does
    not necessarily contain it -- `diverged` resets the clone to the base before
    the local commits, so upstream's edit exists only here -- and a blob object id
    encodes content, so this axis is content rather than commit-SHA cosmetics.
    """
    out = run_git(("ls-tree", "-r", "HEAD"), cwd=box.upstream, check=False).stdout
    return tuple(sorted(line for line in out.splitlines() if line))


def environment_axes(box: Sandbox) -> dict[str, tuple[str, ...]]:
    """The axes issue #86 names, plus content and tracking, each as strings.

    These are the quantities #86 says must vary *within* a resolution. They are
    measured independently of each other, so a report can say which axis is fixed
    rather than only that the whole environment is.
    """
    files = work_files(box)
    commits = run_git(("rev-list", "--count", "HEAD"), cwd=box.work, check=False).stdout.strip()
    upstream_commits = run_git(
        ("rev-list", "--count", "--all"), cwd=box.upstream, check=False
    ).stdout.strip()
    return {
        "file bodies": _file_bodies(box),
        "file names": files,
        "file count": (str(len(files)),),
        "commit count": (commits,),
        "upstream commit count": (upstream_commits,),
        "upstream tree": _upstream_tree(box),
        "conflict positions": _conflict_positions(box),
        "submodule paths": _submodule_paths(box),
        "branch names": _branch_names(box),
        "branch tracking": _branch_tracking(box),
    }


AXES: tuple[str, ...] = (
    "file bodies",
    "file names",
    "file count",
    "commit count",
    "upstream commit count",
    "upstream tree",
    "conflict positions",
    "submodule paths",
    "branch names",
    "branch tracking",
)
"""The axis names, in report order, so a reader can tell a non-report from an empty axis."""


def instance_signature(box: Sandbox) -> str:
    """A canonical content signature: the axes, without refs or object ids.

    This is what "a different environment" means for issue #86's property, and
    excluding refs is the point: a commit-message change moves every SHA without
    changing the environment the agent has to handle, so a signature that included
    SHAs would call cosmetic variation diversity.
    """
    axes = environment_axes(box)
    return "\n".join(f"{axis} {value!r}" for axis, value in axes.items())


def environment_manifest(box: Sandbox) -> str:
    """`instance_signature` plus every ref and object id in the clone and upstream.

    The stronger comparison: two sandboxes equal here are byte-identical including
    their commit SHAs, which is what same-resolution seeds are today.
    """
    lines = [instance_signature(box)]
    lines += [f"work-ref {ref}" for ref in _refs(box.work)]
    lines += [f"upstream-ref {ref}" for ref in _refs(box.upstream)]
    lines += [f"status {line}" for line in _status(box.work)]
    origin = box.root / "submodule-origin"
    if origin.is_dir() and (origin / ".git").exists():
        lines += [f"origin-ref {ref}" for ref in _refs(origin)]
    return "\n".join(lines)


def environment_digest(box: Sandbox) -> str:
    """The sha256 of `instance_signature`: the environment's content identity."""
    return hashlib.sha256(instance_signature(box).encode("utf-8")).hexdigest()


def manifest_digest(box: Sandbox) -> str:
    """The sha256 of `environment_manifest`, which also covers commit SHAs."""
    return hashlib.sha256(environment_manifest(box).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InstanceGroup:
    """One (fault, resolution) cell: how many seeds select it, and how many differ."""

    fault: str
    resolution: str | None
    seeds: tuple[int, ...]
    instances: int
    """Distinct content environments, by `instance_signature`."""
    sha_instances: int
    """Distinct environments once refs and object ids are compared too."""
    varying_axes: tuple[str, ...]
    fixed_axes: tuple[str, ...]

    @property
    def identical(self) -> bool:
        """True when every seed in the group built the same content environment."""
        return self.instances == 1


def measure(seeds: tuple[int, ...], faults: tuple[str, ...]) -> list[InstanceGroup]:
    """Build every `(fault, seed)` sandbox and group the results by resolution.

    Real sandboxes, destroyed as each is read; no environment is reused between
    groups, and the resolution comes from the injector's own `variant_for_seed`,
    so a group's label cannot disagree with what was injected.
    """
    groups: list[InstanceGroup] = []
    for fault in faults:
        spec = FAULTS[fault]
        by_resolution: dict[str | None, list[tuple[int, str, str, dict[str, tuple[str, ...]]]]] = (
            defaultdict(list)
        )
        for seed in seeds:
            box = build_sandbox(seed, [fault])
            try:
                by_resolution[spec.variant_for_seed(seed)].append(
                    (seed, environment_digest(box), manifest_digest(box), environment_axes(box))
                )
            finally:
                box.destroy()
        for resolution, rows in sorted(by_resolution.items(), key=lambda item: str(item[0])):
            varying = tuple(
                axis for axis in AXES if len({axes[axis] for _, _, _, axes in rows}) > 1
            )
            groups.append(
                InstanceGroup(
                    fault=fault,
                    resolution=resolution,
                    seeds=tuple(seed for seed, _, _, _ in rows),
                    instances=len({digest for _, digest, _, _ in rows}),
                    sha_instances=len({digest for _, _, digest, _ in rows}),
                    varying_axes=varying,
                    fixed_axes=tuple(axis for axis in AXES if axis not in varying),
                )
            )
    return groups


def report(groups: list[InstanceGroup]) -> str:
    """The measured table, as text, with its provenance line."""
    lines = [
        "instance diversity over the pre-registration's seeds "
        f"({len(PLAN_SEEDS)} seeds: smoke, tune and eval)",
        "",
        f"{'fault':18s} {'resolution':9s} {'seeds':>5s} {'instances':>9s} "
        f"{'with SHAs':>9s}  varying axes / fixed axes",
    ]
    for group in groups:
        label = group.resolution if group.resolution is not None else "(none)"
        varying = ", ".join(group.varying_axes) or "none"
        fixed = ", ".join(group.fixed_axes) or "none"
        lines.append(
            f"{group.fault:18s} {label:9s} {len(group.seeds):5d} {group.instances:9d} "
            f"{group.sha_instances:9d}  varying: {varying} | fixed: {fixed}"
        )
    return "\n".join(lines)


def main() -> None:
    """Print the measured diversity table for every fault and resolution."""
    print(report(measure(PLAN_SEEDS, tuple(sorted(FAULTS)))))


if __name__ == "__main__":
    main()
