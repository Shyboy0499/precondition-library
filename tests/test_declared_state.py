"""Status claims must not drift silently.

Twice this repository's prose described something as unimplemented after it was
implemented, and one document contradicted its own status table. Nothing failed,
because tests do not read prose and no test notices a stub that disappears.

So the direction is inverted here: the code is not checked against the prose, the
*declared state* is checked against the code. Implementing a stub or un-skipping a
test fails a test in this file until the declaration below is updated -- and the
moment someone updates the declaration is the moment they should update the prose
that restated it.

What this file cannot do, stated rather than implied: it cannot find a document
that contradicts another document, or one whose meaning contradicts the code. Those
are semantic and remain a review obligation. Only claims that reduce to a
mechanical fact about this repository are pinned here.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from precondition_library.tasks.registry import EXCLUDED_FROM_BENCHMARK

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts)


def _not_implemented_message(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The message of a body that is exactly `raise NotImplementedError(...)`, else None.

    A leading docstring is ignored: the stubs in this repository carry one, and a
    docstring is not an implementation.
    """
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Raise):
        return None
    call = body[0].exc
    if not isinstance(call, ast.Call) or getattr(call.func, "id", None) != "NotImplementedError":
        return None
    if not call.args:
        return ""
    argument = call.args[0]
    return argument.value if isinstance(argument, ast.Constant) else ""


def _stubs_in(tree: ast.Module, prefix: str) -> dict[str, str]:
    """{qualified name: message} for every stub in one module."""
    found: dict[str, str] = {}

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            child_scope = scope
            if isinstance(child, ast.ClassDef):
                child_scope = f"{scope}.{child.name}" if scope else child.name
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_scope = f"{scope}.{child.name}" if scope else child.name
                message = _not_implemented_message(child)
                if message is not None:
                    found[child_scope] = message
            visit(child, child_scope)

    visit(tree, prefix)
    return found


def stubs() -> dict[str, str]:
    """Every stub in `src/`, keyed by qualified name."""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        found.update(_stubs_in(ast.parse(path.read_text(encoding="utf-8")), _module_name(path)))
    return found


def _stub_delta() -> str:
    actual = set(stubs())
    declared = set(DECLARED_STUBS)
    lines = ["", "stubs in src/ that are not declared:"]
    lines += [f"  + {name}" for name in sorted(actual - declared)] or ["  (none)"]
    lines += ["declarations that are no longer stubs:"]
    lines += [f"  - {name}" for name in sorted(declared - actual)] or ["  (none)"]
    lines += [
        "",
        "Paste the '+' names into DECLARED_STUBS, each mapped to the issue that",
        "will implement it, and delete the '-' names after updating whatever prose",
        "described them as pending.",
    ]
    return "\n".join(lines)


def test_every_stub_is_declared() -> None:
    """Each stub is declared, and each declaration is still a stub.

    A stub that vanished without its declaration being updated means someone
    implemented something and left every document that described it as pending
    exactly as it was.
    """
    assert set(stubs()) == set(DECLARED_STUBS), _stub_delta()


DECLARED_STUBS: dict[str, str] = {
    # The dispatch arms and the benchmark harness that runs them: issue #5.
    "precondition_library.agents.dispatch.dispatch_preconditions": "#5",
    "precondition_library.agents.dispatch.dispatch_semantic": "#5",
    "precondition_library.bench.ledger.append": "#5",
    "precondition_library.bench.ledger.read": "#5",
    "precondition_library.bench.report.ablation_table": "#5",
    "precondition_library.bench.report.cost_curve": "#5",
    "precondition_library.bench.report.mismatch_comparison": "#5",
    "precondition_library.bench.report.write_report": "#5",
    "precondition_library.bench.run.run_benchmark": "#5",
    "precondition_library.bench.run.run_episode": "#5",
    "precondition_library.library.Library.match_semantic": "#5",
    # The admission path (issue #4) is the first caller that needs a dry run.
    "precondition_library.runtime.guard.prepare_dry_run": "#4",
    # Not pending work: the base contract. Every fault overrides these, so the
    # base bodies are unreachable placeholders. A fault that forgot to override
    # one would raise at injection time, which its own sandbox test would catch.
    "precondition_library.tasks.spec.FaultSpec.check": "abstract placeholder",
    "precondition_library.tasks.spec.FaultSpec.inject": "abstract placeholder",
    "precondition_library.tasks.spec.FaultSpec.task_text": "abstract placeholder",
}


