# Pre-registration: do merges break lock files, and is the ecosystem's check a precondition worth executing? (study 6)

- **Registered:** by the commit that adds this file and its pin in `bench.preregistration`
  (`tool-precondition`). Measuring code calls `preregistration.require("tool-precondition")`
  before it mines anything.
- **Issues:** #297 (external oracles), #306 (the lock-file task from what maintainers do), #294.
- **Decisions behind it:** ADR-0048 (pre-registration), ADR-0056 (study 3), ADR-0058 (study 4),
  ADR-0059 (study 5), ADR-0060 (this design and its size).

## 1. Question

`results/lock-tool-check-2026-11-08/` ran each ecosystem's own consistency check on studies
3–5's conflicted `composer.lock`, `package-lock.json` and `pnpm-lock.yaml` files, after seeing
them (610 files, 45 repository units). It found three things:

- **Merges break lock files.** The merged files failed the check about five times as often as
  the lock files of ordinary commits, each checked in its own tree: 0.14 against 0.03. In 61 of
  the 85 failing merged files, both parents' own files passed. By repository, the merged files
  failed more often than the repository's own base rate in 26 and less often in 2.
- **The check makes a precondition.** Study 5's divergence gate fires the predicted merge only
  where no package diverges. Rule D adds the check where the gate refuses: if exactly one side's
  lock file passes, take that side. That lifted coverage from 0.40 to 0.69 at mismatch 0.32.
- **Its tie-break never lost to "take your own branch".** On the 176 files where a package
  diverged and the check accepted exactly one side, the accepted side was the maintainer's set
  where the first parent's file was not on 20, and never the reverse. That is expected from the
  check's structure, if maintainers' own merged files mostly pass it.

These findings are exploratory. This study tests them on repositories nobody here has mined or
counted:

> **Does resolving a lock-file conflict leave the lock file inconsistent more often than an
> ordinary commit does; is rule D, a dispatcher of two executed checks, still not rarely wrong;
> and does the check's tie-break rarely lose to taking the first parent's file?**

## 2. Hypotheses

The unit is a conflicted lock file the check exists for (§4). Per repository:

- **g**, for H1: the share of its merged files the check rejects, minus the share of its
  ordinary commits' lock files the check rejects in their own trees (§4). A figure needs at
  least one judged merged file and one judged ordinary check.
- **m_D**, for H2: rule D's wrong fires over its fires.

| | statistic | prediction |
| --- | --- | --- |
| **H1 (primary)** | mean g over repositories | above 0: merges leave lock files inconsistent more often than ordinary commits |
| **H2** | mean m_D over repositories where rule D fires | above 0.10: rule D is not rarely wrong |
| **H3** | pooled over the tie-break files (§4): the share where the first parent's file is the maintainer's set and the accepted side's is not | its Wilson upper bound below 0.10: the tie-break rarely loses |

**H2 is expected to be supported**, as study 5's H1 was. It is registered so that the best rule
found so far is held to the same bar, "rarely mis-fires", on fresh data. **H1 and H3 are the
claims that could fail.** H1 would fail if the exploratory gap came from a few repositories'
habits, or from the studies' conflicted merges being unusual. H3 would fail if maintainers here
commit inconsistent merges where a side would have passed.

## 3. Cases

### 3.1 Repositories

The study mines these repositories in this order. None was mined, labelled or counted by this
project before. None is on any earlier study's lists or among the candidates their counts
touched; a test checks this. Each was chosen from the feasibility count in §11, which reads no
merge commit's own tree.

