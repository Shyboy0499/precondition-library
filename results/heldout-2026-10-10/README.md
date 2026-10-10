# The held-out stage, 2026-10-10

The first measurement of the primary metric on states **no library saw** (issue #263, spec §7
item 13, ADR-0033). `dirty_tree` declares a path axis the shipped draw never varies -- deeper
directories, a path with a space, a non-ASCII name, a dotfile -- and the registered block
`bench.splits.HELD_OUT_SEEDS` (3000-3039) was dispatched against a **committed** frozen library
with no model call and no rebuild, reported apart from the eval pairs.

## What each file holds

| file | what it is |
| --- | --- |
| `run-12/heldout.json` | provenance: scorer, the frozen library's digest, the block, the fire counts |
| `run-12/summary.json`, `summary.txt` | the stage's own record and text: counts, the matched sentence, the power statement, the wording limit |
| `run-12/primary/figure1.csv` | Figure 1: every arm-2 operating point with its Wilson interval, arm 3's coverage point, the 2b and 2c baselines |
| `run-12/primary/figure1.png`, `primary.txt` | the same figure drawn, and its rendered text |
| `run-12/wrong_fires.jsonl` | **arm 3's mis-fires**, one line each, naming the pair's label and request. It is empty here. Arm 2's counts are in `figure1.csv`; this file is arm 3's because arm 3 is the arm the issue asks about |
| `README.md` | this file |

## Provenance

| | |
| --- | --- |
| frozen library | `results/replicates-2026-10-05/run-12/library-two-sided`, `library_hash ad311de65eb51b120ea97aabb83fe22492c89812232e21bf2c5f1cde4dc8c8c1`, 14 admitted of 14 programs -- the committed library of replicate 2, read-only (digest compared before and after, and the stage raises if it moved) |
| code | branch `pr/263-held-out-states`, commit `003ecf3` for this run; the artifacts are in the commit after it |
| model calls | none. The build happened in the replicate run; this stage only dispatches |
| arm 2 scorer | `lexical` -- the shipped seam. The pinned reranker (#256) is one command away and is **not** in this figure |
| block | `HELD_OUT_SEEDS` 3000-3039 -- 40 seeds, 31 distinct instances, 80 labelled pairs |
| host | Windows, Git for Windows; 105 minutes for the block, which is the cost note in ADR-0033 |

## The measurement

| | value |
| --- | --- |
| labelled pairs | 80 (40 held-out positive states, 40 fault-free negatives) |
| distinct held-out instances (the reading level, ADR-0005 decision 4) | 31 |
| arm 3: fires / wrong | 40 / **0** -- coverage 40/80, mismatch 0/40 |
| arm 3's held-out mis-fire rate, 95% Wilson | **[0, 0.0876]** |
| the same rate in-distribution (run-12's eval pairs, for scale) | 0/187, 95% Wilson [0, 0.0201] |
| arm 2 at matched coverage (39 fires of 80) | mismatch **28/39 = 0.718**, 95% Wilson [0.562, 0.835] |
| smallest detectable mismatch difference, 50% base rate | **0.315** |
| comparison | **vacuous**, by the registered rule: arm 3 decided all 80 pairs correctly |

## What it shows

**Preconditions carried to every held-out state, and were right on all of them.** Arm 3 fired on
all 40 held-out positive states -- it did not merely abstain, which is what a path-sensitive probe
would have done -- and refused all 40 fault-free ones. Across four path families the frozen
programs' probes recognised the state and their preconditions held where they should. The
registered reading applies (ADR-0033 decision 5): because arm 3 also *decided* every pair
correctly, `bench.primary` prints `vacuous_reason` and no comparison; on hand-written gold that
would be a tautology, but on compiled programs it is the result, and the interval is what may be
read -- **this block rules out a held-out mis-fire rate above 8.8%**, where the in-distribution
figure bounds it at 2.0%.

**The axis found a defect before it could measure.** The first attempt at this run failed on seed
3006: `StateFingerprint.observe` read `git diff --name-only` with `str.split()`, so
`docs/release notes.md` became two entries, the `same_file` state read as `disjoint`, and
`build_sandbox` refused the build as mislabelled (ADR-0005 decision 3). Fixed in the same change
(spec revision 124), with that state as the regression test. Nothing in the shipped draw could
have exposed it: every shipped path is space-free.

## What it does not show

- **That no mis-fire would occur.** 40 fires bound the rate at 8.8%, not at 0. The in-distribution
  figure's own bound is 2.0%, so a rise of up to ~9 points is not excluded by this block, and the
  smallest detectable mismatch *difference* at these fire counts is 0.315 -- this block is a
  pilot, and the comparison it cannot state is not a null result.
- **The family.** One fault's axis, not five. The other four faults' states remain in-distribution;
  ADR-0033 names their axes as the next stage.
- **Real repositories.** Four path shapes are a family of shapes, not a sample of checkouts. The
  issue's other source -- real states through the checkout path (#181) -- is not in this stage.
- **A win over text similarity.** No held-out floor is measured, so the stage refuses the wording
  (`WORDING_LIMIT` is a field in `summary.json`, not a footnote here), and the comparison is
  vacuous besides. Arm 2's matched point above is a **description of the figure**, not a licensed
  contrast.
- **The reranker baseline (#256).** The committed figure is the shipped lexical arm 2.
- **Replicates 1 and 3.** The stage measures the library it is given; the other two run
  directories are the same command, and a figure from one library is not a figure over three.

## Reproducing

```bash
# the committed figure: the shipped lexical arm 2, no extra, no key
python -m precondition_library.bench.heldout \
  --run results/replicates-2026-10-05/run-12 --out /tmp/heldout-run-12

# the strongest text scorer measured so far (#256), same block and library
uv sync --extra dev --extra embedding
python -m precondition_library.bench.heldout \
  --run results/replicates-2026-10-05/run-12 --out /tmp/heldout-run-12-cross-encoder \
  --scorer cross-encoder

# the other two committed libraries
python -m precondition_library.bench.heldout \
  --run results/replicates-2026-10-05/run-13 --out /tmp/heldout-run-13
```

The run is deterministic: same library, same seeds, same scorer. Cheaper on Linux than on the host
this was measured on -- one held-out environment is a real sandbox plus every admitted program's
probes, about 2.5 minutes per seed on Windows, which is why the block is 40 seeds and not the
family's ~150 fires. A larger block, and the other four faults' axes, is a pre-registration
revision (ADR-0033), not a flag.
