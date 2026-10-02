"""Arm 1b's memory: the trajectories of tasks the agent believes it finished (issue #7).

Arm 1 starts every episode from nothing, so its cost curve is flat by construction. A
reviewer's first objection is that no reasonable engineer runs an agent that way:
the standard experience-reuse baseline gives the agent its own past successes to
read. Issue #7 calls it arm 1b, "react plus prior-success memory/reflexion", and its
absence would make the compiled arms' amortization look better than it is.

The owner's choices (ADR-0017):

* **What is stored** is a trajectory, not a reflection: the request and the git
  commands that ran without error, in order. No extra model call writes it, so 1b's
  only extra cost is the longer prompt the recalled entries make.
* **When it is stored** is decided by the model's own verdict -- the episode ended
  with the model declaring the task done (`EpisodeOutcome.SUCCESS` from `solve`) --
  and never by the fault's checker. That is the same no-oracle rule arm 1 runs under
  (issue #9): a deployment's memory would hold the agent's mistakes too, and a memory
  filtered by ground truth would hand 1b a signal no compiled arm receives.

Recall is the `RECALL_K` most similar stored requests by deterministic lexical
similarity, over the request text only. Lexical rather than the run's similarity seam
so that 1b spends nothing in arm 2's embedding currency; ties go to the more recent
entry. The recalled entries are rendered into the **user** message, not the system
prompt, so the system prefix every arm sends stays identical (spec §7's prompt-prefix
report depends on that).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..similarity import lexical_similarity

RECALL_K = 3
"""Entries recalled per episode. Small, because every recalled entry is re-sent on
every turn of the episode and billed each time."""

MAX_COMMANDS = 12
"""Commands kept per entry: a solve that took more than this many successful commands
is summarised by its first ones rather than letting one entry dominate the prompt."""


@dataclass(frozen=True)
class MemoryEntry:
    """One task the agent declared finished, and the commands that got it there."""

    request: str
    commands: tuple[str, ...]


def successful_commands(transcript: list[dict]) -> tuple[str, ...]:
    """The git commands a transcript ran without error, in order, capped at `MAX_COMMANDS`.

    Read from the transcript's tool entries (`role: "tool"`, `ok: True`), which `solve`
    writes for every call. A refused or failed command is left out: it is not part of
    how the task was done, and re-reading it would teach the next episode a mistake.
    """
    commands = [
        entry["command"]
        for entry in transcript
        if entry.get("role") == "tool" and entry.get("ok") and entry.get("command")
    ]
    return tuple(commands[:MAX_COMMANDS])


class SuccessMemory:
    """Arm 1b's store, grown in episode order within one run and never read across runs."""

    def __init__(self) -> None:
        self._entries: list[MemoryEntry] = []

    def __len__(self) -> int:
        return len(self._entries)

    def record(self, request: str, transcript: list[dict]) -> None:
        """Store a trajectory the model declared finished. A solve with no successful
        command teaches nothing to repeat, so it is not stored."""
        commands = successful_commands(transcript)
        if commands:
            self._entries.append(MemoryEntry(request=request, commands=commands))

    def recall(self, request: str, k: int = RECALL_K) -> list[MemoryEntry]:
        """The `k` stored entries whose request is most similar to `request`.

        An entry with zero similarity is not recalled -- an unrelated task's commands
        are noise in the prompt, and paying tokens for noise is the opposite of what
        memory is for. Ties go to the more recent entry, so a later, possibly corrected
        trajectory is preferred over an earlier one for the same request.
        """
        scored = [
            (lexical_similarity(request, entry.request), index, entry)
            for index, entry in enumerate(self._entries)
        ]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (-item[0], -item[1]))
        return [entry for _, _, entry in scored[:k]]


def render(entries: list[MemoryEntry]) -> str | None:
    """The recalled entries as a prelude to the user message, or `None` when there are none.

    Worded as the agent's own past work, not as instructions: the model must still read
    this repository's state, because a past task with a similar request may have needed
    a different resolution -- the ambiguity the benchmark is built on.
    """
    if not entries:
        return None
    lines = [
        "Notes from tasks you previously completed in other repositories. They may or may "
        "not apply here; check this repository's state before reusing any of them."
    ]
    for number, entry in enumerate(entries, start=1):
        lines.append(f"{number}. Request: {entry.request}")
        lines.append("   Commands that ran: " + "; ".join(entry.commands))
    return "\n".join(lines)
