"""Fault: a submodule's recorded commit no longer matches what upstream expects.

Three resolutions, indistinguishable from the request text:

  init    the submodule directory was never initialised in this clone.
  repin   it is initialised, upstream still tracks it, and the recorded commit drifted.
  remove  upstream no longer references the submodule at all.

The third is the one that punishes a plausible wrong answer: re-pinning a
submodule upstream has dropped *looks* like it worked (the command succeeds) while
leaving the tree in a state the checker rejects. That is exactly the silent
wrong-program fire the primary claim is about, which is why this intent is worth
having even though the first two resolutions are less interesting.

The injector and checker are real against live git. `inject` builds a third
repository inside the sandbox for the submodule to point at -- a local path is a
valid submodule URL, which keeps the fault offline and deterministic -- and picks
one of the three states from the seed with `sample_index`, exactly as `diverged`
does. `check` grades the outcome per state from git alone. The fault is a usable
negative sandbox for admission, and it *is* part of dispatch measurement: the
registry returns its ambiguous intent from `ambiguous_intents()` and does not list
it in `EXCLUDED_FROM_BENCHMARK`, so `tasks/registry.py` is the single place that
decides this. Issue #25 tracked the faults that returned a single fixed request
sentence; since ADR-0029 none does, and none is excluded.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ...sandbox import (
    RECORDED_SUBMODULE_PATH,
    Sandbox,
    create_submodule_origin,
    git_out,
    record_base,
    run_git,
)
from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant, draw_index, sample_index
from ..spec import FaultSpec, GroundTruth

# The path the submodule lives at, and the directory inside the sandbox root that
# plays its origin. Both are fixed, so the same seed rebuilds the same URLs and
# SHAs; the origin directory is inside `root`, so `Sandbox.destroy` removes it.
SUBMODULE_PATH = "vendor/libcore"
ORIGIN_DIRNAME = "submodule-origin"

# The three live states, chosen by seed. The order is part of the seed-to-state
# mapping, so appending to it would change which state an existing seed injects;
# add states deliberately.
INJECTED_STATES = ("init", "repin", "remove")
_STATE_SALT = "submodule_moved:inject"


# --- Tier 1 instance axes (ADR-0005) -----------------------------------------
#
# The one safe Tier 1 axis here is the *content* of the nested repository. Every
# predicate this fault decides on -- upstream still references the submodule, the
# clone initialised it, the recorded pin matches upstream -- is invariant under
# what the submodule's files contain, so varying that content changes the
# environment without touching the label.
#
# The content is visible in three different places, which is why it is enough for
# this fault even though the clone does not always check the submodule out:
#
#   init    the checkout is absent, but upstream's tree still records the gitlink
#           whose commit is the origin's first commit, and its diff against the
#           base names that commit -- both vary with the content.
#   repin   the clone is checked out at the pinned (first) commit, so the working
#           tree body varies; upstream records the grown commit.
#   remove  upstream has dropped the reference, and the clone is checked out at
#           the pinned commit, so the working tree body varies.
#
# Not drawn: the submodule path or the parent repo's file names (Tier 2 -- they
# need probe/body parameter binding and are out of scope here), file counts
# (Tier 3), and commit SHAs/dates on their own (cosmetic: #86 and ADR-0005 refuse
# a SHA-only difference as a new environment).
@dataclass(frozen=True)
class _LibraryContent:
    """One drawn content value: the nested repo's first and grown file bodies."""

    initial: str
    grown: str


_LIBRARY_CONTENTS: tuple[_LibraryContent, ...] = (
    _LibraryContent("VERSION = 1\n", "VERSION = 2\n"),
    _LibraryContent("VERSION = 10\n", "VERSION = 11\n"),
    _LibraryContent(
        "VERSION = 100\n\nRELEASED = False\n",
        "VERSION = 101\n\nRELEASED = False\n",
    ),
    _LibraryContent('VERSION = 7\n\nNAME = "libcore"\n', 'VERSION = 8\n\nNAME = "libcore"\n'),
    _LibraryContent("VERSION = 3\n\nSTABLE = True\n", "VERSION = 4\n\nSTABLE = True\n"),
    _LibraryContent("VERSION = 42\n\nSTABLE = False\n", "VERSION = 43\n\nSTABLE = False\n"),
)

