"""Two boundaries must stay closed: neither replay nor the library may reach a model.

A replay episode costs zero tokens, and so does a dispatch decision. Both claims
are structural, not behavioural: an import that makes `provider` reachable from
`runtime.replay` or from `library` would make the claim false without breaking any
obvious test, so the invariants are asserted against the import graph instead of
trusted.

The two boundaries guarded here, and why exactly these:

* `runtime.replay` must not reach `provider`. If it could, a replay could call a
  model and the central cost claim -- a stored program is executed with no LLM in
  the loop -- would be void.
* `library` must not reach `provider`. This is what makes *both* dispatch arms'
  decisions cost zero tokens: an episode that dispatches (hit or miss) spends
  nothing on the choice. It is also the boundary a foreseeable change would
  breach: arm 2's mechanism is a lexical proxy today and the intended replacement
  is an embedding model, so the swap is exactly the edit that would import an API
  client into the library.

Parameterised over `(entry, forbidden)` so both are checked by one walker rather
than two copies that could drift. The graph is walked from source with `ast`, not
read by eye, so a function-local or `if False:` import is seen like any other.

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
def test_entry_cannot_reach_provider(entry: str, forbidden: str) -> None:
    """No path in the import graph leads from `entry` to `forbidden`."""
    graph = _graph()
    reachable = _reachable(graph, entry)
    assert forbidden not in reachable, (
        f"{forbidden} became reachable from {entry}; either a replay or a dispatch "
        f"decision could now spend tokens and the claim would be void. Reachable "
        f"set: {sorted(reachable)}"
    )
