# Pre-registration: does refusing where a package diverges make the lock-file merge rarely wrong? (study 5)

- **Registered:** by the commit that adds this file and its pin in `bench.preregistration`
  (`divergence-gate`). Measuring code calls `preregistration.require("divergence-gate")` before it
  mines anything.
- **Issues:** #306 (the lock-file task from what maintainers do), #297, #294.
- **Decisions behind it:** ADR-0048 (pre-registration), ADR-0056 (study 3), ADR-0058 (study 4),
  ADR-0059 (this design and its size).

## 1. Question

Studies 3 and 4 found that a merge computed from a lock-file conflict's three sides reproduces
the maintainer's package set on most conflicts. After seeing both, `results/lock-anatomy-2026-11-04/`
read every conflicted file package by package. A package **diverges** when both sides changed its
versions from the base, to different versions. Where nothing diverges, the conflict is the line
format colliding, not the sides disagreeing. That analysis found:

- The predicted per-ecosystem merge reproduced 0.66–0.82 of files where nothing diverges, and
  much less where something does.
- A rule over the three sides alone, the **gate**, fires the merge on a conflict only if no
  package diverges in any of its conflicted lock files, and refuses otherwise. It cut the merge's
  case-level mismatch from 0.56 to 0.32 in study 3, and from 0.45 to 0.22 in study 4. Both are
  still well above study 1's 0.10 for "rarely mis-fires".

The gate is an executable precondition of exactly the kind this project compiles. Those findings
are exploratory. This study tests them on repositories nobody here has mined or counted:

> **Does the divergence gate make the package-level merge rarely wrong, does it lower the merge's
> mismatch, and does divergence still matter where it cannot defeat the merge by construction?**

## 2. Hypotheses

The **predicted merge** is study 4's: `three_way_unified` for the one-version family and
`three_way` for npm's (§4). On each case it is *right* if it gives the maintainer's package set on
every conflicted lock file, and *wrong* otherwise. Per repository:

- **m_always**: the share of its cases on which the predicted merge is wrong;
- **m_gate**: the same share among the cases where no package diverges, the gate's fires.

H1 and H2 are means over the repositories where the gate fires at least once.

| | statistic | prediction |
| --- | --- | --- |
| **H1 (primary)** | mean m_gate | above 0.10: the gate does not make the merge rarely wrong |
| **H2** | mean (m_always − m_gate) | above 0: the gate lowers the merge's mismatch |
| **H3** | on cases whose conflicted lock files are all one-version: within repositories, the share the merge reproduces where nothing diverges minus where something does | above 0 |

**H2 is largely structural in npm's family, and the registration says so before the data.**
There, the plain merge keeps both sides' versions of a divergent package, and maintainers almost
never do, so the gate is near-certain to help. **H3 is the test that could most plausibly fail.**
In the one-version family the unified merge keeps one version of a divergent package, and that
can be the one the maintainer kept.

## 3. Cases

### 3.1 Repositories

The study mines these repositories in this order. None was mined, labelled or counted by this
project before. None is on study 1's lists, study 2's (Amendment 2 included), study 3's or study
4's lists, or among the candidates studies 3 and 4 counted; a test checks this. Each was chosen
from the feasibility count in §11, which reads no merge commit's own tree.

| | repository | lock-file conflicts in the count (§11) | of them with a one-version lock file | with an npm-family lock file |
| ---: | --- | ---: | ---: | ---: |
| 1 | `Kovah/LinkAce` | 11 | 10 | 2 |
| 2 | `krayin/laravel-crm` | 8 | 8 | 0 |
| 3 | `PrivateBin/PrivateBin` | 6 | 5 | 1 |
| 4 | `cachethq/cachet` | 24 | 24 | 0 |
| 5 | `coollabsio/coolify` | 23 | 14 | 11 |
| 6 | `bagisto/bagisto` | 34 | 34 | 0 |
| 7 | `phpbb/phpbb` | 89 | 89 | 0 |
| 8 | `Attendize/Attendize` | 6 | 5 | 1 |
| 9 | `pelican-dev/panel` | 12 | 10 | 2 |
| 10 | `Part-DB/Part-DB-server` | 17 | 17 | 7 |
| 11 | `elabftw/elabftw` | 13 | 3 | 10 |
| 12 | `lobsters/lobsters` | 12 | 12 | 0 |
| 13 | `paperless-ngx/paperless-ngx` | 27 | 24 | 3 |
| 14 | `ProcessMaker/processmaker` | 197 | 155 | 90 |
| 15 | `penpot/penpot` | 11 | 0 | 11 |
| 16 | `PrefectHQ/prefect` | 41 | 0 | 41 |
| 17 | `DFE-Digital/apply-for-teacher-training` | 8+ | 2 | 6 |
| 18 | `nextcloud/polls` | 7+ | 1 | 6 |
| 19 | `TryGhost/Ghost` | 16 | 1 | 15 |
| 20 | `nextcloud/activity` | 107 | 0 | 107 |

