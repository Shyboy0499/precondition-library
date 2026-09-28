"""Fault: local branch and upstream have diverged, both with unique commits.

Three resolutions, and the request text cannot tell them apart. Which is correct
depends on what the local-only commits actually contain:

  discard  the local commits are empty of file changes, so resetting to upstream
           loses no work.
  rebase   the local commits change files upstream did not, so replaying them on
           top of upstream is conflict-free and yields a linear history.
  merge    both sides changed the same file, so rewriting local history would
           discard a resolution someone already made.

The discriminators are all observable (`upstream_behind`,
`local_touched_files`, `upstream_touched_files`), which matters: arm 3 decides by
running probes, so a resolution that needed a *judgement* could not be decided by
either mechanism and the comparison would be between two blind dispatchers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ...sandbox import Sandbox, git_out, record_base, run_git, tip_contained
from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant, draw_index, sample_index
from ..spec import FaultSpec, GroundTruth

# The three live states, and the resolution each is the real-world equivalent of.
# The order is part of the seed-to-state mapping, so appending to it would change
# which state an existing seed injects; add states deliberately.
INJECTED_STATES = ("empty_local_commits", "disjoint_files", "overlapping_files")
STATE_VARIANT = {
    "empty_local_commits": "discard",
    "disjoint_files": "rebase",
    "overlapping_files": "merge",
}
# One salt for the whole codebase's "deterministic choice from a seed".
_INJECTION_SALT = "diverged:inject"

# --- Tier 1 instance axes (ADR-0005) -----------------------------------------
#
# Each state shape is parameterised along declared axes and the seed draws one
# value per axis, so a new seed can be a genuinely new environment within a
# resolution rather than the same shape with a different commit SHA (#86). Which
# axes are safe is a property of the resolution's `decided_by` predicate:
#
#   content   the file bodies each side writes -- the upstream insertion into
#             `app.py`, the local insertion into `app.py` (the `merge` side) and
#             the local notes appended to `docs/readme.md`. None of the drawn
#             bodies can move the local edit into a file upstream also touched or
#             remove the overlap, which are the relabellings ADR-0005 forbids.
#   commits   the number of local-only commits (1-3) and their subjects. The
#             count is part of the environment; the subjects ride on the drawn
#             content, so a subject never varies without a body varying. A
#             subject-only change is cosmetic and must not create an instance.
#   hunk      where each side's insertion sits in `app.py`. The decision rule is
#             *file* overlap, not hunk overlap, so hunk position is free; the
#             local anchor is derived to a different one of the three anchors so
#             the two hunks never overlap and a `merge` instance stays
#             conflict-free.
#
# Not drawn, deliberately: file names and the which-file-each-side-edits mapping
# (Tier 2 -- they need probe/body parameter binding and are out of scope here),
# file counts (Tier 3 -- a count can flip `rebase` into `merge`), and commit
# SHAs/dates (cosmetic: #86 and ADR-0005 both refuse a SHA-only difference as a
# new environment).
_ANCHORS = ("top", "after_greet", "bottom")
"""Where a side inserts its text into `app.py`: before line 1, after line 2, or at the end."""

_LOCAL_COMMIT_RANGE = (1, 3)
"""The local-only commit count is drawn from 1..3 inclusive."""


@dataclass(frozen=True)
class _Flavour:
    """One drawn `content` value: the bodies both sides write, and the subjects.

    `local_notes` and `subjects` each carry three entries, one per possible local
    commit, so a count of *k* uses the first *k* of each.
    """

    upstream: str
    local_app: str
    local_notes: tuple[str, str, str]
    subjects: tuple[str, str, str]


_FLAVOURS: tuple[_Flavour, ...] = (
    _Flavour(
        upstream="import os\n\n",
        local_app='\n\ndef farewell(name):\n    return f"bye {name}"\n',
        local_notes=("\nLocal note.\n", "\nMore notes.\n", "\nFinal note.\n"),
        subjects=("docs: local note", "docs: extend the note", "docs: finish the note"),
    ),
    _Flavour(
        upstream="import sys\n\n",
        local_app='\n\ndef part(name):\n    return f"goodbye {name}"\n',
        local_notes=("\nLocal memo.\n", "\nExtra memo.\n", "\nClosing memo.\n"),
        subjects=("docs: local memo", "docs: add to the memo", "docs: close the memo"),
    ),
    _Flavour(
        upstream="import json\n\n",
        local_app='\n\ndef salutation(name):\n    return f"so long {name}"\n',
        local_notes=("\nLocal aside.\n", "\nSecond aside.\n", "\nLast aside.\n"),
        subjects=("docs: local aside", "docs: another aside", "docs: last aside"),
    ),
    _Flavour(
        upstream="import re\n\n",
        local_app='\n\ndef leave(name):\n    return f"take care, {name}"\n',
        local_notes=("\nLocal remark.\n", "\nFurther remark.\n", "\nFinal remark.\n"),
        subjects=("docs: local remark", "docs: further remark", "docs: final remark"),
    ),
)

AXES: Mapping[str, tuple[str, ...]] = {
    "content": tuple(str(index) for index in range(len(_FLAVOURS))),
    "local_commit_count": tuple(
        str(count) for count in range(_LOCAL_COMMIT_RANGE[0], _LOCAL_COMMIT_RANGE[1] + 1)
    ),
    "hunk": _ANCHORS,
}
"""The Tier 1 axes this fault draws, with the values each may take.

