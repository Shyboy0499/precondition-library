"""The boundary between generated code and the machine.

Compiled bodies are authored by a model that has been reading untrusted
repository content, and they execute unattended on repeat. Two consequences
shape this module:

* Screening is deny-by-default over *effects*, not intent. We cannot know what
  the model meant; we can refuse to hand it a filesystem root, a force-push to
  a shared remote, or a network fetch that exfiltrates repository contents.
* What the guard cannot make safe, it makes recoverable: destructive-looking
  programs are still permitted to run inside a disposable sandbox, because that
  is what the sandbox is for — the guard's job is to guarantee the sandbox is
  the only thing at risk.

A refused program is recorded, not silently skipped. The refusal rate is part of
the result, and a high one means the compile prompt is producing dangerous code
rather than that the guard is being annoying.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    ALLOW = "allow"
    REFUSE = "refuse"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str = ""


def screen(body: str, *, env_root: str) -> Decision:
    """Inspect a program body before execution.

    Refuses, at minimum: writes outside `env_root`, force-pushes to any remote
    not recognised as a sandbox, credential or environment-variable reads, and
    outbound network calls. Everything else runs inside the sandbox.
    """
    raise NotImplementedError("implemented per plan: phase 3")


def prepare_dry_run(program, env) -> Decision:
    """Report what a program would do, without letting it do it.

    Git has no general dry-run, so this is implemented by running the body
    against a copy of the environment and diffing — the copy is discarded.
    """
    raise NotImplementedError("implemented per plan: phase 3")
