# Real lock-file merges, stage B (confirmatory), 2026-10-27 (#296)

Stage B is the confirmatory stage of the real-merge study. It was registered in
[`docs/preregistration/real-merges.md`](../../../docs/preregistration/real-merges.md) and amended
before any of its data was mined (Amendment 1, ADR-0049). Every number below comes from the files
in this directory, and [`verification/`](verification/) recomputes them independently.

## The registered decisions (§9), in order

The rules are applied per replicate. Each replicate is one committed library:
`results/replicates-2026-10-05/run-{11,12,13}/library-two-sided`.

| rule | run 11 | run 12 | run 13 | decision |
| --- | --- | --- | --- | --- |
| 1. Applicability: arm 3 fires on at least 20 cases (A6) | 150 | 122 | 244 | tested in every replicate |
| 2. Arm 3's reliability: Wilson lower bound of mismatch at most 0.10 | **0.338** | 0.045 | **0.478** | **falsified**: "arm 3 rarely mis-fires" does not hold on real merges |
| 3. H1, against similarity: interval's lower bound above 0 | +0.357 | +0.810 | +0.279 | supported in every replicate |
| 4. H2, against reading the state: interval's lower bound above 0 | +0.427 | +0.803 | +0.282 | supported in every replicate |
| H3 (A3), refusing inexpressible conflicts: lower bound above 0 | +0.605 | +0.848 | +0.046 | supported in every replicate |

Stage B is not underpowered. It has 274 cases from 11 repositories with a case, against
Amendment 1's target of 247 cases from at least 8 repositories.

**Read the rows together, and with the next two sections.** Rule 2 is falsified: on real
lock-file merges, arm 3 is wrong on 41% and 54% of its fires in two of the three replicates. H1,
H2 and H3 hold as registered. However, the next section shows that H2's margin comes from where
each dispatcher is allowed to fire, a flaw in the design. It does not come from executing
preconditions on conflicts.

## Where the margins come from (descriptive, not a test)

| | run 11 | run 12 | run 13 |
| --- | --- | --- | --- |
| arm 3 fires on clean cases, right / all | 87 / 113 | 112 / 113 | 112 / 113 |
| arm 3 fires on conflicted cases, right / all | 1 / 37 | 0 / 9 | 0 / 131 |
| control fires on clean cases | 0 | 0 | 0 |
| control fires on conflicted cases, right / all | 1 / 160 | 1 / 160 | 1 / 160 |

- **Almost no conflict is expressible.** One of the 161 conflicted cases has a non-empty
  acceptable set (§4). So on a real lock-file conflict, almost every fire by every dispatcher is
  wrong. That is how a maintainer resolves them: 79 regenerated the file, 48 did something else
  ("other"), 20 took the local file and 12 took upstream's. Only 2 matched what `take_upstream`
  produces.
- **Arm 3's right fires are `merge` on clean merges.** The rule A2 labels `merge` right on a clean
  case whose tree equals `git merge-tree`'s, and that holds for all 113 clean cases. Arm 3
  searches the whole library, so it fires another intent's `merge` program there. A2 counts that
  as right: "every resolution named `merge`, in any intent, counts as `merge`".
- **The control cannot fire `merge`.** `bench.state_classifier` decides with the lock-file
  intent's own tree (`StateClassifier.decide(INTENT, state)`). That tree's classes are the lock
  intent's resolutions and "none". So the control never fires on a clean case, and on conflicted
  cases it fires `keep_local` or `take_upstream`, almost always wrongly. **H2 therefore compares
  arm 3's fires on mostly clean cases with the control's fires on conflicted ones.** The paired
  McNemar check found no discordant pair in any replicate (b/c 0/0): wherever both fired, both
  were wrong. Nor is the control's point matched to arm 3's coverage in any replicate. Its curve
  has a single point, 160 fires, against arm 3's 150, 122 and 244.
- **What H3 shows is real but narrow.** On the 160 inexpressible conflicts, arm 3 fires on 36, 9
  and 131. The control fires on 159. So two libraries mostly refuse what cannot be resolved. The
  third, run 13, fires on 82% of them, mostly `keep_local` (120), and H3's interval there barely
  clears 0.

| fire rate on the 160 inexpressible conflicts (95% Wilson) | run 11 | run 12 | run 13 |
| --- | --- | --- | --- |
| arm 3 | 0.225 [0.167, 0.296] | 0.056 [0.030, 0.103] | 0.819 [0.752, 0.871] |
| arm 2 | 0.319 [0.252, 0.394] | 0.200 [0.145, 0.269] | 0.825 [0.759, 0.876] |
| control | 0.994 [0.965, 0.999] | 0.994 [0.965, 0.999] | 0.994 [0.965, 0.999] |

