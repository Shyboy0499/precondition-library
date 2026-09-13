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
    """Observable git-level facts about an environment, gathered without an LLM."""

    dirty_worktree: bool
    branch: str
    upstream_ahead: int
    upstream_behind: int
    has_locked_branch: bool
    has_submodule_reference: bool
    remotes: list[str] = []

    @classmethod
    def observe(cls, env) -> StateFingerprint:
        """Run the probes. Must not mutate the environment."""
        raise NotImplementedError("implemented per plan: phase 2")


class TaskSignature(BaseModel):
    """A request plus the state it arrived in."""

    intent: str
    """The user-facing request, e.g. 'sync this fork with upstream'."""
    fingerprint: StateFingerprint
    target: str
    """Environment identity, e.g. the sandbox path. Never a real repo in phase 1."""
