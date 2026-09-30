"""The {dispatch} x {admission} 2x2 (issue #4, ADR-0010).

The admission factor is the negative-sandbox criterion (Claim 3) against "an otherwise
identical positive-only gate" (spec §3). Pinned here:

* `admit(gate=POSITIVE_ONLY)` skips exactly the negative sandboxes: a program too
  permissive for the two-sided gate is admitted, and the pre-sandbox contract checks
  still refuse what they refuse under both gates.
* `build_library(positive_only_root=...)` compiles once and gates twice, so the two
  libraries hold the same programs and differ only in what each gate admitted.
* A frozen run labels every dispatch row with its library's gate, and
  `admission_factorial` groups the rows into cells -- refusing rows it cannot place.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeProvider, make_record
from test_episode_runner import (
    DISCARD_SEED,
    _completion,
    _discard_program,
    _library_with_admitted,
    _reply_text,
    _resolves_discard,
)

from precondition_library.agents.compile import AdmissionGate, admit
from precondition_library.bench.build_library import build_library
from precondition_library.bench.ledger import Arm, OccurrenceRole, append, read
from precondition_library.bench.report import admission_factorial
from precondition_library.bench.run import MANIFEST, read_admission_gate, run_benchmark
from precondition_library.library import Library
from precondition_library.program import ProgramStatus


def _permissive_discard():
    """`discard` guarded only by "there are local commits": sibling states pass it too.

    Its postcondition holds on the discard state, so the positive side passes; its lone
    precondition also accepts the `merge` and `rebase` states, so the two-sided gate's
    same-intent class must refuse it. That difference is the whole admission factor.
    """
    full = _discard_program()
    return _discard_program(id="permissive-discard", preconditions=full.preconditions[:1])


# --- the gate -------------------------------------------------------------------


def test_positive_only_admits_what_only_the_negative_side_refuses() -> None:
    program = _permissive_discard()
    two_sided, why_not = admit(program, "diverged", seeds=[DISCARD_SEED])
    positive_only, why = admit(
        program, "diverged", seeds=[DISCARD_SEED], gate=AdmissionGate.POSITIVE_ONLY
    )
    assert two_sided is False and "negative side failed" in why_not
    assert positive_only is True and "negative sandboxes were not checked" in why


def test_the_contract_checks_run_under_both_gates() -> None:
    """Only the negative sandboxes differ: an undeclared variant is refused either way."""
    program = _discard_program(id="no-variant", variant=None)
    for gate in AdmissionGate:
        admitted, reason = admit(program, "diverged", seeds=[DISCARD_SEED], gate=gate)
        assert admitted is False and "before any sandbox" in reason


# --- the build: compiled once, gated twice -----------------------------------------


def test_the_build_gates_one_compile_into_two_libraries(tmp_path: Path) -> None:
    provider = FakeProvider(*_resolves_discard(), _completion(_reply_text(_permissive_discard())))
    report = build_library(
        faults=["diverged"],
        root=tmp_path / "gated",
        ledger=tmp_path / "build.jsonl",
        provider=provider,
        model="fake",
        seeds=(DISCARD_SEED,),
        positive_only_root=tmp_path / "ungated",
    )

    assert len(provider.calls) == 4, "one solve and one compile, shared by both gates"
    assert report.positive_only is not None
    (gated,), (ungated,) = report.programs, report.positive_only.programs
    assert gated.program_id == ungated.program_id
    assert (gated.admitted, ungated.admitted) == (False, True)
    assert [p.status for p in Library(tmp_path / "gated").load_all()] == [ProgramStatus.CANDIDATE]
    assert [p.status for p in Library(tmp_path / "ungated").load_all()] == [ProgramStatus.ADMITTED]
    assert read_admission_gate(tmp_path / "gated") is AdmissionGate.TWO_SIDED
    assert read_admission_gate(tmp_path / "ungated") is AdmissionGate.POSITIVE_ONLY
    assert report.library_hash != report.positive_only.library_hash


def test_a_frozen_run_labels_its_rows_with_the_librarys_gate(tmp_path: Path) -> None:
    root = tmp_path / "ungated"
    _library_with_admitted(root, _discard_program())
    (root / MANIFEST).write_text(json.dumps({"admission_gate": "positive_only"}), "utf-8")

    out = run_benchmark(
        arms=[Arm.REACT, Arm.PRECONDITION],
        faults=["diverged"],
        occurrences=1,
        seeds=[DISCARD_SEED],
        out=tmp_path / "ledger.jsonl",
        model="fake",
        provider=FakeProvider(*_resolves_discard()),
        frozen_library=root,
    )

    react, precondition = read(out)
    assert react.admission_gate is None, "arm 1 has no library, so no gate"
    assert precondition.admission_gate == "positive_only"


# --- the table ------------------------------------------------------------------------


def _row(arm: Arm, gate: str | None, fired: str | None, *, library: str, **extra):
    return make_record(
        arm=arm, admission_gate=gate, fired_variant=fired, library_hash=library, **extra
    )


def test_the_factorial_has_one_cell_per_arm_and_gate(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    for record in [
        _row(Arm.SEMANTIC, "two_sided", "merge", library="g"),
        _row(Arm.SEMANTIC, "two_sided", None, library="g"),
        _row(Arm.PRECONDITION, "two_sided", None, library="g"),
        _row(Arm.SEMANTIC, "positive_only", "rebase", library="u"),
        _row(Arm.PRECONDITION, "positive_only", "merge", library="u"),
        # Excluded: arm 1, and a replay (not an independent observation).
        _row(Arm.REACT, None, None, library="g"),
        _row(
            Arm.PRECONDITION,
            "positive_only",
            "rebase",
            library="u",
            occurrence_role=OccurrenceRole.REPLAY,
        ),
    ]:
        append(ledger, record)

    cells = {(c.admission_gate, c.arm): c for c in admission_factorial(ledger)}
    assert set(cells) == {
        ("positive_only", Arm.SEMANTIC),
        ("positive_only", Arm.PRECONDITION),
        ("two_sided", Arm.SEMANTIC),
        ("two_sided", Arm.PRECONDITION),
    }
    semantic_gated = cells[("two_sided", Arm.SEMANTIC)]
    assert (semantic_gated.coverage.numerator, semantic_gated.coverage.denominator) == (1, 2)
    assert (semantic_gated.mismatch.numerator, semantic_gated.mismatch.denominator) == (0, 1)
    assert cells[("two_sided", Arm.PRECONDITION)].mismatch.value is None, "nothing fired"
    assert cells[("positive_only", Arm.SEMANTIC)].mismatch.numerator == 1
    assert cells[("positive_only", Arm.PRECONDITION)].episodes == 1, "the replay is excluded"


def test_the_factorial_refuses_an_unknown_gate(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    append(ledger, _row(Arm.PRECONDITION, None, "merge", library="x"))
    with pytest.raises(ValueError, match="no admission gate"):
        admission_factorial(ledger)


def test_the_factorial_refuses_a_gate_spread_over_two_libraries(tmp_path: Path) -> None:
    """Per-arm online libraries are two libraries, so the arms faced different programs."""
    ledger = tmp_path / "ledger.jsonl"
    append(ledger, _row(Arm.SEMANTIC, "two_sided", "merge", library="semantic-lib"))
    append(ledger, _row(Arm.PRECONDITION, "two_sided", "merge", library="precondition-lib"))
    with pytest.raises(ValueError, match="span 2 libraries"):
        admission_factorial(ledger)
