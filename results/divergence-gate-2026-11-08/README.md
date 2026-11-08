# Study 5: the divergence gate, 2026-11-08

**Registered** in `docs/preregistration/divergence-gate.md` (ADR-0059), before any of its data
was mined. Run at commit `3aeeba5` (the registration as merged) with:

```bash
PYTHONPATH=src python -m precondition_library.bench.divergence_gate --out results/divergence-gate-2026-11-08
```

It took about 20 minutes on 2026-11-08. Nothing here deviates from the registration. The one
surprise in the mining, `nextcloud/activity`, is described below.

## The question

The anatomy of studies 3 and 4 suggested a precondition over a lock-file conflict's three sides,
the **gate**. A package *diverges* when both sides changed its versions, to different versions.
The gate fires the predicted per-ecosystem merge only where no package diverges, and refuses
otherwise. This study tests it on 20 repositories nobody here had mined or counted.

## Result

223 conflicts from 20 repositories, and the gate fires in 19 of them.

| | estimate [95% interval] | registered decision |
| --- | --- | --- |
| **H1 (primary):** mean over repositories of the gate's mismatch, above 0.10 | **0.352** [0.178, 0.527] | **supported**: the gate does not make the merge rarely wrong |
| **H2:** mean of m_always − m_gate, above 0 | **0.236** [0.089, 0.384] | **supported**: the gate lowers the merge's mismatch |
| **H3:** one-version cases, within repositories: reproduced where nothing diverges minus where something does | **0.248** [−0.022, 0.476] | **not supported**, and uninformative by §8: its interval does not exclude 0.22 |

The three hypotheses, read together:

- **The precondition helps, and is not enough.** Pooled over cases, firing the merge always is
  wrong on 127 of 223 conflicts (0.570). The gate fires on 108 (0.484 of cases) and is wrong on
  32 of them: 0.296 [0.218, 0.388]. That is about half the error. Its interval still lies well
  above the 0.10 that "rarely mis-fires" would need.
- **H3 failed for want of power, not of effect.** Its estimate, 0.248, is close to the 0.224
  found in studies 3 and 4. The registration put H3's power at 0.37, and said in advance that a
  failure would be read as uninformative unless the interval's upper end fell below 0.22. It is
  0.476.
- **The exploratory figures replicate.** In studies 3 and 4 the gate's mean mismatch was 0.39
  and 0.24, and its gain 0.15 and 0.19. Here they are 0.35 and 0.24.

By family, over files (descriptive, §7):

| family | no package diverges: reproduced | some package diverges: reproduced |
| --- | ---: | ---: |
| npm's | 23 of 28 (0.82) | 5 of 69 (0.07) |
| one-version | 55 of 83 (0.66) | 17 of 69 (0.25) |

Study 3's coverage replicates a third time: 0.643 [0.524, 0.762].

## By repository

