"""`bench.live` end to end, every real stage, with a scripted model (#170's weakest point).

`tests/test_live_run.py` replaces the two stages that call a model -- the build and the
episode runs -- with stand-ins, so the first live run was also the first proof that
`build_library`, `run_benchmark`, admission, the 2b tuning, the factorial and Figure 1
compose. Here nothing is stubbed except the model itself:

* as the **agent** (a call that offers tools), it declares done at once with `finish`;
* as the **compiler** (a call with none), it reads `state_at_arrival` from the compile
  payload, asks the intents' own rules which resolution the state needs, and replies
  with that resolution's committed gold program, as a model would reply with YAML.

So the build compiles real programs through the real gate on real sandboxes, the frozen
benchmark dispatches against what was admitted, and every artifact is written. Nothing
here measures anything: the agent never fixes a repository, and gold arm 3 is the
labelling rule, so Figure 1 reports itself vacuous.
"""

from __future__ import annotations

import itertools
import json

import pytest
import yaml
from conftest import gold_programs

from precondition_library.agents.compile import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from precondition_library.agents.react import FINISH_TOOL
from precondition_library.bench import live
from precondition_library.bench.ledger import read, transcripts_path
from precondition_library.provider import Completion, TokenUsage
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.registry import ambiguous_intents

_USAGE = TokenUsage(tokens_in=10, tokens_out=5, uncached_tokens_in=10)
PLAN = live.LivePlan(
    build_seeds=(0,), tune_seeds=(0,), pair_seeds=(0, 1), episode_seeds=(2000,), online=True
)


class ScriptedModel:
    """Plays the agent (finish at once) and the compiler (the gold program for the state)."""

    def __init__(self) -> None:
        self.ids = itertools.count(1)
        self.agent_calls = 0
        self.compile_calls = 0

    def complete(self, *, system: str, messages: list[dict], tools=None) -> Completion:
        if tools:
            self.agent_calls += 1
            call = {
                "id": f"call_{next(self.ids)}",
                "type": "function",
                "function": {"name": FINISH_TOOL, "arguments": json.dumps({"summary": "done"})},
            }
            return Completion(tool_calls=[call], usage=_USAGE, model="scripted")
        self.compile_calls += 1
        return Completion(text=self._gold_for(messages[-1]["content"]), usage=_USAGE, model="s")

    @staticmethod
    def _gold_for(content: str) -> str:
        payload = json.loads(content.split(UNTRUSTED_OPEN, 1)[1].split(UNTRUSTED_CLOSE, 1)[0])
        state = StateFingerprint.model_validate(payload["state_at_arrival"])
        for intent in ambiguous_intents():
            variant = intent.correct_variant(state)
            if variant is None:
                continue
            program = next(p for p in gold_programs(intent.name) if p.variant == variant.id)
            document = program.model_dump(mode="json")
            document.pop("provenance")
            document.pop("status")
            return yaml.safe_dump(document, sort_keys=False)
        return "not a program: this state needs nothing done"


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("live") / "run"
    model = ScriptedModel()
    result = live.run_live(PLAN, provider=model, model="scripted", out=out)
    return out, result, model


def test_the_build_compiles_and_admits_real_programs(run) -> None:
    out, result, model = run
    assert model.compile_calls >= len(live.MEASURED_FAULTS), "every declared success compiled"
    assert result.compiled >= 1 and result.admitted_two_sided >= 1, result.build
    assert result.stopped_after is None, result.stop_reason
    assert all(e.outcome == "fallback" for e in result.build), "each solve declared done"


def test_every_stage_ran_and_wrote_its_artifact(run) -> None:
    out, result, _ = run
    for name in ("frozen_ledger", "positive_only_ledger", "factorial_ledger", "online_ledger"):
        assert (out / result.artifacts[name]).is_file(), name
    assert (out / "report").is_dir() and (out / "primary" / "figure1.csv").is_file()
    assert (out / "summary.json").is_file() and (out / "summary.txt").is_file()
    assert result.soft_threshold is not None and result.figure1 is not None


def test_the_frozen_rows_carry_one_library_and_every_arm(run) -> None:
    out, result, _ = run
    rows = read(out / result.artifacts["frozen_ledger"])
    assert {row.arm for row in rows} == set(live.FROZEN_ARMS)
    assert {row.library_hash for row in rows} == {result.library_hash}
    assert all(row.acceptable_variants is not None for row in rows), "ADR-0023 is recorded"


def test_transcripts_are_kept_for_every_solve(run) -> None:
    out, _, _ = run
    lines = (out / "build.transcripts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(PLAN.build_seeds) * len(live.MEASURED_FAULTS)
    assert transcripts_path(out / "frozen.jsonl").is_file(), "the frozen fallbacks solved too"


def test_gold_arm_3_never_misfires_in_figure1(run) -> None:
    """Gold fires only where its resolution is right, so arm 3's mismatch is zero.

    The build admits only the programs its seeds' states needed, so arm 3 refuses the
    other states rather than being the whole labelling rule; the comparison is real,
    and arm 3's side of it must show no wrong fire.
    """
    _, result, _ = run
    arm3 = next(line for line in (result.figure1 or "").splitlines() if "arm 3" in line)
    assert "mismatch 0/" in arm3, arm3
