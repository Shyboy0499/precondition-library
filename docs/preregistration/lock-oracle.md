# Pre-registration: which computed action reproduces a maintainer's lock file (study 3)

- **Registered:** by the commit that adds this file and its pin in `bench.preregistration`
  (`lock-oracle`). Measuring code calls `preregistration.require("lock-oracle")` before it
  mines anything.
- **Issues:** #306 (rebuild the lock-file task from what maintainers do), #297 (an external
  oracle), #294.
- **Decisions behind it:** ADR-0048 (pre-registration), ADR-0050 (the rebuild), ADR-0056 (this
  design and its size).

## 1. Question

Study 1 (`real-merges.md`) labelled a real lock-file merge by whether the maintainer's file was
one of two *line* unions, and found that none of stage A's 30 was. The exploratory pilot
(`results/lock-actions-2026-10-27/`) read the same 30 files as sets of resolved
`(package, version)` pairs. There, a package-level three-way merge, or one side's file, gave the
maintainer's exact set on 10 of 30. Where they missed, they missed by a few packages. That pilot
ran on data already seen, chose its actions after looking, and comes from six repositories.

This study asks the question on repositories nobody here has mined:

> **How often does an action computed from the base and the two sides alone -- no tool, no
> registry, no judgement -- give exactly the package set a maintainer committed? And is the
> package-level three-way merge closer to what they committed than either side taken whole?**