## What it shows

- On real lock-file merges, the claim that arm 3 rarely mis-fires is **falsified** by the
  registered rule. The synthetic study's near-zero mismatch (Figure 1) does not carry over.
- No library resolves a real lock-file conflict. Arm 3 is right on 1 of 177 fires on conflicted
  cases, summed over the replicates. The intent's line-union resolutions express 1 of 161
  maintainer resolutions. This is stage A's finding again, at 5 times the size.
- Arm 3 beats lexical similarity (H1) at matched coverage in every replicate. That margin also
  comes mostly from clean merges. There arm 2's top candidate is `merge` on 9, 0 and 0 of the 113
  clean cases.
- Two of three libraries mostly decline to fire on conflicts no resolution can express (H3).

## What it does not show

- **That executing preconditions beats reading the state.** H2 is supported as registered, and
  §2 says only H2 can license that sentence. But the registered control can only ever fire the
  lock-file intent's resolutions, while arm 3 may fire any intent's. The margin is that
  difference, not execution. I should have seen this when registering. On conflicted cases, where
  both can fire, both are wrong almost every time. So ADR-0047's wording stands: a dispatcher that
  reads the state matched arm 3 on the synthetic states, and nothing here shows otherwise.
- That the libraries handle real merges in general. The cases are lock-file merges from 11
  repositories, mined in the registered order and stopped once the target was reached
  (`paritytech/substrate` and `ruffle-rs/ruffle` were not mined).
