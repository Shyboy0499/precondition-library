"""The build's admit set covers every resolution, and asks for it (ADR-0032).

Arm 2's floor (spec §7 item 11) needs at least two resolutions per intent in the library.
Built from four seeds with the fault's own request, the fourth and sixth live runs held
one or none for three intents of five: the agent picks a resolution the state accepts,
and most states accept several. These tests pin the registered table that replaces it --
every resolution of every measured intent once, each at a state labelled with it (the
state that accepts it alone, where one exists), outside the tune and eval blocks -- and
that a build with no `seeds` runs exactly that table, with requests that ask for each
resolution in words no measured request uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precondition_library.agents.react import FINISH_TOOL
from precondition_library.bench.admit_set import ADMIT_SET, admit_request, admit_seeds
from precondition_library.bench.build_library import build_library
from precondition_library.bench.ledger import read
from precondition_library.bench.live import MEASURED_FAULTS
from precondition_library.bench.run import MANIFEST
from precondition_library.bench.splits import EVAL_SEEDS, TUNE_SEEDS
from precondition_library.provider import Completion, TokenUsage
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import FAULTS, build_sandbox
from precondition_library.tasks.registry import INTENTS
from precondition_library.tasks.state_grid import STATE_GRID

_INTENT_OF = {intent.fault: intent for intent in INTENTS.values()}
EPISODES = [(fault, episode) for fault, episodes in ADMIT_SET.items() for episode in episodes]
SEEDS = [(fault, episode, seed) for fault, episode in EPISODES for seed in episode.seeds]


def test_every_resolution_of_every_measured_intent_is_covered_once() -> None:
    assert set(ADMIT_SET) == set(MEASURED_FAULTS)
    for fault, episodes in ADMIT_SET.items():
        declared = [variant.id for variant in _INTENT_OF[fault].variants]
        assert sorted(episode.resolution for episode in episodes) == sorted(declared), fault
        assert len(set(admit_seeds(fault))) == len(admit_seeds(fault)), f"{fault}: repeated seed"
        assert all(len(episode.seeds) == 2 for episode in episodes), "a first seed and a fallback"


@pytest.mark.parametrize(("fault", "episode", "seed"), SEEDS, ids=lambda item: str(item))
def test_each_seed_is_labelled_with_its_resolution(fault, episode, seed) -> None:
    assert FAULTS[fault].variant_for_seed(seed) == episode.resolution
    assert seed not in TUNE_SEEDS and seed not in EVAL_SEEDS


@pytest.mark.parametrize(("fault", "episode", "seed"), SEEDS, ids=lambda item: str(item))
def test_a_resolution_some_state_forces_is_built_on_such_a_state(fault, episode, seed) -> None:
    """Where a declared state accepts this resolution alone, the episode is on one: there
    the agent's solution must be this resolution, whatever the request says."""
    intent = _INTENT_OF[fault]
    forcing = any(
        intent.acceptable_variants(state) == (episode.resolution,)
        for state in STATE_GRID[intent.name].values()
    )
    box = build_sandbox(seed, [fault])
    try:
        acceptable = intent.acceptable_variants(StateFingerprint.observe(box))
    finally:
        box.destroy()
    assert episode.resolution in acceptable
    if forcing:
        assert acceptable == (episode.resolution,), f"{fault} seed {seed}: {acceptable}"


@pytest.mark.parametrize(("fault", "episode", "seed"), SEEDS, ids=lambda item: str(item))
def test_the_request_is_the_faults_phrasing_then_a_directive(fault, episode, seed) -> None:
    request = admit_request(fault, episode, seed)
    own = FAULTS[fault].task_text(seed)
    assert request == f"{own} {episode.directive}"
    intent = _INTENT_OF[fault]
    measured = [*intent.phrasings, *(p for ps in intent.variant_phrasings.values() for p in ps)]
    assert all(episode.directive not in phrasing for phrasing in measured), (
        "a directive must never reach a measured request"
    )


class _FinishThenNoProgram:
    """Declares every solve done at once and answers every compile with no program."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def complete(self, *, system: str, messages: list[dict], tools: list[dict] | None = None):
        usage = TokenUsage(tokens_in=1, tokens_out=1, uncached_tokens_in=1)
        if tools:
            self.requests.append(messages[0]["content"])
            call = {
                "id": f"call_{len(self.requests)}",
                "type": "function",
                "function": {"name": FINISH_TOOL, "arguments": json.dumps({"summary": "done"})},
            }
            return Completion(tool_calls=[call], usage=usage, model="fake")
        return Completion(text="not a program", usage=usage, model="fake")


def test_a_build_that_admits_nothing_tries_every_fallback(tmp_path: Path) -> None:
    provider = _FinishThenNoProgram()
    report = build_library(
        faults=["diverged"],
        root=tmp_path / "library",
        ledger=tmp_path / "build.jsonl",
        provider=provider,
        model="fake",
    )
    rows = read(tmp_path / "build.jsonl")
    assert [row.seed for row in rows] == list(admit_seeds("diverged"))
    assert provider.requests == [
        admit_request("diverged", e, seed) for e in ADMIT_SET["diverged"] for seed in e.seeds
    ]
    assert report.programs == [], "no reply was a program"
    manifest = json.loads((tmp_path / "library" / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["episodes"]["diverged"] == [
        {"resolution": e.resolution, "seeds": list(e.seeds)} for e in ADMIT_SET["diverged"]
    ]


def test_a_build_with_seeds_keeps_the_faults_own_requests(tmp_path: Path) -> None:
    provider = _FinishThenNoProgram()
    build_library(
        faults=["diverged"],
        root=tmp_path / "library",
        ledger=tmp_path / "build.jsonl",
        provider=provider,
        model="fake",
        seeds=(0, 1),
    )
    assert provider.requests == [FAULTS["diverged"].task_text(seed) for seed in (0, 1)]


def test_a_resolution_whose_first_episode_admits_skips_its_fallback(tmp_path, monkeypatch):
    """The fallback is for a resolution the build has not covered; a covered one stops."""
    from conftest import gold_programs, make_record

    from precondition_library.bench import build_library as build_module
    from precondition_library.program import ProgramStatus

    ran: list[int] = []
    gold = {p.variant: p for p in gold_programs("sync_fork_with_upstream")}

    def fake_episode(arm, fault, seed, occurrence, *, library, request, **_):
        ran.append(seed)
        if seed in (1, 0):  # discard's and merge's first seeds admit; rebase's does not
            variant = FAULTS[fault].variant_for_seed(seed)
            program = gold[variant].model_copy(
                update={"id": f"{variant}-{seed}", "status": ProgramStatus.CANDIDATE}
            )
            library.add(program)
            library.set_status(program.id, ProgramStatus.ADMITTED)
        return make_record(seed=seed, fault_type=fault)

    monkeypatch.setattr(build_module, "run_episode", fake_episode)
    report = build_library(
        faults=["diverged"],
        root=tmp_path / "library",
        ledger=tmp_path / "build.jsonl",
        provider=object(),
        model="fake",
    )
    assert ran == [1, 2, 5, 0], "discard and merge stop at their first seed; rebase falls back"
    assert sorted(p.resolution for p in report.programs if p.admitted) == ["discard", "merge"]