| | repository | conflicts with a checked lock file, binary aside | `composer.lock` | `package-lock.json` | `pnpm-lock.yaml` |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | `appwrite/appwrite` | 320+ | 318 | 0 | 2 |
| 2 | `filamentphp/filament` | 109 | 69 | 51 | 0 |
| 3 | `woocommerce/woocommerce` | 106 | 51 | 45 | 16 |
| 4 | `thorsten/phpMyFAQ` | 95 | 87 | 0 | 60 |
| 5 | `activepieces/activepieces` | 89+ | 0 | 89 | 0 |
| 6 | `akeneo/pim-community-dev` | 86 | 86 | 1 | 0 |
| 7 | `Infisical/infisical` | 61 | 0 | 61 | 0 |
| 8 | `louislam/uptime-kuma` | 60 | 0 | 60 | 0 |
| 9 | `nocodb/nocodb` | 52 | 0 | 42 | 10 |
| 10 | `TriliumNext/Notes` | 52+ | 0 | 34 | 18 |
| 11 | `ToolJet/ToolJet` | 45 | 0 | 45 | 0 |
| 12 | `Hubs-Foundation/hubs` | 35 | 0 | 37 | 0 |
| 13 | `hoppscotch/hoppscotch` | 33 | 0 | 13 | 20 |
| 14 | `umami-software/umami` | 30 | 0 | 0 | 30 |
| 15 | `Sylius/Sylius` | 24 | 24 | 0 | 0 |
| 16 | `cryptpad/cryptpad` | 18 | 0 | 18 | 0 |
| 17 | `firefly-iii/data-importer` | 18 | 14 | 8 | 0 |
| 18 | `statamic/cms` | 18 | 0 | 18 | 0 |
| 19 | `payloadcms/payload` | 17 | 0 | 2 | 15 |
| 20 | `SuiteCRM/SuiteCRM-Core` | 15 | 15 | 0 | 0 |
| 21 | `formbricks/formbricks` | 14 | 0 | 0 | 14 |
| 22 | `ampache/ampache` | 13 | 15 | 2 | 0 |
| 23 | `nextcloud/nextcloud-vue` | 13+ | 0 | 13 | 0 |
| 24 | `SolidInvoice/SolidInvoice` | 13 | 13 | 0 | 0 |
| 25 | `Ctrlpanel-gg/panel` | 12 | 10 | 3 | 0 |

A candidate is eligible when the count found at least 5 merges whose conflict includes a
checked lock file, binary conflicts aside, and no earlier study counted it. Of the eligible
candidates, the 25 with the most such merges are listed, largest first, ties by name. A `+`
marks a count that stopped at the script's limit of 400 tried merges. The three columns by kind
count every such conflict, binary ones included, and one conflict can include more than one kind.

### 3.2 Cases, the cap and exclusions

Study 3's mining and labels (`lock_oracle.label_repository` over `real_merges.mine`), with two
changes made before labelling, so neither takes a place under the cap:

- **A case's conflict must include a checked lock file** (`composer.lock`, `package-lock.json`
  or `pnpm-lock.yaml`). Other cases are left out.
- **A case is left out if a conflicted checked lock file has a `merge` attribute at the first
  parent**, as `git check-attr --source=<first parent> merge` reports it. That is
  `results/mining-attributes-2026-11-08/`'s recommendation: a maintainer's working tree would not
  have merged that file as text. Each one is recorded.

Otherwise as study 3:
- criss-cross merges and submodule or binary conflicts are excluded;
- a repository's cases are labelled from its most recent merge back, until 15 are labelled;
- a case whose maintainer's merged lock file cannot be read is passed over and recorded.

## 4. Checks, labels and rules

- **The checks** are `bench.lock_check`'s, the code the exploratory run used, made a library.
  None installs a package or runs a package's or project's code.
  - **npm:** `npm ci --dry-run --ignore-scripts --engine-strict=false`, which refuses with
    `EUSAGE` when the lock file and `package.json` are out of sync.
  - **pnpm:** `pnpm install --frozen-lockfile --lockfile-only --ignore-scripts`, with the pnpm the
    tree's `package.json` declares, or 10.28.0. It refuses for an outdated lock file, or one
    written under other settings.
  - **Composer:** offline. `composer install --dry-run --ignore-platform-reqs` judges whether the
    locked set satisfies every root requirement, and `composer validate` reads the content-hash
    (descriptive only).

  A verdict is consistent, inconsistent, or an error (the tool failed for another reason).
  Errors are left out of every share.
