"""What a merge attempt returns."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Merged:
    """The merged file's text."""

    text: str


@dataclass(frozen=True)
class Declined:
    """No safe automatic merge; `reasons` say why, one line each."""

    reasons: list[str] = field(default_factory=list)
    diverged: bool = False
    """At least one package was changed differently on both sides."""
    inconsistent: bool = False
    """The entries merged, but the result would break a dependency neither side broke."""


Outcome = Merged | Declined
