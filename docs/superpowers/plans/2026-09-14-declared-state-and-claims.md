# Declared State and Claims Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the *checkable* subset of status claims fail CI when they go stale, so a stub that gets implemented or a test that gets un-skipped cannot leave prose behind it.

**Architecture:** Invert the direction. Do not check the prose against the code — instead **assert the declared state against the code**: an explicit inventory of every stub and every skipped test, plus a small hand-picked table pairing a quoted sentence in a document with the mechanical fact that must hold while that sentence is there. Implementing a stub, un-skipping a test, or changing an excluded set then fails a test until the declaration is updated, and updating the declaration is the moment the prose should be updated too.

**Tech Stack:** Python 3.12, `ast` from the stdlib (no markdown parser, no new dependency), pytest. One test file, no new source module.

---

## Scope: what this catches, and what it does not

Four instances of prose drift were found by hand this session: `library/README.md` contradicting its own status table; the spec claiming a rejected program is "not stored" while `library.py` stores candidates; the README claiming the gold check "runs today" while that test is skipped; a test docstring describing injectors as stubs after they existed.

They are not one class, and only some are mechanizable:

| class | example | this plan |
| --- | --- | --- |
| a doc contradicting **another doc** | `library/README.md` rule 1 vs its status table | **not caught.** Semantic; stays a review obligation |
| a doc whose **meaning** contradicts the code | spec "not stored" vs `add` storing candidates | **not caught.** Same reason |
| a doc asserting a **state that changed** | README "gold check runs today" while it is skipped | **caught**, when the claim is in the table |
| a **skip or stub that disappeared** silently | injectors implemented, docstring still said stub | **caught**, by the inventory |

So: the inventory is general and needs no maintenance beyond the moment of change; the claims table only covers what someone has explicitly pinned, and its value grows one row at a time. Say both plainly in the docs (Task 4) — a mechanism that oversells itself is the same defect in a new place.

---

## File structure

| File | Responsibility |
| --- | --- |
| `tests/test_declared_state.py` | **Create.** The `ast` collectors, the declared stub inventory, the declared skip inventory, and the claims table. One file: the declaration must sit next to the assertion that reads it, so it is visible in review and cheap to edit. |
| `tests/test_checkers_against_gold.py` | **Modify.** Its skip reason still says "faults and gold solutions are stubs; implemented per plan, phase 1" — stale, and it must name the issue that will implement it, which Task 2 asserts for every skip. |
| `CONTRIBUTING.md` | **Modify.** Rule: status lives in one place; other documents link rather than restate. States the limit of the mechanism. |
| `docs/superpowers/specs/2026-09-13-precondition-library-design.md` | **Modify.** §10 gains the automation and its limit. |
| `CHANGELOG.md` | **Modify.** One `Added` line. |

---

### Task 1: The stub inventory

**Files:**
- Create: `tests/test_declared_state.py`

- [ ] **Step 1: Write the collectors and a test with an empty declaration**

Create `tests/test_declared_state.py`:

```python
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


def test_every_stub_is_declared() -> None:
    """Each stub is declared, and each declaration is still a stub.

    A stub that vanished without its declaration being updated means someone
    implemented something and left every document that described it as pending
    exactly as it was.
    """
    assert set(stubs()) == set(DECLARED_STUBS), _stub_delta()


def _stub_delta() -> str:
    actual, declared = stubs(), DECLARED_STUBS
    lines = ["", "stubs in src/ that are not declared:"]
    lines += [f"  + {name}" for name in sorted(set(actual) - set(declared))] or ["  (none)"]
    lines += ["declarations that are no longer stubs:"]
    lines += [f"  - {name}" for name in sorted(set(declared) - set(actual))] or ["  (none)"]
    lines += [
        "",
        "Paste the '+' names into DECLARED_STUBS, each mapped to the issue that",
        "will implement it, and delete the '-' names after updating whatever prose",
        "described them as pending.",
    ]
    return "\n".join(lines)


DECLARED_STUBS: dict[str, str] = {}
```

- [ ] **Step 2: Run it, and read the failure as the inventory**

Run: `uv run pytest tests/test_declared_state.py -v`
Expected: FAIL, listing every stub under `stubs in src/ that are not declared:` — **17** of them at the time of writing, because `src/` declares no stubs here yet.

- [ ] **Step 3: Declare them**