A candidate is listed when the count found at least 5 merges whose conflict includes a lock file.
A `+` marks a count that stopped at the script's limit of 400 tried merges. The order is the order
the counts finished in.

### 3.2 Cases, the cap and exclusions

These are study 3's, made by the same code (`lock_oracle.label_repository` over
`real_merges.mine`):

- A case is a two-parent merge whose sides both changed a lock file since their single merge base,
  and whose `git merge-tree` conflict includes a lock file.
- Criss-cross merges and submodule or binary conflicts are excluded.
- A repository's cases are labelled from its most recent merge back, until 15 are labelled.
- A case whose maintainer's merged lock file cannot be read is passed over and recorded.

## 4. Labels, families and divergence

- **Labels.** Each conflicted lock file is read into its set of `(package, version)` pairs, and
  the computed actions are formed exactly as in study 3 §4 (`lock_actions.computed_actions`).
- **Families.** Study 4's (§4 there): one-version is `composer.lock`, `Gemfile.lock`,
  `poetry.lock`, `uv.lock`, `Pipfile.lock` and `Cargo.lock`; npm's is `package-lock.json`,
  `npm-shrinkwrap.json`, `yarn.lock` and `pnpm-lock.yaml`.
- **Divergence.** Each side's file at the base, the first parent (local) and the second parent
  (upstream) is read into a map from package name to its set of versions. A side whose file
  cannot be read counts as empty. In npm's family a name's set holds the versions of all its
  nested copies. A package diverges when local's set differs from the base's, upstream's set
  differs from the base's, and local's differs from upstream's.

`bench.divergence_gate` computes divergence, the figures and the decisions at the commit that
adds this file. Its definition reproduces `results/lock-anatomy-2026-11-04/` on all 290 of study
4's conflicted files.

## 5. Order of work

1. This registration, the power analysis, the feasibility count, the code and its tests, committed
   together.
2. `python -m precondition_library.bench.divergence_gate --out results/divergence-gate-<date>`
   mines, labels and reports every repository of §3.1 in one run.
3. The results are committed as they come out, with any deviation reported in their README,
   never written into this file.

## 6. Analysis

