# Did the ecosystem's check see the maintainer's answer? 2026-11-11

**Exploratory.** It was done after study 6, on its data and on studies 3–5's. Nothing here was
registered, and no registered decision changes. The decisions are exactly what the registration
defined: it judged each side "in the merge's tree, as committed" (tool-precondition §4). What
changes is how far those figures describe a resolver that runs before anything is resolved.

## The question

The check judges a side's lock file against the manifests beside it. In the merge's tree those
are the maintainer's committed manifests, which hold the maintainer's resolution of every
conflict in them. A tool resolving a lock-file conflict at merge time does not have that. It has
git's merge of the two sides. Where git merged the manifests cleanly, the two are usually the
same. Where git could not, it has nothing to check against.

So for every lock file the check judged, `audit.py` compares the files the check reads in two
trees:
- the merge's tree, as committed;
- git's own merge of the parents, `git merge-tree --write-tree --merge-base=<base>`.

It puts each file in one class:

| class | meaning | study 6 | studies 3–5 |
| --- | --- | ---: | ---: |
| **same** | every file the check reads is git's merge: the recorded verdicts are what a resolver at merge time gets | 240 | 377 |
| **conflicted** | git reports a conflict in one of them: a resolver has no manifest to check against | 150 | 230 |
| **edited** | git merged them all, and the maintainer committed something else | 5 | 3 |

The files compared, under the lock file's folder at any depth, `node_modules/` and `vendor/`
aside:
- npm: `package.json`, `.npmrc`, `npm-shrinkwrap.json`;
- pnpm: those and `pnpm-workspace.yaml`, `.pnpmfile.cjs`;
- Composer: `composer.json` and `auth.json` in the folder itself.

For a workspace that is more than each tool reads, so "same" is conservative. As a cross-check,
the mining's own record of conflicted files lists the lock file's sibling manifest on 352 of the
1,005 files. The audit classes 351 of them as conflicted. The other one is a SuiteCRM merge
where git reports a conflict in `composer.json` and still writes the maintainer's blob. The
audit counts it as conflicted (the check accepts no side there, so no rule's figure depends on
it). The audit also finds 28 more conflicted files, where a workspace's other manifests
conflicted.

## Result

**The check is far more often right where it saw the maintainer's resolved manifest.** Over the
files where it accepts exactly one side, the accepted side is wrong on:

| | conflicted | same |
| --- | ---: | ---: |
| study 6 | 9 of 70 (0.13) | 27 of 88 (0.31) |
| studies 3–5 | 19 of 104 (0.18) | 75 of 179 (0.42) |

So **C'** and **D'** use the check only on "same" files and refuse it elsewhere. The gate's
step is unchanged, because it reads only the three lock files.

| rule | study 6: coverage | mismatch [95% Wilson] | studies 3–5: coverage | mismatch |
| --- | ---: | --- | ---: | --- |
| B: the gate's merge, else refuse (no check) | 0.45 | 0.296 [0.234, 0.367] | 0.40 | 0.279 [0.227, 0.338] |
| C: the side the check accepts, as recorded | 0.40 | 0.233 [0.174, 0.304] | 0.46 | 0.332 [0.280, 0.389] |
| **C': the same, only on "same" files** | **0.22** | **0.307** [0.220, 0.410] | **0.29** | **0.419** [0.349, 0.492] |
| D: the gate's merge, else C, as recorded | 0.71 | 0.272 [0.224, 0.327] | 0.69 | 0.317 [0.274, 0.363] |
| **D': the gate's merge, else C'** | **0.58** | **0.299** [0.243, 0.361] | **0.58** | **0.343** [0.295, 0.394] |

The tie-break files are those where a package diverges and the check accepts one side. On them,
the accepted side is compared with the first parent's file:

