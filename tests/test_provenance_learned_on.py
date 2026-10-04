"""Where a program was learned is recorded, without moving a single recorded hash (#188).

`Provenance.learned_on` is `"checkout"` for a program learned on a user's existing
repository (ADR-0026) and `None` for one compiled in the harness. These tests pin:

* a harness program serializes exactly as before the field existed -- no `learned_on`
  key in its canonical content or its `program.yaml` -- so every library hash a ledger
  recorded still describes the same library;
* a checkout-learned program carries the marker through write, load and hash;
* a measured run refuses a frozen library that holds a checkout-learned program.
"""

from __future__ import annotations

import json

import pytest
import yaml
from conftest import gold_programs

from precondition_library.bench.run import _require_frozen_library
from precondition_library.library import Library, _canonical
from precondition_library.program import ProgramStatus
from precondition_library.tasks.registry import ambiguous_intents

INTENTS = [intent.name for intent in ambiguous_intents()]


def _gold():
    return [program for intent in INTENTS for program in gold_programs(intent)]


def _learned(program):
    provenance = program.provenance.model_copy(update={"learned_on": "checkout"})
    return program.model_copy(update={"provenance": provenance, "id": f"{program.id}-learned"})


def test_a_harness_program_serializes_exactly_as_before_the_field(tmp_path) -> None:
    library = Library(tmp_path)
    for program in _gold():
        assert program.provenance.learned_on is None
        assert "learned_on" not in json.loads(_canonical(program))["provenance"]
        library.add(program)
        written = yaml.safe_load((tmp_path / program.id / "program.yaml").read_text("utf-8"))
        assert "learned_on" not in written["provenance"]


def test_a_checkout_learned_program_keeps_its_marker(tmp_path) -> None:
    program = _learned(_gold()[0])
    library = Library(tmp_path)
    library.add(program)
    (loaded,) = library.load_all()
    assert loaded.provenance.learned_on == "checkout"
    assert json.loads(_canonical(loaded))["provenance"]["learned_on"] == "checkout"


def test_the_marker_changes_the_hash_and_its_absence_does_not(tmp_path) -> None:
    plain, marked = Library(tmp_path / "plain"), Library(tmp_path / "marked")
    program = _gold()[0]
    plain.add(program)
    marked.add(program.model_copy(update={"provenance": program.provenance.model_copy()}))
    assert plain.library_hash() == marked.library_hash(), "an unset marker is invisible"
    learned = Library(tmp_path / "learned")
    learned.add(_learned(program).model_copy(update={"id": program.id}))
    assert learned.library_hash() != plain.library_hash()


def test_a_measured_run_refuses_a_library_with_a_checkout_learned_program(tmp_path) -> None:
    library = Library(tmp_path)
    for program in _gold():
        library.add(program)
        library.set_status(program.id, ProgramStatus.ADMITTED)
    assert _require_frozen_library(tmp_path) == library.library_hash()

    learned = _learned(_gold()[0])
    library.add(learned)
    library.set_status(learned.id, ProgramStatus.ADMITTED)
    with pytest.raises(ValueError, match="learned on a checkout"):
        _require_frozen_library(tmp_path)
