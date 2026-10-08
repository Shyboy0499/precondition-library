# First demonstration: the smoke pass

Moved here from the README, where the [Primary result](../README.md#primary-result) now stands
in its place. It is kept as the record of the mechanism, not of the claim.

This is a **smoke pass**, not the measurement. Its job is to fail loudly on
wiring, not to produce a number; the pre-registered comparison — mismatch at
matched coverage over labelled dispatch pairs, issue #5 — was not run, and the
seeds are the smoke set from `bench/splits.py`, not the eval set.

**Provenance.** One pass, `deepseek-chat`, 48 episodes = 8 occurrences × 2 faults
(`diverged` and `submodule_moved`) × 3 arms, using the smoke seeds run twice
(`[0, 1, 2, 4, 0, 1, 2, 4]`). The raw ledger is
`.skillpilot/temp/smoke/previous-4/ledger.jsonl`; it is workspace-local and not
committed, its format is `bench/ledger.py`, and `bench/run.py` regenerates it.

Per arm over the whole pass:

| arm | episodes | correct end state | programs fired | replays | tokens |
| --- | --- | --- | --- | --- | --- |
| `react` — arm 1, the baseline | 16 | 16/16 | 0 | 0 | 285,607 |
| `semantic` — arm 2 | 16 | 15/16 | 5 | 2 | 302,060 |
| `precondition` — arm 3 | 16 | 16/16 | 5 | 5 | 276,431 |

"Correct end state" is the fault's own checker grading the final repository
state. A **replay** is an episode in which a program fired and the run spent
**zero LLM calls**; the seven replays across the two compiled arms each spent
0 tokens. 17 of 48 compiles were admitted, and 3 episodes carry a
`replay_failure_reason`.

Mean tokens per episode by occurrence index 1–8. These are the raw per-occurrence
means for the pass, not the figure `bench/report.py` reports. Two differences, and
both matter for reading the table below:

- **The reported figure is cumulative, not per-occurrence.** `bench/report.py`
  plots the running amortized tokens per episode with the break-even marked, because
  a per-occurrence mean is a snapshot: it cannot show whether an arm has yet paid
  back what compiling cost it. On this pass's numbers the two readings disagree
  about when the compiled arms cross the baseline, and the cumulative one is later.
- **It is computed over the replay occurrences only** (here occurrences 3–8 for
  `submodule_moved` and 4–8 for `diverged`, per the roles in the bullet below),
  because a variant is the learning pass. The table shows every occurrence so the
  learning pass is visible too.

| arm | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `react` — baseline | 22.7k | 13.4k | 11.4k | 19.2k | 13.6k | 23.5k | 17.4k | 21.7k |
| `semantic` — arm 2 | 25.8k | 25.7k | 22.4k | 25.9k | 18.2k | 18.4k | 8.7k | 5.8k |
| `precondition` — arm 3 | 20.2k | 38.0k | 8.1k | 30.8k | 9.2k | 12.2k | 10.2k | 9.4k |

LLM calls per occurrence on `submodule_moved`, where the zero-call replays are
plain to see:

```text
semantic      submodule_moved   13 13 13 13 10 10  0  0
precondition  submodule_moved   13 13  0 13  0  0  0  0
```

**What this shows.** A compiled program is replayed with no LLM calls on a later
occurrence of the same state, and the compiled arms' cost falls across
occurrences while the baseline stays flat — the baseline has no library, so it
must solve every episode with the agent and cannot fall. That is the mechanism,
demonstrated end to end against a real model.

**What it does not show, and must not be read as showing.**

- **It is not a result for the primary claim.** The pre-registered comparison
  (mismatch at matched coverage over labelled dispatch pairs, issue #5) did not
  run here, and these are the smoke seeds, not eval. No figure above measures
  the claim; [Primary result](../README.md#primary-result) does.
- **Five fires per compiled arm is not evidence of anything.** Of `semantic`'s
  five fires, four selected a resolution other than the episode's own correct
  one, and one of those ended in the wrong state (`semantic`, occurrence 7).
  `precondition`'s five fires all selected the correct resolution. Four
  mis-fires against zero is a *signal in the predicted direction* at n=5 fires
  per arm — not evidence. It is recorded because it is the honest state of the
  evidence, and a reader should know it exists.
- **Not every occurrence above is an independent observation** (issue #81). Under
  the role rule `bench/splits.py` used when this pass ran — keyed on the
  **resolution**, as row 13 of the spec's revision history records — occurrences
  5–8 are all replays (the smoke seeds are run twice, so they revisit occurrences
  1–4's states with the library those occurrences built), and two first-pass
  occurrences are replays too: seed 2 re-injects `repin` for `submodule_moved`
  (occurrence 3) and seed 4 re-injects `overlapping_files` for `diverged`
  (occurrence 4). So the independent observations in that pass's eight occurrences
  are 3 per family, not 8; the cost curve is computed over the replays and the
  mismatch comparison over the variants, which is why it cannot be read off this
  pass as a finding. **ADR-0005 has since changed the rule**, because it found
  those same-resolution seeds build byte-identical environments: an occurrence is
  now a replay only on a genuine repeat of one *instance*, and the current
  injectors draw a distinct instance at every smoke seed. The numbers above are
  the record of that earlier pass under the code that produced it, not a
  prediction of what a run on the current injectors yields.
- **The cache figure is a confound, not a result.** Across the pass 864,098
  tokens were spent over 407 calls in 687s, and 73% of the input tokens were
  cache hits, so the baseline's real marginal cost is lower than the raw token
  counts above suggest.
