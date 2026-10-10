"""Arm 2's judge seam (#264): the wrapper's contract, offline, against a scripted provider.

The judge's promises are properties of this module's own code -- one provider call per pair, one
score per candidate in the order given, a memo and a cache that change the cost and not the score,
a reply that cannot be scored becoming a counted abstain rather than a dropped pair, and
`ProviderAuthError` stopping the run instead of becoming a data point. All of it is tested against
`conftest.FakeProvider`, so no test here needs a key, a network or a token. What a real model does
on the gold programs is a run, not a unit test: it is the floor and the rescores of ADR-0034.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeProvider, gold_programs

from precondition_library.bench import rescore as rescore_module
from precondition_library.bench.judge_similarity import (
    JUDGE_PROMPT,
    PROMPT_VERSION,
    JudgeRecord,
    JudgeSimilarity,
    cache_key,
    parse_scores,
    prompt_hash,
)
from precondition_library.bench.live import LivePlan
from precondition_library.library import Library, _program_text
from precondition_library.program import ProgramStatus
from precondition_library.provider import (
    Completion,
    ProviderAuthError,
    ProviderEmptyCompletionError,
    ProviderTransportError,
    TokenUsage,
)
from precondition_library.similarity import ReportsUsage, Similarity, score_all, similarity_usage

USAGE = TokenUsage(tokens_in=100, tokens_out=20, uncached_tokens_in=100)


def _completion(text: str, usage: TokenUsage = USAGE) -> Completion:
    return Completion(text=text, usage=usage, model="deepseek-flash", temperature=0.0)


def _scores(*values: float) -> str:
    return json.dumps({"scores": list(values)})


def _judge(
    *completions: Completion, cache: Path | None = None, **kwargs
) -> tuple[JudgeSimilarity, FakeProvider]:
    provider = FakeProvider(*completions, **kwargs)
    return JudgeSimilarity(provider, cache_path=cache), provider


def test_the_judge_satisfies_the_seam_and_meters_its_own_currency() -> None:
    judge, _ = _judge(_completion(_scores(0.9, 0.1)))
    seam: Similarity = judge
    reporter: ReportsUsage = judge
    assert similarity_usage(seam) == reporter.usage()
    assert judge.score_many("q", ["a", "b"]) == [0.9, 0.1]
    assert judge.usage().tokens == 120, "the seam's currency is the provider's tokens, in and out"
    assert judge.usage().calls == 1
    assert judge.report().uncached_tokens_in == 100
    assert judge.model and judge.temperature == 0.0 and judge.prompt_hash == prompt_hash()


def test_one_call_scores_every_candidate_in_the_order_given() -> None:
    judge, provider = _judge(_completion(_scores(0.1, 0.7, 0.2)))
    scores = judge.score_many(
        "the request and state", ["program one", "program two", "program three"]
    )
    assert scores == [0.1, 0.7, 0.2]
    assert len(provider.calls) == 1, "one provider call per (request, state) pair"
    prompt = provider.calls[0]["messages"][0]["content"]
    assert provider.calls[0]["system"].startswith("You are choosing which stored program")
    for index, text in enumerate(("program one", "program two", "program three"), start=1):
        assert f"[{index}] {text}" in prompt
    assert "exactly 3 number(s)" in prompt
    assert "the request and state" in prompt

    assert (
        judge.score_many("the request and state", ["program one", "program two", "program three"])
        == scores
    )
    assert len(provider.calls) == 1, "the same inputs are memoised, not asked again"
    assert judge.report().memoised == 1
    assert judge.score_many("q", []) == []
    assert judge.usage().calls == 1


def test_the_probe_path_asks_one_candidate_at_a_time_and_memoises() -> None:
    judge, provider = _judge(_completion(_scores(0.4)), _completion(_scores(0.6)))
    assert judge("query", "first") == 0.4
    assert judge("query", "second") == 0.6
    assert judge("query", "first") == 0.4
    assert judge.usage().calls == 2, "the pairwise path is one call per candidate, memoised"
    assert len(provider.calls) == 2


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ("I think the first one fits best.", "no JSON object"),
        ('{"scores": null}', "no `scores` list"),
        (_scores(0.5), "1 score(s) for 2 candidate(s)"),
        (_scores(0.5, "high"), "not a number"),
        (_scores(0.5, 1.4), "outside [0, 1]"),
    ],
)
def test_a_reply_that_cannot_be_scored_is_a_counted_abstain(
    reply: str, reason: str, tmp_path: Path
) -> None:
    cache = tmp_path / "judge.jsonl"
    judge, _ = _judge(_completion(reply), cache=cache)
    assert judge.score_many("q", ["a", "b"]) == [0.0, 0.0], "an unscoreable reply is a non-fire"
    report = judge.report()
    assert report.abstained == 1 and report.unparseable == 1 and report.errors == 0
    assert report.tokens_in == 100, "the endpoint charged for the reply, so the seam counts it"
    record = JudgeRecord.model_validate_json(cache.read_text(encoding="utf-8"))
    assert record.status == "abstained" and reason in record.reason and record.scores == [0.0, 0.0]


def test_an_empty_completion_keeps_its_charge_and_a_transport_error_does_not() -> None:
    empty_usage = TokenUsage(tokens_in=42, tokens_out=0, uncached_tokens_in=42)
    judge, _ = _judge(raises=ProviderEmptyCompletionError("empty", usage=empty_usage))
    assert judge.score_many("q", ["a"]) == [0.0]
    report = judge.report()
    assert report.errors == 1 and report.abstained == 1 and report.tokens_in == 42
    assert judge.usage().calls == 1, "an attempt is provider traffic"

    transport, _ = _judge(raises=ProviderTransportError("timed out"))
    assert transport.score_many("q", ["a", "b"]) == [0.0, 0.0]
    assert transport.report().errors == 1 and transport.report().tokens_in == 0


def test_an_auth_error_stops_the_run_instead_of_becoming_a_data_point() -> None:
    judge, _ = _judge(raises=ProviderAuthError("no balance", status_code=402))
    with pytest.raises(ProviderAuthError):
        judge.score_many("q", ["a"])
    report = judge.report()
    assert report.abstained == 0 and report.errors == 0, (
        "a failed account is not a judge abstention"
    )


def test_the_scores_are_the_evidence_and_recomputing_them_costs_nothing(tmp_path: Path) -> None:
    cache = tmp_path / "nested" / "judge.jsonl"
    first, provider = _judge(_completion(_scores(0.3, 0.8)), cache=cache)
    scores = first.score_many("q", ["a", "b"])
    record = JudgeRecord.model_validate_json(cache.read_text(encoding="utf-8"))
    assert record.prompt_hash == prompt_hash() and record.prompt_version == PROMPT_VERSION
    assert record.model == first.model and record.temperature == first.temperature
    assert record.calls == 1 and record.tokens_in == 100

    # A second judge with the same cache, and a provider that would blow up if it were asked.
    second = JudgeSimilarity(FakeProvider(), cache_path=cache)
    assert second.score_many("q", ["a", "b"]) == scores
    assert second.usage() == type(second.usage())(tokens=0, calls=0), "a cache hit is not a call"
    assert second.report().reused == 1 and second.report().calls == 0


def test_a_cache_record_from_another_configuration_is_refused(tmp_path: Path) -> None:
    cache = tmp_path / "judge.jsonl"
    stale = JudgeRecord(
        key=cache_key("q", ["a"], model="another-model", temperature=0.0),
        prompt_hash=prompt_hash(),
        prompt_version=PROMPT_VERSION,
        model="another-model",
        temperature=0.0,
        candidates=1,
        scores=[1.0],
        status="ok",
    )
    other_prompt = stale.model_copy(update={"model": "deepseek-flash", "prompt_hash": "0" * 64})
    cache.write_text(
        stale.model_dump_json() + "\n" + other_prompt.model_dump_json() + "\n" + "not json\n",
        encoding="utf-8",
    )
    judge, provider = _judge(_completion(_scores(0.25)), cache=cache)
    assert judge.score_many("q", ["a"]) == [0.25], (
        "the model is asked rather than a stale score reused"
    )
    assert len(provider.calls) == 1
    assert judge.report().stale_records == 3, "a different model, a different prompt and a bad line"


def test_the_key_names_everything_a_score_depends_on() -> None:
    base = cache_key("q", ["a"], model="m", temperature=0.0)
    assert base == cache_key("q", ["a"], model="m", temperature=0.0)
    assert base != cache_key("q", ["a", "b"], model="m", temperature=0.0)
    assert base != cache_key("q", ["b", "a"], model="m", temperature=0.0), "order is part of it"
    assert base != cache_key("q", ["a"], model="m", temperature=0.7)


def test_the_prompt_carries_the_state_and_never_the_probe_text() -> None:
    program = gold_programs()[0]
    prompt = JUDGE_PROMPT.format(query=program.intent, candidates=_program_text(program), count=1)
    assert _program_text(program) in prompt
    for predicate in program.preconditions:
        assert predicate.probe not in prompt, (
            "the judge must not read the predicates arm 3 executes"
        )


def test_parse_scores_accepts_a_fenced_reply_and_rejects_a_short_one() -> None:
    assert parse_scores('```json\n{"scores": [0.5, 1]}\n```', 2) == ([0.5, 1.0], "")
    assert parse_scores('Sure! {"scores": [0, 0.25]} hope that helps', 2) == ([0.0, 0.25], "")
    scores, reason = parse_scores('{"scores": [0.5]}', 2)
    assert scores == [0.0, 0.0] and "1 score" in reason


def test_scorer_judge_requires_a_provider_and_a_cache(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs a provider"):
        rescore_module.scorer("judge", judge_cache=tmp_path / "c.jsonl")
    with pytest.raises(ValueError, match="judge-cache"):
        rescore_module.scorer("judge", provider=FakeProvider())
    judge, identity = rescore_module.scorer(
        "judge", provider=FakeProvider(), judge_cache=tmp_path / "c.jsonl"
    )
    assert identity["scorer"] == "judge" and identity["prompt_version"] == PROMPT_VERSION


def _finished_run(tmp_path: Path) -> Path:
    """A run directory `rescore` accepts: a library and a plan, as `test_rescore` builds it."""
    run = tmp_path / "run"
    library = Library(run / "library-two-sided")
    for program in gold_programs():
        candidate = program.model_copy(update={"status": ProgramStatus.CANDIDATE})
        library.add(candidate)
        library.set_status(
            candidate.id, ProgramStatus.ADMITTED, episode_id=candidate.provenance.episode_id
        )
    (run / "plan.json").write_text(
        json.dumps(
            {"model": "m", "plan": LivePlan(episodes=False, online=False).model_dump(mode="json")}
        ),
        encoding="utf-8",
    )
    (run / "build.jsonl").write_text("", encoding="utf-8")
    return run


def test_a_rescore_records_the_judges_spend_and_recomputes_from_its_cache(
    tmp_path: Path, monkeypatch
) -> None:
    """The pair-level stage's seam spend is recorded, and a replay from cache spends nothing."""
    run = _finished_run(tmp_path)
    cache = tmp_path / "judge.jsonl"

    def judged_pair_level(result, plan, library, out):
        """Stands in for `live._pair_level`: it asks the seam, which is what has to be metered."""
        texts = [_program_text(program) for program in library.load_all()]
        score_all(library.similarity, "a request\nstate: dirty true", texts)
        result.figure1 = "figure"
        (out / "primary").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(rescore_module, "_pair_level", judged_pair_level)
    provider = FakeProvider(*[_completion(_scores(*([0.5] * 3)))] * 3)
    judge = JudgeSimilarity(provider, cache_path=cache)
    first_out = tmp_path / "out-one"
    rescore_module.rescore(
        run, first_out, judge, {"scorer": "judge", "prompt_version": PROMPT_VERSION}
    )
    record = json.loads((first_out / "rescore.json").read_text(encoding="utf-8"))
    assert record["scorer"] == "judge"
    assert record["usage"]["calls"] == 1 and record["usage"]["tokens"] == 120
    assert record["judge"]["prompt_hash"] == prompt_hash()
    assert record["judge"]["cache"] == str(cache)
    assert record["judge"]["abstained"] == 0 and record["judge"]["errors"] == 0

    # Same cache, a provider that cannot answer: the figure is recomputed with no spend at all.
    replay = JudgeSimilarity(FakeProvider(), cache_path=cache)
    second_out = tmp_path / "out-two"
    rescore_module.rescore(run, second_out, replay, {"scorer": "judge"})
    replayed = json.loads((second_out / "rescore.json").read_text(encoding="utf-8"))
    assert replayed["usage"] == {"tokens": 0, "calls": 0}
    assert replayed["judge"]["reused"] == 1 and replayed["judge"]["calls"] == 0
    assert (second_out / "summary.json").is_file() and (second_out / "summary.txt").is_file()
