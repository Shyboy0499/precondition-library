# ADR-0033 — Measure held-out states with a path axis, one fault at a time

- **Status:** proposed
- **Date:** 2026-10-10
- **Supersedes:** nothing. It extends ADR-0022's pair-level metric to a state source the
  primary result never used, and narrows nothing already decided.
- **Deciders:** repository owner, in issue #263. This record states the resolution chosen
  for that issue, so a later reader can tell whether the code complies with it.

## Context

**The question.** Arm 3's zero mis-fire rate -- 0 of 563 fires across the three replicate
libraries -- was measured on states the fault injectors build. Admission tested every
compiled program's preconditions against states from *the same* injectors and the same
`STATE_GRID`. So the figure is an in-distribution one: it shows the two-sided gate fits
this generator, not that preconditions carry to states the generator never produced.
Issue #263 is that gap, and it is the first thing a reviewer asks.

**What the states already vary, and what they never vary.** Per seed, the injectors draw
content (bodies, commit subjects, hunk positions) along declared Tier 1 axes
(ADR-0005). They never draw **paths**: `dirty_tree` says so in its own axes note -- "file
names and paths (Tier 2: they need parameter binding)" -- and every shipped state writes
`app.py`, `docs/readme.md` and `notes/scratch.txt` whatever the seed. So paths are the one
axis that is both (a) undeclared and (b) cheap to vary without touching a program.

**Why varying it is a real test, not a formality.** The frozen programs' probes name no
path: they read `git status`, `git diff --name-only`, `git ls-files --others`, `comm`,
`git rev-list` and the bound `{upstream_remote}` / `{upstream_branch}`. A probe that is
*path-sensitive* therefore has two possible failures on a held-out path -- it does not
recognise the state (an abstention, which lowers coverage) or it fires and is wrong (a
mismatch, which is the failure the primary claim rests on) -- and neither can be exposed by
the shipped draw, which uses the same three names at every seed.

**The evidence base.** The frozen libraries are committed under
`results/replicates-2026-10-05/`, so a held-out measurement needs no model call and no
rebuild: the same library, the same matchers, other states. The reranker that issue #256
pinned ships behind the same seam (`bench.rescore.scorer`).

**What was measured before this record was written.** Two of the block's seeds (3000-3001)
were built to verify the stage runs end to end: 4 pairs, arm 3 firing on both held-out
states with 0 wrong, and a **vacuous** comparison. Those two seeds are excluded from every
figure this ADR registers, and the block's own seeds had not been built. One decision
below was written *after* that smoke: decision 5's reading rule, because the smoke showed a
compiled arm 3 can decide a small block perfectly -- which `bench.primary` reports as
vacuous, with a message that describes hand-written gold rather than a compiled library.

## Decision

1. **The held-out source for this stage is a new instance axis in `dirty_tree`:** the three
   paths a state writes, drawn from a pool for seeds at or above
   `tasks.spec.HELD_OUT_SEED_BASE` (3000). Below the base, `paths_for_seed` returns the
   shipped triple, so **no shipped seed's state moves** and every committed figure stays
   recomputable from the code that produced it. No other fault gains an axis here.
2. **The plan block is `bench.splits.HELD_OUT_SEEDS`** -- 40 seeds, 3000-3039, the eval
   block's size, chosen against the measured cost of one held-out environment -- disjoint
   from `SMOKE_SEEDS`, `TUNE_SEEDS`, `EVAL_SEEDS`, from `bench.admit_set.ADMIT_SET`, and
   from admission's own seed search (`agents.compile._SEED_SEARCH_LIMIT`, 64). Changing a
   value in it is a pre-registration revision logged in the spec, not a config tweak.
3. **The stage is `bench.heldout`**, and it does three things only: open a **committed**
   frozen library read-only (digest compared before and after), dispatch the held-out block
   through that library's own matchers on real sandboxes, and report the primary metric --
   mismatch at matched coverage, one regime, with the power statement. No model call, no
   rebuild, no library write.
4. **The stage may not word a win.** Spec section 7 item 11 measures arm 2's floor on the
   `TUNE_SEEDS` against the eval library, which is a statement about the shipped states and
   does not transfer to states no library saw. The summary therefore carries
   `bench.heldout.WORDING_LIMIT` as a field, so a reader cannot miss it.
5. **A vacuous comparison is a registered outcome.** `bench.primary` suppresses the
   comparison when arm 3 decides every pair correctly. On hand-written gold that means the
   comparison is a tautology; on **compiled** programs it means arm 3 neither mis-fired nor
   abstained, which is a result and not a tautology. The stage reports the vacuum verbatim
   and the reading is: the interval on arm 3's held-out rate is what bounds the claim, and
   the arm-2 contrast waits for a block on which arm 3 abstains somewhere.
6. **The reranker baseline is runnable in this stage but is not run by it by default:**
   `--scorer cross-encoder` measures the same block with `#256`'s pinned reranker, needs the
   `embedding` extra and no provider key. The committed first run names the scorer it used.
7. **What is deferred is named, not dropped:** held-out axes in the other four faults, the
   real-checkout source (`#181`) and a held-out floor are separate stages of #263.

