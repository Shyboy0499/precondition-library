"""A finished run's primary metric can be re-measured with another arm 2 scorer (#104).

The pair-level stage itself is `bench.live._pair_level`, tested where it lives; these tests pin
what `bench.rescore` adds around it: the chosen scorer is the one behind the library arm 2
reads, the scorer is recorded beside the figures, the build is never touched, and a rescore
writes only into a fresh directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import gold_programs

from precondition_library.bench import rescore as rescore_module
from precondition_library.bench.live import LivePlan
from precondition_library.library import Library
from precondition_library.program import ProgramStatus

PLAN = LivePlan(episodes=False, online=False)


def _finished_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    library = Library(run / "library-two-sided")
    for program in gold_programs():
        candidate = program.model_copy(update={"status": ProgramStatus.CANDIDATE})
        library.add(candidate)
        library.set_status(
            candidate.id, ProgramStatus.ADMITTED, episode_id=candidate.provenance.episode_id
        )
    (run / "plan.json").write_text(
        json.dumps({"model": "m", "plan": PLAN.model_dump(mode="json")}), encoding="utf-8"
    )
    (run / "build.jsonl").write_text("", encoding="utf-8")
    return run


def _scored_by(similarity):
    seen: dict = {}

    def pair_level(result, plan, library, out):
        seen["similarity"] = library.similarity
        seen["plan"] = plan
        result.figure1 = "figure"
        (out / "primary").mkdir()

    return seen, pair_level


def test_the_chosen_scorer_is_the_one_arm_2_reads(tmp_path, monkeypatch) -> None:
    run = _finished_run(tmp_path)
    before = sorted(p.name for p in (run / "library-two-sided").iterdir())

    def custom(query: str, candidate: str) -> float:
        return 0.5

    seen, fake = _scored_by(custom)
    monkeypatch.setattr(rescore_module, "_pair_level", fake)
    out = tmp_path / "out"
    result = rescore_module.rescore(run, out, custom, {"scorer": "custom"})

    assert seen["similarity"] is custom
    assert seen["plan"] == PLAN
    assert result.admitted_two_sided == len(before) and result.figure1 == "figure"
    assert json.loads((out / "rescore.json").read_text())["scorer"] == "custom"
    assert (out / "summary.json").exists() and (out / "summary.txt").exists()
    assert sorted(p.name for p in (run / "library-two-sided").iterdir()) == before


def test_a_rescore_writes_only_into_a_fresh_directory(tmp_path, monkeypatch) -> None:
    run = _finished_run(tmp_path)
    _, fake = _scored_by(None)
    monkeypatch.setattr(rescore_module, "_pair_level", fake)
    (tmp_path / "used").mkdir()
    with pytest.raises(ValueError, match="fresh directory"):
        rescore_module.rescore(run, tmp_path / "used", lambda q, c: 0.0, {"scorer": "x"})


def test_an_empty_library_has_nothing_to_rescore(tmp_path) -> None:
    run = tmp_path / "run"
    (run / "library-two-sided").mkdir(parents=True)
    (run / "plan.json").write_text(
        json.dumps({"model": "m", "plan": PLAN.model_dump(mode="json")}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="nothing to rescore"):
        rescore_module.rescore(run, tmp_path / "out", lambda q, c: 0.0, {"scorer": "x"})


def test_the_lexical_scorer_is_the_shipped_seam() -> None:
    from precondition_library.similarity import lexical_similarity

    similarity, identity = rescore_module.scorer("lexical")
    assert similarity is lexical_similarity and identity == {"scorer": "lexical"}
    with pytest.raises(ValueError, match="unknown scorer"):
        rescore_module.scorer("bm25")
