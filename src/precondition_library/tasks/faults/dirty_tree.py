"""Fault: the worktree has uncommitted work while upstream has moved.

The archetype of the whole project. The right recovery depends on state —
whether the local edit is worth keeping, whether upstream touched the same
region, whether the edit should be stashed, rebased, or committed first — so
the solution is not a fixed command sequence and re-deriving it costs a full
LLM pass. This is a fault where compiling pays.

Upstream has one commit the local branch lacks, and the working tree holds
uncommitted work. Each seed selects one of three states (#189), chosen so that
different fixed resolutions are right in different states, by this checker:

* ``disjoint`` -- a tracked edit to a file upstream left alone, plus an untracked
  file at a path upstream does not have;
* ``same_file`` -- a tracked edit to the file upstream changed, in a separate hunk;
* ``collision`` -- the disjoint edit, plus an untracked file **at a path upstream's
  new commit adds**, so a sync cannot bring upstream's file in without displacing it.

Stash-sync-pop and commit-then-merge both keep the work on the first two and both
fail on the third: the pop cannot restore an untracked file over a tracked one, and
the merge meets an add/add conflict. Only moving the colliding file aside first
keeps both.

`check` grades the outcome rather than the method: upstream's tip must be contained
in the local branch *and* the recorded uncommitted work must still be in the tree.
That second clause is the point -- `git reset --hard upstream/main`, `git checkout
-- .` and `git clean -fd` each make the sync look successful while destroying the
work, and must be rejected. On a collision the untracked work may survive at
``<path>.local``, the one place it can, since both versions cannot live at one path.

The fault is measured (ADR-0027): `INTENT` is registered in `tasks.registry`, so the
request is one of its phrasings, none of which names a resolution, and
`variant_for_seed` labels every seed with the resolution its state needs. Admission's
unrelated-fault class therefore builds one dirty_tree state per resolution, as it does
for `diverged` and `submodule_moved`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ...sandbox import Sandbox, git_out, record_base, run_git, tip_contained
from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant, draw_index, sample_index
from ..spec import FaultSpec, GroundTruth

# The three live states a seed selects between, and the salt that chooses them.
# Appending a state would change which state an existing seed injects, so add
# states deliberately.
INJECTED_STATES = ("disjoint", "same_file", "collision")
_STATE_SALT = "dirty_tree:state"

# Upstream moves `app.py` at its top. The disjoint and collision states edit
# `docs/readme.md`; the same-file state appends to `app.py`, a separate hunk.
_UPSTREAM_FILE = "app.py"
_TRACKED_FILE = "docs/readme.md"
_UNTRACKED_PATH = "notes/scratch.txt"
ASIDE_SUFFIX = ".local"
"""Where a colliding untracked file may be kept: `<path>.local` (see `check`)."""


# --- Tier 1 instance axes (ADR-0005) ---------------------------------------------
#
#   content    the text each side writes: upstream's comment at the top of `app.py`,
#              the local edit (to `docs/readme.md`, or appended to `app.py` on the
#              same-file state), the untracked note, and upstream's file at the
#              collision path. No body moves the local edit between files or adds a
#              path to either side, so no draw can relabel a state.
#   untracked  whether a non-colliding untracked file accompanies the disjoint and
#              same-file states. No rule reads it -- only a *colliding* untracked
#              file decides anything -- and every resolution keeps it. The collision
#              state always has one: it is what the state is.
#
# Not drawn: file names and paths (Tier 2: they need parameter binding), file counts
# (Tier 3: a second edited file could move the same-file state's overlap), SHAs.


@dataclass(frozen=True)
class _Flavour:
    """One drawn `content` value: every text the injector writes."""

    upstream_comment: str
    local_work: str
    same_file_work: str
    untracked_note: str
    upstream_note: str


_FLAVOURS: tuple[_Flavour, ...] = (
    _Flavour(
        upstream_comment="# upstream moved on\n",
        local_work="\nLocal work in progress: keep me.\n",
        same_file_work="\n# Local work in progress in the file upstream changed: keep me.\n",
        untracked_note="scratch note, not committed yet\n",
        upstream_note="upstream's notes: this path is tracked upstream now\n",
    ),
    _Flavour(
        upstream_comment="# upstream: tidy imports\n",
        local_work="\nDraft section, still being written.\n",
        same_file_work="\n# Draft helper, still being written.\n",
        untracked_note="todo: finish the draft\n",
        upstream_note="upstream's changelog: tracked upstream now\n",
    ),
    _Flavour(
        upstream_comment="# upstream: pin the runtime\n",
        local_work="\nExperiment notes from today.\n",
        same_file_work="\n# Experiment: try a faster path.\n",
        untracked_note="experiment log\n",
        upstream_note="upstream's experiment plan: tracked upstream now\n",
    ),
    _Flavour(
        upstream_comment="# upstream: release prep\n",
        local_work="\nReview comments to address.\n",
        same_file_work="\n# Address review: rename later.\n",
        untracked_note="review checklist\n",
        upstream_note="upstream's release notes: tracked upstream now\n",
    ),
)

AXES: Mapping[str, tuple[str, ...]] = {
    "content": tuple(str(index) for index in range(len(_FLAVOURS))),
    "untracked": ("absent", "present"),
}
"""The Tier 1 axes this fault draws, with the values each may take."""

AXES_BY_RESOLUTION: Mapping[str, tuple[str, ...]] = {
    "stash": ("content", "untracked"),
    "commit": ("content", "untracked"),
    "aside": ("content",),
}
"""Which axes may vary for each resolution. `aside`'s state always has its untracked
file -- the collision is the state -- so that axis does not vary there."""

# The injected work is recorded in `Sandbox.recorded`, outside the clone, so the
# checker grades from git alone: the patch is text the working tree must still
# contain, and the untracked entry exists only when a file was injected.


def state_for_seed(seed: int) -> str:
    """Which live state this seed injects. Deterministic.

    One definition shared by `inject` and the tests, so a test cannot disagree with the
    injected environment.
    """
    return INJECTED_STATES[sample_index(seed, _STATE_SALT, len(INJECTED_STATES))]


@dataclass(frozen=True)
class Draw:
    """Everything one seed's instance draw decides, for `inject` and identity."""

    state: str
    resolution: str
    content: int
    untracked: bool

    @property
    def identity(self) -> str:
        """The stable instance identity: resolution plus every drawn axis value."""
        presence = "present" if self.untracked else "absent"
        return f"dirty_tree/{self.resolution}/content={self.content}/untracked={presence}"

    @property
    def axes(self) -> Mapping[str, str]:
        """The drawn value for each axis the resolution declares, by axis name."""
        drawn = {
            "content": str(self.content),
            "untracked": "present" if self.untracked else "absent",
        }
        return {name: drawn[name] for name in AXES_BY_RESOLUTION[self.resolution]}