AXES: Mapping[str, tuple[str, ...]] = {
    "library_content": tuple(str(index) for index in range(len(_LIBRARY_CONTENTS))),
}
"""The Tier 1 axis this fault draws, with the values it may take."""

AXES_BY_RESOLUTION: Mapping[str, tuple[str, ...]] = {
    "init": ("library_content",),
    "repin": ("library_content",),
    "remove": ("library_content",),
}
"""Which axes each resolution may vary along.

The same single axis for all three: the nested repo's content leaves every
submodule predicate invariant, so it is safe everywhere, and the load-bearing
facts (initialised, still referenced, pin equal) are never drawn.
"""


@dataclass(frozen=True)
class Draw:
    """Everything one seed's instance draw decides, for `inject` and identity."""

    state: str
    content: int

    @property
    def identity(self) -> str:
        """The stable instance identity: resolution plus the drawn axis value."""
        return f"submodule_moved/{self.state}/content={self.content}"

    @property
    def axes(self) -> Mapping[str, str]:
        """The drawn value for each declared axis, by axis name."""
        return {"library_content": str(self.content)}


def state_for_seed(seed: int) -> str:
    """Which of the three live states this seed injects. Deterministic.

    One definition shared by `inject` and the tests, so a test cannot disagree
    with the injected environment.
    """
    return INJECTED_STATES[sample_index(seed, _STATE_SALT, len(INJECTED_STATES))]


def draw_for_seed(seed: int) -> Draw:
    """The Tier 1 draw for `seed`: the state shape and the nested repo's content.

    Shared by `inject`, `instance_for_seed` and the tests, so the built
    environment and the recorded identity cannot disagree. The content axis goes
    through `draw_index` with its own salt, independent of the state selection.
    """
    return Draw(
        state=state_for_seed(seed),
        content=draw_index(seed, "submodule_moved", "library_content", len(_LIBRARY_CONTENTS)),
    )


# Local paths are a valid submodule URL, but git >= 2.38 refuses them for
# submodule operations unless allowed. Passed per command, so no global or
# per-repo config is changed and the pinned environment stays what `run_git`
# defines.
_FILE_PROTOCOL = ("-c", "protocol.file.allow=always")


def _pin(repo: Path, rev: str, path: str) -> str:
    """The gitlink SHA `rev` records for `path`, or "" when it records none."""
    line = git_out("ls-tree", rev, "--", path, cwd=repo)
    return line.split()[2] if line else ""


def _is_initialised(work: Path, path: str) -> bool:
    """Whether the clone has a checkout for the submodule at `path`.

    `git submodule status` prefixes an uninitialised entry with `-`; a path that
    is referenced nowhere prints nothing at all, which is also not initialised.
    """
    status = run_git(("submodule", "status", "--", path), cwd=work, check=False).stdout.strip()
    return bool(status) and not status.startswith("-")


