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

**AI-written commits carry the trailer.** Work authored by Claude ends with
`Co-Authored-By: Claude <noreply@anthropic.com>`. Git otherwise records every commit
as the repository owner's, which is not what happened — most of this repository was
written by an agent. The trailer keeps the provenance truthful.

It is attribution, **not** review. A co-authored commit has still had one party
involved, and should not be read as a second pair of eyes.

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

### 5. Status lives in one place

A document must not restate whether something is implemented. It either links to the
declared inventory in `tests/test_declared_state.py` — which CI checks against the
code — or states the claim in that file's claims table, where the fact behind it is
asserted.

**Why:** prose describing the code drifts the moment the code moves, and nothing
fails. Four instances were found by hand: a README rule contradicting its own status
table, the spec saying a rejected program is not stored while `library.py` stores
it, the README claiming the gold check runs while its test is skipped, and a
docstring describing injectors as stubs after they existed.

**Where the line falls.** The rule forbids restating status; it does not forbid
recording it. A document that describes the code **now** must be current, and a
document that records a decision **at a point in time** must not be rewritten.

- **Live documents are kept current.** `README.md`, the spec, module and function
  docstrings, this file, `library/README.md`, `bench/gold/README.md` — anything a
  reader consults to learn what the code does today. When the code moves, correct
  them in place. The spec's "not stored" claim is the worked example: it was
  corrected when `library.py` was found to store candidates, and the correction is
  in the spec's revision history.
- **Records of a time are not.** Merged changelog entries, ADRs, and the merged plan
  documents under `docs/superpowers/plans/` describe a state as it was. A superseded
  record is narrowed by a *new* ADR or changelog entry, never edited. A changelog
  entry whose "Not done in this change" list has since been overtaken is
  deliberately left alone (#57).

**Why the second half matters:** an agent that "fixes" history destroys the record
of the decision it is fixing. Once the entry is rewritten, a reader can no longer
see that the earlier state was chosen, or why it changed — the correction has
removed its own evidence. The current state belongs in a live document; the
decision belongs in the record.

**What that inventory cannot do, and this rule therefore cannot replace:** find a
document that contradicts another document, or one whose meaning contradicts the
code. Those are semantic and remain a review obligation. Pin only claims that reduce
to a mechanical fact; do not add a row that restates a sentence without checking
anything behind it.

### 6. Python in markdown is formatted by CI

`ruff format --check` runs over the Python code inside fenced blocks in committed
markdown, so a snippet in a plan or a spec has to be ruff-clean like any other
code. Two consequences:

- **Complete files** go in a ` ```python ` fence and must be formatted.
- **Fragments** — a few lines lifted from the middle of a file — go in a
  ` ```text ` fence. Ruff will happily reformat a fragment into something that is
  no longer a faithful excerpt, which is worse than no highlighting.

This bit the first version of the issue #3 plan: CI failed on a docs-only PR
because a snippet was four characters over the line limit. That is the system
working — but knowing the rule saves a red build.

### 7. Design reversals get a decision record

Anything that reverses or narrows an earlier decision gets an ADR in
`docs/decisions/`, using `TEMPLATE.md`. The ADR records the alternatives that were
rejected and what would reverse *this* decision — the second part is what makes it
a record rather than a rationalisation. See
[ADR-0001](docs/decisions/ADR-0001-reframe-after-prior-art.md).

### 8. Measurements follow the pre-registration

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

An agent writes most of this repository, so **it must not merge its own work.** The
loop is: the author opens a PR with the self-review checklist filled in, and the
repository owner reviews and merges. A self-reviewed PR is not a review, and
`Co-Authored-By` is attribution rather than a second pair of eyes.

The author's job is to make the review cheap:

- say which decision is most contestable, rather than which parts are done;
- name what was **not** verified, and what was assumed;
- put the evidence in the PR body — the command run and its real output — instead of
  asserting that something works.

A PR that cannot be reviewed by reading it, because a claim is not tied to a check,
is a defect in the PR rather than in the reviewer.

Adding a second human reviewer is still the better version of this, and remains a
settings change plus a name.

## Reporting a citation error

That is the most valuable contribution anyone can make here. Open a defect issue
with the source that contradicts the claim. If the error invalidates a prior-art
conclusion, it may change what the project claims, and that is worth knowing.
