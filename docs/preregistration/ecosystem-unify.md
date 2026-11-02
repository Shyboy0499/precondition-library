# Pre-registration: does the resolver predict which package-level merge a maintainer kept? (study 4)

- **Registered:** by the commit that adds this file and its pin in `bench.preregistration`
  (`ecosystem-unify`). Measuring code calls `preregistration.require("ecosystem-unify")` before it
  mines anything.
- **Issues:** #306 (the lock-file task from what maintainers do), #297, #294.
- **Decisions behind it:** ADR-0048 (pre-registration), ADR-0056 (study 3), ADR-0058 (this
  design and its size).

## 1. Question

Study 3 (`lock-oracle.md`, `results/lock-oracle-2026-11-02/`) computed two package-level
three-way merges of every conflicted lock file:

- `three_way`: what both sides kept, plus what either added;
- `three_way_unified`: the same, with only the highest version kept within each package's
  compatible range.

After seeing the data, it found that the two disagree in opposite directions by ecosystem:

- In lock files whose resolver installs one version of a package, the unified merge
  reproduced the maintainer where the plain one did not (31 files to 1).
- In npm's family, which keeps compatible duplicates in nested `node_modules`, the plain merge
  did (42 files to 4).

That finding is exploratory. This study tests it on repositories nobody here has mined or counted:

> **Where the two package-level merges disagree, does the ecosystem's resolver predict which one
> the maintainer committed?**

A yes fixes the lock-file task's merge action: one rule, per ecosystem, written from what
maintainers did.

## 2. Hypotheses

A conflicted lock file is **discordant** when exactly one of `three_way` and `three_way_unified`
gives the maintainer's package set. The **predicted** merge is fixed by the file's family (§4):

- `three_way_unified` for the one-version family;
- `three_way` for npm's family.

Each repository with a discordant file **votes**:

- *for* the prediction, if the predicted merge wins more of its discordant files than it loses;
- *against*, if it loses more;
- not at all on a tie.

| | discordant files counted | prediction |
| --- | --- | --- |
| **H1 (primary)** | all | the resolver's rule, per file |
| **H2** | the one-version family's only | `three_way_unified` |
| **H3** | npm's family's only | `three_way` |
| **H4 (replication)** | — | study 3's H1: mean coverage over repositories above 0.10 |

## 3. Cases

### 3.1 Repositories

The study mines these repositories in this order. None was mined, labelled or counted by this
project before. None is on study 1's lists, study 2's (Amendment 2 included), study 3's list, or
among study 3's 53 counted candidates; a test checks this. Each was chosen from the feasibility
count in §11, which reads no merge commit's own tree.

| | repository | lock-file conflicts in the count (§11) |
| ---: | --- | ---: |
| 1 | `rubyforgood/human-essentials` | 36 |
| 2 | `fatfreecrm/fat_free_crm` | 33 |
| 3 | `rubyforgood/casa` | 18+ |
| 4 | `element-hq/element-desktop` | 8 |
| 5 | `mautic/mautic` | 110 |
| 6 | `glpi-project/glpi` | 176 |
| 7 | `joomla/joomla-cms` | 164 |
| 8 | `humhub/humhub` | 34 |
| 9 | `cypress-io/cypress` | 99 |
| 10 | `akaunting/akaunting` | 6 |
| 11 | `espocrm/espocrm` | 18 |
| 12 | `pixelfed/pixelfed` | 7 |
| 13 | `matrix-org/matrix-react-sdk` | 72 |
| 14 | `Leantime/leantime` | 36 |
| 15 | `element-hq/element-web` | 147+ |
| 16 | `SuiteCRM/SuiteCRM` | 29 |
| 17 | `rust-lang/rustlings` | 5 |
| 18 | `civicrm/civicrm-core` | 17 |
| 19 | `strapi/strapi` | 147+ |
| 20 | `storybookjs/storybook` | 76+ |

A candidate is listed when the count found at least 5 merges whose conflict includes a lock
file. A `+` marks a count that stopped at the script's limit of 400 tried merges. The order is
the order the counts finished in.

