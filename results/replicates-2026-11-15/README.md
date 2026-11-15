# Two six-family replicates, one with a second model (#266 steps 2–3, ADR-0061)

Runs 11–13 built libraries over five git families. These two builds add the sixth,
`config_renamed`, whose state is an app's config files rather than git history (ADR-0041), and
build the same plan with two compiling models:

- **`run-14`:** `deepseek-flash`, the model of runs 11–13 (#266 step 2);
- **`run-15`:** `deepseek-v4-pro`, a second model from the same provider (#266 step 3).

Both are `bench.live --primary-only` with the default plan, temperature 0, on commit `a89c767`.
They are descriptive, as ADR-0061 registered: **one build per model**, so nothing here separates
a model effect from the build-to-build spread study 2 is measuring.

## Result

| | run-11 | run-12 | run-13 | **run-14** | **run-15** |
| --- | --- | --- | --- | --- | --- |
| compiling model | flash | flash | flash | flash | **v4-pro** |
| families | 5 | 5 | 5 | 6 | 6 |
| programs admitted (two-sided) | 13 | 14 | 13 | 16 of 19 | 17 of 20 |
| lexical arm 2 floor (Wilson lower bound vs 0.333) | not measurable | 111/240 (0.401) | 111/240 (0.401) | 177/288 (0.557) | 153/288 (0.474) |
| arm 3: coverage, mis-fires | 187/400, 0/187 | 187/400, 0/187 | 189/400, 0/189 | 215/480, **0/215** | 238/480, **0/238** |
| lexical arm 2 at matched coverage: mis-fires | 148/187 | 149/185 | 143/187 | 192/220 | 190/234 |
| coverage gap (arm 2 − arm 3) | | | | +0.010 | −0.008 |
| difference (arm 2 − arm 3) | +0.79 | +0.81 | +0.76 | **+0.87** | **+0.81** |
| smallest detectable difference (50% base rate) | 0.145 | 0.145 | 0.144 | 0.134 | 0.129 |

Runs 11–13 are the committed ones ([replicates-2026-10-05](../replicates-2026-10-05/README.md)).

**Per family** (`per_family.txt`), arm 3's wrong fires over its fires, and the lexical arm 2's
at the run's matched threshold. Each family has 80 pairs, 40 of them positive:

| family | run-14 admitted | run-14 arm 3 | run-14 arm 2 | run-15 admitted | run-15 arm 3 | run-15 arm 2 |
| --- | --- | --- | --- | --- | --- | --- |
| branch_renamed | 3 | 0/40 | 33/33 | 3 of 4 | 0/40 | 28/46 |
| **config_renamed** | **2 of 4** | **0/26** | 9/11 | **3** | **0/40** | 31/33 |
| dirty_tree | 3 of 4 | 0/40 | 34/41 | 3 | 0/40 | 41/41 |
| diverged | 3 | 0/40 | 30/41 | 3 of 5 | 0/38 | 30/44 |
| lockfile_conflict | 2 | 0/29 | 24/28 | 2 | 0/40 | 22/23 |
| submodule_moved | 3 | 0/40 | 62/66 | 3 | 0/40 | 38/47 |

"2 of 4" means four programs were compiled for the family and two admitted; a program admission
refused stays in the library directory as a candidate and is never dispatched.

## What it shows

- **Neither of ADR-0061's two reversing outcomes happened.**
  - **The second model's library does not mis-fire like text similarity.** `run-15`'s arm 3 made
    no wrong fire in 238, where the lexical arm 2 at the same coverage was wrong on 190 of 234.
  - **The config family's programs were admitted and did not fire wrongly.** Two of four were
    admitted in `run-14` and all three in `run-15`; arm 3 fired them on 26 and 40 of the 40
    positive config pairs and on no negative one.
- **Both runs agree with runs 11–13.** The difference from text similarity is +0.81 to +0.87,
  against +0.76 to +0.81 before, about six times the smallest detectable difference. Arm 3's
  zero carries to a family outside git history and to a second compiling model.
- **Where the two builds differ, it is coverage, not correctness.** `run-14` fires on 26 of 40
  config positives and 29 of 40 lock-file positives; `run-15` fires on all 40 of each. With one
  build per model, this may be the build-to-build spread study 2 measures rather than the model.

## What it does not show

- **That the method is independent of the compiling model.** One build per model. A sentence that
  compares the two models rests on one build each, and study 2 found a large spread between
  builds of one model.
- **That it holds outside this provider.** Both models are DeepSeek's; a second provider needs a
  key the owner has not supplied.
- **That it holds outside synthetic states.** The config family is a new domain, but its states
  come from this project's own injector and are graded by its own labels, like runs 11–13.
- **Like-for-like with runs 11–13.** These runs have 480 pairs, not 400, because the config
  family adds 80; the five shared families' rows are the comparable ones.

## Commit, model and spend

| | run-14 | run-15 |
| --- | --- | --- |
| model | `deepseek-flash` | `deepseek-v4-pro` |
| commit | `a89c767` | `a89c767` (resumed once with `--resume` after the session's worker restarted) |
| build episodes, compile attempts | 19, 29 | 20, 33 |
| LLM calls, tool calls | 181, 252 | 172, 234 |
| tokens in (cached) / out | 502,753 (333,056) / 513,027 | 503,013 (303,488) / 549,720 |

The money is not reported: study 2's builds and the judge ran on the same key at the same time,
so the account balance cannot separate these two. At the provider's listed rates it is a few
dollars, well within ADR-0061's USD 100.

Commit `a89c767` predates #370, which fixed arm 2's floor for plans that lack a registered family.
These plans hold all six, so the fix does not touch them.

## Files

- `run-14/`, `run-15/`: each run's `plan.json`, `summary.txt`, `summary.json`, build ledger and
  transcripts, both libraries and `primary/` (Figure 1). `run-14.log` and `run-15.log` are the
  runs' own output.
- `per_family.py` and `per_family.txt`: the per-family rows, recomputed from each frozen library
  with no model call. The totals equal each run's `summary.txt`.

## Reproduce

```bash
PYTHONPATH=src python results/replicates-2026-11-15/per_family.py
python -m precondition_library.bench.rescore --run results/replicates-2026-11-15/run-15 \
  --scorer lexical --out /tmp/run-15-rescore
```

The builds themselves need a DeepSeek key:

```bash
python -m precondition_library.bench.live --primary-only --api-key-env DEEPSEEK_API_KEY \
  --model deepseek-v4-pro --out results/replicates-2026-11-15/run-15
```
