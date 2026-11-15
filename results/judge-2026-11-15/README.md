# An LLM judge that reads the state, as arm 2 (#295 item 2, ADR-0034)

Arm 2 dispatches by scoring each admitted program against the request. Until now every scorer
behind that seam read text: a lexical scorer, an embedding model and a local reranker. This run
puts a hosted LLM there. It reads the request, the observed state (`StateFingerprint.as_text()`)
and each candidate's description, and returns one score per candidate. It does **not** see the
probe strings, which are what arm 3 executes. The registration is spec §7 item 14 (revision 123)
and its budget and repeatability subsample are revision 156, both declared before the first
scored call.

## Result

On the two libraries where the judge is a usable baseline, **arm 3 mis-fires less often than the
judge at matched coverage, in both repeats**. The judge closes most of the gap the text scorers
left, but not all of it.

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| arm 3: coverage, mis-fires | 187/400, 0/187 | 187/400, 0/187 | 189/400, 0/189 |
| judge floor, run A: strict top-1 (Wilson lower bound vs 0.333) | not measurable | 129/240 (0.474), usable | 121/240 (0.441), usable |
| judge floor, run B | not measurable | 136/240 (0.503), usable | 97/240 (0.344), usable |
| judge at matched coverage, run A: mis-fires (95% Wilson) | 5/188 (0.011–0.061) | 38/230 (0.123–0.219) | 13/196 (0.039–0.110) |
| judge at matched coverage, run B | 0/183 (0.000–0.021) | 23/213 (0.073–0.157) | 10/190 (0.029–0.094) |
| coverage gap (judge − arm 3), A / B | +0.002 / −0.010 | +0.107 / +0.065 | +0.018 / +0.003 |
| difference (judge − arm 3), A / B | +0.027 / +0.000 | +0.165 / +0.108 | +0.066 / +0.053 |
| the same, reranker arm 2 | +0.763 | +0.711 | +0.709 |
| the same, lexical arm 2 | +0.791 | +0.805 | +0.765 |
| smallest detectable difference, A (50% base rate / observed rate) | 0.145 / 0.033 | 0.138 / 0.079 | 0.143 / 0.052 |