| repository | cases | of them one-version | gate fires | always: wrong | gate: wrong | m_always | m_gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Kovah/LinkAce` | 11 | 9 | 2 | 10 | 1 | 0.91 | 0.50 |
| `krayin/laravel-crm` | 8 | 8 | 4 | 4 | 1 | 0.50 | 0.25 |
| `PrivateBin/PrivateBin` | 6 | 5 | 1 | 5 | 0 | 0.83 | 0.00 |
| `cachethq/cachet` | 15 | 15 | 12 | 2 | 0 | 0.13 | 0.00 |
| `coollabsio/coolify` | 15 | 11 | 11 | 3 | 1 | 0.20 | 0.09 |
| `bagisto/bagisto` | 15 | 15 | 3 | 13 | 3 | 0.87 | 1.00 |
| `phpbb/phpbb` | 15 | 15 | 2 | 12 | 0 | 0.80 | 0.00 |
| `Attendize/Attendize` | 6 | 5 | 3 | 5 | 3 | 0.83 | 1.00 |
| `pelican-dev/panel` | 11 | 10 | 10 | 7 | 7 | 0.64 | 0.70 |
| `Part-DB/Part-DB-server` | 12 | 9 | 5 | 8 | 2 | 0.67 | 0.40 |
| `elabftw/elabftw` | 12 | 3 | 3 | 8 | 0 | 0.67 | 0.00 |
| `lobsters/lobsters` | 11 | 11 | 9 | 5 | 5 | 0.45 | 0.56 |
| `paperless-ngx/paperless-ngx` | 15 | 13 | 12 | 7 | 4 | 0.47 | 0.33 |
| `ProcessMaker/processmaker` | 15 | 14 | 12 | 4 | 2 | 0.27 | 0.17 |
| `penpot/penpot` | 10 | 0 | 1 | 9 | 1 | 0.90 | 1.00 |
| `PrefectHQ/prefect` | 15 | 0 | 7 | 8 | 0 | 0.53 | 0.00 |
| `DFE-Digital/apply-for-teacher-training` | 8 | 2 | 4 | 3 | 0 | 0.38 | 0.00 |
| `nextcloud/polls` | 8 | 1 | 5 | 4 | 1 | 0.50 | 0.20 |
| `TryGhost/Ghost` | 14 | 0 | 2 | 9 | 1 | 0.64 | 0.50 |
| `nextcloud/activity` | 1 | 0 | 0 | 1 | 0 | 1.00 | — |

- **The gate's errors are concentrated.** It is never wrong in six repositories. Two
  repositories hold 12 of its 32 wrong fires: `pelican-dev/panel` (7 of 10) and
  `lobsters/lobsters` (5 of 9).
- **In five repositories the gate does worse than always firing.** These are bagisto, Attendize,
  pelican-dev, lobsters and penpot. In three of them it fires on only 1–3 cases. Why the other
  two miss was not examined. The anatomy's manifest effect, a maintainer deciding outside the lock
  file, is one candidate.

## Exclusions

As registered (§3.2), 27 merges were passed over:

- 11 criss-cross merges, 10 of them in ProcessMaker;
- 11 merged lock files that could not be read, 5 of them in Part-DB;
- 5 submodule or binary conflicts, 4 of them in phpBB.

## `nextcloud/activity`, and git attributes

The feasibility count found 107 lock-file conflicts in `nextcloud/activity`, but the study mined
one case. The cause is found:

- **The repository's `.gitattributes` says `package-lock.json binary`.**
- **The count's clone applied it.** That clone is bare and blobless with a normal HEAD, and git
  applied HEAD's attributes. So every merge whose sides both changed the file conflicted as a
  binary file: 107 of 113.
- **The study's clone did not.** Study 1's mining fetches into a cache with no HEAD content, so
  no attributes apply. The file is merged as JSON text, and it conflicts once.

Either way the repository gives at most one case. Under the attribute, those conflicts would be
binary conflicts, which the registration excludes. Its one case has a divergent package, so the
gate refuses it, and it enters none of H1–H3. Without it, the pooled "always" figure is 126/222
rather than 127/223.

This is a property of study 1's mining, shared by every study since: it ignores repositories'
`.gitattributes`. Among this study's 20 repositories only two declare an attribute on a lock file:

- `nextcloud/activity`, above;
- `nextcloud/polls`, on `vendor-bin/**/composer.lock`, which none of its cases touches.

`TryGhost/Ghost`'s `merge=ours` applies to `*.lock.yml` workflow files, which are not lock files
the study reads.

## Verification

| script | what it does | result |
| --- | --- | --- |
| `verification/recompute.py` | Imports nothing from the project. Recomputes every figure and decision from `gates.jsonl`, `labels.jsonl` and `report.json`, with its own t quantiles from the incomplete beta function and its own Mantel-Haenszel bootstrap. | all agree (`recompute.txt`) |
| `verification/rederive.py` | Re-derives every file's divergence with `results/lock-anatomy-2026-11-04/anatomy.py`, which classifies packages with its own code. | 249 of 249 files agree (`rederive.txt`) |

## Files

- `manifest.json`: every repository's pinned tip, every case's SHAs, every exclusion.
- `labels.jsonl`: study 3's per-file, per-action labels.
- `gates.jsonl`: each case's per-file divergence count, family and predicted-merge verdict. No
  package name is written.
- `report.json` and `summary.txt`: every figure and decision.
