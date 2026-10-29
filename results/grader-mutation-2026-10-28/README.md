# Mutation testing of the graders, 2026-10-28 (#299)

`bench.grader_mutation` mutates every grader one small change at a time, then runs the tests that
grade with `-x`. The graders are each fault's `check` and the `recorded_state_intact` family. The
changes are a comparison flipped, `and`/`or` swapped, a `not` removed, a boolean swapped, or an
integer moved by one. A mutant that every test still passes **survived**: no test exercises the
clause it changed.

```bash
python -m precondition_library.bench.grader_mutation --out results/grader-mutation-<date>
```

The run was on `720ddaf` (feat/grader-tests), 07:28–09:11 UTC. The 15 grading test files took
88.7 s per clean run. It produced 171 mutants and none timed out.

## Result

| grader | mutants | killed | survived, could change a verdict | message only |
| --- | ---: | ---: | ---: | ---: |
| `invariants.py` (`recorded_state_intact`, `_recorded`, `_descends_from`) | 38 | 27 | 0 | 11 |
| `branch_renamed.py` | 26 | 22 | 0 | 4 |
| `config_renamed.py` | 35 | 29 | **4** | 2 |
| `dirty_tree.py` | 15 | 13 | 0 | 2 |
| `diverged.py` | 10 | 8 | 0 | 2 |
| `lockfile_conflict.py` | 23 | 20 | **1** | 2 |
| `submodule_moved.py` | 24 | 14 | **3** | 7 |
| **total** | **171** | **133** | **8** | **30** |

**The score as run is 133 of 141 = 0.943.** It counts mutants that can change a verdict, killed
or timed out. Thirty mutants sit inside a verdict's message, an f-string or a `detail=` argument.
They can change what a verdict says, never whether it passes, so they are reported apart from the
score.

## The eight survivors

| where | mutant | what it means | now |
| --- | --- | --- | --- |
| `config_renamed.py:458` | `ok=False` → `True` | nothing tested the new key set to a different value | killed by `test_the_new_key_set_to_another_value_fails` |
| `config_renamed.py:463` | `ok=False` → `True` | nothing tested another setting in the target being changed | killed by `test_another_setting_changed_in_the_target_fails` |
| `config_renamed.py:475` | `ok=False` → `True` | nothing tested the already-current settings file being edited in the `local_override` state | killed by `test_editing_the_already_current_settings_in_a_local_override_state_fails` |
| `submodule_moved.py:515` | `ok=False` → `True` | nothing tested `repin` once upstream had dropped the submodule | killed by `test_repin_fails_when_upstream_no_longer_records_the_submodule` |
| `submodule_moved.py:555` | `ok=False` → `True` | nothing tested an unknown injected state | killed by `test_an_unknown_injected_state_fails` |
| `config_renamed.py:456` | `values[0]` → `values[-1]` | equivalent: the line before requires exactly one value | left as is |
| `lockfile_conflict.py:469` | `splitlines()[0]` → `[-1]` | equivalent for the verdict: it picks which marker line the message quotes | left as is |
| `submodule_moved.py:534` | `and` → `or` | equivalent for the verdict: it picks the wording of the failure, and every branch fails | left as is |

Each new test was written against its mutant. Applied on its own with the runner's own
`mutated_source`, each mutant now fails its test. Each test passes on the unmutated grader. With the
five killed and the three equivalent set aside, **no clause that can change a verdict is left
unexercised**. That holds for these mutation operators, not for every possible defect.

The full run was not repeated after the tests were added, which would take about 1 h 45 min. The
five kills are checked one mutant at a time, as above.

## What it shows

- Five failure clauses in two graders, `config_renamed` and `submodule_moved`, could have been
  broken to accept, and no test would have noticed. Each is now tested. None of them was ever
  reached by a state the benchmark builds: they guard against fixes an agent might make (a wrong
  value, an extra setting, an edit to a file that was already right) or against states the harness
  never injects. So no committed figure was graded by a broken clause.
- An earlier, partial run found three more gaps, and the earlier commits on this branch close
  them: `recorded_state_intact` accepted a diff it could not read, now fixed; nothing tested
  deleting the conflicted lock file; and nothing tested a branch that tracks only half an
  upstream.

## What it does not show

- **That the graders are right where they accept.** A mutant that makes a grader accept too much
  is caught only if some test presents a wrong resolution there. The Hypothesis properties
  (`results/grader-properties-2026-10-26/`) cover two faults with generated states.
- **Defects outside these operators.** A wrong constant string, a missing clause, or a wrong rule
  is not a mutation the runner makes.
- **Agreement with people.** That is #299's third step, blind human labels, which needs
  practitioners the owner arranges.

## Files

- `report.json`: the summary and every mutant's outcome.
- `results.jsonl`: the same results, one line each as the run wrote them, so a stopped run
  resumes.
- `baseline.json`: the clean selection's time and each target's SHA-256.
- `run.log`: the run's output.
