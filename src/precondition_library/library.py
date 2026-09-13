"""The program library: storage, admission, and dispatch.

Two dispatch strategies live here because the ablation compares them against
each other as much as against the ReAct baseline:

  match_semantic     arm 2 — nearest by embedding of the task intent
  match_preconditions arm 3 — every candidate whose probes accept the state

Admission is the safety gate. A program the LLM authored is only allowed to
become replayable once it has demonstrated both halves of its contract:
postconditions satisfied on a freshly faulted sandbox, and preconditions
rejecting every negative sandbox (states where firing would be wrong).
"""

from __future__ import annotations

from pathlib import Path

from .program import Program, ProgramStatus


class Library:
    """Programs on disk under `library/`, committed as a research artifact."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def load_all(self) -> list[Program]:
        raise NotImplementedError("implemented per plan: phase 2")

    def add(self, program: Program) -> None:
        raise NotImplementedError("implemented per plan: phase 2")

    def set_status(self, program_id: str, status: ProgramStatus) -> None:
        raise NotImplementedError("implemented per plan: phase 3")

    def match_semantic(self, signature, *, limit: int = 3) -> list[Program]:
        """Arm 2. Rank by embedding similarity of intent; no state awareness."""
        raise NotImplementedError("implemented per plan: phase 2")

    def match_preconditions(self, signature, env) -> list[Program]:
        """Arm 3. Return only programs whose preconditions accept `env`."""
        raise NotImplementedError("implemented per plan: phase 2")
