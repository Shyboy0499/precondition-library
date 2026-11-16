"""Task family: seeded, checkable, branchy git maintenance chores."""

from __future__ import annotations

from precondition_library.tasks.faults import ALL as ALL_FAULTS
from precondition_library.tasks.intent import IntentSpec, ResolutionVariant
from precondition_library.tasks.registry import INTENTS, ambiguous_intents
from precondition_library.tasks.spec import FaultSpec, GroundTruth

__all__ = [
    "ALL_FAULTS",
    "INTENTS",
    "FaultSpec",
    "GroundTruth",
    "IntentSpec",
    "ResolutionVariant",
    "ambiguous_intents",
]
