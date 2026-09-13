"""Replay must be structurally incapable of calling a model.

The central claim is that a replay episode costs zero tokens. An import that
makes `provider` reachable from `runtime.replay` would make that claim false
without breaking any obvious test, so the invariant is asserted against the
import graph instead of trusted.

This test is deliberately implemented while nearly everything else is a stub:
it is the guardrail, and a guardrail that arrives with the implementation is
not a guardrail.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PKG = SRC / "precondition_library"
ENTRY = "precondition_library.runtime.replay"
FORBIDDEN = "precondition_library.provider"


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


def test_entry_module_exists() -> None:
    """Fails loudly if runtime/replay.py moves, rather than passing vacuously."""
    assert ENTRY in _graph()


def test_replay_cannot_reach_provider() -> None:
    graph = _graph()
    reachable = _reachable(graph, ENTRY)
    assert FORBIDDEN not in reachable, (
        f"{FORBIDDEN} became reachable from {ENTRY}; a replay episode could now "
        f"spend tokens and the central claim would be void. Reachable set: "
        f"{sorted(reachable)}"
    )