| | files | check right, first parent wrong | the reverse |
| --- | ---: | ---: | ---: |
| study 6, all | 100 | 9 | 1 |
| study 6, "same" only | 52 | 3 | 1 |
| studies 3–5, all | 176 | 20 | 0 |
| studies 3–5, "same" only | 106 | 4 | 0 |

What this says:
- **Run before anything is resolved, the check adds coverage at about the gate's own error, not
  less.**
  - In study 6, D' covers 0.58 of files at mismatch 0.30. The gate alone covers 0.45 at 0.30,
    and D as recorded covers 0.71 at 0.27.
  - In studies 3–5, D' covers 0.58 at 0.34, against the gate's 0.40 at 0.28.
  - What the check adds is mostly "take your own branch", made selective. D' fires on 52
    files where the gate refuses in study 6, and on 106 in studies 3–5.
    - The accepted side is the first parent's on 46 of the 52, and on 97 of the 106.
    - It is wrong on 16 of the 52, where the first parent's file would be wrong on 18. In
      studies 3–5 it is 52 against 56.
    - The check's contribution, at merge time, is chiefly to refuse where neither side, or both,
      passes.
- **Most of the tie-break's gain over "take your own branch" came from files where the check
  read the maintainer's manifest.** Its wins drop from 9 to 3 in study 6 and from 20 to 4 in
  studies 3–5. Its losses stay at 1 and 0.
- **Study 6's H3, read on "same" files only, would not have passed.** That reading has 1
  reverse among 52 tie-break files, so the Wilson upper bound is 0.101, against the registered
  0.10. On all 100 files, as registered, it is 0.054.
- **H2 is unaffected.** Study 6's per-repository mean of D' is 0.327 [0.235, 0.419], against
  0.320 [0.228, 0.412] for D as recorded. Either way, rule D is not rarely wrong.
- **H1 is unaffected.** It compares the maintainer's merged lock file with ordinary commits,
  each in its own tree. Nothing there is judged against a manifest the file did not come with.

## How to read it

The recorded figures still describe a real workflow: resolve the manifest first, then let the
check choose the lock file. That is Composer's documented procedure for a conflicted
`composer.lock`. For example, a person might resolve `package.json`, and a tool then picks the
lock file.

D' describes a fully automatic resolver of the lock file. Read that way, the check is a modest
addition, not the source of most of rule D's coverage. Two cautions:
- **The populations differ.** "Conflicted" files are those where both sides changed the
  manifest. With the maintainer's manifest in hand they may simply be easier to judge. So the
  difference between the classes measures this mix, not the leak alone.
- **"Edited" files are refused by D'.** There are 8 of them. Their verdicts in git's merge were
  never computed.

## Files

- `audit.py`: rebuilds git's merge of each case from four commits fetched at depth 1, blobs on
  demand, and writes `inputs.jsonl`. That file gives each checked file's class and the number
  of files compared, differing and conflicted. No path other than the lock file's own is
  written, and no package name.
- `analyze.py`: reads `inputs.jsonl` with study 6's `files.jsonl` and studies 3–5's records,
  and writes `summary.txt`. It imports nothing from the project. As recorded, its rule D
  reproduces study 6's figures (279 fires, 76 wrong; per-repository 0.320) and the exploratory
  `dispatch.txt` for each of studies 3–5.

```bash
python -I results/manifest-leak-2026-11-11/audit.py results/manifest-leak-2026-11-11/inputs.jsonl <cache> \
  study-6=results/tool-precondition-2026-11-09 \
  study-3=results/lock-oracle-2026-11-02:results/lock-tool-check-2026-11-08/study-3.jsonl \
  study-4=results/ecosystem-unify-2026-11-02:results/lock-tool-check-2026-11-08/study-4.jsonl \
  study-5=results/divergence-gate-2026-11-08:results/lock-tool-check-2026-11-08/study-5.jsonl
python -I results/manifest-leak-2026-11-11/analyze.py > results/manifest-leak-2026-11-11/summary.txt
```

The audit took about two minutes once the cache held the commits. Fetching them took a few
more.
