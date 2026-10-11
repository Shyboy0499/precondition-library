"""Arm 2's `Similarity` seam, filled with a **judge that reads the state** (issue #264).

Every arm 2 measured before this one compares text with text -- the shipped lexical overlap,
#104's embedding, #256's pinned reranker -- so none of them can verify the state, and "running
checks beats reading text" is close to built into the comparison. This module fills the same seam
with a model that is shown the request *and* the repository state and asked how well each candidate
program fits, which is the baseline a reviewer asks for.

**It sits behind the seam, not beside it.** `JudgeSimilarity` implements `Similarity`,
`ScoresMany` and `ReportsUsage`, so `library.py`, `coverage.py`, `primary.py` and `rescore.py` learn
nothing about judges, and arm 3 is unchanged by construction -- it does not read the seam.

**What it sees is exactly what arm 2 sees.** The query is `library._query_text(signature)`: the
request followed by `StateFingerprint.as_text()`. The candidates are `library._program_text`:
each program's `intent` and its predicate **descriptions**. The probe strings are deliberately
absent -- a judge that reads the probes is reasoning about the predicates arm 3 executes, which is a
different mechanism and a separate experiment (ADR-0034's rejected table).

**One provider call per (request, state) pair.** `score_many` -- the path `match_semantic` takes --
asks for one score per candidate in the order given, so the coverage sweep keeps its meaning
(a judge that merely names one program degenerates the curve into a step) and the cost is one call
per pair rather than one per candidate. `__call__` stays available and memoised, so
`similarity_probe`'s pairwise loop works unchanged at a higher cost.

**The scores are the evidence.** Every reply is written to a JSONL cache as it arrives, keyed by the
digest of the prompt inputs, and carrying the prompt hash, model, temperature and candidate count.
A record whose metadata disagrees with the running configuration is **skipped**, not reused, and
counted, so a changed prompt cannot silently inherit an old score; a rescore can then recompute a
figure from the file with no key and no tokens (ADR-0034 decision 5).

**Failures stay in the denominator.** An empty completion, a transport error, an unparseable reply,
a wrong score count and an out-of-range score all become an **abstain** -- `0.0` for every
candidate,
which is an arm-2 non-fire -- and each is counted. `ProviderAuthError` is re-raised instead: every
later call would fail the same way, and a run of failed rows looks measured while measuring nothing
(issue #157). Nothing is retried silently; the endpoint's charge for a failed call is counted when
the provider reports it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..provider import (
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    Provider,
    ProviderAuthError,
    ProviderEmptyCompletionError,
    ProviderError,
    TokenUsage,
)
from ..similarity import SimilarityUsage

PROMPT_VERSION = "judge-v1"
"""Bumped whenever `JUDGE_SYSTEM` or `JUDGE_PROMPT` changes.

It is part of every cache key and every record, so a text change cannot inherit a score the old
prompt produced.
"""

JUDGE_SYSTEM = """\
You are choosing which stored program, if any, a repository maintenance agent should run.

You are given the user's request, the repository state as git-level facts, and one or more candidate
programs. Each candidate is described by what it does and by the descriptions of the checks it runs.

You cannot run anything and you cannot inspect the repository: decide from the text alone. A
candidate whose checks would not hold in this state must not score highly, however well its wording
matches the request.

Reply with JSON and nothing else, no prose and no code fence, in exactly this shape:

{"scores": [<one number per candidate, in the order given>]}

Each number is how well that candidate fits this request and this state: 1.0 means it is the program
to run here, 0.0 means it must not run here, and a value between is a partial fit. If nothing should
run, every score is 0.0."""

JUDGE_PROMPT = """\
The user's request and the repository state, as the text arm 2 is given:

{query}

Candidate programs, numbered in the order the scores must be given:

{candidates}

Reply with JSON only: {{"scores": [...]}} with exactly {count} number(s), in that order."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_hash() -> str:
    """The digest of the pinned prompt text, part of every key and every record."""
    return _sha256(f"{PROMPT_VERSION}\x00{JUDGE_SYSTEM}\x00{JUDGE_PROMPT}")


def cache_key(query: str, candidates: Sequence[str], *, model: str, temperature: float) -> str:
    """The digest of everything a score depends on, so nothing else can be substituted for it."""
    parts = [PROMPT_VERSION, model, repr(temperature), query, *candidates]
    return _sha256("\x00".join(parts))


