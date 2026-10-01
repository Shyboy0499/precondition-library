"""Arm 2c's mechanism: dispatch by the request string itself (issue #7, ADR-0015).

The cheapest credible competitor to both dispatchers is a lookup table: normalise
the request, and fire the program that was compiled from a request with the same
normalised text. It reads neither the environment (arm 3) nor a similarity score
(arm 2), so if it ties either of them, the comparison was not measuring what it
claimed to.

Two definitions live here, shared by `Library.match_intent_key` (the episodes) and
`bench.coverage.intent_key_outcomes` (the labelled pairs), so the arm the episodes
run and the arm the primary metric measures cannot drift apart:

* **The key** (`intent_key`). Lower-cased, with slot values abstracted into
  placeholders -- quoted strings, path-like tokens, commit ids, numbers -- and
  punctuation dropped, so "Sync `main` with upstream." and "sync `dev` with
  upstream" share a key. That is the "parameterised" half of #7's "exact/
  parameterised intent-key dispatch". On this task family it is mostly
  normalisation: the request phrasings name no paths, branches or commits, so the
  slot abstraction is stated and tested rather than load-bearing.
* **The abstain rule** (`agreeing`). A program's key is the key of the request it
  was compiled from (`Provenance.compiled_from_task`). When every admitted program
  under a key implements one variant, the key fires; when they implement two or
  more, it **abstains** and the caller falls back. The owner's choice (ADR-0015):
  it decides from the library alone, without ground truth, and it is the strongest
  fair version of a lookup -- "last write wins" would misfire by construction on a
  phrasing that recurs across states needing different resolutions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .program import Program, ProgramStatus

_QUOTED = re.compile(r"(['\"`])(?:(?!\1).)+\1")
_PATH = re.compile(r"\S*/\S*")
# A commit id is hex with at least one digit, so an all-letter hex word such as
# "defaced" is not mistaken for one.
_COMMIT = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
_NUMBER = re.compile(r"\b\d+\b")
_NOISE = re.compile(r"[^a-z0-9<> ]+")
_SPACE = re.compile(r"\s+")


def intent_key(text: str) -> str:
    """The lookup key for a request: lower-cased, slot values abstracted, punctuation gone.

    Slots are replaced in a fixed order -- quoted strings first, so a quoted path is
    one slot rather than a quote around a path -- and only then is punctuation
    dropped, so a placeholder's angle brackets survive and a slot can never be
    mistaken for a word of the same spelling.
    """
    lowered = text.lower()
    lowered = _QUOTED.sub(" <str> ", lowered)
    lowered = _PATH.sub(" <path> ", lowered)
    lowered = _COMMIT.sub(" <commit> ", lowered)
    lowered = _NUMBER.sub(" <n> ", lowered)
    lowered = _NOISE.sub(" ", lowered)
    return _SPACE.sub(" ", lowered).strip()


def agreeing(programs: Iterable[Program], request: str) -> list[Program]:
    """The admitted programs stored under `request`'s key, or `[]` if they disagree.

    "Stored under" means compiled from a request with the same key. The result is
    sorted by id, so the first element -- the one a dispatcher fires -- is stable;
    every element implements the same variant, so which of them fires changes the
    program run but not the resolution. `[]` covers both a key nothing was compiled
    from and a key whose programs implement two or more variants: either way the
    lookup has no single answer and the caller falls back.

    Eligibility is `admitted` and nothing else, the same filter both other
    dispatchers apply (`library/README.md` rule 1).
    """
    key = intent_key(request)
    keyed = sorted(
        (
            program
            for program in programs
            if program.status is ProgramStatus.ADMITTED
            and intent_key(program.provenance.compiled_from_task) == key
        ),
        key=lambda program: program.id,
    )
    if len({program.variant for program in keyed}) > 1:
        return []
    return keyed
