# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Versions are **0.x** and the design is still moving. Nothing below claims a
measured result; there are none yet. See
[`docs/decisions/`](docs/decisions/) for reversals and the reasoning behind them.

## Unreleased

### Added

- `tests/test_declared_state.py`: every stub and every skipped test is declared and
  asserted against the code, so implementing one fails CI until the declaration and
  the prose that restated it are updated. Four status claims are pinned to the facts
  behind them, each failing with the document to update. It deliberately does not
  attempt to detect a document contradicting another document — that stays a review
  obligation, and the file says so.
- The compile step (`agents/compile.py`): a solved task plus its transcript and
  state observations become a candidate `Program`. It reads and never executes
  what it generates — a test proves a body that writes a marker file leaves no
  marker until a replay runs it — and a malformed reply is a `CompileResult`
  carrying the reply's token usage, not an exception that would lose the
  episode's cost. Preconditions must be specific, and an empty precondition list
  is recorded as a defect.
- The two-sided admission gate (`agents/compile.py`): the body must satisfy the
  program's postconditions on freshly faulted sandboxes, **and** the
  preconditions must reject each of the other faults' states. An all-accepting
  precondition set is rejected by the negative side, which is the gate's reason
  to exist; a rejection returns `(False, reason)` rather than being dropped.
- Library storage (`library.py`): `library/<program-id>/program.yaml` plus a
  `history.jsonl` of status changes, with `add` accepting only candidates,
  `set_status` refusing unknown ids and unlisted transitions (so `quarantined`
  is terminal), and nothing ever deleted. `library_hash()` is a stable digest
  over every stored program's content, sorted by id, which issue #4 requires in
  every ledger row so a comparison can be shown to have run against one frozen
  library.
- `tests/test_compile_and_admission.py`: the whole pipeline offline against real
  fault-injected sandboxes, including the gate's two rejection modes and its
  determinism.

- `test_no_phrasing_names_a_resolution`: a phrasing may not name a resolution, in
  either wording channel. The AUC controls structurally cannot check this — the
  uninformed one is fixed at 0.500 whatever the words say — so a shared phrasing
  reading "use rebase" would have handed the answer to a text-only dispatcher with
  every gate green. Verified by writing exactly that phrasing and watching the
  check fail. A *paraphrase* that reveals the answer without naming it stays a
  review obligation: no gate can see it, and the spec says so.
- `EpisodeRecord` now stores correctness as facts — `correct_variant`,
  `fired_variant`, `ground_truth_ok` — with `misfired` and `succeeded` derived from
  them, so the quadrant that matters is expressible: a wrong fire in an episode that
  nevertheless succeeded via the fallback. Both facts are required fields, because
  `None` is a meaningful ground truth and a defaulted field could be forgotten and
  read as a benign state (`bench/ledger.py`).
- `IntentSpec` and `ResolutionVariant`: intents carry a paraphrase distribution
  and two or more resolutions decided only by observable state
  (`tasks/intent.py`, `tasks/registry.py`).
- Labelled (state, resolution) pair generator with denominators
  (`bench/pairs.py`) — the raw material the spec's primary metric needs.
- A text-only control measuring how far the request text gets a dispatcher, with
  a positive control that proves the detector fires (`bench/textcontrol.py`).
- Hand-written gold resolutions for both ambiguous intents (`bench/gold/`).
- `Program.variant`, so a wrong dispatch decision is definable at all.
- Determinism tests over the task text, proving every declared phrasing is
  reachable and the same seed yields the same wording
  (`tests/test_faults_deterministic.py`).

### Changed

- `diverged` and `submodule_moved` now have three state-decided resolutions each,
  replacing the single fixed request sentence that made the task text a class
  label and the primary claim untestable (issue #3).
- The text-only control reports the **uninformed and informed request regimes
  separately**, replacing a single pooled number measured under one ceiling. The
  pooled figures (0.795 / 0.801, from the control's pre-split revision) averaged
  a regime in which the text is the answer in disguise with one in which it is
  noise, and described neither; the primary claim is now scoped to the
  uninformed regime, whose AUC is the gated one.
- Arm 1 (`agents/react.py`) now maps a model-declared finish to
  `EpisodeOutcome.SUCCESS` instead of `FALLBACK`. `EpisodeOutcome` records how
  the arm's mechanism completed, not whether the environment is correct, and
  `FALLBACK` means "no stored program applies, so the agent takes over" — the
  compiled arms' outcome. Arm 1 *is* that agent, so the label never described
  it. Correctness stays in `ground_truth_ok`; this changes what an already
  recorded arm-1 `success`/`fallback` row means, not the episodes themselves.
- Arm 1 drives the model's structured tool calls: `Completion` now carries
  `tool_calls` (`provider.py`) and the baseline answers each call with a native
  `role: "tool"` message keyed by `tool_call_id`, instead of parsing JSON out of
  free text. One protocol path, the API's own.

### Not done in this change

- `Library.match_semantic` and `Library.match_preconditions` are still stubs that
  raise. They are the ablation's two arms, and the design requires them to differ
  in exactly one function, decided in the next task; implementing them here would
  have pre-empted that decision.
- Three of the five faults — `dirty_tree`, `branch_renamed`, and
  `lockfile_conflict` — still return a single fixed request sentence and
  therefore still carry the original defect. They are deliberately unconverted,
  must not be included in any dispatch measurement until they gain an
  `IntentSpec`, and are tracked in issue #25.

## 0.0.1 — 2026-09-13

Design-phase release. No agent exists and no result is claimed.

Untagged and deliberately so: nothing here is releasable, and the tag that once
marked it was dropped because a rebase-merge left it pointing at a commit
reachable only through the tag itself. Versions get tagged when there is an
artifact worth downloading and a released snapshot would mean something.

### Added

- Design of record with a pre-registered analysis
  (`docs/superpowers/specs/2026-09-13-precondition-library-design.md`).
- Repository skeleton: every stub names the invariant it must uphold and the plan
  phase that implements it; 30 tests skipped, each marked with its phase.
- `tests/test_replay_isolated_from_provider.py` — a passing test that fails if
  `runtime.replay` can reach `provider`. The claim that a replay costs zero tokens
  depends on this, so the guardrail ships before the code it guards.
- CI running ruff, `ruff format --check`, mypy, and pytest on Python 3.12 via uv.
- ADR-0001, recording the reframe after a prior-art sweep and a method review:
  Claim 1 dropped as prior art, Claim 2 narrowed to its empirical form, the
  primary metric moved to matched dispatch coverage.
- Verified prior-work table in the README, with five corrected attributions from
  the original sweep kept visible rather than silently fixed.

### Changed

- `EpisodeOutcome.MISMATCH` is removed. `outcome` now records only how the arm's
  mechanism completed, never whether the episode was correct — a stored outcome
  could not hold "misfired" and "succeeded" in one row without the two disagreeing.
- `ProgramStatus.VERIFIED` renamed to `ADMITTED`. A program that passed this
  project's own gate has not been verified by anyone.
- The pre-registered analysis was revised **before any data existed**; the
  revision is logged in the spec's revision history.