Stated once here so `instance_diversity` and the tests can read the declaration
rather than reconstruct it from the injector's behaviour.
"""

AXES_BY_RESOLUTION: Mapping[str, tuple[str, ...]] = {
    "discard": ("content", "local_commit_count", "hunk"),
    "rebase": ("content", "local_commit_count", "hunk"),
    "merge": ("content", "local_commit_count", "hunk"),
}
"""Which axes may vary for each resolution, and why the others may not.

Every drawn body keeps its resolution's predicate invariant: `discard`'s local
commits stay empty, `rebase`'s local edit stays in a file upstream left alone,
and `merge`'s local edit keeps a file upstream also touched. ADR-0005 calls the
unsafe moves relabellings, not variation, and `build_sandbox` refuses one.
"""


@dataclass(frozen=True)
class Draw:
    """Everything one seed's instance draw decides, for `inject` and identity."""

    state: str
    resolution: str
    content: int
    local_commits: int
    hunk: str

    @property
    def identity(self) -> str:
        """The stable instance identity: resolution plus every drawn axis value."""
        return (
            f"diverged/{self.resolution}"
            f"/content={self.content}"
            f"/commits={self.local_commits}"
            f"/hunk={self.hunk}"
        )

    @property
    def axes(self) -> Mapping[str, str]:
        """The drawn value for each declared axis, by axis name."""
        return {
            "content": str(self.content),
            "local_commit_count": str(self.local_commits),
            "hunk": self.hunk,
        }


def state_for_seed(seed: int) -> str:
    """Which of the three live states this seed injects. Deterministic."""
    return INJECTED_STATES[sample_index(seed, _INJECTION_SALT, len(INJECTED_STATES))]


def draw_for_seed(seed: int) -> Draw:
    """The Tier 1 draw for `seed`: state, content, local commit count and hunk.

    One definition shared by `inject`, `instance_for_seed` and the tests, so the
    built environment and the recorded identity cannot disagree. Each axis goes
    through `draw_index` with its own salt, so the axes are independent of each
    other and of the state selection.
    """
    state = state_for_seed(seed)
    low, high = _LOCAL_COMMIT_RANGE
    return Draw(
        state=state,
        resolution=STATE_VARIANT[state],
        content=draw_index(seed, "diverged", "content", len(_FLAVOURS)),
        local_commits=low + draw_index(seed, "diverged", "local_commit_count", high - low + 1),
        hunk=_ANCHORS[draw_index(seed, "diverged", "hunk", len(_ANCHORS))],
    )


