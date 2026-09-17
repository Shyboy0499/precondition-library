# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Versions are **0.x** and the design is still moving. Nothing below claims a
measured result; there are none yet. See
[`docs/decisions/`](docs/decisions/) for reversals and the reasoning behind them.

## Unreleased

### Added

- The ablation report (`bench/report.py`): `ablation_table` groups the ledger into
  one row per (arm, fault, occurrence) carrying episodes, success rate, mismatch
  rate, mean tokens, mean LLM calls and mean wall clock — every rate with its
  numerator and denominator, every mean with the count it averaged. `invalid`
  episodes are excluded from those denominators and reported as their own rate,
  and an invalid rate above 10% is flagged as making the run suspect rather than
  analysed (spec §7, item 9). `cost_curve` and `mismatch_comparison` are the two
  demo figures: a secondary cost model grouped by arm and occurrence, and an
  arm 2 vs arm 3 mismatch rate at matched N with a Wilson interval implemented
  here in the standard library (no scipy). Both say in their output that the
  pre-registered primary analysis — mismatch vs coverage at matched coverage over
  labelled dispatch pairs — is elsewhere, and that the episode loop is
  underpowered; a rate under the small-N guard is labelled noise, not printed as
  a finding. `write_report` emits the CSVs, `report.txt` and PNGs. Figures need a
  plotting library: `matplotlib` was already declared in pyproject's `dev` extra,
  so it is used and no dependency was added; the CSV is the deliverable and the
  PNG is a rendering of it.
- The episode runner (`bench/run.py`): `run_episode` takes one fault and seed end
  to end — build a sandbox, inject, observe, let the arm act, grade with the
  fault's own checker, and return one ledger row — and `run_benchmark` runs the
  repeat structure, each arm from an empty library, occurrence by occurrence, so
  the library accumulates the way it would in use. The three arms differ in one
  place: arm 1 solves with the agent, arms 2 and 3 dispatch to a stored program
  and fall back to solving, at full price, when none applies. An arm's token
  spend is summed through a provider wrapper for the episode that incurred it,
  compile included, so a replay records zero LLM calls — the cost model's
  load-bearing invariant, asserted at the integration level with a provider that
  records every call. `run_benchmark` refuses a fault in
  `EXCLUDED_FROM_BENCHMARK` rather than skipping it, because a skipped fault
  would shrink a denominator silently.
- The two dispatch arms (`agents/dispatch.py`): `dispatch_semantic` (arm 2) and
  `dispatch_preconditions` (arm 3) each call one matcher and return a shared
  `Dispatch` record — the chosen program or `None`, the score when the mechanism
  has one, and a reason. Deliberately trivial, because the arms must differ in
  exactly one function: every arm-specific decision stays in `library.py` behind
  the matcher, and a re-rank, a second filter or a score adjustment written here
  would be logic only one arm gets, which §4 of the spec calls a failed design.
- Arm 3's dispatch (`library.py`, `runtime/probes.py`): `Library.match_preconditions`
  returns the `admitted` programs whose executable preconditions all accept the
  environment, most-specific first by precondition count, and `[]` when nothing
  matches, which is the fallback path rather than an error. Evaluation lives in
  `runtime.probes.evaluate_preconditions`, shared with admission so the gate and
  the matcher cannot disagree about what "the preconditions held" means, and the
  sandbox parameter binding moved there from `replay` for the same reason.
  `Program.applicable` was deleted rather than implemented: `program.py` declares
  itself data-only, and running a probe is I/O.
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

