"""Configuration R's admission: the refusal side after the two sides (refusal-population §5).

A fake refusal set stands in for R's real states, so the gate's logic is checked without the
network: a program the set's states accept is refused and its revision is shown them; one they
all refuse is admitted; one the two-sided gate already refused never reaches the set; and a
configuration R build records which set gated it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeProvider
from test_episode_runner import (
    DISCARD_SEED,
    _completion,
    _discard_program,
    _reply_text,
    _resolves_discard,
)

from precondition_library.agents.compile import AdmissionGate, admit
from precondition_library.bench.build_library import build_library
from precondition_library.program import Program
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import build_sandbox


def _a_state() -> StateFingerprint:
    box = build_sandbox(2, ["lockfile_conflict"])
    try:
        return StateFingerprint.observe(box)
    finally:
        box.destroy()


class FakeRefusals:
    """A refusal set of `size` states, which accepts what it is told to and counts its calls."""

    def __init__(
        self,
        accepted: list[tuple[str, StateFingerprint]],
        error: str | None = None,
        size: int = 3,
    ) -> None:
        self.accepted = accepted
        self.error = error
        self.size = size
        self.checked: list[Program] = []
        self.digest = "d" * 64

    def __len__(self) -> int:
        return self.size

    def accepted_by(
        self, program: Program
    ) -> tuple[list[tuple[str, StateFingerprint]], str | None]:
        self.checked.append(program)
        return self.accepted, self.error


def test_a_program_every_refusal_state_refuses_is_admitted() -> None:
    refusals = FakeRefusals([])
    admitted, reason = admit(
        _discard_program(), "diverged", seeds=[DISCARD_SEED], refusals=refusals
    )
    assert admitted, reason
    assert reason.endswith(
        "and refused all 3 real conflicts no resolution can express (configuration R)"
    )
    assert len(refusals.checked) == 1


def test_a_program_a_refusal_state_accepts_is_refused_and_told_which() -> None:
    state = _a_state()
    refusals = FakeRefusals([("org/repo@abcdef123456", state)])
    refused_on: list[StateFingerprint] = []
    admitted, reason = admit(
        _discard_program(),
        "diverged",
        seeds=[DISCARD_SEED],
        refusals=refusals,
        refused_on=refused_on,
    )
    assert not admitted
    assert reason.startswith("refusal side failed: preconditions accepted 1 of 3 real conflicts")
    assert "org/repo@abcdef123456" in reason
    assert refused_on == [state]


def test_a_refusal_state_that_cannot_be_evaluated_refuses_the_program() -> None:
    refusals = FakeRefusals([], error="precondition 'x' was refused: wrote to the tree")
    admitted, reason = admit(
        _discard_program(), "diverged", seeds=[DISCARD_SEED], refusals=refusals
    )
    assert not admitted
    assert reason == (
        "refusal side failed: preconditions could not be evaluated (precondition 'x' was "
        "refused: wrote to the tree)"
    )


def test_the_refusal_side_runs_only_after_the_two_sides_pass() -> None:
    full = _discard_program()
    permissive = _discard_program(id="permissive", preconditions=full.preconditions[:1])
    refusals = FakeRefusals([])
    admitted, reason = admit(permissive, "diverged", seeds=[DISCARD_SEED], refusals=refusals)
    assert not admitted and reason.startswith("negative side failed")
    assert refusals.checked == [], "a program the two-sided gate refused never reaches R"


def test_the_positive_only_gate_has_no_refusal_side() -> None:
    with pytest.raises(ValueError, match="two-sided gate's negative side only"):
        admit(
            _discard_program(),
            "diverged",
            seeds=[DISCARD_SEED],
            gate=AdmissionGate.POSITIVE_ONLY,
            refusals=FakeRefusals([]),
        )


def _build(tmp_path: Path, refusals: FakeRefusals | None, *replies: str) -> dict:
    provider = FakeProvider(*_resolves_discard(), *(_completion(reply) for reply in replies))
    report = build_library(
        faults=["diverged"],
        root=tmp_path / "frozen",
        ledger=tmp_path / "build.jsonl",
        provider=provider,
        model="fake",
        seeds=(DISCARD_SEED,),
        refusals=refusals,
    )
    manifest = json.loads((tmp_path / "frozen" / "build.json").read_text(encoding="utf-8"))
    return {"report": report, "manifest": manifest, "provider": provider}


def test_a_configuration_r_build_records_its_refusal_set(tmp_path: Path) -> None:
    refusals = FakeRefusals([])
    built = _build(tmp_path, refusals, _reply_text(_discard_program()))
    assert built["report"].admitted == 1
    assert built["manifest"]["refusal_set"] == refusals.digest
    assert len(refusals.checked) == 1


def test_a_build_without_a_refusal_set_records_none(tmp_path: Path) -> None:
    built = _build(tmp_path, None, _reply_text(_discard_program()))
    assert built["manifest"]["refusal_set"] is None


def test_the_revision_is_shown_the_refusal_states_its_program_fired_on(tmp_path: Path) -> None:
    """Both compiles fire on R's state, so nothing is admitted; the revision's payload carries
    the state as observed, as it carries a negative state's (ADR-0030)."""
    state = _a_state()
    refusals = FakeRefusals([("org/repo@abcdef123456", state)])
    program = _reply_text(_discard_program())
    built = _build(tmp_path, refusals, program, program)
    assert built["report"].admitted == 0
    assert len(refusals.checked) == 2, "the first compile and its one revision"
    revision = built["provider"].calls[-1]
    payload = json.loads(revision["messages"][-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert payload["admission_refusal"].startswith("refusal side failed")
    assert payload["refused_states"] == [state.model_dump(mode="json")]


@pytest.mark.parametrize(
    "plan",
    [{"build_order": 1}, {"refusal_set": "R"}],
    ids=["a build order", "a refusal set"],
)
def test_a_study_2_live_run_is_bound_by_its_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plan: dict
) -> None:
    """With either of study 2's options, nothing is written unless the registration holds."""
    from precondition_library.bench import live, preregistration

    monkeypatch.setitem(preregistration.REGISTRATIONS, live.STUDY_2, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError, match="differs"):
        live.run_live(
            live.LivePlan(**plan), provider=FakeProvider(), model="fake", out=tmp_path / "run"
        )
    assert not (tmp_path / "run").exists()


def test_the_live_refusal_set_option_parses() -> None:
    from precondition_library.bench import live
    from precondition_library.bench.refusal_set import REGISTRATION

    base = ["--api-key-env", "UNUSED", "--out", "x"]
    assert live._parser().parse_args([*base, "--refusal-set", "R"]).refusal_set == "R"
    assert live._parser().parse_args(base).refusal_set is None
    assert live.STUDY_2 == REGISTRATION