- **H1 and H2:** the mean over repositories where the gate fires, with a 95% t-interval over those
  repositories (study 3's analysis, `lock_oracle.t_975`).
- **H3:** the Mantel-Haenszel risk difference with repositories as strata. Each repository with
  one-version cases of both kinds contributes its difference, reproduced where nothing diverges
  minus where something does. Its weight is n_calm · n_split / (n_calm + n_split). The 95%
  interval is the percentile bootstrap over 2,000 resamples of the repositories with replacement,
  seed 20261108. If fewer than 90% of the resamples define the statistic, the interval is
  undefined.

## 7. Descriptive figures (no hypothesis)

The report also gives:

- the merge's mismatch pooled over cases, fired always and fired by the gate, with Wilson
  intervals;
- the share of cases on which the gate fires;
- per family, the files with no divergent package and with some, and those the predicted merge
  reproduces;
- study 3's coverage, as a second replication.

## 8. Sample size and power

`divergence-gate-power.py` (beside this file; output `divergence-gate-power.json`) simulates this
analysis by resampling studies 3 and 4's 47 repositories and their cases, at up to 15 cases each.
In the null worlds:

- for H1, every one of the gate's fires is wrong with probability exactly 0.10;
- for H2 and H3, each repository's divergence flags are shuffled among its cases.

With 1,000 simulated studies per design and 500 bootstrap resamples within each:

| repositories | H1 power | H2 power | H3 power | false support, H1 / H2 / H3 |
| ---: | ---: | ---: | ---: | ---: |
| 12 | 0.56 | 0.58 | 0.29 | 0.002 / 0.016 / 0.051 |
| 15 | 0.68 | 0.69 | 0.31 | 0.002 / 0.011 / 0.045 |
| 20 | 0.85 | 0.85 | 0.37 | 0.010 / 0.018 / 0.046 |
| 25 | 0.94 | 0.93 | 0.40 | 0.008 / 0.014 / 0.034 |

- **H1 and H2 are what the study is sized for.** At 20 repositories each has power 0.85.
- **H3 is underpowered at any feasible size.** The within-repository effect in studies 3 and 4 is
  0.22 (pooled over cases it looks larger, 0.4, but most of that difference is between
  repositories). Its power is about 0.37 at 20 repositories. The percentile bootstrap also
  supports it falsely about 4.6% of the time against a nominal 2.5%. A failure of H3 is therefore
  read as uninformative unless its interval's upper end falls below 0.22, the exploratory estimate.
- **A target of 20 repositories where the gate fires, and at least 15.**

## 9. Decision rules, in order

1. **Power.** If the gate fires in fewer than 15 repositories, the study is underpowered. Every
   figure is reported, and no hypothesis is decided.
2. **H1** is *supported* if its interval's lower end is above 0.10. If its upper end is below
   0.10, it is *not supported* and the finding is stated: the gate makes the merge rarely wrong.
   Otherwise it is *not supported*.
3. **H2** is *supported* if its interval's lower end is above 0. If its upper end is below 0, the
   gate raised the merge's mismatch, and that is reported.
4. **H3** is *supported* if its interval's lower end is above 0. If the interval is undefined, it
   is *not decided*. Otherwise it is *not supported*, and §8's reading applies.

## 10. Reporting

- `summary.txt` and `report.json` give every figure of §6 and §7 and the decisions.
- `labels.jsonl` gives every case's per-file, per-action result, and `gates.jsonl` every case's
  divergence, re-derivable from git with the SHAs in `manifest.json`. No package name is written.
- A result against a hypothesis is reported as plainly as one for it.

## 11. Feasibility, done before registration

`divergence-gate-feasibility.py` (beside this file) is study 1's count with one addition. For each
merge whose conflict includes a lock file, it records whether those lock files include the
one-version family and npm's. It counts two-parent merges, those whose sides both changed a lock
file, and those whose `git merge-tree` conflict includes one. It never reads a merge commit's own
tree. Every candidate counting at least 5 is listed in §3.1. The counts are committed beside this
file (`divergence-gate-feasibility.jsonl`).

| repository | two-parent merges | both sides changed a lock file | tried | conflict | includes a lock file | one-version | npm | listed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| `monicahq/monica` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `LycheeOrg/Lychee` | 5 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `koel/koel` | 188 | 2 | 2 | 1 | 0 | 0 | 0 | no |
| `solidtime-io/solidtime` | 15 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `Kovah/LinkAce` | 208 | 19 | 19 | 12 | 11 | 10 | 2 | yes |
| `crater-invoice/crater` | 429 | 1 | 1 | 1 | 1 | 1 | 0 | no |
| `krayin/laravel-crm` | 1815 | 15 | 15 | 11 | 8 | 8 | 0 | yes |
| `PrivateBin/PrivateBin` | 1129 | 15 | 15 | 10 | 6 | 5 | 1 | yes |
| `cachethq/cachet` | 1367 | 88 | 88 | 29 | 24 | 24 | 0 | yes |
| `coollabsio/coolify` | 3678 | 73 | 73 | 36 | 23 | 14 | 11 | yes |
| `FreshRSS/FreshRSS` | 941 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `opencart/opencart` | 4829 | 1 | 1 | 1 | 0 | 0 | 0 | no |
| `bagisto/bagisto` | 9077 | 66 | 66 | 39 | 34 | 34 | 0 | yes |
| `alphagov/signon` | 4046 | 1464 | 400 | 0 | 0 | 0 | 0 | no |
| `alphagov/content-publisher` | 2892 | 479 | 400 | 0 | 0 | 0 | 0 | no |
| `alphagov/smart-answers` | 6783 | 653 | 400 | 0 | 0 | 0 | 0 | no |
| `phpbb/phpbb` | 10995 | 147 | 147 | 99 | 89 | 89 | 0 | yes |
| `Attendize/Attendize` | 284 | 10 | 10 | 8 | 6 | 5 | 1 | yes |
| `InvoiceShelf/InvoiceShelf` | 586 | 5 | 5 | 5 | 3 | 3 | 0 | no |
| `unopim/unopim` | 261 | 15 | 15 | 4 | 1 | 1 | 0 | no |
| `pelican-dev/panel` | 734 | 21 | 21 | 16 | 12 | 10 | 2 | yes |
| `Part-DB/Part-DB-server` | 276 | 25 | 25 | 18 | 17 | 17 | 7 | yes |
| `alphagov/collections` | 4017 | 566 | 400 | 0 | 0 | 0 | 0 | no |
| `LinkStackOrg/LinkStack` | 284 | 53 | 53 | 1 | 1 | 1 | 0 | no |
| `elabftw/elabftw` | 377 | 26 | 26 | 16 | 13 | 3 | 10 | yes |
| `alphagov/frontend` | 5258 | 559 | 400 | 0 | 0 | 0 | 0 | no |
| `alphagov/content-tagger` | 2109 | 424 | 400 | 0 | 0 | 0 | 0 | no |
| `alphagov/publisher` | 3154 | 612 | 400 | 0 | 0 | 0 | 0 | no |
| `DFE-Digital/get-into-teaching-app` | 4161 | 232 | 232 | 6 | 2 | 2 | 0 | no |
| `DFE-Digital/register-trainee-teachers` | 3749 | 437 | 400 | 1 | 0 | 0 | 0 | no |
| `alphagov/specialist-publisher` | 3517 | 620 | 400 | 2 | 1 | 1 | 0 | no |
| `exercism/website` | 4 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `mealie-recipes/mealie` | 248 | 9 | 9 | 2 | 0 | 0 | 0 | no |
| `HumanSignal/label-studio` | 20 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `lobsters/lobsters` | 310 | 29 | 29 | 18 | 12 | 12 | 0 | yes |
| `paperless-ngx/paperless-ngx` | 1836 | 94 | 94 | 41 | 27 | 24 | 3 | yes |
| `danbooru/danbooru` | 1285 | 17 | 17 | 2 | 1 | 0 | 1 | no |
| `maybe-finance/maybe` | 16 | 1 | 1 | 0 | 0 | 0 | 0 | no |
| `nextcloud/forms` | 2209 | 549 | 400 | 0 | 0 | 0 | 0 | no |
| `ProcessMaker/processmaker` | 9172 | 345 | 345 | 242 | 197 | 155 | 90 | yes |
| `nextcloud/contacts` | 3099 | 907 | 400 | 0 | 0 | 0 | 0 | no |
| `alphagov/government-frontend` | 3296 | 503 | 400 | 0 | 0 | 0 | 0 | no |
| `nextcloud/news` | 311 | 2 | 2 | 2 | 2 | 2 | 2 | no |
| `alphagov/manuals-publisher` | 2610 | 464 | 400 | 2 | 0 | 0 | 0 | no |
| `penpot/penpot` | 4267 | 36 | 36 | 24 | 11 | 0 | 11 | yes |
| `rust-lang/team` | 2186 | 11 | 11 | 1 | 1 | 1 | 0 | no |
| `nextcloud/notes` | 743 | 81 | 81 | 3 | 3 | 0 | 3 | no |
| `rust-lang/crater` | 602 | 10 | 10 | 0 | 0 | 0 | 0 | no |
| `PrefectHQ/prefect` | 3692 | 207 | 207 | 46 | 41 | 0 | 41 | yes |
| `rust-lang/measureme` | 115 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `rust-lang/www.rust-lang.org` | 964 | 62 | 62 | 0 | 0 | 0 | 0 | no |
| `nextcloud/collectives` | 905 | 73 | 73 | 0 | 0 | 0 | 0 | no |
| `DFE-Digital/apply-for-teacher-training` | 9684 | 721 | 400 | 9 | 8 | 2 | 6 | yes |
| `alphagov/support` | 1978 | 445 | 400 | 0 | 0 | 0 | 0 | no |
| `discourse/discourse` | 3958 | 33 | 33 | 6 | 2 | 2 | 0 | no |
| `nextcloud/polls` | 2873 | 605 | 400 | 15 | 7 | 1 | 6 | yes |
| `alphagov/email-alert-api` | 2521 | 412 | 400 | 0 | 0 | 0 | 0 | no |
| `TryGhost/Ghost` | 4053 | 78 | 78 | 24 | 16 | 1 | 15 | yes |
| `alphagov/finder-frontend` | 3590 | 496 | 400 | 1 | 1 | 1 | 0 | no |
| `nextcloud/richdocuments` | 2890 | 733 | 400 | 0 | 0 | 0 | 0 | no |
| `alphagov/static` | 3860 | 424 | 400 | 0 | 0 | 0 | 0 | no |
| `nextcloud/groupfolders` | 1665 | 353 | 353 | 2 | 2 | 0 | 2 | no |
| `alphagov/search-api` | 3411 | 554 | 400 | 1 | 0 | 0 | 0 | no |
| `nextcloud/activity` | 1582 | 113 | 113 | 107 | 107 | 0 | 107 | yes |
| `mozilla/fxa` | 14667 | 1728 | 400 | 2 | 1 | 0 | 1 | no |
| `nextcloud/photos` | 1489 | 301 | 301 | 6 | 1 | 0 | 1 | no |
| `ministryofjustice/laa-apply-for-legal-aid` | — | — | — | — | — | — | — | no: not found |

The counts were taken on 2026-11-08.

## 12. What was seen before this registration

- Studies 3 and 4's labels and their anatomy, which motivated the question and sized §8.
- The feasibility counts in §11.
- Nothing of any listed repository's merged lock files.
