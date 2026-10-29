"""The library-scoped control's comparison on a finished stage (ADR-0052).

A hand-built stage of four cases: two clean merges whose label is `merge`, and two conflicts
nothing can resolve. The registered control fires `keep_local` on the conflicts and nothing on the
clean merges; the library-scoped one fires `merge` on the clean merges and nothing on the
conflicts. The comparison must use the second in the first's place, count each by kind, and
refuse a stage whose states are missing or did not rebuild as they were.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precondition_library.bench import library_control as lc
from precondition_library.bench import real_merges as rm
from precondition_library.signatures import StateFingerprint

KINDS = ("negative", "negative", "positive", "positive")


def _state(conflict: bool) -> StateFingerprint:
    fields = {
        name: (
            []
            if str(field.annotation).startswith("list")
            else ""
            if field.annotation is str
            else False
            if field.annotation is bool
            else 0
        )
        for name, field in StateFingerprint.model_fields.items()
    }
    fields["merge_conflicted_files"] = ["yarn.lock"] if conflict else []
    return StateFingerprint.model_validate(fields)


class _Library:
    def decide_library(self, state: StateFingerprint) -> tuple[str | None, float]:
        return (None, 0.0) if state.merge_conflicted_files else ("merge", 0.9)


def _stage(tmp_path: Path, *, matches: bool = True, states: int = 4) -> Path:
    stage = tmp_path / "stage"
    stage.mkdir()
    cases = [
        rm.Case(
            index=i,
            repo=f"example/repo-{i % 2}",
            kind=kind,
            merge=f"{i:040x}",
            first="1" * 40,
            second="2" * 40,
            base="3" * 40,
            conflicted=["yarn.lock"] if kind == "positive" else [],
        )
        for i, kind in enumerate(KINDS)
    ]
    manifest = rm.Manifest(stage="B", repositories=[], cases=cases, exclusions=[])
    (stage / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    labels = [
        rm.Label(
            index=c.index,
            acceptable=["merge"] if c.kind == "negative" else [],
            descriptive="clean merge reproduced" if c.kind == "negative" else "regenerated",
        )
        for c in cases
    ]
    (stage / "labels.jsonl").write_text(
        "".join(lab.model_dump_json() + "\n" for lab in labels), encoding="utf-8"
    )
    decided = [
        rm.Decisions(
            index=c.index,
            rule=None,
            arm3=["merge" if c.kind == "negative" else None] * len(rm.LIBRARIES),
            arm2=[(None, None)] * len(rm.LIBRARIES),
            control=("keep_local", 1.0) if c.kind == "positive" else (None, 1.0),
        )
        for c in cases
    ]
    (stage / "decisions.jsonl").write_text(
        "".join(d.model_dump_json() + "\n" for d in decided), encoding="utf-8"
    )
    observed = [
        rm.ObservedState(
            index=c.index,
            state=_state(c.kind == "positive"),
            control_matches=matches or c.index != 0,
        )
        for c in cases[:states]
    ]
    (stage / "states.jsonl").write_text(
        "".join(o.model_dump_json() + "\n" for o in observed), encoding="utf-8"
    )
    return stage


@pytest.fixture(autouse=True)
def _stub_control(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc, "control_classifier", lambda: _Library())


def test_the_library_control_takes_the_registered_controls_place(tmp_path: Path) -> None:
    report = lc.compare(_stage(tmp_path))
    assert report.cases == 4
    assert report.fired == {"merge": 2}
    assert (report.control_clean, report.control_conflicted) == (
        lc.Kinds(fires=2, right=2),
        lc.Kinds(fires=0, right=0),
    )
    assert (report.registered_clean, report.registered_conflicted) == (
        lc.Kinds(fires=0, right=0),
        lc.Kinds(fires=2, right=0),
    )
    for replicate in report.replicates:
        assert replicate.arm3.mismatch.numerator == 0
        assert replicate.control_matched.mismatch.numerator == 0
        assert replicate.h2.statistic == 0.0, "both right on every fire: no margin left"
        assert replicate.h3.statistic == 0.0, "neither fires on the inexpressible conflicts"
    assert "library-scoped control: clean 2/2 right" in lc.text(report)


def test_a_stage_without_every_state_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no recorded state"):
        lc.compare(_stage(tmp_path, states=3))


def test_a_state_that_did_not_rebuild_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="did not rebuild"):
        lc.compare(_stage(tmp_path, matches=False))


def test_the_committed_compressed_states_are_read(tmp_path: Path) -> None:
    import gzip

    stage = _stage(tmp_path)
    plain = stage / "states.jsonl"
    (stage / "states.jsonl.gz").write_bytes(gzip.compress(plain.read_bytes()))
    plain.unlink()
    assert lc.compare(stage).fired == {"merge": 2}
