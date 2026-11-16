# Held-out lock-file paths, on the 22 libraries built since the compile prompt changed, 2026-11-16

`results/heldout-2026-10-18/` moved the lock file to four paths no build had seen. There, arm 3 was
wrong on 41 of its 101 fires over the three replicate libraries, every one on a path with a space or
a non-ASCII name. Four probes caused them all, each reading a git path list without `-z` and finding
nothing on a name git quotes. Afterwards the compile prompt was changed to tell the model to read
path lists with `-z` (ADR-0038). Whether that removes the defect was left "for the next live build".

This block is that test. It runs the same held-out stage, unchanged, on every library built since:
run-14 and run-15 (#266) and study 2's 20 builds. All were compiled with the changed prompt.

**Exploratory.** Nothing here was registered, and the libraries were not built for this question.
No model call, no rebuild: each frozen library is read, as in October.

```bash
python -m precondition_library.experiment.stages.heldout --run <run> --faults lockfile_conflict \
  --out results/heldout-2026-11-16/<name>
PYTHONPATH=src python results/heldout-2026-11-16/per_path.py > per_path.json
```

## Result

Seeds 3000–3039: 40 held-out positive states and 40 fault-free negatives per library, ten states at
each path.

| held-out lock-file path | October: fires, wrong (3 libraries) | now: fires, wrong (22 libraries) |
| --- | --- | --- |
| `services/api/deps.lock` (nested) | 20, 0 | 100, 0 |
| `web app/deps.lock` (space) | 30, 16 | **100, 0** |
| `vendor/abhängigkeiten.lock` (non-ASCII) | 30, 25 | 105, **10** |
| `config/.deps.lock` (dotfile) | 21, 0 | 98, **10** |
| all | 101, 41 | 403, 20 |
| fires on the fault-free negatives | 0 | 0 |

`per_path.json` gives every library's row; each library's totals equal its own `summary.txt`. Six of
the 22 libraries never fire on these states (0-2, 0-9, R-2, R-5, R-7, R-8), so they count toward
neither column.

## What it shows

- **The quoting defect did not recur.** The new libraries fire on the spaced path 100 times and on
  the non-ASCII path 105 times. None of their wrong fires comes from reading a quoted path. In
  October the same two paths drew 60 fires and 41 were wrong.
- **One library has a second defect of the same kind.** All 20 wrong fires are build 0-4's: a
  `diverged` merge program firing on a lock-file conflict. Its precondition
  `no_common_lockfile_changes` reads the path lists correctly with `-z`, then recognises a lock file
  only by a fixed list of names (`deps.lock`, `package-lock.json`, `yarn.lock` and so on).
  `abhängigkeiten.lock` and `.deps.lock` are not on the list, so "no lock file changed on both
  sides" finds nothing, holds, and the merge fires. It is an absence check failing open again, by a
  different route: a closed list of names instead of a misread path.
- **So the README's "compiled probes generalise to unseen states" moves, but not to survived.** The
  defect the prompt named is gone in 22 of 22 libraries. The class of defect, an absence check that
  holds when it cannot see, is not: 1 library in 22 has it.

## What it does not show

- **That the prompt change caused the improvement.** Nothing else was held fixed: these libraries
  also differ from October's in the admit-set plan, the config family and every fix since.
- **A comparison with arm 2.** As in October, no held-out floor is measured (ADR-0033).
- **Other kinds of held-out state.** Only the lock file's path is varied.

## Files

- `<name>/`: the held-out stage's output per library (`summary.txt`, `summary.json`,
  `heldout.json`, `wrong_fires.jsonl`, `primary/`) and `<name>.log`.
- `per_path.py` and `per_path.json`: fires and wrong fires by path and library.
