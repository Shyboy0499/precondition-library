# A state reader that sees only what the probes see, 2026-11-02 (#295, item 3)

**Exploratory**, like the fingerprint classifier it extends (`results/state-classifier-2026-10-26/`,
ADR-0047). That classifier read the whole `StateFingerprint`, including facts arm 3's programs
never look at, and matched arm 3. This control reads only arm 3's own evidence. Its features are
the verdicts of the library's precondition probes on the state: every distinct precondition among
the library's admitted programs, run on the state, held or not.

```bash
python -m precondition_library.bench.probe_classifier --out results/probe-classifier-2026-11-02
# the same analysis again, from the recorded verdicts, with no sandbox or probe:
python -m precondition_library.bench.probe_classifier \
    --from results/probe-classifier-2026-11-02 --out <scratch>
```

- **Per library.** The three committed libraries (runs 11, 12 and 13) have 60, 60 and 57 distinct
  preconditions among 13, 14 and 13 admitted programs.
- **The tree may fire only what its library can.** It may fire only a resolution its library
  holds an admitted program for. Run 11 holds no `keep_local` program and run 13 no `rename`
  program, so their trees label those states "fire nothing". A tree free of that restriction, as
  the fingerprint classifier was, is reported beside it.
- **Training and scoring** are the fingerprint classifier's:
  - one decision tree per intent, with default hyper-parameters and `random_state=0`;
  - trained on the 56 build states (the admit seeds, with the fault-free state at each), labelled
    by the intents' rules;
  - scored on Figure 1's 400 eval pairs and the 400 held-out pairs, graded by `bench.coverage`.
- **Arm 3 is recomputed from the very same verdicts.** A program fires when all its
  preconditions hold, the most preconditions first. The recomputation reproduces the committed
  counts exactly: Figure 1's 187/0, 187/0 and 189/0 fires/wrong on eval, and the held-out stage's
  193/13, 193/8 and 195/21. On 36 sandboxes it also agrees with `Library.match_preconditions`
  itself, which a test re-checks.
- **Every sandbox's verdicts are recorded** in `verdicts.jsonl.gz`. Re-running the analysis
  from them reproduces `report.json` and `summary.txt` byte for byte.

## Result

Each cell is fires / wrong fires on 400 pairs, 200 of them positives (pairs whose state needs a
resolution).

| library | block | tree over probe verdicts | arm 3, same verdicts | unrestricted tree | same decision as arm 3 |
| --- | --- | ---: | ---: | ---: | ---: |
| run 11 | eval | 187 / **0** | 187 / 0 | 200 / 0 | 370 |
| run 11 | held-out | 193 / **8** | 193 / 13 | 200 / 8 | 363 |
| run 12 | eval | 200 / **0** | 187 / 0 | 200 / 0 | 330 |
| run 12 | held-out | 200 / **8** | 193 / 8 | 200 / 8 | 334 |
| run 13 | eval | 171 / **0** | 189 / 0 | 200 / 11 | 353 |
| run 13 | held-out | 176 / **5** | 195 / 21 | 200 / 15 | 338 |

- **Every wrong fire of the restricted tree is on the same block**: the lock-file intent on
  held-out states (8, 8 and 5). It fires `take_upstream` where only `keep_local` is acceptable.
  Arm 3 also errs there, as often or more.
- **The unrestricted tree's extra errors are fires the library could not make.** On run 13 it
  fires `rename` 11 times on eval and 10 times on held-out, a resolution that library holds no
  program for.

## What it shows

- **Executing the probes as a conjunction is not what makes arm 3 right.** A tree reading the
  same verdicts, and allowed to fire only what the library holds, makes no more wrong fires than
  arm 3 in all six library-blocks, and fewer in two: 8 against 13, and 5 against 21.
- **Coverage is mixed.**
  - Run 11's tree fires exactly as often as arm 3.
  - Run 12's tree fires on all 200 positives without a wrong fire. Arm 3 refused 13 of them.
  - Run 13's tree fires less than arm 3: 171 against 189 on eval.
- **With ADR-0047, arm 3's advantage over a state reader on these states is not in the facts it
  reads, nor in how it combines them.** The fingerprint classifier saw more facts and matched
  arm 3. This tree sees exactly arm 3's facts and, read from them by a learned tree, is at least as
  accurate.
- **What a library's probes can see is set by which programs it admitted.** A missing program is
  a missing resolution for both arm 3 and the restricted tree. The unrestricted tree shows that
  the label is otherwise learnable, but not always separable from what that library's probes see.

## What it does not show

- **Anything at matched coverage.** The trees' leaves are mostly pure, so their probabilities give
  almost no ordering to sweep.
- **Refusal on states nobody built.** Every state here comes from this project's injectors. Study 2
  measures refusal on real conflicts.
- **The LLM state judge** (#295 item 2). It needs an API key.

`report.json` gives each library's operating points and every wrong fire of both trees. `run.log`
is the run's output.