Replace `DECLARED_STUBS: dict[str, str] = {}` with the seventeen names the failure printed, each mapped to what will remove it. The values are the record of what is outstanding, so they must be actionable — an issue number, or a short note when the stub is deliberate rather than pending. Expected set:

```python
DECLARED_STUBS: dict[str, str] = {
    # The dispatch arms and the benchmark harness: issue #5.
    "precondition_library.agents.dispatch.dispatch_semantic": "#5",
    "precondition_library.agents.dispatch.dispatch_preconditions": "#5",
    "precondition_library.bench.report.ablation_table": "#5",
    "precondition_library.bench.report.cost_curve": "#5",
    "precondition_library.bench.report.mismatch_comparison": "#5",
    "precondition_library.bench.report.write_report": "#5",
    "precondition_library.bench.run.run_benchmark": "#5",
    "precondition_library.bench.run.run_episode": "#5",
    "precondition_library.bench.ledger.append": "#5",
    "precondition_library.bench.ledger.read": "#5",
    "precondition_library.library.Library.match_semantic": "#5",
    "precondition_library.library.Library.match_preconditions": "#5",
    "precondition_library.program.Program.applicable": "#5",
    # The admission path (issue #4) is the first caller that needs a dry run.
    "precondition_library.runtime.guard.prepare_dry_run": "#4",
}
```

**Reconcile this against what Step 2 actually printed, and do not paste a name you did not see.** The plan's list is a starting point, not the source of truth; the printed set is. Three further entries are expected and are **not** pending work — the base class's abstract placeholders, which every fault overrides, so they are deliberate rather than outstanding:

```python
    # Not pending: the base contract. Every fault overrides these, so the base
    # bodies are unreachable placeholders. A fault that forgot to override one
    # would raise at injection time, which its own sandbox test would catch.
    "precondition_library.tasks.spec.FaultSpec.inject": "abstract placeholder",
    "precondition_library.tasks.spec.FaultSpec.task_text": "abstract placeholder",
    "precondition_library.tasks.spec.FaultSpec.check": "abstract placeholder",
```

If the printed set is larger than these, that is a finding: declare the extra names with their issue and say so in your report.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_declared_state.py -v`
Expected: PASS, 1 test.

- [ ] **Step 5: Verify the test can fail**

Run: `uv run python -c "import ast,pathlib; p=pathlib.Path('src/precondition_library/program.py'); t=ast.parse(p.read_text()); print('about to tamper')"` and then, having made a copy, delete the `raise NotImplementedError(...)` line from `Program.applicable` in a scratch copy under `/tmp` — do not edit the repo. Confirm by reasoning and say so: the test compares two sets, so removing a stub makes the declaration the larger one and the assertion fails with the `-` line naming it.

Then restore nothing, because you never touched the repo. Confirm `git status` is clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_declared_state.py
git commit -m "test(docs): declare every stub, so implementing one cannot go unnoticed"
```

---

### Task 2: The skip inventory

**Files:**
- Modify: `tests/test_declared_state.py`
- Modify: `tests/test_checkers_against_gold.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_declared_state.py`:

```python
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
    is a real gap and is why the declared set is asserted rather than the count.
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

    A skip is a claim that something cannot run yet. A claim with no issue behind
    it is a claim nobody has agreed to discharge.
    """
    actual = skips()
    assert set(actual) == set(DECLARED_SKIPS), (
        f"\nactual:   {sorted(actual)}\ndeclared: {sorted(DECLARED_SKIPS)}"
    )
    for node_id, reason in actual.items():
        assert "#" in reason, f"{node_id}: reason must name the issue that removes it"


DECLARED_SKIPS: dict[str, str] = {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_declared_state.py -v -k skip_is_declared`
Expected: FAIL listing two node ids.

- [ ] **Step 3: Make the reasons actionable, then declare them**

`tests/test_checkers_against_gold.py` carries two skip decorators whose reason reads "faults and gold solutions are stubs; implemented per plan, phase 1". That is stale twice over: gold solutions exist for the two intents, and a live sandbox exists, so the checkers *could* now be validated for those two — the reason no longer describes the world. Replace both reasons with one that names what is actually missing:

```python
@pytest.mark.skip(
    reason="checker execution needs a live fault per fault; the two intents with gold "
    "solutions can be validated once issue #4 wires admission to the sandbox"
)
```