### 3.2 Cases, the cap and exclusions

These are study 3's, made by the same code (`lock_oracle.label_repository` over
`real_merges.mine`):

- A case is a two-parent merge whose sides both changed a lock file since their single merge base,
  and whose `git merge-tree` conflict includes a lock file.
- Criss-cross merges and submodule or binary conflicts are excluded.
- A repository's cases are labelled from its most recent merge back, until 15 are labelled.
- A case whose maintainer's merged lock file cannot be read is passed over and recorded.

## 4. Labels and families

Each conflicted lock file is read into its set of `(package, version)` pairs, and the computed
actions are formed exactly as in study 3 §4 (`lock_actions.computed_actions`). The two families
partition every lock file study 1 counts:

| family | lock files | why |
| --- | --- | --- |
| one-version | `composer.lock`, `Gemfile.lock`, `poetry.lock`, `uv.lock`, `Pipfile.lock`, `Cargo.lock` | the resolver installs one version of a package, or one per semver-incompatible range for Cargo, so two compatible versions cannot both stay |
| npm | `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml` | compatible duplicates coexist in nested installs |

`bench.ecosystem_unify` computes votes, tests and figures at the commit that adds this file.

## 5. Order of work

1. This registration, the power analysis, the code and its tests, committed together.
2. `python -m precondition_library.bench.ecosystem_unify --out results/ecosystem-unify-<date>`
   mines, labels and reports every repository of §3.1 in one run.
3. The results are committed as they come out, with any deviation reported in their README,
   never written into this file.

## 6. Analysis

- **H1–H3** use the exact two-sided sign test over the votes. The test is over repositories, so
  a repository counts once however many discordant files it has.
- **H4** uses study 3's analysis: the mean over repositories of each repository's coverage, with
  a 95% t-interval over repositories.

## 7. Descriptive figures (no hypothesis)

The report also gives:

- discordant files won and lost by the prediction, pooled over repositories;
- the votes for, against and tied;
- the share of cases the predicted merge reproduces on every lock file;
- the share each computed action reproduces.

## 8. Sample size and power

`ecosystem-unify-power.py` (beside this file; output `ecosystem-unify-power.json`) simulates
this analysis by resampling study 3's 27 repositories and their cases, at up to 15 cases each.
The null world swaps each discordant file's winner with probability one half. With 2,000
simulated studies per design:

| repositories | H1 power | H2 power | H3 power | H1 votes (mean) | false support, H1 / H2 / H3 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 0.68 | 0.10 | 0.10 | 6.9 | 0.005 / 0.000 / 0.001 |
| 12 | 0.85 | 0.23 | 0.23 | 8.4 | 0.010 / 0.004 / 0.004 |
| 15 | 0.94 | 0.46 | 0.43 | 10.4 | 0.009 / 0.003 / 0.004 |
| 18 | 0.98 | 0.64 | 0.62 | 12.5 | 0.015 / 0.006 / 0.007 |
| 20 | 0.99 | 0.74 | 0.71 | 13.9 | 0.010 / 0.009 / 0.004 |

- **H1 is the one hypothesis this study is sized for.** H2 and H3 each see one family's
  repositories, and with two families split across the repositories, few repositories vote in
  each.
- **A target of 12 repositories with a case.** H1's power is then 0.85, and 0.98 at 18.

## 9. Decision rules, in order

1. **Power.** If fewer than 12 repositories have a labelled case, the study is underpowered.
   Every figure is reported, and no hypothesis is decided.
2. **H1, H2 and H3**, each on its own votes:
   - If it has fewer than 6 votes, it is *not decided*: no sign test on fewer votes can reach
     p < 0.05.
   - Otherwise it is *supported* if the prediction wins more votes than it loses and the sign
     test gives p < 0.05.
   - Otherwise it is *not supported*. That includes a significant loss, which is reported as a
     finding against the prediction.
3. **H4** is supported if its interval's lower end is above 0.10.