The answer decides whether these labels can serve as an external oracle for the lock-file task
(#297): an oracle that labels too few conflicts, or labels them from the wrong starting point, is
not one.

## 2. Hypotheses

Write a repository's **coverage** for the share of its cases on which some computed action
(§4) reproduces the maintainer's lock files exactly.

- **H1 (primary).** The mean coverage over repositories is above **0.10**. At least one real
  lock-file conflict in ten has an answer that a computed action reproduces exactly.
- **H2.** The three-way merge with unification (`three_way_unified`, §4) is closer to the
  maintainer's package set than each side taken whole. Per case, closeness is the Jaccard
  similarity of the action's set to the maintainer's. The statistic is the mean over
  repositories of the per-repository mean of the merge's Jaccard minus the side's, once for the
  local side and once for upstream. H2 needs both to be positive.

## 3. Cases

### 3.1 Repositories

Mined in this order. None was mined, labelled or opened by this project before: none is on
study 1's lists (`real_merges.PILOT`, `real_merges.CONFIRMATORY`) or study 2's
(`refusal_set.ADMISSION`, `refusal_study.EVALUATION`). Each was chosen from the feasibility count
in §11, which reads no merge commit's own tree.

| | repository | lock-file conflicts in the count (§11) |
| ---: | --- | ---: |
| 1 | `phpstan/phpstan-src` | 118 |
| 2 | `huginn/huginn` | 16 |
| 3 | `diaspora/diaspora` | 80 |
| 4 | `rust-lang/rustfmt` | 7 |
| 5 | `pterodactyl/panel` | 10 |
| 6 | `BookStackApp/BookStack` | 17 |
| 7 | `getgrav/grav` | 58 |
| 8 | `Textualize/rich` | 6 |
| 9 | `Textualize/textual` | 15 |
| 10 | `invoiceninja/invoiceninja` | 55 |
| 11 | `bolt/core` | 50 |
| 12 | `snipe/snipe-it` | 62 |
| 13 | `rust-lang/crates.io` | 10+ |
| 14 | `openstreetmap/openstreetmap-website` | 25 |
| 15 | `firefly-iii/firefly-iii` | 57+ |
| 16 | `wallabag/wallabag` | 5+ |
| 17 | `feedbin/feedbin` | 11 |
| 18 | `contao/contao` | 94 |
| 19 | `nightscout/cgm-remote-monitor` | 31 |
| 20 | `MagicMirrorOrg/MagicMirror` | 17 |
| 21 | `otwcode/otwarchive` | 16 |
| 22 | `node-red/node-red` | 11 |
| 23 | `webpack/webpack` | 9+ |
| 24 | `consuldemocracy/consuldemocracy` | 18 |
| 25 | `laurent22/joplin` | 23 |
| 26 | `processing/p5.js` | 9 |
| 27 | `loomio/loomio` | 18+ |

A candidate is listed when the count found at least 5 merges whose conflict includes a lock
file. A `+` marks a count that stopped at the script's limit of 400 tried merges.

### 3.2 Cases

A repository's cases are the merges `real_merges.mine` calls *positive* at its default branch's
tip, pinned on the day it is mined. These are exactly study 1's §3.2-§3.5:

- a two-parent merge;
- whose sides both changed a lock file since their single merge base;
- whose `git merge-tree` conflict includes a lock file;
- excluding criss-cross merges and submodule or binary conflicts.

A lock file is any path whose final component is one of `real_merges.LOCK_FILES`: npm's two, yarn,
pnpm, Cargo, poetry, Pipfile, uv, Gemfile and composer. Clean merges are not cases here.

### 3.3 At most 15 per repository

A repository's cases are labelled from its most recent merge back, by committer date and then
SHA, until 15 are labelled. A repository with fewer contributes all it has.

### 3.4 Passed over

A case is passed over, recorded with its reason, and does not count toward the 15 when the
maintainer's own merged file, at any of the case's conflicted lock-file paths, cannot be read.
That covers a file the merge deleted, one committed with conflict markers, and one that does not
parse. There is then no package set to reproduce. A side's file that cannot be read does not
pass a case over: the actions that need it reproduce nothing, and its Jaccard is 0.

## 4. The label

Each conflicted lock file of a case is read into its set of `(package, version)` pairs by
`lock_actions.packages`. The readers are tested on each format (`tests/test_lock_actions.py`).
Formatting, ordering, checksums, sources and the file's format version are ignored. Four actions
are computed from the base's, the local side's (first parent's) and upstream's (second parent's)
sets, with no tool and no network:

| action | the set it gives |
| --- | --- |
| `take_local` | the local side's |
| `take_upstream` | upstream's |
| `three_way` | `(B ∩ L ∩ U) ∪ (L − B) ∪ (U − B)`: what both kept, plus what either added |
| `three_way_unified` | `three_way`, then within each package's compatible range only the highest version (`lock_actions.unify`): a semver caret range for Cargo, npm, yarn and pnpm, and the whole package for the one-version ecosystems (poetry, uv, Pipfile, composer, and Gemfile per platform) |

An action **reproduces** a case when its set equals the maintainer's at every one of the case's
conflicted lock files. A case is **covered** when some action reproduces it. An action's
**Jaccard** on a case is the smallest, over the case's conflicted lock files, of
`|A ∩ M| / |A ∪ M|`, with 0 where the action has no set.

The label is computed by `bench.lock_oracle`, at the commit that adds this file.

## 5. Order of work

1. This registration, the power analysis, the code and its tests, committed together.
2. `python -m precondition_library.bench.lock_oracle --out results/lock-oracle-<date>` mines,
   labels and reports every repository of §3.1 in one run, writing `manifest.json`,
   `labels.jsonl`, `report.json` and `summary.txt`.
3. The results are committed as they come out, with any deviation from this text reported in
   their README, never written into this file.

## 6. Metric and analysis

Every figure is a **mean over repositories** of a per-repository mean over its cases, so that a
repository counts once however many cases it gave. Its interval is the **95% t-interval** over
the repositories' means, with repositories − 1 degrees of freedom (`lock_oracle.t_975`).

This replaces study 1's percentile bootstrap over repositories for three reasons:

- coverage varies a great deal between repositories (between-repository SD 0.28 in the pilot),
  so the repository, not the case, is the unit;
- in §8's simulations the t-interval claimed H1 falsely less often than the bootstrap did;
- it has a closed form, so every interval can be re-derived by hand from `report.json`'s
  per-repository counts.

- **H1:** the mean of the repositories' coverages, and its interval.
- **H2:** the mean of the repositories' mean `J(three_way_unified) − J(take_local)`, and the same
  against `take_upstream`, each with its interval.

## 7. Descriptive figures (no hypothesis)

The report also gives:

- the pooled coverage, with each case counted once;
- the share of cases each action reproduces;
- each action's median per-case Jaccard;
- the share of cases study 1's line unions (`real_merges.produced`) reproduce line for line on
  every lock file, for the contrast with §4;
- per lock-file name, how many conflicted files there are and how many some action reproduces.

## 8. Sample size and power

`lock-oracle-power.py` (beside this file; output `lock-oracle-power.json`) simulates this
analysis from the pilot:

- **H1.** Each repository's coverage is drawn from a beta distribution with the pilot's pooled
  mean (0.333) and its between-repository SD (0.284, method of moments), and 15 cases are drawn
  at that rate.
- **H2.** The pilot's repositories and cases are resampled.

Each design has 15 cases per repository, and 2,000 simulated studies (500 for H2 and for the resampled column):

| repositories | H1 power (bound 0.10) | H1 power (bound 0.15) | H1 false support at 0.10, beta / resampled | H2 power |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 0.57 | 0.35 | 0.003 / 0.016 | 0.84 |
| 15 | 0.85 | 0.58 | 0.004 / 0.010 | 0.98 |
| 20 | 0.96 | 0.75 | 0.004 / 0.012 | 1.00 |
| 25 | 0.99 | 0.88 | 0.002 / 0.014 | 1.00 |

H2's false support, with both differences centred on zero, was 0 in every design. A repository
with fewer than 15 cases lowers power below these figures.

- **Targets: at least 150 cases from at least 15 repositories.** Below either, the study is
  underpowered (§9 rule 1).
- **H1's bound is 0.10, not 0.15.** At 15 repositories, 0.15 has power 0.58 against the pilot's
  coverage, and 0.10 has 0.85.
- **Wrong support for H1 stays rare.** When coverage is exactly at the bound, the t-interval
  supports H1 at most 0.4% of the time under the beta model and at most 1.6% when the pilot is
  resampled. The bootstrap does so at most 1.1% and 2.6%.

## 9. Decision rules, in order

1. **Power.** If fewer than 150 cases or fewer than 15 repositories with a case are labelled,
   the study is underpowered. Every estimate is reported, and neither hypothesis is decided.
2. **H1** is supported if its interval's lower end is above 0.10, and not supported otherwise.
3. **H2** is supported if both of its intervals' lower ends are above 0, and not supported
   otherwise.

## 10. Reporting

- `summary.txt` and `report.json` give every figure of §6 and §7, the decisions, the cases and
  exclusions per repository, and each repository's pinned tip.
- `labels.jsonl` gives every case's per-file, per-action result, so each label can be
  re-derived from git with the SHAs in `manifest.json`.
- A finding against a hypothesis is reported as plainly as one for it.

## 11. Feasibility, done before registration

`real-merges-feasibility.py` (study 1's) was run on each candidate. It counts two-parent merges, those whose sides both changed a lock file, and those whose
`git merge-tree` conflict includes one. It never reads a merge commit's own tree, so it saw no
maintainer's resolution.

| repository | two-parent merges | both sides changed a lock file | tried | conflict | includes a lock file | listed |
| --- | ---: | ---: | ---: | ---: | ---: | :---: |
| `phpstan/phpstan-src` | 2187 | 141 | 141 | 119 | 118 | yes |
| `owncloud/core` | 14051 | 98 | 98 | 0 | 0 | no |
| `nextcloud/spreed` | 8579 | 1095 | 400 | 0 | 0 | no |
| `mozilla/pdf.js` | 10102 | 31 | 31 | 0 | 0 | no |
| `huginn/huginn` | 1161 | 59 | 59 | 23 | 16 | yes |
| `diaspora/diaspora` | 4182 | 239 | 239 | 112 | 80 | yes |
| `rubygems/rubygems.org` | 2436 | 329 | 329 | 3 | 3 | no |
| `rust-lang/rustfmt` | 1620 | 18 | 18 | 12 | 7 | yes |
| `rust-lang/docs.rs` | 294 | 8 | 8 | 2 | 2 | no |
| `mastodon/mastodon` | 426 | 1 | 1 | 1 | 0 | no |
| `pterodactyl/panel` | 604 | 19 | 19 | 14 | 10 | yes |
| `BookStackApp/BookStack` | 783 | 20 | 20 | 17 | 17 | yes |
| `nextcloud/deck` | 3144 | 656 | 400 | 0 | 0 | no |
| `getgrav/grav` | 1600 | 78 | 78 | 68 | 58 | yes |
| `nextcloud/text` | 3741 | 682 | 400 | 0 | 0 | no |
| `Textualize/rich` | 1073 | 14 | 14 | 6 | 6 | yes |
| `OpenMage/magento-lts` | 302 | 1 | 1 | 0 | 0 | no |
| `Textualize/textual` | 2364 | 23 | 23 | 20 | 15 | yes |
| `rust-lang/mdBook` | 1061 | 26 | 26 | 0 | 0 | no |
| `rust-lang/rustc-perf` | 1724 | 8 | 8 | 0 | 0 | no |
| `jellyfin/jellyfin-web` | 5233 | 971 | 400 | 3 | 3 | no |
| `rust-lang/rustup` | 1376 | 46 | 46 | 3 | 3 | no |
| `invoiceninja/invoiceninja` | 4744 | 86 | 86 | 70 | 55 | yes |
| `bolt/core` | 2383 | 82 | 82 | 60 | 50 | yes |
| `phpstan/phpstan` | 25 | 0 | 0 | 0 | 0 | no |
| `snipe/snipe-it` | 6775 | 110 | 110 | 73 | 62 | yes |
| `chatwoot/chatwoot` | 272 | 1 | 1 | 1 | 1 | no |
| `rust-lang/crates.io` | 4742 | 647 | 400 | 10 | 10 | yes |
| `openstreetmap/openstreetmap-website` | 3551 | 169 | 169 | 33 | 25 | yes |
| `firefly-iii/firefly-iii` | 3836 | 497 | 400 | 63 | 57 | yes |
| `wallabag/wallabag` | 4469 | 964 | 400 | 5 | 5 | yes |
| `publiclab/plots2` | 321 | 0 | 0 | 0 | 0 | no |
| `feedbin/feedbin` | 402 | 22 | 22 | 13 | 11 | yes |
| `contao/contao` | 2967 | 114 | 114 | 112 | 94 | yes |
| `nightscout/cgm-remote-monitor` | 1897 | 42 | 42 | 34 | 31 | yes |
| `alphagov/publishing-api` | 3788 | 666 | 400 | 0 | 0 | no |
| `python-poetry/poetry-core` | 55 | 0 | 0 | 0 | 0 | no |
| `MagicMirrorOrg/MagicMirror` | 1524 | 35 | 35 | 22 | 17 | yes |
| `otwcode/otwarchive` | 2957 | 78 | 78 | 29 | 16 | yes |
| `ether/etherpad-lite` | 1506 | 6 | 6 | 3 | 2 | no |
| `hedgedoc/hedgedoc` | 2 | 0 | 0 | 0 | 0 | no |
| `node-red/node-red` | 2625 | 11 | 11 | 11 | 11 | yes |
| `webpack/webpack` | 5116 | 814 | 400 | 11 | 9 | yes |
| `zotero/zotero` | 516 | 1 | 1 | 1 | 0 | no |
| `rust-lang/miri` | 15900 | 21 | 21 | 0 | 0 | no |
| `consuldemocracy/consuldemocracy` | 4373 | 296 | 296 | 25 | 18 | yes |
| `laurent22/joplin` | 769 | 63 | 63 | 33 | 23 | yes |
| `processing/p5.js` | 5008 | 70 | 70 | 20 | 9 | yes |
| `nextcloud/calendar` | 3144 | 609 | 400 | 0 | 0 | no |
| `loomio/loomio` | 8047 | 1887 | 400 | 27 | 18 | yes |
| `alphagov/whitehall` | 10782 | 1175 | 400 | 0 | 0 | no |
| `rust-lang/triagebot` | 1921 | 685 | 400 | 0 | 0 | no |
| `nextcloud/mail` | 6878 | 1424 | 400 | 2 | 2 | no |

The 53 candidates were named in three batches, as active projects that commit a lock file and
appeared to merge rather than squash. The second and third batches were added because the earlier
ones yielded too few qualifying repositories. Every candidate named was counted, and every one
counting at least 5 is listed. The counts were taken on 2026-11-02 and are committed beside this
file (`lock-oracle-feasibility.jsonl`).

## 12. What was seen before this registration

- The pilot's 30 stage-A cases, measured package by package, which shaped §4's actions and §8's
  power.
- The feasibility counts in §11.
- Nothing of any listed repository's merged lock files.
