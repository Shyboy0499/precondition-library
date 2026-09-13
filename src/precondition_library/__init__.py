"""precondition-library: an agent that compiles chores into replayable programs.

The agent solves a task once with an LLM, compiles the solution into a
*program* carrying executable preconditions, and later replays that program
with zero LLM calls when a task arrives in a state those preconditions accept.

Design of record: docs/superpowers/specs/2026-09-13-precondition-library-design.md
"""

__version__ = "0.0.1"

__all__ = ["__version__"]