def _gitmodules_references(work: Path, path: str) -> bool:
    """Whether `.gitmodules` still declares the submodule at `path`."""
    result = run_git(
        ("config", "--file", ".gitmodules", "--get", f"submodule.{path}.path"),
        cwd=work,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


# Every rule first requires a submodule in HEAD. Without one, `observe` reports the
# defaults -- not initialised, upstream still referencing it -- and `_not_initialised`
# alone would call a repository with no submodule at all an `init` state. That never
# mattered while only this fault's own states were labelled; it does once admission
# labels *other* faults' states with this intent (ADR-0019), where it made every
# diverged state an `init` overlap state (found while building #162's pairs).


def _upstream_dropped_it(state: StateFingerprint) -> bool:
    return state.has_submodule_reference and not state.upstream_still_references_submodule


def _not_initialised(state: StateFingerprint) -> bool:
    return (
        state.has_submodule_reference
        and state.upstream_still_references_submodule
        and not state.submodule_initialised
    )


def _pin_drifted(state: StateFingerprint) -> bool:
    return (
        state.has_submodule_reference
        and state.upstream_still_references_submodule
        and state.submodule_initialised
        and not state.submodule_pin_matches_upstream
    )


VARIANTS = [
    ResolutionVariant(
        id="remove",
        decided_by=_upstream_dropped_it,
        rationale="Upstream's tree no longer contains the submodule, so it must go.",
    ),
    ResolutionVariant(
        id="init",
        decided_by=_not_initialised,
        rationale="Upstream still tracks it but this clone never initialised it.",
    ),
    ResolutionVariant(
        id="repin",
        decided_by=_pin_drifted,
        rationale="Initialised and still tracked, but recording a commit upstream no longer pins.",
    ),
]

INTENT = IntentSpec(
    name="restore_submodule_state",
    fault="submodule_moved",
    phrasings=[
        "The submodule in this fork is out of step with upstream. Bring it back into line.",
        "Something is off with the nested repository here. Put it right.",
        "Get this repo's nested dependency consistent with upstream.",
        "One of the nested checkouts looks wrong. Resolve it.",
        "Upstream and this clone disagree about a nested repository. Reconcile them.",
        "Sort out the nested checkout so it matches what upstream expects.",
        "A nested repository in this project needs bringing into line.",
    ],
    naming_markers=["submodule"],
    variants=VARIANTS,
    # Repin and remove share a symptom phrase ("disagrees with upstream") that is
    # true of both -- a drifted pin and a dropped reference both look that way.
    # The shared phrase keeps the text a *partial* signal (see bench/textcontrol.py).
    variant_phrasings={
        "init": ["the nested checkout was never initialised here"],
        "repin": [
            "the nested checkout records a commit upstream no longer pins",
            "the nested checkout disagrees with upstream",
        ],
        "remove": [
            "upstream dropped the nested repo entirely",
            "the nested checkout disagrees with upstream",
        ],
    },
)


class SubmoduleMovedFault(FaultSpec):
    name = "submodule_moved"
    # The `.gitmodules` entry and the gitlink: removing the submodule deletes
    # both, and the other states move the gitlink.
    change_surface = (".gitmodules", SUBMODULE_PATH)
    description = "A submodule's recorded state no longer matches what upstream expects"

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Build the shared submodule history, then mutate one of three states.

        The clone first adds a submodule pinned to the origin's first commit and
        publishes that commit, so upstream and the clone agree before the fault.
        The origin then grows a second commit, which is what gives `repin` (and
        the remove state's plausible wrong answer) somewhere to move to. The
        state-specific mutation follows:

          init    deinitialise the checkout, so the reference remains but the
                  working tree is empty and `upstream` still pins it.
          repin   advance upstream's pin to the grown commit, push, then rewind
                  the clone to the original pin and re-check it out.
          remove  drop the submodule on upstream and push, then rewind the clone
                  to the commit that still references it and re-check it out.

        Deterministic in the seed: `sample_index` chooses the state, the origin
        and the clone are committed under the pinned environment, and the local
        URL is a fixed function of the seed's sandbox root. The nested repo's
        content is drawn per seed (Tier 1, ADR-0005), so two seeds that select one
        state build different environments without moving a predicate.
        """
        work = sandbox.work
        record_base(sandbox, fault="submodule_moved")

        draw = draw_for_seed(seed)
        state = draw.state
        content = _LIBRARY_CONTENTS[draw.content]

        # The third repository: the submodule's origin. Its first commit is what
        # both sides start pinned to.
        origin = create_submodule_origin(sandbox.root, ORIGIN_DIRNAME)
        (origin / "lib.py").write_text(content.initial, encoding="utf-8")
        run_git(("add", "-A"), cwd=origin)
        run_git(("commit", "-q", "-m", "feat: initial library"), cwd=origin)

        # Add the submodule and publish the commit that pins it, so upstream and
        # the clone agree before the state-specific mutation.
        #
        # The URL is *relative* to the superproject's origin (`<root>/upstream.git`)
        # rather than an absolute path into this sandbox root. An absolute path is
        # written into the committed `.gitmodules`, so it enters every commit SHA
        # of this fault and the same `(seed, fault)` built at a different root has
        # a different HEAD -- measured in #72. A relative URL resolves to the same
        # `<root>/submodule-origin` these two repositories already stand in, and
        # keeps the committed content independent of where the sandbox was built.
        run_git(
            (*_FILE_PROTOCOL, "submodule", "add", "-q", f"../{ORIGIN_DIRNAME}", SUBMODULE_PATH),
            cwd=work,
        )
        run_git(("commit", "-q", "-m", "chore: add nested library"), cwd=work)
        pinned = git_out("rev-parse", "HEAD", cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # The origin moves on: a second commit for a pin to drift to.
        (origin / "lib.py").write_text(content.grown, encoding="utf-8")
        run_git(("add", "-A"), cwd=origin)
        run_git(("commit", "-q", "-m", "feat: library grows"), cwd=origin)
        grown = git_out("rev-parse", "HEAD", cwd=origin)

        if state == "init":
            run_git(("submodule", "deinit", "-f", "--", SUBMODULE_PATH), cwd=work)
        elif state == "repin":
            self._advance_upstream_pin(work, grown)
            run_git(("reset", "--hard", pinned), cwd=work)
            self._sync_checkout(work)
        else:
            self._drop_upstream_reference(work)
            run_git(("reset", "--hard", pinned), cwd=work)
            self._sync_checkout(work)

        # The path is recorded because the *probes* bind `{submodule_path}` from it, and
        # a correct removal deletes the `.gitmodules` entry that would otherwise carry it.
        # It is recorded on the sandbox object, never in the clone: a ref there was
        # readable by the agent and could anchor a precondition (issues #103, #161).
        sandbox.recorded[RECORDED_SUBMODULE_PATH] = SUBMODULE_PATH

        # Leave the remote-tracking ref current so observe() can read it without
        # fetching (observe must not mutate the environment).
        run_git(("fetch", "-q", "upstream"), cwd=work)

    @staticmethod
    def _sync_checkout(work: Path) -> None:
        """Check the submodule out at whatever commit the clone records."""
        run_git(
            (*_FILE_PROTOCOL, "submodule", "update", "--init", "--", SUBMODULE_PATH),
            cwd=work,
        )

    @staticmethod
    def _advance_upstream_pin(work: Path, commit: str) -> None:
        """Move the submodule to `commit` and publish a clone commit pinning it."""
        run_git(("fetch", "-q", "origin"), cwd=work / SUBMODULE_PATH)
        run_git(("checkout", "-q", commit), cwd=work / SUBMODULE_PATH)
        run_git(("add", SUBMODULE_PATH), cwd=work)
        run_git(("commit", "-q", "-m", "chore: bump nested library"), cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

    @staticmethod
    def _drop_upstream_reference(work: Path) -> None:
        """Remove the submodule on upstream and publish that removal."""
        # `git rm` drops the gitlink, the working tree and the `.gitmodules`
        # entry; on a single-submodule repo it leaves an empty `.gitmodules`.
        run_git(("rm", "-q", "--", SUBMODULE_PATH), cwd=work)
        run_git(("commit", "-q", "-m", "chore: drop nested library"), cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

    def task_text(self, seed: int) -> str:
        return INTENT.task_text(seed)

    def variant_for_seed(self, seed: int) -> str:
        """The resolution the state injected at `seed` is correct in.

        `INJECTED_STATES` names each state after the resolution it requires -- an
        uninitialised clone is "init", a drifted pin is "repin", a dropped upstream
        reference is "remove" -- and those names are the `ResolutionVariant` ids, so
        the state's name is its resolution. Returning it here exposes the
        seed-to-resolution mapping admission's same-intent negative class needs
        without a sandbox to observe, and `test_sandbox_submodule_moved` pins the
        name/variant-id agreement rather than leaving it assumed.
        """
        return state_for_seed(seed)

    def instance_for_seed(self, seed: int) -> str:
        """The instance identity this seed builds, from the same draw `inject` uses.

        Resolution plus the drawn Tier 1 axis value (ADR-0005 decision 4), so
        `bench.splits` keys independence on the environment rather than on the
        resolution and only a genuine repeat of one instance is a replay.
        """
        return draw_for_seed(seed).identity

    def axes_for_resolution(self, resolution: str) -> Mapping[str, tuple[str, ...]]:
        """The axes `resolution` may vary along, with their value pools.

        The declaration ADR-0005 decision 2 requires, and the answer here is one
        axis for every resolution: the nested repo's content is invariant under
        all three predicates. Raises for an undeclared resolution so a typo cannot
        read as "no axes".
        """
        if resolution not in AXES_BY_RESOLUTION:
            raise KeyError(f"submodule_moved declares no resolution {resolution!r}")
        return {name: AXES[name] for name in AXES_BY_RESOLUTION[resolution]}

    def drawn_axes_for_seed(self, seed: int) -> Mapping[str, str]:
        """The drawn value of each declared axis at `seed` (ADR-0005 decision 2)."""
        return draw_for_seed(seed).axes

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome per injected state, from git alone.

        The state is a **selector**, taken from `sandbox.injected_state` -- the harness's
        own record of what it injected -- rather than read out of the clone. It used to be
        recorded under `refs/sandbox/submodule-state`, which put the answer inside the
        environment the graded code reads: a precondition could be
        `test "$(git cat-file -p refs/sandbox/submodule-state)" = "remove"`, and admission
        could not reject it, because it fires in precisely the state it is supposed to
        (issue #103).

        Nothing is taken on trust by the move. The selector says *which* clause applies and
        the clause is still read from the environment, so the checker still verifies rather
        than believes. Each state has one clause:

          init    the submodule is initialised -- its working tree has a checkout.
          repin   the commit HEAD records for the submodule equals the one
                  upstream pins.
          remove  the submodule is referenced neither in HEAD's tree nor in
                  `.gitmodules`.

        The remove clause is the fault's reason to exist. A program that re-pins
        the submodule to its origin's latest commit *succeeds* -- the submodule
        updates and the commit is recorded -- while upstream has dropped it
        entirely; the reference clause rejects that where a "did the command
        succeed" check would not.
        """
        work = sandbox.work
        state = sandbox.injected_state
        if state is None:
            raise ValueError(
                "submodule_moved.check needs the injected state; build the sandbox through "
                "tasks.faults.build_sandbox, which records it on the sandbox"
            )
        path = SUBMODULE_PATH

        if state == "init":
            if not _is_initialised(work, path):
                return GroundTruth(
                    ok=False,
                    detail=f"submodule {path!r} is uninitialised: it has no checkout",
                )
            return GroundTruth(
                ok=True, detail=f"submodule {path!r} is initialised and has a checkout"
            )

        if state == "repin":
            recorded = _pin(work, "HEAD", path)
            # Upstream's pin is read from the upstream repository itself, not the
            # clone's remote-tracking ref, so a rewritten cache cannot fake it.
            upstream = _pin(sandbox.upstream, "refs/heads/main", path)
            if not upstream:
                return GroundTruth(
                    ok=False,
                    detail=f"upstream no longer records {path!r}, so it has no pin to match",
                )
            if recorded != upstream:
                return GroundTruth(
                    ok=False,
                    detail=(
                        f"recorded submodule commit {recorded[:12] or '(none)'} does not "
                        f"equal upstream's pin {upstream[:12]}"
                    ),
                )
            return GroundTruth(
                ok=True,
                detail=f"recorded submodule commit equals upstream's pin {upstream[:12]}",
            )

        if state == "remove":
            in_tree = _pin(work, "HEAD", path)
            in_modules = _gitmodules_references(work, path)
            if in_tree and in_modules:
                where = "the tree and .gitmodules"
            elif in_tree:
                where = "the tree"
            elif in_modules:
                where = ".gitmodules"
            else:
                return GroundTruth(
                    ok=True,
                    detail=(
                        f"submodule {path!r} is no longer referenced in the tree or .gitmodules"
                    ),
                )
            return GroundTruth(
                ok=False,
                detail=(
                    f"submodule {path!r} is still referenced in {where}, but upstream "
                    "has dropped it"
                ),
            )

        return GroundTruth(ok=False, detail=f"unknown injected state {state!r}")


SPEC = SubmoduleMovedFault()
