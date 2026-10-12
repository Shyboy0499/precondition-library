# The hybrid arm on the three replicate libraries, 2026-10-11

The measurement registered in ADR-0035 (spec §7 item 15, issue #265): retrieve by text, then gate by
preconditions. Each committed frozen library from
[`../replicates-2026-10-05/`](../replicates-2026-10-05/) was re-measured with `bench.hybrid`, with no
model call and no rebuild, under the shipped lexical scorer and the pinned reranker of #256.

```bash
python -m precondition_library.bench.hybrid --run results/replicates-2026-10-05/run-N \
  --scorer lexical --out results/hybrid-2026-10-11/run-N/lexical
python -m precondition_library.bench.hybrid --run results/replicates-2026-10-05/run-N \
  --scorer cross-encoder --out results/hybrid-2026-10-11/run-N/cross-encoder
```

Each `run-N/<scorer>/` holds `hybrid.json` (library digest, scorer, grid, matched point),
`hybrid.csv` (every firing grid point with its Wilson interval), `hybrid.png`, and `summary.txt` /
`summary.json`. Code: main at `28bd85b`.

## Result

Over 400 labelled pairs per library (200 positive, 200 fault-free negatives), uninformed regime:

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| arm 3 alone: fires, mis-fires | 187, 0 | 187, 0 | 189, 0 |
| hybrid at arm 3's coverage (lexical / reranker): fires, mis-fires | 187, 0 / 187, 0 | 187, 0 / 187, 0 | 189, 0 / 189, 0 |
| hybrid grid points (lexical / reranker) | 2,862 / 12,798 | 2,808 / 13,776 | 2,892 / 12,798 |
| mis-fires at **any** grid point | 0 | 0 | 0 |
| most fires at any grid point | 187 | 187 | 189 |

Widest zero-mismatch point per `k` (fires; a description of these pairs, ADR-0035):

| k | run-11 lexical / reranker | run-12 lexical / reranker | run-13 lexical / reranker |
| --- | --- | --- | --- |
| 1 | 56 / 65 | 56 / 75 | 65 / 76 |
| 2 | 85 / 117 | 83 / 115 | 76 / 101 |
| 3 | 91 / 136 | 107 / 145 | 87 / 137 |
| 5 | 122 / 157 | 117 / 167 | 113 / 152 |
| 10 | 172 / 181 | 160 / 181 | 172 / 177 |
| all | 187 / 187 | 187 / 187 | 189 / 189 |

## What it shows

**The hybrid never mis-fired and never fired more often than arm 3.** No grid point, under either
scorer, in any library, fired a wrong program. And no grid point fired more than arm 3 alone. That
second half is a property of the design, not a finding: the hybrid fires only a program whose
preconditions hold, so its fires are a subset of arm 3's. Retrieval can only remove fires; it can
never add one. At `k = all` with no binding floor it makes exactly arm 3's 187–189 fires.

**So the text stage costs coverage and buys nothing here.** Under both scorers' orderings, every
accepting program the walk reached was an acceptable resolution of its state, so the order text put
them in never turned a fire wrong. A tighter `k` or floor only drops correct fires. The reranker
drops fewer than lexical at every `k` below `all` (for example 75 against 56 fires at `k = 1` on
run-12), because it ranks an accepting program higher more often. Neither ever beats `k = all`.

**This corrects a premise of issue #265.** The issue described arm 3's 187/400 as giving up coverage.
But 200 of the 400 pairs are fault-free negatives, where the correct action is not to fire. On the 200
positives, arm 3 fired on 187, 187 and 189: 93.5–94.5%. The coverage arm 3 does give up is the
remaining 11–13 positives where no admitted program's checks held. A gate-after-retrieval hybrid
cannot recover them by construction.

## What it does not show

- **That a hybrid never helps.** On these libraries the accepting programs never disagree. A library
  where two accepting programs resolve a state differently is where text order would matter. These
  libraries do not contain such a case, and this measurement cannot say how often one would arise.
- **A cost saving.** A hybrid that probes only the top `k` programs would run fewer checks. This
  stage derives every point from one full pass, so it measures decisions, not probe cost.
- **Anything at episode level, or on held-out states** (#263).
