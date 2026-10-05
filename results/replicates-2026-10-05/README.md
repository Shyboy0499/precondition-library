# Three replicate primary-only builds, 2026-10-05

The evidence behind the README's [Primary result](../../README.md#primary-result): the three
whole-run replicates (spec §7 item 2) of `bench.live --primary-only`. Each run built its own
frozen library from the admit set (ADR-0032) and then measured the pair-level primary metric
(ADR-0022) on it, with no model call after the build. The per-run table and the discussion are on
[#214](https://github.com/Shyboy0499/precondition-library/issues/214#issuecomment-5999250801).

Committed because a frozen library is the artifact every pair-level figure is computed from
(ADR-0009), and a figure that cannot be recomputed from what is committed is not a result. With
these, anyone can re-measure the primary metric -- with the shipped arm 2 or another -- without a
model key and without rebuilding.

## What each directory holds

| file | what it is |
| --- | --- |
| `library-two-sided/` | the frozen library: every compiled program with its `history.jsonl`, admitted or refused, and `build.json` |
| `plan.json` | the run's `LivePlan` and model, as `bench.live` wrote it first |
| `build.jsonl` | one ledger row per build episode: outcome, tool calls, tokens, admission and its reason |
| `build.transcripts.jsonl` | each build episode's whole solve: the request, every command and its output |
| `summary.json`, `summary.txt` | the run's own summary: floor, Figure 1, Claim 2 |
| `primary/` | Figure 1: `figure1.csv` (every operating point with its Wilson interval), `figure1.png`, `primary.txt` |

Not committed: the positive-only libraries (the admission factorial's second library; no pair-level figure
reads them), and the sandboxes.

## Provenance

| run | replicate | code (main) | model | notes |
| --- | --- | --- | --- | --- |
| `run-11` | 1 | `a6ff042` | `deepseek-flash` | Built before #244 (awk `{next}`), #245 (`^{param}` anchors) and #246 (empty replies retried): both lockfile programs met the awk defect (one would have been refused anyway) and a third lockfile compile was lost to an empty model reply; one container restart, resumed with `--resume`; the pair-level stage was recomputed with #247's code after its Figure 1 plot crashed on a Wilson rounding error. Re-gated offline under the final admission it reads arm 3 0/187 against arm 2 141/186, floor still not measurable. |
| `run-12` | 2 | `d524978` | `deepseek-flash` | Every resolution of every intent admitted. |
| `run-13` | 3 | `44a1ffc` | `deepseek-flash` | |

## Re-measuring

```bash
# the shipped lexical arm 2: reproduces summary.txt exactly
python -m precondition_library.bench.rescore --run results/replicates-2026-10-05/run-12 \
  --scorer lexical --out /tmp/run-12-lexical

# the pinned embedding arm 2 (#104): needs the embedding extra and huggingface.co reachable
uv sync --extra dev --extra embedding
python -m precondition_library.bench.rescore --run results/replicates-2026-10-05/run-12 \
  --scorer embedding --out /tmp/run-12-embedding
```

The lexical rescore of `run-12` was checked against its own summary and matches it to the last
digit: arm 2's threshold, 149/185 at matched coverage, the 111/240 floor.
