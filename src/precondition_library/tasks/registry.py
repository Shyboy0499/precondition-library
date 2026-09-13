"""Which task families are usable, and which have an experimental surface.

Only ambiguous intents -- two or more correct resolutions -- can support a claim
about dispatch. A single-resolution intent is still a legitimate task, but on it
both dispatchers have the same single answer available and the comparison says
nothing. Keeping the distinction in one place stops an unambiguous intent being
counted into a rate as if it were evidence.
"""

from __future__ import annotations

from .faults.diverged import INTENT as DIVERGED_INTENT
from .faults.submodule_moved import INTENT as SUBMODULE_INTENT
from .intent import IntentSpec

INTENTS: dict[str, IntentSpec] = {
    intent.name: intent for intent in (DIVERGED_INTENT, SUBMODULE_INTENT)
}


def ambiguous_intents() -> list[IntentSpec]:
    """Intents with at least two correct resolutions, sorted by name."""
    return sorted(
        (intent for intent in INTENTS.values() if intent.is_ambiguous),
        key=lambda intent: intent.name,
    )


__all__ = ["INTENTS", "ambiguous_intents"]