def draw_for_seed(seed: int) -> Draw:
    """The Tier 1 draw for `seed`: state, content flavour, and the untracked file.

    One definition shared by `inject`, `instance_for_seed` and the tests. Each axis uses
    `draw_index` with its own salt, independent of the state selection, so which
    resolution a seed needs stays a function of the seed alone (ADR-0005).
    """
    state = state_for_seed(seed)
    untracked = state == "collision" or bool(draw_index(seed, "dirty_tree", "untracked", 2))
    return Draw(
        state=state,
        resolution=STATE_VARIANT[state],
        content=draw_index(seed, "dirty_tree", "content", len(_FLAVOURS)),
        untracked=untracked,
    )


def injects_untracked(seed: int) -> bool:
    """Whether this seed injects an untracked file alongside the tracked edit."""
    return draw_for_seed(seed).untracked


# --- the intent (#189), registered in `tasks.registry` (ADR-0027) ---------------

STATE_VARIANT = {"disjoint": "stash", "same_file": "commit", "collision": "aside"}
"""Which resolution each injected state is labelled with; what `INTENT`'s rules decide."""


def has_work_to_keep_and_upstream_ahead(state: StateFingerprint) -> bool:
    """The family's situation: uncommitted work, upstream ahead, and no local-only commits.

    Local-only commits are `diverged`'s situation, not this one; a clean tree, or one
    with nothing to bring in from upstream, needs nothing done -- the benign state.
    """
    return state.dirty_worktree and state.upstream_ahead > 0 and state.upstream_behind == 0


def _collides(state: StateFingerprint) -> bool:
    return bool(state.untracked_upstream_collisions)


def _edits_a_file_upstream_changed(state: StateFingerprint) -> bool:
    return bool(set(state.dirty_files) & set(state.upstream_touched_files))


