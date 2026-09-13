# Contributing

This is a research repository, so the process exists to protect two things: the
**integrity of the measurements** and the **accuracy of the claims**. Everything
below follows from those.

## The workflow

```
issue  ──▶  branch  ──▶  pull request  ──▶  green CI  ──▶  rebase merge
```

1. **Open an issue first** for anything that changes the design, the claims, or the
   experiment. Use the templates — they ask for the reasoning that a future reader
   will need. Small fixes (a typo, a broken link) can go straight to a PR.
2. **Branch** as `pr/NN-short-slug`, where `NN` is the issue number.
3. **Open the PR** and fill in the template. The self-review checklist is not
   decoration; the "does this change what the experiment measures?" line is the
   most important question in this repository's process.
4. **Wait for CI.** Ruff, `ruff format --check`, mypy, and pytest must pass.
   Run them locally first — CI only re-runs what you already ran.
5. **Rebase merge.** `main` is linear; merge commits are disabled.

Direct pushes to `main` are blocked by branch protection. That applies to the
maintainer too, deliberately.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`docs:`, `chore:`, `test:`, `refactor:`. Write the body for someone reading the
history in two years without the PR open: what changed, and why the alternative
was rejected.

## The rules that are specific to this repository

### 1. A claim may not be stated as a finding

If it was not measured, it is a hypothesis, an intention, or a question — and it
must be written as one. This is not pedantry. The most serious defect found in
this repository so far was a sentence in the spec that stated the project's
central hypothesis in the indicative mood as an accomplished result. It was
caught by review and fixed; do not reintroduce it.

### 2. Every citation is checked against its source

Before a work enters the README or the spec, check the title, authors, venue, and
**each attributed figure** against the source itself. Record the work's status —
peer-reviewed, preprint, or under review — because a preprint is not a result.

If an attribution turns out to be wrong, **correct it in public** rather than
removing it silently. The README keeps a visible record of five wrong
attributions from its first prior-art sweep, and that record is more valuable than
a clean-looking table.

This applies to negative claims too. A previous sweep asserted that a neighboring
repository published "no control arm, no matched-library comparison, and no
mismatch metric"; the repository published both. Verify absences before asserting
them.

### 3. Numbers say where they came from

Any figure in the documentation either cites its source or says which script
produced it. A number with no provenance is a defect.

### 4. Stubs and skips are described as such

If something is not implemented, the documentation must not imply it is. A skipped
test must name the phase that implements it. "Enforced by tests" is false if the
test is skipped — and that exact sentence was a defect here once.

### 5. Design reversals get a decision record

Anything that reverses or narrows an earlier decision gets an ADR in
`docs/decisions/`, using `TEMPLATE.md`. The ADR records the alternatives that were
rejected and what would reverse *this* decision — the second part is what makes it
a record rather than a rationalisation. See
[ADR-0001](docs/decisions/ADR-0001-reframe-after-prior-art.md).

### 6. Measurements follow the pre-registration

Tuning happens on a set disjoint from the evaluation set. Failed runs stay in the
denominator with their cost. Any revision to a pre-registered analysis is logged
in the spec's revision history **before** data exists, never applied silently
afterwards.

## Labels

| label | use |
| --- | --- |
| `design` | architecture and design decisions |
| `methodology` | experimental method, statistics, validity |
| `experiment` | benchmark runs, metrics, ledger |
| `safety` | sandboxing, guards, injection resistance |
| `infra` | CI, tooling, repository plumbing |
| `process` | workflow, templates, review policy |
| `docs` | documentation, spec, ADRs |

## Reviewing

A self-reviewed pull request is **not** a review. If you want genuine review,
raise the required-approval count in the repository settings and add a reviewer —
until then, the process buys scoped diffs, CI gating, and a decision record, and
it should not be described as more than that.

## Reporting a citation error

That is the most valuable contribution anyone can make here. Open a defect issue
with the source that contradicts the claim. If the error invalidates a prior-art
conclusion, it may change what the project claims, and that is worth knowing.
