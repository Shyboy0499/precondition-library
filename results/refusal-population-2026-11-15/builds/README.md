# Study 2's 20 library builds, frozen 2026-11-15 (refusal-population §4 step 4, §5)

The libraries study 2 evaluates, committed before its evaluation finishes so they exist outside the
machine that built them. Nothing here is a result yet: the registered analysis (§4 steps 5–7) reads
these libraries and is running, and its report will sit beside this folder.

**What was run.** `bench.population` on commit `e7b48ea`, the code the registration's step 2 fixed,
with the frozen refusal set `results/refusal-population-2026-11-01/R`:

```bash
python -m precondition_library.bench.population \
  --out results/refusal-population-2026-11-15/builds \
  --refusal-set results/refusal-population-2026-11-01/R \
  --api-key-env DEEPSEEK_API_KEY --jobs 4
```

Each build is `bench.live --primary-only` with `deepseek-flash` at temperature 0. Build `b` (0–9)
permutes the admit-set plan with seed `b`; configuration R adds the rule that a program must refuse
every state of R. Each folder holds its `plan.json`, build ledger and transcripts, both libraries
(`library-two-sided/build.json` records the order and, under R, the refusal set's SHA-256),
Figure 1 on the synthetic pairs, and `summary.txt`. `population.json` is the runner's record.

| build | compiled | admitted (two-sided) | build | compiled | admitted (two-sided) |
| --- | --- | --- | --- | --- | --- |
| 0-0 | 17 | 17 | R-0 | 19 | 16 |
| 0-1 | 22 | 14 | R-1 | 22 | 15 |
| 0-2 | 21 | 15 | R-2 | 18 | 17 |
| 0-3 | 19 | 16 | R-3 | 21 | 15 |
| 0-4 | 19 | 17 | R-4 | 22 | 14 |
| 0-5 | 21 | 16 | R-5 | 20 | 14 |
| 0-6 | 17 | 17 | R-6 | 20 | 15 |
| 0-7 | 20 | 16 | R-7 | 20 | 15 |
| 0-8 | 19 | 16 | R-8 | 22 | 15 |
| 0-9 | 18 | 17 | R-9 | 19 | 16 |

**Spend.** 3,936 model calls; 11.7 million input tokens (7.4 million of them cached) and 10.8
million output tokens over the 20 builds. The money is not reported: the judge and #266's builds
ran on the same key at the same time.

## Deviations

§5 allows a build stopped for a reason outside the method to be resumed, and replaced by build 10,
11 or 12 only if it cannot be completed. Two kinds of interruption happened. Neither needed a
replacement, so all 20 builds are the registered indices, and both configurations have 10 valid
builds (§8 asks for at least 8).

- **The session's worker restarted** at about 11:00 UTC, part-way through builds R-0 to R-3. The
  runner was started again and resumed each with `bench.live --resume`, which keeps the episodes a
  build had committed. `population.json` counts the runs of the second invocation only, so it shows
  one run for each of these four.
- **Build R-8 crashed in admission** (`re.error: incomplete escape \u`): a compiled postcondition's
  `expect_pattern` was not a regular expression Python could read, and the exception ended the build
  instead of refusing the program. The runner resumed it, and the second run completed
  (`population.json`: two runs). The bug was fixed afterwards on main (#373, spec revision 159), not
  in this code: the builds ran on the registered commit throughout.
