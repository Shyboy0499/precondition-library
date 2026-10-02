"""Every agent solve's transcript is kept beside its ledger row (issue #171).

The ledger stores numbers, not what the agent did, so diagnosing #171 -- an agent that
fixed the repository and kept verifying until its budget ran out -- needed a separate
traced re-run. `run_benchmark` and `build_library` now write `<ledger>.transcripts.jsonl`,
one line per solve, keyed the way the row is.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from conftest import FakeProvider

from precondition_library.agents.react import FINISH_TOOL
from precondition_library.bench.gold import load_gold_programs
from precondition_library.bench.ledger import Arm, OccurrenceRole, transcripts_path
from precondition_library.bench.run import run_benchmark, run_episode
from precondition_library.library import Library
from precondition_library.provider import Completion, TokenUsage

DISCARD_SEED = 1
_IDS = itertools.count(1)
_USAGE = TokenUsage(tokens_in=10, tokens_out=5, uncached_tokens_in=10)


def _turn(name: str, **arguments: str) -> Completion:
    call = {
        "id": f"call_{next(_IDS)}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    return Completion(tool_calls=[call], usage=_USAGE, model="fake")


def _solves_discard() -> list[Completion]:
    return [
        _turn("run_git", command="git fetch -q upstream"),
        _turn("run_git", command="git reset --hard upstream/main"),
        _turn(FINISH_TOOL, summary="dropped the empty local commits"),
    ]


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_sidecar_sits_beside_its_ledger(tmp_path: Path) -> None:
    assert transcripts_path(tmp_path / "frozen.jsonl") == tmp_path / "frozen.transcripts.jsonl"


def test_a_solve_writes_its_transcript_keyed_like_its_row(tmp_path: Path) -> None:
    log = tmp_path / "t.jsonl"
    record = run_episode(
        Arm.REACT,
        "diverged",
        DISCARD_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=FakeProvider(*_solves_discard()),
        library=Library(tmp_path / "lib"),
        model="fake",
        transcript_log=log,
    )

    (line,) = _lines(log)
    assert (line["arm"], line["fault_type"], line["seed"], line["occurrence_index"]) == (
        "react",
        "diverged",
        DISCARD_SEED,
        1,
    )
    assert line["outcome"] == record.outcome.value == "success"
    commands = [e["command"] for e in line["transcript"] if e["role"] == "tool"]
    assert commands == ["git fetch -q upstream", "git reset --hard upstream/main"]
    assert line["transcript"][-1]["content"] == "dropped the empty local commits"


def test_an_episode_with_no_agent_writes_nothing(tmp_path: Path) -> None:
    """The gold oracle replays a program; no model ran, so there is no transcript."""
    log = tmp_path / "t.jsonl"
    run_episode(
        Arm.GOLD,
        "diverged",
        DISCARD_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=FakeProvider(raises=AssertionError("the oracle must not call the model")),
        library=Library(tmp_path / "lib"),
        model="fake",
        transcript_log=log,
        gold_variants=load_gold_programs()["diverged"],
    )
    assert not log.exists()


def test_run_benchmark_writes_the_sidecar_by_default(tmp_path: Path) -> None:
    out = run_benchmark(
        arms=[Arm.REACT],
        faults=["diverged"],
        occurrences=1,
        seeds=[DISCARD_SEED],
        out=tmp_path / "ledger.jsonl",
        model="fake",
        provider=FakeProvider(*_solves_discard()),
    )
    (line,) = _lines(transcripts_path(out))
    assert line["arm"] == "react" and line["seed"] == DISCARD_SEED
