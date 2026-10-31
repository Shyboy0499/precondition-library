# Mutation testing of the graders, repeated, 2026-10-31 (#299)

The full run of [`../grader-mutation-2026-10-28/`](../grader-mutation-2026-10-28/README.md), repeated
on main at `9b2326d`, after the tests that close its five gaps were merged. The command, the
operators and the 15 test files are the same:

```bash
python -m precondition_library.bench.grader_mutation --out results/grader-mutation-2026-10-31
```

The 15 test files took 62.2 s per clean run. The run produced the same 171 mutants, and none timed
out.

## Result

| | 2026-10-28 | 2026-10-31 |
| --- | ---: | ---: |
| mutants | 171 | 171 |
| killed, of the 141 that can change a verdict | 133 | **138** |
| survived, could change a verdict | 8 | **3** |
| message only | 30 | 30 |
| score | 0.943 | **0.979** |

**Mutant by mutant**, exactly six outcomes changed, all from survived to killed:

- the five gaps the earlier run found, each now killed by the test written against it:
  `config_renamed.py` lines 458, 463 and 475, and `submodule_moved.py` lines 515 and 555;
- one message-only mutant, `config_renamed.py:459` (`0 -> 1`), which a new test's assertion on
  the message now also catches.

The three survivors that could change a verdict are the three the earlier run argued equivalent:
`config_renamed.py:456`, `lockfile_conflict.py:469` and `submodule_moved.py:534`. So every
non-equivalent mutant these operators make is killed: 138 of 138.

## Files

- `report.json`: the summary and every mutant's outcome.
- `results.jsonl`: the same results, one line each as the run wrote them.
- `baseline.json`: the clean selection's time and each target's SHA-256.
- `run.log`: the run's output. The container restarted during an earlier attempt, and this run
  started from the beginning, so it is one uninterrupted run.