Arm 3's upper Wilson bound is 0.020 in every library, below the judge's lower bound in all four
usable cells. The reranker and lexical rows are the committed ones
([Reranker arm 2](../replicates-2026-10-05/README.md#reranker-arm-2)).

**What it decides, by the registered rules (ADR-0034 decisions 7 and 8):**

- **run-12 and run-13: the comparison counts.** The judge clears item 11's floor in both runs,
  and its two repeats differ by less than its gap from arm 3: the repeats' differences are 0.165
  and 0.108 on run 12 (0.057 apart), and 0.066 and 0.053 on run 13 (0.013 apart). Arm 3 mis-fires
  less than the judge, in both runs.
- **run-11: no comparison may be worded.** The floor is not measurable. The lock-file intent has
  only one admitted resolution (`take_upstream`), so there is nothing for arm 2 to choose between.
  Separately, the two repeats differ by 0.027, which is as large as the judge's gap from arm 3, so
  by ADR-0034 the number is a draw the run cannot pin at k = 2. Run B's 0/183 ties arm 3, and run
  A's 5/188 does not. Neither is a finding.

**What it shows.** Reading the state through a model call takes text dispatch's mis-fire rate
from 71–81% of its fires to 5–17%. Most of the old gap was the text not saying whether a
program's preconditions hold, and a model given the state mostly can tell. The rest of the gap
remains: at arm 3's coverage the judge still fires a wrong program on 10–38 pairs per library,
where arm 3 fires none. The judge's floor (lower bounds 0.344–0.503) is *below* the reranker's
(0.571 and 0.508), yet it mis-fires far less at coverage. The floor asks which candidate is right when one
must be chosen; the mis-fire rate also asks whether to fire at all, and the state is what answers
that.

**How this sits beside the state-reading controls.** A decision tree fit on the build's states
(ADR-0047), and one over only the library's own precondition verdicts (#295 item 3), both matched
arm 3 on these states with no model call. So the ordering here is: a fitted rule over the state
≈ arm 3 < this judge ≪ text scorers. The judge is a model reading the state *without* being fit
to it, and that costs it 5–17 points of mis-fire rate.

## What may and may not be claimed

- **May:** on libraries 12 and 13, at matched coverage, compiled-precondition dispatch mis-fired
  less often than this LLM judge reading the same state, in both of two independent runs.
- **May not:** that LLM judges in general mis-fire more. This is one model (`deepseek-flash`), one
  prompt (`judge-v1`), temperature 0, and no probe strings in the prompt (ADR-0034's rejected
  table explains why). A stronger model, a different prompt or one shown the probes is a different
  experiment.
- **May not:** anything about library 11, for the two reasons above.
- **May not:** that the gap is what executing checks adds. The fitted state-reading controls
  above close it without executing anything. What this run adds is that a capable model reading
  the state, unfitted, does not.
- **Coverage is matched only approximately on run 12.** The judge gives many candidates a score
  of 1.0, so even at its highest threshold it fires on 230 (run A) and 213 (run B) pairs, against
  arm 3's 187. That is the nearest point item 1's rule allows; its gap (+0.107, +0.065) is
  reported beside it. At the fires it does have, the judge's mis-fire rate barely moves with the
  threshold (`figure1.csv`), so a closer match would be unlikely to close the difference.

## Repeatability (ADR-0034 decision 8)

The registered subsample is every pair: each library was rescored twice, runs A and B, each with
its own cache, so no score is shared. Run A's figures are the registered ones.

| | run-11 | run-12 | run-13 | pooled |
| --- | --- | --- | --- | --- |
| calls in both runs | 164 | 210 | 207 | 581 |
| identical score vectors | 88 | 96 | 116 | 300 (0.516) |
| same top-scored candidate | 157 | 187 | 190 | 534 (0.919) |
| mean absolute A − B, per score | 0.0147 | 0.0270 | 0.0221 | 0.0214 |

Temperature 0 is not determinism on a hosted model (spec revision 41): about half the calls
returned a different score vector, and one call in twelve a different top candidate. The lexical,
embedding and reranker rows carry no such component; they are computed again bit for bit. Every
judge figure above should be read with these numbers in view, and the run B row is why each cell
gives two values.

## Model, prompt and spend

- **Model and prompt:** `deepseek-flash`, temperature 0, prompt version `judge-v1`, prompt hash
  `c01790be38b1e6df880d96e9600138baca216f5fea7e66f9cde649c8632daacb`. Every cache record carries
  the hash, model and temperature, and a cache that disagrees is refused rather than reused.
- **Calls:** 1,162 scored calls in the six caches (164, 210 and 207 per library, twice). The
  floor's calls are 46 on library 12 and 43 on library 13 per run; library 11 has no floor to
  score.
- **Tokens, from the caches:** 2,804,874 input and 6,635,140 output, 9.44 million in all; most of
  the output is the model's reasoning. The largest cache totals 1.76 million, half one rescore's
  registered cap of 3.5 million (`--judge-token-budget`); no run reached the cap.
- **Abstains:** 5 of the 1,162 calls (one in run 11 A, 11 B and 12 A, two in 12 B), all transport
  errors ("peer closed connection without sending complete message body"). Each scored every
  candidate 0.0 and stays in the denominator (item 14); none was retried.
- **Money:** not reported. Study 2's and #266's builds ran on the same key at the same time, so the
  account balance cannot separate this run's cost. Revision 156's 30-call probe cost CNY 0.71;
  scaled by tokens, these 1,162 calls come to about CNY 23, well within the owner's USD 50.

## A bug found and fixed before these figures

The first rescores ran on commit `79e4fa7` (01:35–05:41 UTC). Every library's floor read **not
measurable**, including runs 12 and 13, whose committed lexical floor is 111/240. The cause was in
`live.baseline_floor`, not the judge: since `config_renamed` was added (ADR-0041), the floor scored
every registered intent, and these libraries, planned earlier, hold none of that family's
programs. #370 made the floor measure only the plan's own faults, as Figure 1 already did. The
rescores were then run again on `de5e414` (06:37–07:21 UTC) from the first run's own caches, so
Figure 1's 164 calls per library were read back, not re-asked, and only the floor's calls were new.
**Every Figure 1 point is identical between the two runs**; only the floor lines changed. The
committed outputs are the second run's. Revision 156's dry run counted "164 calls per library, the
floor included": under the bug the floor made none, so the true count is 164 + 46 and 164 + 43.

## Files

- `run-N/{A,B}/cache.jsonl`: every score, one record per call, keyed by the digest of the prompt
  version, model, temperature, request and candidates. This is the evidence.
- `run-N/{A,B}/rescore/`: `summary.txt`, `summary.json`, `rescore.json` (scorer identity and this
  rescore's own usage) and `primary/` (Figure 1 as `figure1.csv` and `figure1.png`).
- `run-N/{A,B}/stdout.txt`, `stderr.txt`: the rescore's own output.
- `verification/agreement.py` and `agreement.txt`: the repeatability table, from the caches alone.
  It imports nothing from this project.
- `verification/recompute.py` and `recompute.txt`: rescores all six from the committed caches with
  a provider that fails if it is called, and checks each `summary.txt` matches, its output paths
  and spend aside (ADR-0034 decision 5: no key and no tokens).

## Reproduce

From the caches, with no key:

```bash
python results/judge-2026-11-15/verification/agreement.py
PYTHONPATH=src python results/judge-2026-11-15/verification/recompute.py /tmp/judge-recompute
```

The runs themselves (needs a DeepSeek key; about two hours per library at the provider's pace):

```bash
python -m precondition_library.bench.rescore --run results/replicates-2026-10-05/run-N \
  --scorer judge --api-key-env DEEPSEEK_API_KEY --judge-token-budget 3500000 \
  --judge-cache results/judge-2026-11-15/run-N/A/cache.jsonl \
  --out results/judge-2026-11-15/run-N/A/rescore
```
