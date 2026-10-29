# Pre-registration: refusal over a population of builds (study 2)

- **Registered:** by the commit that adds this file and its pin in `bench.preregistration`
  (`refusal-population`). Measuring code calls `preregistration.require("refusal-population")`
  before it mines or decides anything.
- **Issues:** #307 (a population of builds, refusal-tested admission), #295 (controls), #294.
- **Decisions behind it:** ADR-0048 (pre-registration), ADR-0052 (study 1's outcome), ADR-0053
  (this design and its size).

## 1. Question

Study 1 (`docs/preregistration/real-merges.md`) found that on real lock-file merges, arm 3's
advantage over reading the state is not in what it fires but in what it declines. Exploratory
after-the-fact analysis supports this. A control given arm 3's scope is right on clean merges as
often as arm 3. But it fires on every conflict that no resolution can express, where two of three
libraries mostly declined (`results/real-merges-2026-10-26/stage-B/library-control-exploratory/`).
That analysis tests nothing, and it rests on three builds that behaved very differently.

This study asks the question again on cases nobody has seen, over a population of builds:

> **On real conflicts that no resolution can express, does executable-precondition dispatch
> decline more often than a state-reading control that was given the same evidence, and does
> admitting only programs that decline known such conflicts make it decline more?**

## 2. Hypotheses

Write `f(x)` for a dispatcher's **fire rate on the evaluation set's inexpressible conflicts**: the
share of those cases on which it fires anything. Lower is better, since nothing is right on them.

- **H1 (primary).** Builds with refusal-tested admission (configuration R, §5) fire less on
  inexpressible conflicts than Control-R, the state reader given the same refusal evidence:
  `mean over R's builds of f(Control-R) − f(build) > 0`.
- **H2 (secondary).** Builds with the current admission (configuration 0) fire less than Control-0,
  the state reader fitted as study 1 fitted it: `mean over 0's builds of f(Control-0) − f(build) > 0`.
- **H3 (secondary).** Refusal-tested admission lowers the fire rate:
  `mean f(0's builds) − mean f(R's builds) > 0`.
- **H4 (guard, non-inferiority).** Refusal-tested admission does not cost clean merges. Configuration
  R's right-fire rate on clean evaluation cases is not lower than configuration 0's by more than
  0.10.

Each null is no difference. Only H1 can license a sentence saying executing checks declines
better than reading the state, because only H1 gives both sides the same evidence. H2 repeats
study 1's comparison on new cases. H3 and H4 are about the admission rule, not about
executability.

## 3. Cases

### 3.1 Repositories

Repositories are taken from these lists, in order, and nowhere else. None was listed, mined,
counted (study 1's §11) or used as a host base by any earlier study or stage. A repository is pinned at its default
branch's tip on the day it is first mined, and its history is read up to that commit only.

**Admission (A): the refusal set's source.**

1. [`matomo-org/matomo`](https://github.com/matomo-org/matomo)
2. [`saleor/saleor`](https://github.com/saleor/saleor)
3. [`openfoodfoundation/openfoodnetwork`](https://github.com/openfoodfoundation/openfoodnetwork)
4. [`RocketChat/Rocket.Chat`](https://github.com/RocketChat/Rocket.Chat)

**Evaluation (E), in order:**

1. [`openproject/openproject`](https://github.com/openproject/openproject)
2. [`PrestaShop/PrestaShop`](https://github.com/PrestaShop/PrestaShop)
3. [`home-assistant/frontend`](https://github.com/home-assistant/frontend)
4. [`rust-lang/rust-analyzer`](https://github.com/rust-lang/rust-analyzer)
5. [`getredash/redash`](https://github.com/getredash/redash)
6. [`zellij-org/zellij`](https://github.com/zellij-org/zellij)
7. [`forem/forem`](https://github.com/forem/forem)
8. [`zulip/zulip`](https://github.com/zulip/zulip)
9. [`lapce/lapce`](https://github.com/lapce/lapce)
10. [`magento/magento2`](https://github.com/magento/magento2)
11. [`microsoft/vscode`](https://github.com/microsoft/vscode)
12. [`elastic/kibana`](https://github.com/elastic/kibana)

None of these has been looked at for merge commits or lock files. Some may yield nothing, as five
of study 1's did. Only SHAs and derived labels are committed, never the repositories' content.

### 3.2 Cases and labels

A **conflicted case**, a **clean case**, the state built for each, the exclusions and the labels
are exactly study 1's, with Amendment 1 in force: §3.2–§3.5, §4, A1 and A2. The lock-file intent
is `sync_through_a_conflicting_lockfile`, as it stands at registration. An **inexpressible
conflict** is a conflicted case whose acceptable set is empty.

### 3.3 The refusal set R

The inexpressible conflicts of the admission repositories, at most 10 per repository and the most
recent first, until there are 40 or list A is exhausted. R is mined, labelled and frozen before
any build runs. It is never part of the evaluation.

### 3.4 The evaluation set

Mined from list E, in order, only after all 20 libraries (§5) are built and frozen. Mining stops
once there are **at least 100 inexpressible conflicts and at least 60 clean cases from at least 6
repositories with a case**. No repository may contribute more than 25% of the cases. Past that
share, the most recent cases are kept, conflicted and clean in equal number. If list E runs out
first, the study is **underpowered** (§8).

## 4. Order of work

1. Commit this registration and its pin.
2. Implement the study's code, in a separate change that reviewers can read before any build:
   the build ordering, refusal-tested admission, Control-R, the runner and the tests.
3. Mine and freeze R (§3.3).
4. Build the 20 libraries (§5) and freeze them.
5. Fit both controls (§6).
6. Mine the evaluation set (§3.4), decide every case with every library and both controls, and
   label every case.
7. Apply §9's rules in order and report as §10 says.

## 5. The population of builds

Each build runs `bench.live --primary-only`: the admit set (ADR-0032), the model and settings as
committed at step 2, and temperature 0, recorded per episode. **Build `b`** (0–9) permutes the order
of the admit-set plan with a seeded shuffle of seed `b`: the order of resolutions, and the order
of seeds within each resolution. It records the permutation, every model call's metadata and the
code's commit. A build that fails for a reason outside the method (a provider error, an
interruption) is resumed. If it cannot be completed, the next index (10, 11, 12) replaces it.
Each replacement and its reason are reported.

- **Configuration 0:** the two-sided admission gate as committed. Builds 0–9.
- **Configuration R:** the same gate, and a program is admitted only if its preconditions refuse
  every state in R, that is, at least one precondition does not hold on each. Builds 0–9, with the
  same permutations as configuration 0. So configuration R differs from 0 in the rule, and in what
  follows from it. A candidate the rule rejects sends the build to that resolution's next seed
  (ADR-0032), so the two configurations may run different episodes. Beyond that, differences in
  what the model wrote come from nondeterminism at temperature 0, not from the order.

A build that admits no program is a valid build: it declines everything.

## 6. Dispatchers

- **Arm 3**, each of the 20 libraries: fires the first program whose preconditions accept the
  state, as study 1 did.
- **Control-0:** `StateClassifier.decide_library`, the library-scoped state reader. It is fitted
  as study 1 fitted the registered control, on the build's 56 synthetic states.
- **Control-R:** the same, fitted on those 56 states plus the observed states of R, each labelled
  "fire nothing" for every intent. It gets exactly the refusal evidence configuration R's
  admission gets.

Neither control varies by build. Neither is refit on evaluation data.

## 7. Metric and analysis

- **Fire rate** `f`: fires over inexpressible evaluation conflicts.
- **Right-fire rate on clean cases**: right fires over clean evaluation cases.
- **The interval:** every hypothesis's statistic gets a **95% two-level bootstrap**. Each of
  2000 resamples (seed 0) resamples evaluation repositories with replacement (the cases are
  clustered by repository) and, independently, the configuration's builds with replacement.
  - H1 and H2 are supported if the interval's lower bound is above 0.
  - H3 is supported if its lower bound is above 0.
  - H4 holds if the lower bound of `right-fire(R) − right-fire(0)` is above −0.10.
- **Reported beside each interval, without overruling it:**
  - each build's own `f`, its difference from the control, and that difference's
    repository-clustered interval;
  - how many builds individually beat the control.

**Spread** is reported in each configuration: the standard deviation, range and interquartile
range of `f` across builds. It is #307's core quantity, and it is not tested.

## 8. Sample size and power

The power is set by the spread between builds more than by the number of cases. Study 1's three
builds fired on 22%, 6% and 82% of the inexpressible conflicts, a standard deviation of about
0.4. With 10 builds, a mean difference's interval has a half-width of about
`2.26 × 0.4 / √10 ≈ 0.29` from builds alone. Cases add to that.

- **H1 and H2** can detect a mean difference of about 0.3 or more. The control in study 1 fired on
  99% of these cases, so that is a modest bar for H2. For H1 it is not, because Control-R is
  trained to decline them.
- **H3** compares two groups of 10 and can detect about 0.4.

These are stated so a null result is read for what it is: a difference below these sizes may be
real and undetected. The owner set the size at 10 builds per configuration (ADR-0053), for cost.
Each past build used about 150–200k uncached input, 300–370k cached input and 400–540k output
tokens.

**Underpowered.** If the evaluation set falls short of §3.4's targets, or fewer than 8 valid builds
complete in either configuration, every figure is reported and no hypothesis is called supported
or refuted.

## 9. Decision rules, in order

1. **Power.** If the study is underpowered (§8), stop here: report, decide nothing.
2. **Applicability.** If every build in a configuration fires on no evaluation case at all, that
   configuration's hypotheses are not tested. The finding is that its libraries do not transfer
   to these repositories.
3. **H1.** If its lower bound is at or below 0, executing checks does not decline better than a
   state reader given the same evidence, and that is the primary result.
4. **H2.** Supported or not, as §7 says.
5. **H3** and **H4**, together. If H3 is supported and H4 fails, the finding is that refusal-tested
   admission buys declining at the cost of clean merges, and both halves are reported.

## 10. Reporting

`results/refusal-population-<date>/` holds:

- the manifests of R and of the evaluation set, with each repository's URL, tip, licence and
  per-repository counts, and each exclusion's reason;
- each build's record: its configuration, index, permutation, the code's commit, its admitted
  programs, and its token use;
- every dispatcher's decision on every evaluation case, and every label;
- each hypothesis's statistic, interval and per-build figures, and §9's decisions in order;
- an independent recomputation of every figure from those files, by code that does not import
  the project, as study 1's `verification/` did;
- the deviations: anything done differently from this document, with its reason.

## Amendments

None.
