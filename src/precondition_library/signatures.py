"""How a task is described, and how its environment's state is fingerprinted.

Two competing dispatch mechanisms consume these:

  arm 2 (semantic)      compares `TaskSignature.intent` embeddings
  arm 3 (preconditions) runs `StateFingerprint` probes and lets each stored
                        Program decide applicability for itself

The fingerprint is what stops arm 3 from being a rerun of arm 2: it describes
the *environment*, not the request. Two tasks phrased identically against
structurally different repos must not resolve to the same program.
"""

from __future__ import annotations

from pydantic import BaseModel


class StateFingerprint(BaseModel):
    """Observable git-level facts about an environment, gathered without an LLM.

    Every field must be obtainable from git alone, because arm 3 decides by
    running probes over exactly these values. A field that cannot be probed does
    not belong here: it would make a resolution undecidable and quietly turn the
    experiment into a comparison of two equally blind dispatchers.
    """

    dirty_worktree: bool
    branch: str
    upstream_ahead: int
    upstream_behind: int
    has_locked_branch: bool
    has_submodule_reference: bool
    remotes: list[str] = []

    # Discriminators for the ambiguous intents (see tasks/intent.py).
    local_only_commits: int = 0
    """Commits present locally that upstream lacks: `git rev-list --count upstream/main..HEAD`."""
    local_touched_files: list[str] = []
    """Files the local-only commits change: `git diff --name-only upstream/main...HEAD`."""
    upstream_touched_files: list[str] = []
    """Files upstream's new commits change: `git diff --name-only HEAD...upstream/main`."""
    submodule_initialised: bool = False
    """Whether the submodule directory has been initialised in this clone:
    `git submodule status` prefixes an uninitialised entry with `-`."""
    submodule_pin_matches_upstream: bool = True
    """Whether the recorded submodule commit equals the one upstream pins:
    `git diff --name-only upstream/main -- <submodule_path>` is empty when it does."""
    upstream_still_references_submodule: bool = True
    """Whether upstream's tree still contains the submodule path at all:
    `git ls-tree upstream/main -- <submodule_path>` is non-empty when it does."""

    @property
    def conflicting_files(self) -> set[str]:
        """Files both sides touched.

        The discriminator that decides merge versus rebase: if the two sides
        changed the same file, replaying local commits on top of upstream would
        discard a resolution someone already made.
        """
        return set(self.local_touched_files) & set(self.upstream_touched_files)

    @property
    def has_local_only_commits(self) -> bool:
        """Whether the local branch is ahead of upstream at all.

        A count rather than a flag because the zero case is the *benign* state:
        nothing to resolve, so every program must refuse to fire. Negative
        examples are half of what a dispatcher has to get right.
        """
        return self.local_only_commits > 0

    @classmethod
    def observe(cls, env) -> StateFingerprint:
        """Run the probes. Must not mutate the environment.

        Still unimplemented: the real probes belong with the live sandbox
        (issues #4/#5). Until then, fingerprints are constructed directly, which
        is sufficient for labelling dispatch decisions because the benchmark
        consumes states, not repositories.
        """
        raise NotImplementedError("implemented per plan: phase 1 (issues #4/#5)")


class TaskSignature(BaseModel):
    """A request plus the state it arrived in."""

    intent: str
    """The user-facing request, e.g. 'sync this fork with upstream'."""
    fingerprint: StateFingerprint
    target: str
    """Environment identity, e.g. the sandbox path. Never a real repo in phase 1."""