- **In the merge's tree**, as committed (`lock_actions._checkout`), the check judges three lock
  files at the conflicted path: the maintainer's merged file, the first parent's and the second
  parent's.
- **In their own trees**, it judges the first parent's, the second parent's and the merge base's
  lock file at that path, each in its own commit's tree. These are the **ordinary checks** of H1.
- **Labels:** each conflicted lock file is read into its set of `(package, version)` pairs, as in
  study 3 §4. A side is *the maintainer's set* when its file's set equals the merged file's
  (`take_local`, `take_upstream`).
- **Divergence and the predicted merge** are study 5's (§4 there): a package diverges when both
  sides changed its versions, to different versions. The predicted merge is study 4's.
- **The accepted side:** both sides' files were judged, and exactly one passed.
- **Rule D:** where no package diverges, fire the predicted merge. Otherwise, fire the accepted
  side if there is one. Otherwise, refuse. A fire is right when its resolution is the
  maintainer's set.
- **The tie-break files** (H3): a package diverges, and there is an accepted side. A *reverse* is
  a tie-break file whose first parent's file is the maintainer's set and whose accepted side's is
  not.

`bench.tool_precondition` computes everything at the commit that adds this file. Run on the
exploratory data, it reproduces every figure of `results/lock-tool-check-2026-11-08/`.

## 5. Order of work

1. This registration, the power analysis, the feasibility count, the code and its tests, committed
   together.
2. `python -m precondition_library.bench.tool_precondition --out results/tool-precondition-<date>
   --scratch <dir>` mines, labels, checks and reports every repository of §3.1 in one run.
3. The results are committed as they come out, with any deviation reported in their README,
   never written into this file.

## 6. Analysis

