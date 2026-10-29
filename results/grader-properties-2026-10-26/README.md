# The graders on generated states, 2026-10-26 (#299)

`tests/test_grader_properties.py` with `HYPOTHESIS_PROFILE=thorough`: 300 generated states per
property, on top of the fixed handful CI runs.

```bash
HYPOTHESIS_PROFILE=thorough python -m pytest -n 2 tests/test_grader_properties.py --hypothesis-show-statistics
```

| property | generated states | failing |
| --- | ---: | ---: |
| `lockfile_conflict`: the gold resolution passes and taking upstream's file whole fails, with the lock file at a generated path and marker-like lines in its header | 300 | 0 |
| `dirty_tree`: the gold resolution passes and discarding the work fails, with all three paths generated | 300 | 0 |

The paths draw from Latin letters with accents, digits and `` $'`&;()#!~-_.,=+@%`` and space,
under up to four directories, with leading dots allowed. The marker-like lines are `=======`
with or without trailing text, runs of six or eight `<`, `>` or `|`, seven of them followed by
something other than a space, and a marker that does not start the line. None of them is a marker
by the definition git and the checker share (ADR-0045).

**What it shows.** On 600 generated states, neither the graders nor the gold programs mishandle
a path a shell must quote, or a line that only looks like a conflict marker. ADR-0045's four
defects were of exactly these kinds. Their fixes now hold on states no seed draws, not only on
the regression cases they were found with.

**What it does not show.** It covers two of the six faults: the two whose state has a path axis.
It also cannot tell whether a grader is right when it accepts. Both properties pass a gold
resolution and fail a discarding one, so a grader that accepted too much elsewhere would go
unnoticed. That is what mutation testing (`bench.grader_mutation`) is for.

`thorough.txt` is the run's output, with Hypothesis's statistics.