## 10. Reporting

- `summary.txt` and `report.json` give every figure of §6 and §7 and the decisions.
- `labels.jsonl` gives every case's per-file, per-action result, re-derivable from git with the
  SHAs in `manifest.json`.
- A result against a hypothesis is reported as plainly as one for it.

## 11. Feasibility, done before registration

`real-merges-feasibility.py` (study 1's) was run on 29 named candidates. It counts two-parent
merges, those whose sides both changed a lock file, and those whose `git merge-tree` conflict
includes one. It never reads a merge commit's own tree. Every candidate counting at least 5 is
listed in §3.1. The counts are committed beside this file (`ecosystem-unify-feasibility.jsonl`).

| repository | two-parent merges | both sides changed a lock file | tried | conflict | includes a lock file | listed |
| --- | ---: | ---: | ---: | ---: | ---: | :---: |
| `zammad/zammad` | 652 | 6 | 6 | 3 | 0 | no |
| `rubyforgood/human-essentials` | 1544 | 144 | 144 | 47 | 36 | yes |
| `fatfreecrm/fat_free_crm` | 1291 | 241 | 241 | 39 | 33 | yes |
| `rubyforgood/casa` | 3901 | 712 | 400 | 25 | 18 | yes |
| `codetriage/CodeTriage` | 996 | 322 | 322 | 4 | 2 | no |
| `element-hq/element-desktop` | 757 | 39 | 39 | 8 | 8 | yes |
| `brave/brave-browser` | 1571 | 13 | 13 | 0 | 0 | no |
| `mautic/mautic` | 11113 | 210 | 210 | 126 | 110 | yes |
| `glpi-project/glpi` | 850 | 213 | 213 | 198 | 176 | yes |
| `joomla/joomla-cms` | 6776 | 248 | 248 | 221 | 164 | yes |
| `kimai/kimai` | 5 | 0 | 0 | 0 | 0 | no |
| `humhub/humhub` | 2222 | 41 | 41 | 39 | 34 | yes |
| `cypress-io/cypress` | 2131 | 251 | 251 | 173 | 99 | yes |
| `akaunting/akaunting` | 2325 | 7 | 7 | 7 | 6 | yes |
| `espocrm/espocrm` | 1951 | 93 | 93 | 22 | 18 | yes |
| `kanboard/kanboard` | 348 | 0 | 0 | 0 | 0 | no |
| `YOURLS/YOURLS` | 174 | 0 | 0 | 0 | 0 | no |
| `pixelfed/pixelfed` | 4013 | 47 | 47 | 11 | 7 | yes |
| `matrix-org/matrix-react-sdk` | 13145 | 264 | 264 | 127 | 72 | yes |
| `freescout-helpdesk/freescout` | 773 | 0 | 0 | 0 | 0 | no |
| `Leantime/leantime` | 1678 | 106 | 106 | 51 | 36 | yes |
| `element-hq/element-web` | 17959 | 662 | 400 | 172 | 147 | yes |
| `rust-lang/rustc_codegen_cranelift` | 1066 | 77 | 77 | 10 | 2 | no |
| `SuiteCRM/SuiteCRM` | 3695 | 41 | 41 | 35 | 29 | yes |
| `rust-lang/rustlings` | 834 | 10 | 10 | 8 | 5 | yes |
| `jitsi/jitsi-meet` | 942 | 6 | 6 | 1 | 0 | no |
| `civicrm/civicrm-core` | 31073 | 46 | 46 | 18 | 17 | yes |
| `strapi/strapi` | 11745 | 1010 | 400 | 187 | 147 | yes |
| `storybookjs/storybook` | 26827 | 3321 | 400 | 165 | 76 | yes |

The counts were taken on 2026-11-02. One more candidate, `chatwoot/chatwoot`, was dropped before
counting because study 3 had already counted it.

## 12. What was seen before this registration

- Study 3's labels, which motivated the question and sized §8.
- The feasibility counts in §11.
- Nothing of any listed repository's merged lock files.