def _is_skip_decorator(decorator: ast.expr) -> bool:
    """True for a `pytest.mark.skip(...)` decorator, in either call or bare form."""
    call = decorator if isinstance(decorator, ast.Call) else None
    target: ast.expr = call.func if call is not None else decorator
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "skip"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
    )


def _skip_reason(decorator: ast.expr) -> str:
    if not isinstance(decorator, ast.Call):
        return ""
    for keyword in decorator.keywords:
        if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return ""


def skips() -> dict[str, str]:
    """{file::function: reason} for every test carrying a skip decorator.

    Decorators only. `pytest.skip()` called inside a body is invisible here, which
    is a real gap -- which is why the declared set is asserted rather than a count.
    """
    found: dict[str, str] = {}
    for path in sorted(TESTS.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if _is_skip_decorator(decorator):
                    found[f"{path.name}::{node.name}"] = _skip_reason(decorator)
    return found


def test_every_skip_is_declared_and_actionable() -> None:
    """Each skip is declared, and each reason says what will remove it.

    A skip is a claim that something cannot run yet. A claim with no issue behind it
    is a claim nobody has agreed to discharge.
    """
    actual = skips()
    assert set(actual) == set(DECLARED_SKIPS), (
        f"\nactual:   {sorted(actual)}\ndeclared: {sorted(DECLARED_SKIPS)}"
    )
    for node_id, reason in actual.items():
        assert "#" in reason, f"{node_id}: reason must name the issue that removes it"


DECLARED_SKIPS: dict[str, str] = {
    # Two functions, each parametrised over every fault: ten skips in the report.
    "test_checkers_against_gold.py::test_checker_accepts_gold_solution": "#9",
    "test_checkers_against_gold.py::test_checker_rejects_untouched_sandbox": "#9",
}


@dataclass(frozen=True)
class Claim:
    """A quoted sentence in a document, and the fact that must hold while it is there."""

    document: str
    """Path relative to the repository root."""
    quote: str
    """Verbatim. The row is dead weight if the sentence is gone, so its absence fails."""
    holds: Callable[[], bool]
    update: str
    """What to do when the fact stops holding: which sentence to rewrite, and how."""


def _gold_checkers_are_skipped() -> bool:
    return any(node_id.startswith("test_checkers_against_gold.py::") for node_id in skips())


CLAIMS: list[Claim] = [
    Claim(
        document="bench/gold/README.md",
        quote="No probe has ever been executed against a sandbox",
        holds=_gold_checkers_are_skipped,
        update=(
            "The gold checkers now run. Rewrite the sentence in bench/gold/README.md "
            "that says no probe has been executed, and the matching line in README.md."
        ),
    ),
    Claim(
        document="docs/superpowers/specs/2026-09-13-precondition-library-design.md",
        quote="but no checker has run against",
        holds=_gold_checkers_are_skipped,
        update="A checker has run. Correct the testing block in §10, which still says none has.",
    ),
    Claim(
        document="src/precondition_library/runtime/guard.py",
        quote="Nothing consumes this yet.",
        holds=lambda: "precondition_library.runtime.guard.prepare_dry_run" in stubs(),
        update=(
            "prepare_dry_run has a caller. Delete that sentence from its docstring: it "
            "exists to tell a reader the function is unreachable, and it no longer is."
        ),
    ),
    Claim(
        document="src/precondition_library/tasks/registry.py",
        quote="Faults that must never be measured",
        holds=lambda: len(EXCLUDED_FROM_BENCHMARK) == 3,
        update=(
            "The excluded set changed size. Check every document that says three faults "
            "are excluded -- the spec's open risk 6 and the testing block in §10 -- and "
            "correct the count."
        ),
    ),
]


def test_claims_are_still_true() -> None:
    """Each pinned sentence is present, and the fact behind it still holds."""
    for claim in CLAIMS:
        text = (ROOT / claim.document).read_text(encoding="utf-8")
        assert claim.quote in text, (
            f"{claim.document}: the pinned sentence is gone -- {claim.quote!r}. Either "
            f"restore it or delete this row; a row pinning nothing is worse than no row."
        )
        assert claim.holds(), f"{claim.document}: stale claim -- {claim.update}"