Then declare the two entries, using the ids the failure printed for the file and function names:

```python
DECLARED_SKIPS: dict[str, str] = {
    # Two functions, each parametrised over every fault: ten skips in the report.
    "test_checkers_against_gold.py::test_checker_accepts_gold_solution": "#4",
    "test_checkers_against_gold.py::test_checker_rejects_untouched_sandbox": "#4",
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_declared_state.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Confirm the reason check is load-bearing**

Reasoning, not a repo edit: the assertion `"#" in reason` fails for any skip whose reason names no issue. Note in your report that this is the clause which would have caught the stale phase-1 reason.

- [ ] **Step 6: Commit**

```bash
git add tests/test_declared_state.py tests/test_checkers_against_gold.py
git commit -m "test(docs): declare every skip and require its reason to name an issue"
```

---

### Task 3: The claims table

**Files:**
- Modify: `tests/test_declared_state.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
@dataclass(frozen=True)
class Claim:
    """A quoted sentence in a document, and the fact that must hold while it is there."""

    document: str
    """Path relative to the repository root."""
    quote: str
    """Verbatim. The row is dead weight if the sentence is not there, so its absence fails."""

    holds: Callable[[], bool]

    update: str
    """What to do when the fact stops holding: which sentence to rewrite, and how."""


CLAIMS: list[Claim] = [
    Claim(
        document="bench/gold/README.md",
        quote="No probe has ever been executed against a sandbox",
        holds=lambda: any(
            node_id.startswith("test_checkers_against_gold.py::") for node_id in skips()
        ),
        update=(
            "The gold checkers now run. Rewrite the sentence in bench/gold/README.md "
            "that says no probe has been executed, and the matching line in README.md."
        ),
    ),
    Claim(
        document="docs/superpowers/specs/2026-09-13-precondition-library-design.md",
        quote="but no checker has run against",
        holds=lambda: any(
            node_id.startswith("test_checkers_against_gold.py::") for node_id in skips()
        ),
        update="A checker has run. Correct the §10 testing block, which still says none has.",
    ),
    Claim(
        document="src/precondition_library/runtime/guard.py",
        quote="Nothing consumes this yet.",
        holds=lambda: "precondition_library.runtime.guard.prepare_dry_run" in stubs(),
        update=(
            "prepare_dry_run has a caller. Delete that sentence from its docstring; it "
            "exists to tell a reader the function is unreachable, and it no longer is."
        ),
    ),
    Claim(
        document="src/precondition_library/tasks/registry.py",
        quote="Faults that must never be measured",
        holds=lambda: len(EXCLUDED_FROM_BENCHMARK) == 3,
        update=(
            "The excluded set changed size. Check every document that says three faults "
            "are excluded -- the spec's open risk 6 and §10 -- and correct the count."
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
```

- [ ] **Step 2: Run it to verify it fails for the right reason**

Run: `uv run pytest tests/test_declared_state.py -v -k claims`
Expected: FAIL only if a quote is not verbatim in its document. If every row passes immediately, that is the correct outcome here — these four facts are true today — but you must then verify the mechanism by falsifying one row in a scratch copy: change `len(EXCLUDED_FROM_BENCHMARK) == 3` to `== 4` in a copy under `/tmp`, run the test, and confirm it fails naming that document. Report the evidence either way. Do not edit the repo to falsify.

- [ ] **Step 3: Verify the quotes are verbatim**

Run:
```bash
grep -c "No probe has ever been executed against a sandbox" bench/gold/README.md
grep -c "but no checker has run against" docs/superpowers/specs/2026-09-13-precondition-library-design.md
grep -c "Nothing consumes this yet." src/precondition_library/runtime/guard.py
grep -c "Faults that must never be measured" src/precondition_library/tasks/registry.py
```
Expected: each prints `1`. If any prints `0`, the quote drifted — fix the quote, not the document.

- [ ] **Step 4: Run the whole file**

Run: `uv run pytest tests/test_declared_state.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_declared_state.py
git commit -m "test(docs): pin the status claims that reduce to a mechanical fact"
```

---

### Task 4: Documentation, and the whole suite

**Files:**
- Modify: `CONTRIBUTING.md`
- Modify: `docs/superpowers/specs/2026-09-13-precondition-library-design.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the CONTRIBUTING rule**

In `CONTRIBUTING.md`, insert after rule 4 ("Stubs and skips are described as such"):

```markdown
### 5. Status lives in one place

A document must not restate whether something is implemented. It either links to
the declared inventory in `tests/test_declared_state.py` — which CI checks against
the code — or states the claim in that file's claims table, where the fact behind it
is asserted.

**Why:** prose describing the code drifts the moment the code moves, and nothing
fails. Four instances were found by hand: a README rule contradicting its own status
table, the spec saying a rejected program is not stored while `library.py` stores
it, the README claiming the gold check runs while its test is skipped, and a
docstring describing injectors as stubs after they existed.

**What that inventory cannot do, and this rule therefore cannot replace:** find a
document that contradicts another document, or one whose meaning contradicts the
code. Those are semantic and remain a review obligation. Pin only claims that
reduce to a mechanical fact; do not add a row that restates a sentence without
checking anything behind it.
```

Renumber the rules that follow (the existing 5 becomes 6, and so on).

- [ ] **Step 2: Note the mechanism in the spec's testing section**

In §10, add to the code block:

```
DECLARED STATE  every stub and every skipped test is declared in
                tests/test_declared_state.py, and the declaration is asserted
                against the code, so implementing a stub or un-skipping a test
                fails CI until the declaration -- and the prose that restated it --
                is updated. A small claims table pins the status sentences that
                reduce to a mechanical fact. It cannot detect a document
                contradicting another document, or the code's meaning.
```

- [ ] **Step 3: Add the changelog line**

Under `## Unreleased` → `### Added`:

```markdown
- `tests/test_declared_state.py`: every stub and every skipped test is declared and
  asserted against the code, so implementing one fails CI until the declaration and
  the prose that restated it are updated. Four status claims are pinned to the facts
  behind them. It deliberately does not attempt to detect a document contradicting
  another document — that stays a review obligation, and the file says so.
```

- [ ] **Step 4: Run the whole suite, lint, and types**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -o addopts="" -q
```

Expected: format leaves files unchanged after the first run; ruff passes; mypy is clean on 30 files; pytest is `252 passed, 10 skipped` (249 + 3 new) with the skipped count **unchanged** — this plan declares skips, it does not remove any. Report the actual numbers, and if the count differs from 10, say why.

- [ ] **Step 5: Commit and open the PR**

```bash
git add CONTRIBUTING.md docs/superpowers/specs/2026-09-13-precondition-library-design.md CHANGELOG.md
git commit -m "docs: state where status lives, and what the declaration cannot check"
git push -u origin pr/NN-declared-state
gh pr create --base main --title "test(docs): declare stubs and skips so status cannot drift silently" \
  --body "References #NN. <fill in the PR template>"
```

Push the plan document itself in the same PR, since it is the reasoning behind it. `main` is protected: the PR links its issue, passes CI, and is rebase-merged. See `CONTRIBUTING.md`.

---

## Self-review

**Coverage against the stated scope.** The four observed instances map as follows: the two semantic ones (doc vs doc, doc-meaning vs code) are **deliberately not covered** and said so in §Scope and in both Task 4 documents; the two currency ones (a status claim that changed, a stub that silently disappeared) are covered by the inventory (Tasks 1–2) and the claims table (Task 3). Nothing in the plan claims to fix prose drift generally.

**Placeholder scan.** One instruction asks the implementer to reconcile a list against observed output (Task 1 Step 3) rather than transcribing it: that is deliberate, because the printed set is the source of truth and a transcribed set would be a second place to be wrong. Every code block is complete and runnable; there are no TBDs.

**Type consistency.** `_not_implemented_message`, `_stubs_in`, `stubs`, `_is_skip_decorator`, `_skip_reason`, `skips`, `Claim`, `CLAIMS`, `DECLARED_STUBS`, `DECLARED_SKIPS` are each defined once and referenced with that exact name. `Claim.holds` is `Callable[[], bool]` and every row is a zero-argument lambda closing over `skips()`, `stubs()` or `EXCLUDED_FROM_BENCHMARK`. `ROOT`, `SRC` and `TESTS` are defined in Task 1 and used by Task 2's `skips()` and Task 3's claim reader.

**Two gaps this plan names rather than hides.** `pytest.skip()` called inside a test body is invisible to the AST scan, so the declared set is asserted rather than a count — a body-level skip added tomorrow would not be caught. And the claims table only covers what someone pins; its coverage grows one deliberate row at a time.
