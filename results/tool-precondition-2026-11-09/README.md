# Study 6: the ecosystem's check as a precondition, 2026-11-09

**Registered** in `docs/preregistration/tool-precondition.md` (ADR-0060) at commit `24213a1`,
before any of its data was mined. Run with:

```bash
PYTHONPATH=src python -m precondition_library.bench.tool_precondition \
  --out results/tool-precondition-2026-11-09 --scratch <dir> --prune
```

- **When and where.** The run took about 9 hours 15 minutes, 06:06 to 15:20 UTC on 2026-11-09.
  It ran at commit `0b82449`, the branch of #356 before it was merged. Its tree is identical to
  `e5bba90` on main.
- **A first attempt was lost.** It ran at `24213a1` and stopped after 11 repositories when the
  session's worker restarted. It wrote no result file; its log holds only each repository's
  case count. #356 then made the run checkpoint each repository and resume. It changed nothing
  the study measures. The run here started again from the first repository and ran to the end in
  one process.
- **Departures from the registration.** The decisions follow §9 exactly. The departures are in
  how the registration's prose describes the checks and the files; they are reported under
  [What the registration did not say](#what-the-registration-did-not-say).

## The question

`results/lock-tool-check-2026-11-08/` ran each ecosystem's own consistency check on studies
3–5's conflicted lock files. That was done after the studies had been seen. It suggested three
things:

- merges break lock files;
- the check makes a precondition: rule D, the divergence gate's merge, else the one side the
  check accepts, else refuse;
- the check's tie-break never loses to taking the first parent's file.

This study tests them on 25 repositories nobody here had mined or counted.

## Result

395 conflicted lock files from 366 merges in 25 repositories. Enough repositories have each
figure (24 and 25, at least 15 needed), so every hypothesis is decided.

| | estimate [95% interval] | registered decision |
| --- | --- | --- |
| **H1 (primary):** mean over repositories of g, merged files' rejection rate minus ordinary commits', above 0 | **0.067** [0.003, 0.130], 24 repositories | **supported** |
| **H2:** mean over repositories of rule D's mismatch, above 0.10 | **0.320** [0.228, 0.412], 25 repositories | **supported**: rule D is not rarely wrong |
| **H3:** reverses among the tie-break files, Wilson upper bound below 0.10 | **1 of 100**, upper bound **0.054** | **supported** |

What the three say, read together:

- **H1 passed, narrowly, and the effect is much smaller than the exploratory one.**
  - The lower end of its interval is 0.003.
  - Pooled over files, the check rejects 55 of 346 judged merged files (0.159) and 86 of 1,054
    judged ordinary checks (0.082). That is about twice the ordinary rate. The exploratory data
    gave about five times (0.14 against 0.03).
  - By repository, g is above 0 in 11 repositories, below 0 in 6 and exactly 0 in 7. The
    exploratory data had 26 above and 2 below.
  - The decision is fragile. Leave any one of seven repositories out, and the interval's lower
    end falls to between −0.007 and −0.001; for example, without
    `firefly-iii/data-importer`. Count pnpm's "settings" verdicts as errors rather than
    rejections, and it is 0.061 [−0.010, 0.133]. Neither reading was registered;
    `verification/describe.py` computes both.
  - Of the 55 rejected merged files, both parents' own files passed in 27. The exploratory
    data had 61 of 85. So about half the breakage here was made by the merge, and half
    inherited.
- **H2 passed, as expected, and the dispatcher replicates.** Pooled over files, rule D fires on
  0.71 of them and is wrong on 0.272 [0.224, 0.327] of its fires. The gate alone (rule B) fires
  on 0.45 and is wrong on 0.296 of its fires. The exploratory figures were coverage 0.69 at
  mismatch 0.32, against the gate's 0.40.
- **H3 passed at the registered bound, and would not have passed at 0.05.** Among the 100
  tie-break files, the check's side lost to the first parent's file once (`ampache/ampache`,
  a `package-lock.json`). The Wilson upper bound is 0.054, so the 0.05 reading the registration
  reports as a description does not hold. The registration chose 0.10 for this reason (§8).
  Against the first parent's file, the check's side was right where the first parent's was
  wrong on 9 files, and the reverse on 1 (exact McNemar p = 0.0215, descriptive). The
  exploratory data had 20 and 0. The 9 wins lie in 8 repositories.

## Rules, pooled over files (§7, descriptive)

| rule | fires | wrong | coverage | mismatch [95% Wilson] |
| --- | ---: | ---: | ---: | --- |
| A: the merge, always | 395 | 245 | 1.00 | 0.620 [0.571, 0.667] |
| B: the gate's merge, else refuse | 179 | 53 | 0.45 | 0.296 [0.234, 0.367] |
| C: the side the check alone accepts, else refuse | 159 | 37 | 0.40 | 0.233 [0.174, 0.304] |
| **D: the gate's merge; else the side the check alone accepts; else refuse** | 279 | 76 | **0.71** | **0.272** [0.224, 0.327] |
| F, control: the gate's merge; else the first parent's file | 395 | 176 | 1.00 | 0.446 [0.397, 0.495] |

By tool:

| tool | merged files: rejected / judged | ordinary checks: rejected / judged |
| --- | ---: | ---: |
| Composer | 9 / 117 (0.08) | 6 / 342 (0.02) |
| npm | 29 / 163 (0.18) | 33 / 493 (0.07) |
| pnpm | 17 / 66 (0.26) | 47 / 219 (0.21) |

Composer's content-hash, which no hypothesis uses, is stale in 20 of 132 merged files (0.15)
and in 20 of 394 ordinary ones (0.05).

## By repository

From `verification/describe.txt`. *g* is H1's figure, merged rejected share minus ordinary
rejected share; errors are left out of both.

| repository | cases | files (composer / npm / pnpm) | merged: rejected / judged | ordinary: rejected / judged | g | rule D: wrong / fires | m_D | tie-break files |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `appwrite/appwrite` | 15 | 15 (15 / 0 / 0) | 1 / 15 | 0 / 45 | +0.067 | 1 / 13 | 0.08 | 4 |
| `filamentphp/filament` | 15 | 19 (6 / 13 / 0) | 0 / 19 | 3 / 57 | -0.053 | 1 / 18 | 0.06 | 16 |
| `woocommerce/woocommerce` | 15 | 15 (4 / 7 / 4) | 2 / 12 | 4 / 36 | +0.056 | 1 / 13 | 0.08 | 1 |
| `thorsten/phpMyFAQ` | 15 | 29 (14 / 0 / 15) | 0 / 29 | 0 / 87 | +0.000 | 0 / 29 | 0.00 | 29 |
| `activepieces/activepieces` | 15 | 15 (0 / 15 / 0) | 4 / 15 | 1 / 45 | +0.244 | 5 / 12 | 0.42 | 2 |
| `akeneo/pim-community-dev` | 15 | 15 (15 / 0 / 0) | 1 / 15 | 0 / 45 | +0.067 | 4 / 10 | 0.40 | 3 |
| `Infisical/infisical` | 15 | 15 (0 / 15 / 0) | 2 / 15 | 0 / 45 | +0.133 | 5 / 14 | 0.36 | 1 |
| `louislam/uptime-kuma` | 15 | 15 (0 / 15 / 0) | 9 / 15 | 1 / 45 | +0.578 | 3 / 8 | 0.38 | 3 |
| `nocodb/nocodb` | 15 | 16 (0 / 9 / 7) | 6 / 15 | 20 / 47 | -0.026 | 2 / 12 | 0.17 | 0 |
| `TriliumNext/Notes` | 15 | 15 (0 / 0 / 15) | 0 / 15 | 1 / 45 | -0.022 | 0 / 13 | 0.00 | 0 |
| `ToolJet/ToolJet` | 15 | 18 (0 / 18 / 0) | 7 / 18 | 21 / 54 | +0.000 | 4 / 7 | 0.57 | 2 |
| `Hubs-Foundation/hubs` | 15 | 15 (0 / 15 / 0) | 0 / 14 | 0 / 45 | +0.000 | 2 / 4 | 0.50 | 0 |
| `hoppscotch/hoppscotch` | 15 | 15 (0 / 0 / 15) | 4 / 4 | 12 / 12 | +0.000 | 1 / 2 | 0.50 | 0 |
| `umami-software/umami` | 15 | 15 (0 / 0 / 15) | 1 / 12 | 0 / 45 | +0.083 | 4 / 13 | 0.31 | 3 |
| `Sylius/Sylius` | 15 | 15 (15 / 0 / 0) | 0 / 0 | 0 / 0 | — | 3 / 13 | 0.23 | 0 |
| `cryptpad/cryptpad` | 15 | 15 (0 / 15 / 0) | 1 / 15 | 2 / 45 | +0.022 | 7 / 12 | 0.58 | 3 |
| `firefly-iii/data-importer` | 15 | 19 (11 / 8 / 0) | 7 / 19 | 0 / 57 | +0.368 | 11 / 14 | 0.79 | 12 |
| `statamic/cms` | 15 | 15 (0 / 15 / 0) | 0 / 15 | 1 / 45 | -0.022 | 2 / 5 | 0.40 | 1 |
| `payloadcms/payload` | 13 | 13 (0 / 2 / 11) | 6 / 9 | 14 / 20 | -0.033 | 3 / 9 | 0.33 | 1 |
| `SuiteCRM/SuiteCRM-Core` | 15 | 15 (15 / 0 / 0) | 0 / 15 | 5 / 37 | -0.135 | 2 / 14 | 0.14 | 10 |
| `formbricks/formbricks` | 14 | 14 (0 / 0 / 14) | 0 / 5 | 0 / 33 | +0.000 | 5 / 7 | 0.71 | 0 |
| `ampache/ampache` | 13 | 15 (13 / 2 / 0) | 2 / 15 | 0 / 45 | +0.133 | 6 / 11 | 0.55 | 4 |
| `nextcloud/nextcloud-vue` | 15 | 15 (0 / 15 / 0) | 0 / 14 | 0 / 42 | +0.000 | 1 / 6 | 0.17 | 0 |
| `SolidInvoice/SolidInvoice` | 14 | 14 (14 / 0 / 0) | 0 / 14 | 0 / 42 | +0.000 | 1 / 10 | 0.10 | 3 |
| `Ctrlpanel-gg/panel` | 12 | 13 (10 / 3 / 0) | 2 / 12 | 1 / 35 | +0.138 | 2 / 10 | 0.20 | 2 |

- **H1's gap sits in a few repositories.** `louislam/uptime-kuma` (+0.578),
  `firefly-iii/data-importer` (+0.368) and `activepieces/activepieces` (+0.244) carry most of it.
  g is exactly 0 in seven repositories: in five the check rejected nothing at all, and in
  `ToolJet` and `hoppscotch` the two rates are equal.
- **pnpm's ordinary base rate is high.** `nocodb`, `hoppscotch` and `payload` reject 20 of 47,
  12 of 12 and 14 of 20 ordinary checks. 44 of those 46 are "settings" verdicts: a lock file
  written under settings the pnpm that ran does not share. Every "settings" verdict of the study,
  16 merged and 44 ordinary, is in these three repositories. They say more about the pnpm that
  ran than about the merge (see below). They fall on merged and ordinary checks alike, so g
  there is near 0.
- **H3's tie-break files are concentrated too.** `thorsten/phpMyFAQ` has 29 of the 100, and
  the check's side and the first parent's file are both right on all 29.
- **Five repositories gave fewer than 15 cases**: formbricks and SolidInvoice 14, payload and
  ampache 13, Ctrlpanel 12. Their histories, as mined, held fewer conflicts with a checked lock
  file that could be read.

## Errors

A verdict is an error when the tool failed for a reason other than the lock file's consistency.
Errors are left out of every share (§4). There were 49 among the 395 merged files, 142 among
the 790 parents' files checked in the merge's tree, and 131 among the 1,185 ordinary checks.
`verification/describe.txt` lists them all by message. The main causes, checked by hand where
stated:

- **Composer, 91: all of `Sylius/Sylius`, and 1 other.** Composer 2.8.12 refuses a
  `composer.json` whose `require-dev` names a package with capital letters, while it loads
  `composer.json`, before any judgement of the lock file. That is the cause on the one Sylius merge re-run by hand. The verdict
  records Composer's usage line, which follows its error, not the error itself. Sylius therefore
  has no H1 figure, and H1 has 24 repositories. Its rule D fires come from the gate alone, which
  does not use the check.
- **pnpm, 99, `ERR_PNPM_NO_LOCKFILE`.** The pnpm that ran did not read the lock file. In each
  of `woocommerce`, `hoppscotch` and `payload`, one such merge was checked by hand. Its lock
  file is of format 5.3 or 6.0, written by an older pnpm, and its `package.json` declares no pnpm.
- **pnpm, 21 + 15 more, from a pnpm switching versions.** The 21 messages come from a pnpm
  8.1.1 that pnpm 10.28.0 had installed for itself; the other 15 are tarball errors
  (`ERR_INVALID_THIS`), consistent with an old pnpm on the current Node (22). See below.
- **npm, 37 `ERESOLVE` and 17 `E403`.** npm could not resolve the tree's peer requirements, or
  the registry refused a request. Neither is a verdict on the lock file.

## What the registration did not say

- **Which pnpm ran.**
  - §4 says pnpm runs "with the pnpm the tree's `package.json` declares, or 10.28.0". The
    registered code, `bench.lock_check.pnpm_version`, takes the declared version only if it is
    10.16 or later. No tree here declared one, so the run invoked pnpm 10.28.0 on every pnpm
    file, and `files.jsonl` records that.
  - pnpm 10.28.0, in turn, installs and runs the version a `packageManager` field names; its
    `manage-package-manager-versions` setting is on by default. The errors above show it did so
    at least where they occurred.
  - So which pnpm judged a given file is not recorded. Its "settings" verdicts (16 merged, 44
    ordinary) are where that matters most, and H1 without them is reported above.
- **Package names in error messages.** §10 says no package name is written. Some error verdicts
  quote the end of a tarball's name, such as `…h-0.7.31.tgz`, as the tool printed it. They are
  left as recorded.

## Exclusions

As registered (§3.2), 169 merges were passed over:

- 99 criss-cross merges, 72 of them in appwrite;
- 44 submodule or binary conflicts, 21 in appwrite and 17 in ToolJet;
- 26 merged lock files that could not be read, 14 of them in nocodb.

No case was left out for a `merge` attribute on a conflicted lock file at the first parent
(`attribute_exclusions` is empty).

## Verification

| script | what it does | result |
| --- | --- | --- |
| `verification/recompute.py` | Imports nothing from the project. Recomputes every figure and decision of §6, §7 and §9 from `files.jsonl` and checks each against `report.json`. Its t quantiles come from its own incomplete beta function. | all agree (`recompute.txt`) |
| `verification/describe.py` | Imports nothing from the project but `recompute.py`. Produces the per-repository table, H1's fragility, the errors by message and the tie-break's reverses and wins. None of it is registered. | `describe.txt` |

## Files

- `manifest.json`: every repository's pinned tip and licence, every case's SHAs, every exclusion.
- `labels.jsonl`: study 3's per-file, per-action labels.
- `files.jsonl`: every checked lock file, with its verdicts (merged, both parents in the merge's
  tree, and both parents and the base in their own trees), divergence and labels.
- `report.json` and `summary.txt`: every figure and decision.