- Anything about the LLM state judge (#295), which did not run (no key).
- **Afterwards, exploratory:** a control given arm 3's scope is right on clean merges as often as
  arm 3, but fires on every conflict. Refusal is what separates them
  ([`library-control-exploratory/`](library-control-exploratory/README.md)).

## The cases

Sixteen of the 18 listed repositories were mined. Five yielded no case:

- `jupyter/notebook`, `voila-dashboards/voila`, `bokeh/bokeh`, `gfx-rs/wgpu`: no merge in their
  history had both sides change the same lock file and then conflict in it, or merge cleanly
  with one merge base.
- `holoviz/panel`: only 4 two-parent merges in its history.

| repository | two-parent merges | conflicted | clean | excluded |
| --- | --- | --- | --- | --- |
| phpmyadmin/phpmyadmin | 16683 | 43 | 6 | 1 (criss-cross) |
| jupyterlab/jupyterlab | 4699 | 19 | 19 | 0 |
| babel/babel | 1396 | 12 | 2 | 0 |
| nextcloud/server | 28145 | 2 | 2 | 0 |
| jupyter/notebook | 3345 | 0 | 0 | 0 |
| voila-dashboards/voila | 408 | 0 | 0 | 0 |
| composer/composer | 2818 | 30 | 30 | 0 |
| nushell/nushell | 866 | 11 | 11 | 0 |
| rust-lang/cargo | 7613 | 3 | 3 | 0 |
| servo/servo | 15148 | 4 | 4 | 0 |
| jupyter-widgets/ipywidgets | 2006 | 3 | 3 | 0 |
| bokeh/bokeh | 3320 | 0 | 0 | 0 |
| holoviz/panel | 4 | 0 | 0 | 0 |
| pypa/pipenv | 2053 | 4 | 3 | 0 |
| gfx-rs/wgpu | 1223 | 0 | 0 | 0 |
| wasmerio/wasmer | 4304 | 30 | 30 | 2 (criss-cross; submodule conflict) |
| **total** | | **161** | **113** | **3** |

No repository exceeds A4's cap of 61 cases (25% of 247). Composer and wasmer each show exactly 30
conflicted and 30 clean cases. That is what the cap keeps: past 61 cases, `_capped` keeps the 30
most recent of each kind. Their uncapped counts are not recorded. The intent's rule disagrees with the
maintainer on 37 conflicted cases, listed one by one in `report.json` (`rule_disagreements`).

## Each arm, per replicate

Each cell gives mismatch at the arm's operating point, with its 95% Wilson interval. Arm 2 and the
control are read at the point of their curves nearest arm 3's coverage (§6).

| | run 11 | run 12 | run 13 |
| --- | --- | --- | --- |
| arm 3 | 62/150 = 0.413 [0.338, 0.493] | 10/122 = 0.082 [0.045, 0.144] | 132/244 = 0.541 [0.478, 0.602] |
| arm 2 (lexical), matched | 140/150 = 0.933 [0.882, 0.963] | 122/122 = 1.000 [0.969, 1.000] | 239/244 = 0.980 [0.953, 0.991] |
| control, matched | 159/160 = 0.994 [0.965, 0.999] | 159/160 = 0.994 | 159/160 = 0.994 |
| H1 = arm 2 − arm 3 [cluster bootstrap] | +0.520 [+0.357, +0.687] | +0.918 [+0.810, +0.984] | +0.439 [+0.279, +0.560] |
| McNemar on joint fires (b/c, p) | 66/3, 1.9e-16 | 89/0, 3.2e-27 | 105/0, 4.9e-32 |
| H2 = control − arm 3 | +0.580 [+0.427, +0.737] | +0.912 [+0.803, +0.984] | +0.453 [+0.282, +0.589] |
| McNemar on joint fires (b/c, p) | 0/0, none | 0/0, none | 0/0, none |
| H3 = control − arm 3 fire rate on inexpressible conflicts | +0.769 [+0.605, +0.893] | +0.938 [+0.848, +0.990] | +0.175 [+0.046, +0.345] |
| McNemar (b/c, p) | 124/1, 5.9e-36 | 151/1, 5.4e-44 | 29/1, 5.8e-8 |

## How it was checked

- [`verification/recompute.py`](verification/recompute.py) reads only this directory's JSON and
  imports nothing from the project. It reproduces every fire and wrong count, the matched points,
  every point estimate of H1, H2 and H3, and the rule-2 bounds exactly. With its own random seed,
  its repository bootstrap gives intervals within 0.01 of the registered ones
  ([`recompute.out`](verification/recompute.out)).
- [`verification/labels.py`](verification/labels.py) re-fetches five repositories at their pinned
  tips: ipywidgets, pipenv, nushell, babel and cargo, 55 cases or 20%. From git alone, it checks:
  - each case's parents and single merge base;
  - that `git merge-tree` conflicts or merges cleanly as the case's kind says, with the same
    conflicted paths;
  - each acceptable set, by §4's multiset rule and A2's tree-equality rule;
  - each descriptive class.

  It also re-mines each repository's whole history. All 55 labels agree, and so do the merge
  counts, the cases kept and the exclusions ([`labels.out`](verification/labels.out)). Pipenv has
  3 criss-cross merges whose sides both changed a lock file. None conflicts in one, so §3.5
  correctly excludes none of them.

## Deviations, and how the run went

- **The run was resumed three times from its per-repository parts.** Parts are written as each
  repository finishes, and a resumed run reads them back without re-mining. The three segments ran
  on these commits:
  1. phpMyAdmin, jupyterlab, babel: `f60b857`, main plus the snapshot cache (#311). That cache
     gives the same digest, part for part (checked on 13 sandboxes).
  2. nextcloud through wgpu: `3c80fea`, which adds the licence-directory fix (#312). The licence
     only feeds the manifest.
  3. wasmer: `99f6351`, which adds the submodule-advice fix (#313). Without it, a wasmer merge with
     a conflicted submodule stopped the parser. That merge is excluded under §3.5, as the
     registration requires.

  No fix changes how a case is chosen, labelled or decided. Without the last two, the run could
  not finish.
- **An earlier attempt** started on 2026-10-26, before the snapshot cache. It spent 4.5 hours on
  phpMyAdmin without finishing it, wrote nothing, and was stopped.
- **The middle segment's console output was lost.** I edited its log file while the process was
  still writing to it. `run.log` holds the last segment's output, which prints the full report.
  The per-repository parts, which hold the data, are complete.
- **Seen before analysis:** while checkpointing, I read each finished repository's counts (cases,
  conflicted, clean, exclusions), never its decisions or labels.

## Files

- `manifest.json`: every repository (URL, tip, licence, counts) and every case (`M`, `P1`, `P2`,
  `B`, conflicted paths), plus exclusions with their reasons.
- `labels.jsonl`: each case's acceptable set and descriptive class.
- `decisions.jsonl`: the rule's label, and each arm's decision per replicate, with arm 2's and the
  control's scores.
- `report.json`, `summary.txt`: the figures and §9's decisions, as the run wrote them.
- `repos/`: the per-repository parts the run resumed from.
- `run.log`: the last segment's console output.
