"""The compile step: a solved task becomes a reusable Program.

This is where the LLM writes code that will later run unattended, so it is also
the project's main safety surface. Two defences live here:

* The compile step never executes what it generates. Execution is `runtime`'s
  job, on a throwaway sandbox, behind `runtime.guard`.
* Admission is a two-sided test, not a happy path. A program must satisfy its
  postconditions on a freshly faulted sandbox *and* have its preconditions
  reject negative sandboxes. Preconditions that accept everything are treated
  as a defect — such a program would fire on unrelated states, which is exactly
  the mismatch failure this project measures.
"""

from __future__ import annotations

from ..program import Program
from ..provider import Provider


def compile_program(signature, env, transcript: list[dict], provider: Provider) -> Program:
    """Ask the model for intent, parameters, preconditions, body, postconditions.

    Returns a CANDIDATE. Nothing becomes replayable until admission passes.
    """
    raise NotImplementedError("implemented per plan: phase 2")


def admit(program: Program, fault, *, seeds: list[int]) -> tuple[bool, str]:
    """Two-sided admission gate.

    Positive side: the program must fix the fault on fresh sandboxes.
    Negative side: its preconditions must reject sandboxes in unrelated states.
    Returns (admitted, reason) so a rejection can be reported rather than
    silently dropped — rejected programs are data for the mismatch analysis.
    """
    raise NotImplementedError("implemented per plan: phase 2")