def _syncable_in_place(state: StateFingerprint) -> bool:
    """Work to keep, and nothing untracked standing where upstream's files go."""
    return has_work_to_keep_and_upstream_ahead(state) and not _collides(state)


VARIANTS = [
    ResolutionVariant(
        id="stash",
        decided_by=lambda s: _syncable_in_place(s) and not _edits_a_file_upstream_changed(s),
        accepted_by=_syncable_in_place,
        rationale=(
            "Nothing local stands in upstream's way, so setting the work aside, "
            "fast-forwarding and putting it back keeps it exactly as it was, uncommitted."
        ),
    ),
    ResolutionVariant(
        id="commit",
        decided_by=lambda s: _syncable_in_place(s) and _edits_a_file_upstream_changed(s),
        accepted_by=_syncable_in_place,
        rationale=(
            "The work edits a file upstream also changed, so recording it first makes the "
            "three-way merge explicit and recoverable from history, not from a half-applied stash."
        ),
    ),
    ResolutionVariant(
        id="aside",
        decided_by=lambda s: has_work_to_keep_and_upstream_ahead(s) and _collides(s),
        accepted_by=has_work_to_keep_and_upstream_ahead,
        rationale=(
            "An untracked file sits where upstream now tracks one, so it has to be moved "
            "out of the way before upstream's file can come in; then both survive."
        ),
    ),
]

INTENT = IntentSpec(
    name="keep_uncommitted_work_and_sync",
    fault="dirty_tree",
    phrasings=[
        "I have changes I have not saved in git yet, and upstream has moved. Get me current "
        "without losing anything.",
        "Bring this branch up to date with upstream, but my work in progress must survive.",
        "Upstream has new work and I am mid-edit. Catch me up without throwing mine away.",
        "Update this checkout from upstream. Do not lose what I am in the middle of.",
        "My working tree has changes and the branch is behind upstream. Fix that and keep "
        "my changes.",
        "Catch this branch up with upstream while keeping my in-progress edits intact.",
        "I am in the middle of something and upstream moved on. Sort it out without losing "
        "my edits.",
        "Get the latest from upstream here, and keep every change I have not saved yet.",
    ],
    naming_markers=["dirty"],
    variants=VARIANTS,
    variant_phrasings={
        "stash": ["my edits are in files upstream did not touch"],
        "commit": ["I edited a file upstream changed as well"],
        "aside": ["upstream added a file where I have an unsaved one"],
    },
)


