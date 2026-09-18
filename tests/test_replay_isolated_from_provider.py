"""Boundaries that must stay closed, asserted against the import graph.

A boundary here is a claim that would go false without breaking any obvious test,
because the breach is one import rather than one behaviour. So each is checked
structurally, by walking the graph from source with `ast`: a function-local or
`if False:` import is seen like any other, and transitivity is handled, so a helper
module in the middle cannot hide the edge.

Two classes of boundary are guarded.

**Cost.** Neither `runtime.replay` nor `library` may reach `provider`. A replay
episode costs zero tokens, and so does a dispatch decision; if either could call a
model, the central cost claim would be void. `library` is the boundary a
foreseeable change would breach: arm 2's mechanism is a lexical proxy today and the
intended replacement is an embedding model, so that swap is exactly the edit that
would import an API client into the library.

**Ground truth.** `tasks.faults` may reach neither `program` nor `runtime` (#9).
The fault checkers grade an episode's outcome, and `program` is the artifact
contract -- `Program`, and the `Predicate` type its postconditions are made of. If
a checker could reach it, ground truth could be evaluated from a program's own
claim of done, and the artifact would define its own correctness: the mismatch
column the whole comparison rests on would measure nothing. `runtime` is listed
because it is the machinery that gives a predicate its meaning, so reaching it is
the same collapse by another route. This is #9's second item -- ground truth is not
the admission postconditions -- pinned as unreachability rather than resemblance.

Parameterised over `(entry, forbidden)` so every boundary is checked by one walker
rather than a copy each that could drift.

The module name records the first boundary only; the other two live here because
they are the same kind of guard -- an invariant that one import would break
silently -- and a second copy of this walker would be the thing that drifts. The
spec's "IMPORT GRAPH" mechanism points at this file.

This test is deliberately implemented while nearly everything else is a stub: it
is the guardrail, and a guardrail that arrives with the implementation is not a
guardrail.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PKG = SRC / "precondition_library"

BOUNDARIES: list[tuple[str, str]] = [
    ("precondition_library.runtime.replay", "precondition_library.provider"),
    ("precondition_library.library", "precondition_library.provider"),
    ("precondition_library.tasks.faults", "precondition_library.program"),
    ("precondition_library.tasks.faults", "precondition_library.runtime"),
]
"""`(entry, forbidden)`: `forbidden` must not be reachable from `entry`.

Both entries are real modules the suite asserts exist, so a rename fails loudly
instead of making the reachability walk pass vacuously.
"""


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    """Absolute module names this file references, with relative imports resolved."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    tree = ast.parse(path.read_text(encoding="utf-8"))

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)])
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _graph() -> dict[str, set[str]]:
    return {_module_name(p): _imports(p) for p in PKG.rglob("*.py")}


def _reachable(graph: dict[str, set[str]], entry: str) -> set[str]:
    seen: set[str] = set()
    stack = [entry]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(target for target in graph.get(current, set()) if target in graph)
    return seen


@pytest.mark.parametrize(("entry", "forbidden"), BOUNDARIES)
def test_entry_module_exists(entry: str, forbidden: str) -> None:
    """Fails loudly if either entry module moves, rather than passing vacuously."""
    assert entry in _graph()


@pytest.mark.parametrize(("entry", "forbidden"), BOUNDARIES)
def test_entry_cannot_reach_forbidden(entry: str, forbidden: str) -> None:
    """No path in the import graph leads from `entry` to `forbidden`."""
    graph = _graph()
    reachable = _reachable(graph, entry)
    assert forbidden not in reachable, (
        f"{forbidden} became reachable from {entry}. For the cost boundaries that "
        f"means a replay or a dispatch decision could spend tokens; for the ground "
        f"truth boundaries it means a fault checker could read the artifact it "
        f"grades, so the artifact would define its own correctness. Either way the "
        f"claim the boundary carries is now void. Reachable set: {sorted(reachable)}"
    )
