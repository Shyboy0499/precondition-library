"""Intents with more than one correct resolution.

The flaw this module removes: when a fault's request is a single fixed sentence,
the text *is* the class label, so a dispatcher that reads only the text cannot
mis-fire and the primary claim is untestable. 60 episodes would produce a number
that looks like a result while measuring nothing.

An `IntentSpec` separates four things that were previously one:

  the request      a paraphrase distribution sampled by seed. A reported fraction
                   of samples do not name the fault at all.
  the state        a `StateFingerprint`, produced by the environment, not the request.
  the resolution   which of >=2 bodies is correct, decided ONLY by the state.
  the wording      when the state is already known, `variant_phrasings` may supply
                   *informed* wording that reveals the situation to a careful
                   reader, as a real user's description often does. State may
                   reach the request ONLY through this declared map.

The resolution is a pure function of state, but the wording is not: informed
wording is allowed to carry a signal about the resolution, because that is what a
real request does. The control in bench/textcontrol.py measures that signal in two
regimes: *uninformed* requests (the shared distribution, sampled with no state)
must not leak the resolution, and *informed* requests are reported as the boundary
condition -- the regime where the wording nearly gives the answer away and no
mechanism is needed -- without being gated.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..signatures import StateFingerprint


def sample_index(seed: int, salt: str, n: int) -> int:
    """Deterministic index in [0, n) from (seed, salt).

    Uses sha256 rather than `hash()` because CPython salts `hash()` for strings
    per process, so the same seed would yield different task text in a different
    run -- and the point of a seed is that a reported episode can be reproduced
    exactly. `tests/test_text_determinism.py` pins this with two subprocesses.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    digest = hashlib.sha256(f"{salt}:{seed}".encode()).hexdigest()
    return int(digest, 16) % n


@dataclass(frozen=True)
class ResolutionVariant:
    """One correct way to resolve an intent, and the states it is correct in."""

    id: str
    """Stable identifier, e.g. 'rebase'. Also the value `Program.variant` carries."""

    decided_by: Callable[[StateFingerprint], bool]
    """Ground truth for this variant.

    Deliberately a Python callable over observable state, NOT the program's probe
    strings. Issue #9 requires ground truth and the artifact contract to be
    separate code, so that a wrong precondition cannot make its own program look
    correct -- the failure the whole project measures.
    """

    rationale: str
    """Why this resolution is right in those states, in one sentence.

    Required, not decorative: a variant whose rationale cannot be written in one
    sentence usually means the state does not actually determine the answer, and
    the variant should be redesigned rather than labelled.
    """

    def correct_in(self, state: StateFingerprint) -> bool:
        return self.decided_by(state)


@dataclass(frozen=True)
class IntentSpec:
    """A task family: one request distribution, one or more correct resolutions."""

    name: str
    fault: str
    """The `FaultSpec.name` that injects the states this intent appears in."""

    phrasings: list[str]
    """The paraphrase distribution. The fraction that names the fault is reported
    by `naming_fraction` and asserted below a ceiling."""

    naming_markers: list[str]
    """Substrings whose presence means a phrasing gives the fault away."""

    variants: list[ResolutionVariant]

    variant_phrasings: dict[str, list[str]] = field(default_factory=dict)
    """Wording used when the situation is already known, keyed by resolution id.

    The shared `phrasings` list is the *uninformed* request -- what someone says
    when they do not know what is wrong, or when nothing is wrong. A variant's
    list is the *informed* request: wording that reveals the situation to a
    careful reader, as a real user's description often does ("my edits are in
    files upstream left alone" versus "something is off with my fork").

    State may influence the request ONLY through this declared map. That is what
    `tests/test_task_text_is_not_a_label.py` pins, because an undeclared channel
    from state to wording would quietly restore the original flaw: the text would
    again be a label, and a dispatch comparison would again measure nothing.
    """

    def __post_init__(self) -> None:
        if not self.phrasings:
            raise ValueError(f"{self.name}: needs at least one phrasing")
        if not self.variants:
            raise ValueError(f"{self.name}: needs at least one resolution variant")
        ids = [v.id for v in self.variants]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.name}: duplicate variant ids {ids}")
        unknown = sorted(set(self.variant_phrasings) - set(ids))
        if unknown:
            raise ValueError(f"{self.name}: variant_phrasings for undeclared variants {unknown}")
        empty = sorted(key for key, values in self.variant_phrasings.items() if not values)
        if empty:
            raise ValueError(f"{self.name}: empty variant_phrasings for {empty}")

    @property
    def is_ambiguous(self) -> bool:
        """Ambiguity is the point.

        With two or more resolutions, the request text cannot be sufficient to
        choose, so a dispatch comparison has an experimental surface. With one,
        the intent is still a valid task but proves nothing about dispatch.
        """
        return len(self.variants) > 1

    def informed_phrasings(self, state: StateFingerprint) -> list[str] | None:
        """The variant-specific wording for this state, or None if there is none.

        One place decides which channel a request came from, so the sampler and
        the ledger that records which regime a pair belongs to cannot disagree.
        """
        resolved = self.correct_variant(state)
        if resolved is None:
            return None
        return self.variant_phrasings.get(resolved.id) or None

    def uses_informed_wording(self, state: StateFingerprint) -> bool:
        return self.informed_phrasings(state) is not None

    def task_text(self, seed: int, state: StateFingerprint | None = None) -> str:
        """The request, sampled from a paraphrase distribution.

        With no state, samples the uninformed distribution. With a state, uses
        that state's resolution wording when one is declared, and otherwise falls
        back to the uninformed distribution -- which is also what a benign state
        gets, since there is nothing to describe.

        The informed channel's salt deliberately does NOT include the variant id:
        which wording a seed samples must not depend on which variant happens to
        be correct, or the sampler would leak the label through the seed-to-text
        mapping itself. Two variants declaring the same number of phrasings
        therefore sample the same index, which is what makes a shared phrase
        collide on purpose rather than by accident.
        """
        if state is not None:
            informed = self.informed_phrasings(state)
            if informed:
                return informed[
                    sample_index(seed, f"{self.name}:informed:{len(informed)}:text", len(informed))
                ]
        return self.phrasings[sample_index(seed, f"{self.name}:text", len(self.phrasings))]

    def names_the_fault(self, text: str) -> bool:
        lowered = text.lower()
        return any(marker.lower() in lowered for marker in self.naming_markers)

    def naming_fraction(self, seeds: Iterable[int]) -> float:
        """Fraction of sampled requests that give the fault away.

        Reported and asserted below a ceiling: a distribution that nearly always
        names the fault would reintroduce the original flaw in a more expensive
        way, and it would be invisible without this number.
        """
        texts = [self.task_text(seed) for seed in seeds]
        if not texts:
            raise ValueError("need at least one seed")
        return sum(self.names_the_fault(text) for text in texts) / len(texts)

    def correct_variant(self, state: StateFingerprint) -> ResolutionVariant | None:
        """The unique variant correct in `state`, or None for a benign state.

        None is a labelled outcome, not an error: the environment needs nothing
        done, so every program must refuse to fire. Overlap *is* an error and
        raises, because silently picking the first match would hide a defect
        inside the label that everything downstream depends on.
        """
        matches = [v for v in self.variants if v.correct_in(state)]
        if len(matches) > 1:
            raise ValueError(
                f"{self.name}: state matched {len(matches)} variants "
                f"({[m.id for m in matches]}); decision rules must partition the states"
            )
        return matches[0] if matches else None