class DirtyTreeFault(FaultSpec):
    name = "dirty_tree"
    description = "Uncommitted local changes present while upstream has new commits"
    # The upstream commit, the uncommitted tracked edit, the untracked file a
    # `clean -fd` destroys, and where a colliding one may be moved aside.
    change_surface = (
        _UPSTREAM_FILE,
        _TRACKED_FILE,
        _UNTRACKED_PATH,
        _UNTRACKED_PATH + ASIDE_SUFFIX,
    )

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Publish one upstream commit, rewind local to base, then dirty the tree.

        The upstream commit is created first and pushed, so upstream is genuinely
        ahead. The local branch is then reset back to the recorded base, which is
        what makes it *behind* upstream rather than equal to it. The uncommitted
        work is written last, on top of that base, so it is a working-tree
        modification the user could still lose.

        Deterministic in the seed: `draw_for_seed` selects the state and the drawn
        axis values, and the pinned sandbox environment fixes the commit SHAs.
        """
        work = sandbox.work
        draw = draw_for_seed(seed)
        state, flavour = draw.state, _FLAVOURS[draw.content]
        base = record_base(sandbox, fault="dirty_tree")

        # Upstream's unique commit, published to the bare repo. On a collision it
        # also starts tracking the path the local untracked file is about to occupy.
        app = work / _UPSTREAM_FILE
        app.write_text(flavour.upstream_comment + app.read_text(encoding="utf-8"), encoding="utf-8")
        if state == "collision":
            tracked_upstream = work / _UNTRACKED_PATH
            tracked_upstream.parent.mkdir(parents=True, exist_ok=True)
            tracked_upstream.write_text(flavour.upstream_note, encoding="utf-8")
        run_git(("add", "-A"), cwd=work)
        run_git(("commit", "-q", "-m", "feat: upstream moves on"), cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # Rewind local to base so upstream is ahead, not already merged in.
        run_git(("reset", "--hard", base), cwd=work)

        # The uncommitted work itself: a tracked modification -- in the file upstream
        # changed, on the same-file state -- plus an untracked file where the state
        # has one.
        if state == "same_file":
            with (work / _UPSTREAM_FILE).open("a", encoding="utf-8") as handle:
                handle.write(flavour.same_file_work)
        else:
            with (work / _TRACKED_FILE).open("a", encoding="utf-8") as handle:
                handle.write(flavour.local_work)
        sandbox.recorded["patch"] = run_git(("diff",), cwd=work).stdout
        if draw.untracked:
            untracked = work / _UNTRACKED_PATH
            untracked.parent.mkdir(parents=True, exist_ok=True)
            untracked.write_text(flavour.untracked_note, encoding="utf-8")
            sandbox.recorded["untracked"] = flavour.untracked_note
        if state == "collision":
            sandbox.recorded["collision"] = _UNTRACKED_PATH

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
        """The instance identity this seed builds, from the same draw `inject` uses."""
        return draw_for_seed(seed).identity

    def axes_for_resolution(self, resolution: str) -> Mapping[str, tuple[str, ...]]:
        """The axes `resolution` may vary along, with their value pools (ADR-0005)."""
        if resolution not in AXES_BY_RESOLUTION:
            raise KeyError(f"dirty_tree declares no resolution {resolution!r}")
        return {name: AXES[name] for name in AXES_BY_RESOLUTION[resolution]}

    def drawn_axes_for_seed(self, seed: int) -> Mapping[str, str]:
        """The drawn value of each declared axis at `seed` (ADR-0005 decision 2)."""
        return draw_for_seed(seed).axes

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome: upstream absorbed and the uncommitted work intact.

        Two clauses. First, upstream's tip must be contained in the local branch.
        Second, the uncommitted work recorded at injection must still be present:
        the tracked half is a patch the working tree must still reverse-apply,
        and the untracked half a file whose content must match. Both are recorded
        in `Sandbox.recorded`, outside the clone, so no branch rewrite removes them.

        The second clause is what makes the destructive "fixes" fail. `reset
        --hard upstream/main`, `checkout -- .` and `clean -fd` all satisfy the
        first clause while discarding the user's work, and each is rejected here.

        The work is graded by *presence*, not by whether it stayed uncommitted:
        committing the work preserves it, and the fault's own text asks only that
        it survive. A resolution that leaves the work only in a stash is rejected,
        because the tree no longer contains it.

        On a collision -- upstream now tracks the untracked file's path -- the
        untracked work may instead be at `<path>.local` (`ASIDE_SUFFIX`): upstream's
        file and the user's cannot both live at one path, and keeping the user's
        beside it is the only way both survive. Nowhere else counts.
        """
        work = sandbox.work
        upstream_tip = git_out("rev-parse", "refs/heads/main", cwd=sandbox.upstream)
        if not tip_contained(work, upstream_tip):
            return GroundTruth(
                ok=False,
                detail=f"upstream tip {upstream_tip[:12]} is not contained in the local branch",
            )

        patch = sandbox.recorded["patch"]
        if patch.strip():
            reverts = run_git(
                ("apply", "--reverse", "--check", "-"), cwd=work, check=False, stdin=patch
            )
            if reverts.returncode != 0:
                return GroundTruth(
                    ok=False,
                    detail="uncommitted tracked changes are no longer in the tree (discarded)",
                )

        has_untracked = "untracked" in sandbox.recorded
        if has_untracked:
            # Not stripped: the checked file must match the stored bytes exactly.
            expected = sandbox.recorded["untracked"]
            places = [work / _UNTRACKED_PATH]
            if "collision" in sandbox.recorded:
                places.append(work / (_UNTRACKED_PATH + ASIDE_SUFFIX))
            if not any(
                place.is_file() and place.read_text(encoding="utf-8") == expected
                for place in places
            ):
                return GroundTruth(
                    ok=False,
                    detail="uncommitted untracked work is no longer in the tree (discarded)",
                )

        return GroundTruth(
            ok=True,
            detail=(
                "upstream tip is contained in the local branch and the uncommitted work survives"
            ),
        )


SPEC = DirtyTreeFault()