def _commit(work: Path, message: str, *, allow_empty: bool = False) -> None:
    command = ["commit", "-q", "-m", message]
    if allow_empty:
        command.append("--allow-empty")
    run_git(command, cwd=work)


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _insert(path: Path, text: str, anchor: str) -> None:
    """Insert `text` into `path` at one of the three declared anchors."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if anchor == "top":
        index = 0
    elif anchor == "after_greet":
        index = min(2, len(lines))
    else:
        index = len(lines)
    lines.insert(index, text)
    path.write_text("".join(lines), encoding="utf-8")


def _is_empty_of_changes(state: StateFingerprint) -> bool:
    """Local commits exist but change no files."""
    return state.has_local_only_commits and not state.local_touched_files


def _overlaps_upstream(state: StateFingerprint) -> bool:
    """Both sides changed at least one of the same files."""
    return state.has_local_only_commits and bool(state.conflicting_files)


def _is_disjoint_from_upstream(state: StateFingerprint) -> bool:
    """Local commits change files, none of which upstream also changed."""
    return (
        state.has_local_only_commits
        and bool(state.local_touched_files)
        and not state.conflicting_files
    )


VARIANTS = [
    ResolutionVariant(
        id="discard",
        decided_by=_is_empty_of_changes,
        rationale="Local commits change no files, so resetting to upstream loses nothing.",
    ),
    ResolutionVariant(
        id="merge",
        decided_by=_overlaps_upstream,
        rationale=(
            "Both sides changed the same file, so replaying local commits would "
            "discard a resolution and risk re-conflicting; merge keeps both."
        ),
    ),
    ResolutionVariant(
        id="rebase",
        decided_by=_is_disjoint_from_upstream,
        rationale=(
            "Local commits touch only files upstream left alone, so replaying them "
            "on top of upstream is conflict-free and keeps history linear."
        ),
    ),
]

INTENT = IntentSpec(
    name="sync_fork_with_upstream",
    fault="diverged",
    phrasings=[
        "Get this fork back in sync with upstream without losing my commits.",
        "Upstream has moved on and so have I. Sort the branch out.",
        "This branch and upstream have both changed. Bring it back into line.",
        "My fork and upstream have both moved. Make them consistent.",
        "Upstream moved ahead of me. Get me back in line with it.",
        "Reconcile this branch with upstream.",
        "I have local work and upstream has new commits. Untangle it.",
        "Something is out of step between my branch and upstream. Fix it.",
    ],
    naming_markers=["diverged", "divergence"],
    variants=VARIANTS,
    # Rebase and merge share a symptom phrase ("both changed files") that is true
    # of both situations. That shared phrase is what keeps the text a *partial*
    # signal -- a text-only dispatcher cannot tell the two apart from it -- rather
    # than fully determining the resolution (see bench/textcontrol.py).
    variant_phrasings={
        "discard": ["my local commits change no files"],
        "rebase": [
            "my edits are in files upstream left alone",
            "my branch and upstream both changed files",
        ],
        "merge": [
            "both sides touched the same files",
            "my branch and upstream both changed files",
        ],
    },
)


class DivergedFault(FaultSpec):
    name = "diverged"
    description = "Local branch and upstream both have commits the other lacks"
    # The two files the local and upstream sides both edit; a merge or a reset
    # resolves the fault entirely inside them.
    change_surface = ("app.py", "docs/readme.md")

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Publish the upstream commits, then replay the local-only commits on top.

        Upstream gets one commit in every variant, so the state is genuinely
        diverged. The local side is then built from the recorded base commit,
        which is what makes the local branch ahead of upstream rather than an
        ancestor of it.

        The shape is built from `draw_for_seed(seed)`: the content both sides write,
        the local commit count, and the anchor each side inserts at. The local
        anchor is derived to a *different* anchor from upstream's, so the two hunks
        never overlap and `merge` keeps the conflict-free result its gold body
        needs -- the rule is file overlap, not hunk overlap, so hunk position is
        free but not unrestricted.
        """
        draw = draw_for_seed(seed)
        flavour = _FLAVOURS[draw.content]
        work = sandbox.work
        base = record_base(sandbox, fault="diverged")

        # Upstream's unique commits, published to the bare repo.
        app = work / "app.py"
        _insert(app, flavour.upstream, draw.hunk)
        run_git(("add", "-A"), cwd=work)
        _commit(work, "feat: upstream stamps the entry point")
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # Local-only commits, replayed from the base so the two sides diverge.
        run_git(("reset", "--hard", base), cwd=work)
        local_anchor = _ANCHORS[(_ANCHORS.index(draw.hunk) + 1) % len(_ANCHORS)]
        if draw.state == "empty_local_commits":
            for index in range(draw.local_commits):
                _commit(work, flavour.subjects[index], allow_empty=True)
        elif draw.state == "disjoint_files":
            for index in range(draw.local_commits):
                _append(work / "docs/readme.md", flavour.local_notes[index])
                run_git(("add", "-A"), cwd=work)
                _commit(work, flavour.subjects[index])
        else:
            for index in range(draw.local_commits):
                if index == 0:
                    _insert(app, flavour.local_app, local_anchor)
                _append(work / "docs/readme.md", flavour.local_notes[index])
                run_git(("add", "-A"), cwd=work)
                _commit(work, flavour.subjects[index])

        local_tip = git_out("rev-parse", "HEAD", cwd=work)
        sandbox.recorded["local-tip"] = local_tip
        # Leave the remote-tracking ref current so observe() can read it without
        # fetching (observe must not mutate the environment).
        run_git(("fetch", "-q", "upstream"), cwd=work)

    def task_text(self, seed: int) -> str:
        """Delegate to the intent so there is one source of truth for phrasing."""
        return INTENT.task_text(seed)

    def variant_for_seed(self, seed: int) -> str:
        """The resolution `state_for_seed` makes correct at `seed`.

        `STATE_VARIANT` is the module's declared state-to-resolution map, so
        admission's same-intent negative class reads the same mapping `inject`
        uses rather than re-deriving it; the two cannot disagree.
        """
        return STATE_VARIANT[state_for_seed(seed)]

    def instance_for_seed(self, seed: int) -> str:
        """The instance identity this seed builds, from the same draw `inject` uses.

        Resolution plus every drawn Tier 1 axis value (ADR-0005 decision 4), so
        `bench.splits` can key independence on the environment rather than on the
        resolution and a genuine repeat of one instance is the only replay.
        """
        return draw_for_seed(seed).identity

    def axes_for_resolution(self, resolution: str) -> Mapping[str, tuple[str, ...]]:
        """The axes `resolution` may vary along, with their value pools.

        The declaration ADR-0005 decision 2 requires: an axis is listed only when
        the resolution's `decided_by` predicate is invariant under it. Raises for a
        resolution this fault does not declare, so a typo cannot read as "no axes".
        """
        if resolution not in AXES_BY_RESOLUTION:
            raise KeyError(f"diverged declares no resolution {resolution!r}")
        return {name: AXES[name] for name in AXES_BY_RESOLUTION[resolution]}

    def drawn_axes_for_seed(self, seed: int) -> Mapping[str, str]:
        """The drawn value of each declared axis at `seed` (ADR-0005 decision 2)."""
        return draw_for_seed(seed).axes

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome, not the method: upstream absorbed, local work intact.

        Two clauses. First, upstream's tip must be contained in the local branch.
        Second, the file changes the local-only commits made must still be present,
        checked by reverting them from the current tree (`git apply --reverse
        --check`) -- a change that cannot be reverted from HEAD is a change that
        was destroyed. The recorded pre-injection commits live under
        `refs/sandbox/`, which no ordinary branch rewrite removes.

        The second clause is the one that matters: `git reset --hard upstream/main`
        on the overlapping state satisfies the first clause while discarding the
        user's work, and this checker must call that not-ok.
        """
        work = sandbox.work
        upstream_tip = git_out("rev-parse", "refs/heads/main", cwd=sandbox.upstream)
        if not tip_contained(work, upstream_tip):
            return GroundTruth(
                ok=False,
                detail=f"upstream tip {upstream_tip[:12]} is not contained in the local branch",
            )

        # From the harness, not the clone: a base ref in the working repository is a
        # diff against the injected change (issue #103).
        base = sandbox.recorded["base"]
        local_tip = sandbox.recorded["local-tip"]
        local_patch = run_git(("diff", base, local_tip), cwd=work).stdout
        if local_patch.strip():
            reverts = run_git(
                ("apply", "--reverse", "--check", "-"), cwd=work, check=False, stdin=local_patch
            )
            if reverts.returncode != 0:
                return GroundTruth(
                    ok=False,
                    detail="local-only file changes are no longer in the tree (discarded)",
                )
        return GroundTruth(
            ok=True,
            detail="upstream tip is contained in the local branch and local-only changes survive",
        )


SPEC = DivergedFault()