class JudgeRecord(BaseModel):
    """One cached reply: the key, what produced it, and the scores or why there are none."""

    key: str
    prompt_hash: str
    prompt_version: str
    model: str
    temperature: float
    candidates: int
    scores: list[float]
    status: str
    """`"ok"` for a parsed reply, `"abstained"` for a failure that scored every candidate 0.0."""
    reason: str = ""
    calls: int = 1
    tokens_in: int = 0
    tokens_out: int = 0


class JudgeReport(BaseModel):
    """What the judge spent and how often it could not answer, for the run's record."""

    model: str
    temperature: float
    prompt_version: str
    prompt_hash: str
    calls: int
    """Provider calls attempted, including ones that failed -- an attempt is traffic."""
    reused: int
    """Scores taken from the cache file, so recomputing a figure costs nothing."""
    memoised: int
    """Scores from this process's own memo: asked once per distinct input."""
    abstained: int
    unparseable: int
    errors: int
    stale_records: int
    """Cache records skipped because their prompt hash, model, temperature or count disagreed."""
    tokens_in: int
    tokens_out: int
    uncached_tokens_in: int
    cached_tokens_in: int


def _json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in `text`, or `None` if there is not one.

    A model asked for JSON sometimes wraps it in a fence or adds a sentence, so the strict parse is
    tried first and a brace scan second -- bounded, string-aware, and it does not try to repair a
    reply that has no object in it at all.
    """
    stripped = text.strip()
    candidates = [stripped]
    if "```" in stripped:
        for part in stripped.split("```")[1::2]:
            candidates.append(part.removeprefix("json").strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    start = stripped.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(stripped[start : index + 1])
                    except ValueError:
                        break
                    return parsed if isinstance(parsed, dict) else None
        start = stripped.find("{", start + 1)
    return None


def parse_scores(text: str, count: int) -> tuple[list[float], str]:
    """`(scores, reason)` for a reply that must score `count` candidates in `[0, 1]`.

    `reason` is empty when the scores are usable, and the caller abstains otherwise: a reply that
    cannot be scored is a non-fire, and `0.0` for every candidate is what arm 2 does when it has
    nothing -- the alternative, dropping the pair, would flatter the arm that fails most.
    """
    zeros = [0.0] * count
    payload = _json_object(text)
    if payload is None:
        return zeros, "no JSON object in the reply"
    scores = payload.get("scores")
    if not isinstance(scores, list):
        return zeros, "the reply has no `scores` list"
    if len(scores) != count:
        return zeros, f"{len(scores)} score(s) for {count} candidate(s)"
    parsed: list[float] = []
    for value in scores:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return zeros, f"a score is not a number: {value!r}"
        if not 0.0 <= float(value) <= 1.0:
            return zeros, f"a score is outside [0, 1]: {value!r}"
        parsed.append(float(value))
    return parsed, ""


class JudgeSimilarity:
    """A pinned model that scores programs against the request and the state, behind the seam."""

    def __init__(
        self,
        provider: Provider,
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        cache_path: Path | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._temperature = temperature
        self._cache_path = cache_path
        self._scores: dict[str, list[float]] = {}
        self._calls = 0
        self._reused = 0
        self._memoised = 0
        self._abstained = 0
        self._unparseable = 0
        self._errors = 0
        self._stale = 0
        self._tokens_in = 0
        self._tokens_out = 0
        self._uncached_tokens_in = 0
        self._cached_tokens_in = 0
        if cache_path is not None:
            self._load(cache_path)

    @property
    def model(self) -> str:
        """The pinned model this instance asks for."""
        return self._model

    @property
    def temperature(self) -> float:
        """The sampling temperature this instance sends; `Completion` echoes what was sent."""
        return self._temperature

    @property
    def prompt_hash(self) -> str:
        return prompt_hash()

    @property
    def cache_path(self) -> Path | None:
        return self._cache_path

    def _load(self, path: Path) -> None:
        """Read a cache, keeping only records this configuration could have produced."""
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = JudgeRecord.model_validate_json(line)
            except ValueError:
                self._stale += 1
                continue
            if (
                record.prompt_hash != prompt_hash()
                or record.model != self._model
                or record.temperature != self._temperature
            ):
                self._stale += 1
                continue
            if len(record.scores) != record.candidates:
                self._stale += 1
                continue
            self._scores[record.key] = list(record.scores)
            self._reused += 1

    def _write(self, record: JudgeRecord) -> None:
        """Append one record, so a run that is killed keeps what it already paid for."""
        if self._cache_path is None:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def _account(self, usage: TokenUsage) -> None:
        self._tokens_in += usage.tokens_in
        self._tokens_out += usage.tokens_out
        self._uncached_tokens_in += usage.uncached_tokens_in
        self._cached_tokens_in += usage.cached_tokens_in

    def score_many(self, query: str, candidates: Sequence[str]) -> list[float]:
        """One provider call for `query` against every candidate, in the order given.

        The reply is parsed into one score per candidate; anything unusable abstains and is counted.
        Every outcome, including an abstention, is written to the cache under a key that names the
        prompt version, the model, the temperature and the two texts -- so a later run with a
        different prompt cannot read a score this one produced.
        """
        if not candidates:
            return []
        key = cache_key(query, candidates, model=self._model, temperature=self._temperature)
        if key in self._scores:
            self._memoised += 1
            return list(self._scores[key])
        prompt = JUDGE_PROMPT.format(
            query=query,
            candidates="\n".join(
                f"[{index}] {text}" for index, text in enumerate(candidates, start=1)
            ),
            count=len(candidates),
        )
        self._calls += 1
        try:
            completion = self._provider.complete(
                system=JUDGE_SYSTEM, messages=[{"role": "user", "content": prompt}]
            )
        except ProviderAuthError:
            # Never recorded as a data point: every later call fails the same way, and a run of
            # failed rows looks measured while measuring nothing (issue #157).
            raise
        except ProviderEmptyCompletionError as exc:
            # The endpoint charged for it, so the ledger of this seam must say so.
            self._account(exc.usage)
            return self._abstain(key, len(candidates), "empty completion", "errors", calls=1)
        except ProviderError as exc:
            return self._abstain(key, len(candidates), f"provider error: {exc}", "errors", calls=1)
        self._account(completion.usage)
        scores, reason = parse_scores(completion.text, len(candidates))
        if reason:
            # A reply that came back and could not be scored is an abstention like any other: the
            # pair stays in the denominator as a non-fire, and the reason is counted and recorded.
            self._unparseable += 1
            self._abstained += 1
        record = JudgeRecord(
            key=key,
            prompt_hash=prompt_hash(),
            prompt_version=PROMPT_VERSION,
            model=self._model,
            temperature=self._temperature,
            candidates=len(candidates),
            scores=scores,
            status="ok" if not reason else "abstained",
            reason=reason,
            tokens_in=completion.usage.tokens_in,
            tokens_out=completion.usage.tokens_out,
        )
        self._scores[key] = list(scores)
        self._write(record)
        return list(scores)

    def _abstain(
        self, key: str, count: int, reason: str, counter: str, *, calls: int
    ) -> list[float]:
        """Record an abstention: `0.0` for every candidate, counted, and written to the cache."""
        if counter == "errors":
            self._errors += 1
        self._abstained += 1
        scores = [0.0] * count
        self._scores[key] = scores
        self._write(
            JudgeRecord(
                key=key,
                prompt_hash=prompt_hash(),
                prompt_version=PROMPT_VERSION,
                model=self._model,
                temperature=self._temperature,
                candidates=count,
                scores=scores,
                status="abstained",
                reason=reason,
                calls=calls,
            )
        )
        return list(scores)

    def __call__(self, query: str, candidate: str) -> float:
        """`query` against one candidate: the probe's pairwise path, one provider call per pair.

        Slower than `score_many` by design -- `discrimination_scores` walks candidates one at a time
        -- and memoised on exactly that input, so a repeated crossing is free. Batching that loop is
        a separate decision: it moves the committed reranker floor figures (ADR-0034).
        """
        return self.score_many(query, [candidate])[0]

    def report(self) -> JudgeReport:
        """What this instance spent and could not answer, with the pinned configuration."""
        return JudgeReport(
            model=self._model,
            temperature=self._temperature,
            prompt_version=PROMPT_VERSION,
            prompt_hash=prompt_hash(),
            calls=self._calls,
            reused=self._reused,
            memoised=self._memoised,
            abstained=self._abstained,
            unparseable=self._unparseable,
            errors=self._errors,
            stale_records=self._stale,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            uncached_tokens_in=self._uncached_tokens_in,
            cached_tokens_in=self._cached_tokens_in,
        )

    def usage(self) -> SimilarityUsage:
        """The seam's own currency: provider tokens (in + out) and provider calls attempted.

        `calls` is provider traffic, not the number of times this instance was asked for a score --
        the memo and the cache keep the two apart (issue #104). Nothing here is ever added to the
        LLM's `tokens_in`/`tokens_out`: a different currency, spent by one arm and not the others.
        """
        return SimilarityUsage(tokens=self._tokens_in + self._tokens_out, calls=self._calls)