- **H1 and H2:** the mean over the repositories that have the figure, with a 95% t-interval over
  them (study 3's analysis, `lock_oracle.t_975`).
- **H3:** the Wilson 95% interval of the reverse share, pooled over the tie-break files. Pooling
  ignores that files cluster in repositories. With few or no reverses, that matters little, and
  the repositories holding any reverse are reported.

## 7. Descriptive figures (no hypothesis)

The report also gives:

- every rule of `results/lock-tool-check-2026-11-08/dispatch.py`, pooled over files, with Wilson
  intervals:
  - A, the merge always;
  - B, the gate;
  - C, the accepted side;
  - D;
  - F, the control: the gate's merge, else the first parent's file;
- on the tie-break files, the accepted side against the first parent's file: files where only one
  is right, each way, and the exact McNemar test;
- per tool, the rejected merged files and the rejected ordinary checks;
- of the rejected merged files: those whose parents' own files both passed, and those where one
  failed;
- Composer's stale content-hash, merged against ordinary;
- the reverse share's reading at 0.05.

## 8. Sample size and power

`tool-precondition-power.py` (beside this file; output `tool-precondition-power.json`) simulates
this analysis. It resamples the exploratory data's 45 repository units. In the null worlds:

- **H1:** within each repository, the merged and ordinary checks are permuted together;
- **H2:** every one of rule D's fires is wrong with probability exactly 0.10;
- **H3:** each tie-break file is a reverse with probability exactly 0.10.

It ran 2,000 simulated studies per design:

| repositories | H1 power | H2 power | H3 power | false support, H1 / H2 / H3 |
| ---: | ---: | ---: | ---: | ---: |
| 12 | 0.64 | 0.89 | 0.78 | 0.006 / 0.010 / 0.011 |
| 15 | 0.76 | 0.97 | 0.94 | 0.006 / 0.006 / 0.017 |
| 20 | 0.89 | 1.00 | 0.99 | 0.009 / 0.007 / 0.019 |
| 25 | 0.95 | 1.00 | 1.00 | 0.010 / 0.008 / 0.015 |

- **25 repositories, and at least 15 with each figure.** At 25, H1 has power 0.95, and H2 and
  H3 about 1. Twenty-five leave room for repositories whose mining yields too few cases.
- **H3's bound is 0.10, not 0.05.** At 0.05, power depends on how many tie-break files the
  mining yields: 0.88 at 25 repositories, but 0.60 at 20 and 0.20 at 15. Zero reverses among
  20 repositories' 77 or so files still leave the Wilson upper bound near 0.05. The 0.05 reading
  is reported as a description.

## 9. Decision rules, in order

1. **Power.** If fewer than 15 repositories have H1's figure, or fewer than 15 have H2's, the
   study is underpowered. Every figure is reported, and no hypothesis is decided.
2. **H1** is *supported* if its interval's lower end is above 0. If its upper end is below 0,
   merges left lock files consistent more often than ordinary commits, and that is reported.
   Otherwise it is *not supported*.
3. **H2** is *supported* if its interval's lower end is above 0.10. If its upper end is below
   0.10, it is *not supported* and the finding is stated: rule D is rarely wrong. Otherwise it is
   *not supported*.
4. **H3** is *supported* if the Wilson upper bound is below 0.10, on at least 20 tie-break files.
   On fewer it is *not decided*. Otherwise it is *not supported*.

## 10. Reporting

- `summary.txt` and `report.json` give every figure of §6 and §7 and the decisions.
- `labels.jsonl` gives every case's per-file, per-action result. `files.jsonl` gives every checked
  file's verdicts, divergence and labels. Both can be re-derived from git with the SHAs in
  `manifest.json`. `manifest.json` also lists each case left out, and why. No package name is
  written.
- A result against a hypothesis is reported as plainly as one for it.

## 11. Feasibility, done before registration

`tool-precondition-feasibility.py` (beside this file) is study 5's count, restricted to the three
checked lock files. It counts:

- two-parent merges;
- those whose sides both changed the same checked lock file;
- those whose `git merge-tree` conflict includes one, by kind;
- those of them that git calls binary.

Its clone has a HEAD, so git applies HEAD's `.gitattributes`, which mining does not (§3.2). It
never reads a merge commit's own tree. The counts are committed beside this file
(`tool-precondition-feasibility.jsonl`).

| repository | two-parent merges | both sides changed a checked lock file | tried | conflict includes one | `composer.lock` | `package-lock.json` | `pnpm-lock.yaml` | binary | listed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| `openemr/openemr` | 512 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | no |
| `appwrite/appwrite` | 14825 | 1859 | 400 | 320 | 318 | 0 | 2 | 0 | yes |
| `pimcore/pimcore` | 3035 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `Sylius/Sylius` | 14306 | 31 | 31 | 24 | 24 | 0 | 0 | 0 | yes |
| `shopware/shopware` | 14440 | 35 | 35 | 9 | 0 | 9 | 0 | 0 | no: outside the 25 |
| `flarum/framework` | 577 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | no |
| `statamic/cms` | 588 | 36 | 36 | 18 | 0 | 18 | 0 | 0 | yes |
| `LimeSurvey/LimeSurvey` | 2969 | 8 | 8 | 7 | 4 | 3 | 0 | 4 | no |
| `opensourcepos/opensourcepos` | 453 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | no |
| `librenms/librenms` | 2885 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | no |
| `phpipam/phpipam` | 618 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `FOSSBilling/FOSSBilling` | 872 | 59 | 59 | 12 | 10 | 2 | 0 | 0 | no: outside the 25 |
| `ampache/ampache` | 1555 | 26 | 26 | 15 | 15 | 2 | 0 | 2 | yes |
| `shlinkio/shlink` | 1044 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `roundcube/roundcubemail` | 635 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `filamentphp/filament` | 7928 | 182 | 182 | 109 | 69 | 51 | 0 | 0 | yes |
| `nextcloud/tasks` | 2178 | 779 | 400 | 1 | 0 | 1 | 0 | 0 | no |
| `nextcloud/cookbook` | 1620 | 210 | 210 | 6 | 0 | 6 | 0 | 0 | no: outside the 25 |
| `nextcloud/viewer` | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/tables` | 1285 | 217 | 217 | 5 | 0 | 5 | 0 | 0 | no: outside the 25 |
| `nextcloud/bookmarks` | 684 | 173 | 173 | 4 | 0 | 4 | 0 | 0 | no |
| `nextcloud/maps` | 776 | 167 | 167 | 9 | 2 | 8 | 0 | 0 | no: outside the 25 |
| `nextcloud/circles` | 913 | 49 | 49 | 1 | 0 | 1 | 0 | 0 | no |
| `nextcloud/user_oidc` | 1025 | 145 | 145 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/notifications` | 1975 | 199 | 199 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/end_to_end_encryption` | 1005 | 172 | 172 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/twofactor_webauthn` | 1175 | 365 | 365 | 0 | 0 | 0 | 0 | 0 | no |
| `nocodb/nocodb` | 6576 | 170 | 170 | 52 | 0 | 42 | 10 | 0 | yes |
| `hoppscotch/hoppscotch` | 1042 | 68 | 68 | 33 | 0 | 13 | 20 | 0 | yes |
| `ToolJet/ToolJet` | 4099 | 136 | 136 | 45 | 0 | 45 | 0 | 0 | yes |
| `documenso/documenso` | 472 | 15 | 15 | 4 | 0 | 4 | 0 | 0 | no |
| `mattermost/mattermost` | 2417 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | no |
| `wekan/wekan` | 2513 | 114 | 114 | 7 | 0 | 7 | 0 | 0 | no: outside the 25 |
| `umami-software/umami` | 1885 | 39 | 39 | 30 | 0 | 0 | 30 | 0 | yes |
| `logto-io/logto` | 820 | 81 | 81 | 5 | 0 | 0 | 5 | 0 | no: outside the 25 |
| `payloadcms/payload` | 1497 | 46 | 46 | 17 | 0 | 2 | 15 | 0 | yes |
| `formbricks/formbricks` | 394 | 28 | 28 | 14 | 0 | 0 | 14 | 0 | yes |
| `Infisical/infisical` | 6939 | 218 | 218 | 61 | 0 | 61 | 0 | 0 | yes |
| `directus/directus` | 653 | 24 | 24 | 11 | 0 | 7 | 4 | 0 | no: outside the 25 |
| `nextcloud/nextcloud-vue` | 5648 | 1218 | 400 | 13 | 0 | 13 | 0 | 0 | yes |
| `nextcloud/recognize` | 301 | 43 | 43 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/password_policy` | 485 | 57 | 57 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/logreader` | 941 | 174 | 174 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/firstrunwizard` | 1163 | 137 | 137 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/privacy` | 733 | 243 | 243 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/suspicious_login` | 537 | 104 | 104 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/app_api` | 295 | 24 | 24 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/assistant` | 346 | 7 | 7 | 1 | 1 | 0 | 0 | 0 | no |
| `nextcloud/whiteboard` | 998 | 303 | 303 | 0 | 0 | 0 | 0 | 0 | no |
| `nextcloud/integration_openai` | 197 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `owncloud/web` | 5409 | 511 | 400 | 0 | 0 | 0 | 0 | 0 | no |
| `firefly-iii/data-importer` | 1116 | 215 | 215 | 18 | 14 | 8 | 0 | 0 | yes |
| `solidtime-io/solidtime` | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no: counted by an earlier study |
| `InvoicePlane/InvoicePlane` | 465 | 6 | 6 | 4 | 4 | 0 | 0 | 0 | no |
| `shaarli/Shaarli` | 1017 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `SuiteCRM/SuiteCRM-Core` | 33 | 15 | 15 | 15 | 15 | 0 | 0 | 0 | yes |
| `unopim/unopim` | 261 | 15 | 15 | 1 | 1 | 0 | 0 | 0 | no: counted by an earlier study |
| `misskey-dev/misskey` | 2721 | 5 | 5 | 2 | 0 | 0 | 2 | 0 | no |
| `bitwarden/clients` | 531 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | no |
| `Kong/insomnia` | 392 | 28 | 28 | 11 | 0 | 11 | 0 | 0 | no: outside the 25 |
| `mozilla/addons-frontend` | 1383 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `decidim/decidim` | 31 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `LemmyNet/lemmy-ui` | 576 | 3 | 3 | 1 | 0 | 0 | 1 | 0 | no |
| `MISP/MISP` | 8171 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `tastyigniter/TastyIgniter` | 142 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `woocommerce/woocommerce` | 11999 | 319 | 319 | 107 | 51 | 45 | 16 | 1 | yes |
| `akeneo/pim-community-dev` | 14695 | 121 | 121 | 87 | 86 | 1 | 0 | 1 | yes |
| `chamilo/chamilo-lms` | 8740 | 7 | 7 | 2 | 2 | 0 | 0 | 1 | no |
| `thorsten/phpMyFAQ` | 754 | 100 | 100 | 95 | 87 | 0 | 60 | 0 | yes |
| `omeka/omeka-s` | 939 | 7 | 7 | 4 | 3 | 2 | 0 | 0 | no |
| `LibreBooking/librebooking` | 348 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `HiEventsDev/hi.events` | 326 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | no |
| `Paymenter/Paymenter` | 158 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | no |
| `Ctrlpanel-gg/panel` | 794 | 15 | 15 | 12 | 10 | 3 | 0 | 0 | yes |
| `Koillection/Koillection` | 427 | 6 | 6 | 3 | 3 | 0 | 0 | 0 | no |
| `alexjustesen/speedtest-tracker` | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `SolidInvoice/SolidInvoice` | 263 | 20 | 20 | 13 | 13 | 0 | 0 | 0 | yes |
| `linuxserver/Heimdall` | 330 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `louislam/uptime-kuma` | 1486 | 104 | 104 | 60 | 0 | 60 | 0 | 0 | yes |
| `Fallenbagel/jellyseerr` | 233 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `morpheus65535/bazarr` | 685 | 6 | 6 | 3 | 0 | 3 | 0 | 0 | no |
| `blakeblackshear/frigate` | 63 | 3 | 3 | 2 | 0 | 2 | 0 | 0 | no |
| `Koenkk/zigbee2mqtt` | 209 | 10 | 10 | 7 | 0 | 7 | 0 | 0 | no: outside the 25 |
| `homebridge/homebridge` | 338 | 10 | 10 | 4 | 0 | 4 | 0 | 0 | no |
| `homebridge/homebridge-config-ui-x` | 419 | 22 | 22 | 1 | 0 | 1 | 0 | 0 | no |
| `Hubs-Foundation/hubs` | 3200 | 161 | 161 | 37 | 0 | 37 | 0 | 2 | yes |
| `zadam/trilium` | 6951 | 2381 | 400 | 8 | 0 | 0 | 8 | 0 | no: outside the 25 |
| `TriliumNext/Notes` | 2132 | 529 | 400 | 52 | 0 | 34 | 18 | 0 | yes |
| `cryptpad/cryptpad` | 3791 | 74 | 74 | 18 | 0 | 18 | 0 | 0 | yes |
| `owncast/owncast` | 159 | 20 | 20 | 10 | 0 | 10 | 0 | 0 | no: outside the 25 |
| `navidrome/navidrome` | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no |
| `openreplay/openreplay` | 688 | 8 | 8 | 2 | 0 | 2 | 0 | 0 | no |
| `activepieces/activepieces` | 9876 | 463 | 400 | 89 | 0 | 89 | 0 | 0 | yes |
| `homarr-labs/homarr` | 247 | 5 | 5 | 4 | 0 | 0 | 4 | 0 | no |
| `photoprism/photoprism` | 285 | 4 | 4 | 2 | 0 | 2 | 0 | 0 | no |
| `thelia/thelia` | 2061 | 10 | 10 | 10 | 10 | 0 | 0 | 0 | no: outside the 25 |

The counts were taken on 2026-11-09.

## 12. What was seen before this registration

- Studies 3–5's labels, their anatomy and `results/lock-tool-check-2026-11-08/`, which motivated
  the question and sized §8.
- The feasibility counts in §11.
- Nothing of any listed repository's merged lock files.
