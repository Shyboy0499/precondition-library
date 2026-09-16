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
decides this. Issue #25 tracks the three faults that still return a single fixed
request sentence; those are the excluded ones.
"""

from __future__ import annotations

from pathlib import Path

from ...sandbox import (
    Sandbox,
    create_submodule_origin,
    git_out,
    require_uninjected,
    run_git,
    store_blob,
)
from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant, sample_index
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

# Ground truth the checker reads, recorded under refs/sandbox/ so `check` grades
# the outcome without being handed the seed, and can still name the submodule's
# path after a correct removal has emptied the `.gitmodules` entry that would
# otherwise reveal it.
_STATE_REF = "refs/sandbox/submodule-state"
_PATH_REF = "refs/sandbox/submodule-path"

# Local paths are a valid submodule URL, but git >= 2.38 refuses them for
# submodule operations unless allowed. Passed per command, so no global or
# per-repo config is changed and the pinned environment stays what `run_git`
# defines.
_FILE_PROTOCOL = ("-c", "protocol.file.allow=always")


def state_for_seed(seed: int) -> str:
    """Which of the three live states this seed injects. Deterministic.

    One definition shared by `inject` and the tests, so a test cannot disagree
    with the injected environment.
    """
    return INJECTED_STATES[sample_index(seed, _STATE_SALT, len(INJECTED_STATES))]


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


def _upstream_dropped_it(state: StateFingerprint) -> bool:
    return not state.upstream_still_references_submodule


def _not_initialised(state: StateFingerprint) -> bool:
    return state.upstream_still_references_submodule and not state.submodule_initialised


def _pin_drifted(state: StateFingerprint) -> bool:
    return (
        state.upstream_still_references_submodule
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
        URL is a fixed function of the seed's sandbox root.
        """
        work = sandbox.work
        require_uninjected(sandbox, fault="submodule_moved", ref=_STATE_REF)

        state = state_for_seed(seed)

        # The third repository: the submodule's origin. Its first commit is what
        # both sides start pinned to.
        origin = create_submodule_origin(sandbox.root, ORIGIN_DIRNAME)
        (origin / "lib.py").write_text("VERSION = 1\n", encoding="utf-8")
        run_git(("add", "-A"), cwd=origin)
        run_git(("commit", "-q", "-m", "feat: initial library"), cwd=origin)

        # Add the submodule and publish the commit that pins it, so upstream and
        # the clone agree before the state-specific mutation.
        run_git(
            (*_FILE_PROTOCOL, "submodule", "add", "-q", str(origin), SUBMODULE_PATH),
            cwd=work,
        )
        run_git(("commit", "-q", "-m", "chore: add nested library"), cwd=work)
        pinned = git_out("rev-parse", "HEAD", cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # The origin moves on: a second commit for a pin to drift to.
        (origin / "lib.py").write_text("VERSION = 2\n", encoding="utf-8")
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

        store_blob(work, _STATE_REF, state)
        store_blob(work, _PATH_REF, SUBMODULE_PATH)

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

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome per injected state, from git alone.

        The injected state is read from `refs/sandbox/submodule-state`, which
        `inject` records, so the checker is never told the seed and cannot derive
        the answer from the request. Each state has one clause:

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
        state = git_out("cat-file", "-p", _STATE_REF, cwd=work)
        path = git_out("cat-file", "-p", _PATH_REF, cwd=work)

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