## Consequences

**Accepted:**

- **One fault.** The stage answers the issue's question for `dirty_tree`, not for the
  family. The other four faults' states remain in-distribution.
- **Thirty-one independent environments, not forty.** The block's 40 seeds draw 31 distinct
  instances, and the stage reports that count (`distinct_instances`) rather than leaving it
  to be inferred: independence is keyed on the instance (ADR-0005 decision 4), and the
  requests crossed with one environment are one decision for a request-blind arm 3. The
  seed count and the pair count are denominators, not observation counts.
- **A family of shapes, not a sample of repositories.** The pool varies directory depth, a
  path with a space, a non-ASCII name and a dotfile. Real repositories vary far more than
  that, and this is not evidence about them.
- **Paths are created by a preparatory commit.** The shipped base tree carries only
  `app.py` and `docs/readme.md`, so a held-out state's paths are committed and pushed
  *before* `record_base` -- part of the base both sides share, not part of the fault.
- **git quotes non-ASCII paths.** `git diff --name-only` prints `docs/Übersicht.md` as
  `"docs/\303\234bersicht.md"` under the default `core.quotepath`. The dispatch stage is
  unaffected (the fingerprint's sets are compared to each other, and they are quoted the
  same way on both sides), but a held-out **resolution** on that path would be refused by
  `tasks.invariants.recorded_state_intact`, which compares the committed diff against
  `change_surface`'s raw names. Nothing in this stage runs a resolution.
- **Cost.** A held-out environment is a real sandbox plus every admitted program's probes;
  on Windows that is about a minute per seed, which is why the block is 40 seeds and not
  larger. The block is a pilot: the smallest detectable difference for its fire count is
  printed beside the comparison, and nothing below it may be read.
- **Replicates 1 and 3.** The stage measures whatever frozen library it is pointed
  at, and its `heldout.json` records that library's digest. The first run names the
  replicate it measured; the other two are the same command against their own run
  directories, and a figure computed from one is not a figure over the three.
- **The axis has already paid for itself, and the defect it found is fixed here.** Its first
  build was refused: `StateFingerprint.observe` read `git diff --name-only` with `str.split()`,
  so a path containing a space became two entries and the `same_file` state read as `disjoint`
  (spec revision 124). `local_touched_files`, `upstream_touched_files` and the change-surface
  check in `tasks.invariants` now read one path per line. No shipped fingerprint moves -- every
  shipped path is space-free -- and the refused state is the regression test.

**Gained:** an out-of-distribution answer for one fault, measured on the committed frozen
libraries with no model call; the mechanism the other faults' axes will reuse; and a test
that proves no shipped seed's state moved.

**New obligations:** `tests/test_heldout_states.py` must be extended in lockstep with
`HELD_OUT_FAULTS` -- a fault listed there without a declared axis fails a test rather than
silently measuring the shipped states again; and any change to the block, the pool or the
reading is a pre-registration revision in the spec's revision history before the data it
would be read from exists.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| A new seed block with the **shipped** axes (100 more seeds of the same generator) | It would vary content draws, which the eval set already varies. It is a second sample of the same distribution, so it cannot answer a question about a different one. |
| A **sixth fault family** | It is the strongest source and the largest: an intent, an injector, a checker, a state grid entry and registry accounting. Worth doing; not as the first stage, because it answers "does a new family work" and not "does the gate generalise". |
| **Real checkouts only** (`#181`, the issue's first source) | Single states, hand-labelled, not reproducible in CI, and n is whatever repositories one happens to have -- no power statement can be attached. Kept as the second source the issue names, reported apart from this one. |
| **Hand-labelling** the held-out states | The label must be the fault's own rule (`bench.pairs.label`), or a dispatcher could be measured against a person's judgement of the same state it reads. Hand labels are the checkout source's method, not this one's. |
| **Crossing each held-out state with several requests** to raise arm 3's fire count | Pseudo-replication. Arm 3 reads no text, so its decision is the same for every request on one environment; multiplying the requests would shrink the smallest detectable difference without adding an independent observation. The unit is the environment (ADR-0005 decision 4). |
| **Rebuilding** a library for the held-out run | The frozen libraries are the artifact the figures are computed from (ADR-0009), and a rebuild admits programs with a model run that the held-out claim would then depend on. |
| Pooling the held-out pairs with the eval pairs into one figure | The two answer different questions -- in-distribution and out-of-distribution -- and pooling them hides which one moved. Regimes are already never pooled (ADR-0004); this is the same rule for state sources. |

## What would reverse this decision

- **A shipped seed's state moving.** `tests/test_heldout_states.py` asserts the shipped
  triple for every seed below the base; a failure means the committed figures are no longer
  recomputable and the axis must be re-drawn.
- **Arm 3 mis-firing on the held-out block.** Then the in-distribution result does not
  generalise, the wording of the primary claim narrows to the states the generators produce,
  and the axis that exposed it becomes the next stage rather than a follow-up.
- **A held-out floor becoming available at no cost** -- the pool crossed with the grid, say
  -- because then the win wording could be registered instead of refused.
- **The other four faults' axes landing.** Then this stage is one row of a family result and
  should be read as such.