- Every ledger row now carries a required `occurrence_role` — `variant` for the
  first occurrence of a resolution of its fault, `replay` for every later one —
  and the two demo figures are computed over different roles (issue #81). The
  role is declared in `bench/splits.py` from the injectors' own
  seed-to-resolution mapping (`occurrence_roles`), written by `bench/run.py`, and
  required on the record with no default: a missing role would read as a variant,
  which is the role that may be counted as an independent observation, so a
  default would claim independence the plan does not provide. The cost curve is
  computed over the **replays** — a variant is the state's learning pass, where
  no program can exist yet and the curve cannot bend — and the mismatch
  comparison over the **variants**, the only independent observations, since a
  replay's program was admitted by the occurrence that introduced its state. Both
  figures, both CSVs and `report.txt` name the occurrences they used, and
  `report.txt` reports the count of each role so a reader can see what was
  excluded. The eval set's arithmetic is stated in spec §7 and pinned by
  `tests/test_seed_splits.py`: each measurable fault declares three states, so
  40 eval seeds yield 3 variants and 37 replays per family, and the episode-level
  mismatch comparison has six independent observations rather than eighty.
  **This narrows a claim rather than adding one** — the pre-registration's
  primary comparison is the pair-level one (issue #5), which the episode loop
  never produced — and it is logged as revision 13 in the spec's history before
  any eval data exists. Ledgers written before this change cannot be read back;
  they are re-run rather than migrated, because a role guessed after the fact is
  the defect the field exists to fix.
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
- The README describes the repository that exists rather than the design phase it
  replaced. Its status block now says the apparatus is implemented and the suite
  is green in CI while **no dispatch comparison and no episode has been run**, so
  no result is claimed; per-module status points at
  `tests/test_declared_state.py` and the issue tracker instead of being restated
  (CONTRIBUTING rule 5); the module layout lists `similarity.py`, the
  `runtime/probes.py` evaluator, the full `bench/` (report and seed plan
  included) and the `tasks/` modules; the phase table is replaced by a "State of
  play" section; and a "Running it" section records that the seed plan is fixed
  in `bench/splits.py` and that the API key is the caller's, not read from the
  environment.
- The README status block now separates a **demonstrated mechanism from an
  unmeasured claim**: a smoke pass has run against `deepseek-chat` (48 episodes,
  the smoke seeds run twice, archived in `.skillpilot/temp/smoke/previous-4/`),
  so "nothing has been measured" is no longer true, while the pre-registered
  comparison (mismatch at matched coverage, issue #5) still is not. A new "First
  demonstration" section reports the pass — per-arm episodes, correct end state,
  fires, replays and tokens; the per-occurrence cost curve; and the
  per-occurrence LLM calls — and states, beside the figures, what the pass is
  not: a result for the primary claim, evidence from five fires per arm,
  independent observations, or a cache-free cost. The status block, the "What
  this is not" table and "State of play" were corrected in place because they are
  live documents (CONTRIBUTING rule 5); the earlier README bullet above is left
  as the record of what it said before.

### Fixed

- The README said the skipped gold checkers in `tests/test_checkers_against_gold.py`
  wait on issue #4. Their own skip reason names issue #9, where the checker
  execution and its negative controls are tracked, so the reference is corrected.
  The README also stated that `library/`'s git history *records* programs being
  demoted; no program has been admitted yet, so that is rewritten as what
  committing the library is for rather than as a present fact.
- `submodule_moved`'s module docstring no longer says the fault is excluded from
  dispatch measurement. It has carried an `IntentSpec` with three resolutions since
  issue #3, so `registry.ambiguous_intents()` returns it and `EXCLUDED_FROM_BENCHMARK`
  does not include it; the prose had restated the status from before it gained an
  intent. It was not caught by `test_declared_state.py` because the claims table pins
  four sentences, not this one. The genuinely excluded faults are unaffected.
- `test_dispatch_arms.py::test_dispatch_leaves_the_repository_clean` no longer
  asserts an empty `git status --porcelain`. An empty status can only pass on a
  pristine checkout, so it failed for a contributor whose branch has uncommitted
  work and made a real leak indistinguishable from their own edits. It now reuses
  the shared `repository_unchanged` fixture, which asserts the working tree is
  unchanged since import — the weaker-looking and stronger check.
- The sandbox environment is an allowlist, not `dict(os.environ)` (spec §9). The
  spec claimed the environment was scrubbed and `HOME` redirected, but every
  other variable the operator had — an exported API key included — was handed to
  model-authored bodies and probes. `git_env` now inherits only `PATH`, the
  locale, `TMPDIR` and the pinned `GIT_*` set, and `HOME` is redirected into the
  sandbox by every caller. A test sets a sentinel in the test process and
  asserts a command under the sandbox environment cannot read it, so a future
  spread fails rather than passing an allowlist-only check.
- Spec §8's "same program mismatches twice" is implemented. The runner counts
  wrong-variant fires in the program's `history.jsonl`, and
  `Library.record_mismatch` quarantines at the second. This covers the failure
  demotion never caught: a program that fires the wrong resolution while its
  postconditions still hold is not demoted, so without the count it would keep
  mis-firing. A timeout is not counted, matching the bar demotion already sets.
- Spec §8's "capped backoff retry" is implemented in the episode runner's
  provider wrapper: 429 and 5xx only, three attempts total, with every attempt
  added to the ledger's `llm_calls`. A 4xx fails immediately. The retry is
  therefore visible, as §8 requires — a retry that hid its failed attempts would
  understate the calls an episode paid for.
- The compile prompt frames repository content as untrusted data. The whole
  payload — request, observed state and solution transcript, the last of which
  carries commit messages and file contents an attacker can write — now travels
  inside delimiters the system prompt names, with a sentence saying it is data
  to compile and never instructions to follow (spec §9).
- `bench/report.py` and spec §7 stated the demo as 5 faults × 4 occurrences × 3
  arms = 60 episodes. Only the two faults with an ambiguous intent are runnable
  (`registry.ambiguous_intents()`; the other three are in
  `EXCLUDED_FROM_BENCHMARK`), so the demo is 24 episodes and 60 is the nominal
  grid. The README no longer names issue #60 as an open defect (it is fixed) and
  points at `EXCLUDED_FROM_BENCHMARK` for the fault exclusion rather than at the
  closed issue #25.
- A replay whose *body* names a declared parameter the current environment cannot
  bind is a recorded outcome, not an exception (issue #76). `runtime.replay` used
  to raise `UnboundParameterError` out of `bench.run`'s `replay(fired, box)`, so a
  program that fired and could not work — the primary metric's numerator — killed
  the whole run instead of being counted, and every later episode was lost.
  `ReplayResult.unbound_parameter` now records it: the body never runs, the
  program is demoted (it fired on a state it cannot serve), the episode falls back
  to ReAct for that episode only, and the ledger's new `replay_failure_reason`
  names the cause, keeping it distinct from a body that ran and failed its
  postconditions. A placeholder outside the runtime's vocabulary still raises, so
  admission still refuses that compile defect and issue #77 can rely on the
  distinction.
- The compile prompt states the exact shape of every field with a minimal example
  (issue #78). Three of four `semantic`-arm compile replies failed `Program`
  validation on field *shape* — `body` returned as a list of commands and
  `parameters` of the wrong type — and the prompt named the fields in prose
  without saying what shape to emit. `body` is now stated to be one
  newline-separated string and `parameters` a list of names. Shape drift is not
  coerced: a list body is still rejected with the field named, because joining it
  would hide the prompt defect and suppress the compile-quality signal
  `compile_failure_reason` carries. The change makes the contract testable; it does
  not measure the real-model rate, which one smoke arm cannot.
- Admission refuses a body that uses a parameter no precondition names (issue #77).
  A precondition is not only how a program decides whether to fire, it is how the
  program declares what it needs: the smoke pass produced three rows carrying
  `replay_failure_reason` because a `submodule` program whose body used
  `submodule_path` and whose preconditions did not mention it accepted a `diverged`
  sandbox, fired there, and could not run. The check is syntactic -- the body's
  placeholders against every precondition's probe -- so it runs before any sandbox,
  and the rejection names the parameter. The obligation is stated in the compile
  prompt, which is what makes it a contract rather than a trap.
- The unrelated-fault negative class probes one seed per *state*, not one fixed
  seed per fault (issue #75). `FaultSpec.variant_for_seed` makes each injector's
  seed-to-state mapping queryable, so `diverged` is built at seeds 0, 1 and 2 and
  `submodule_moved` at 0, 1 and 4, where the old class built each at seed 0 only.
  The rejection reason reports the count actually built, so the number matches the
  coverage. The faults that expose no mapping (`dirty_tree`, `branch_renamed`,
  `lockfile_conflict`) are still one state each; that remainder is sampling and is
  labelled as such in `_state_seeds`' docstring rather than presented as coverage.

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
