# The technical report, and how to submit it

`main.tex` is a technical report on the project's results:

- the measurement design, with its definitions, matching rule, floor and seed blocks, and the
  derivation of the smallest detectable difference;
- the synthetic primary result and why it is not the result;
- study 1 on real lock-file merges, including the falsified claim;
- studies 3 and 4, an external oracle for real lock-file conflicts read as package sets, with the
  anatomy of a conflict and the mismatch of rules a dispatcher could deploy;
- the graders' mutation testing, survivor by survivor;
- a Monte Carlo power analysis of study 2's registered tests;
- a comparison with executability gating and retrieval-risk work;
- a discussion: what executing a check buys, where wrong fires come from, threats to validity.

It has no BibTeX step. Its figures are in `figures/`, drawn from committed result files by
`analysis/figures.py`. The power analysis is `analysis/power.py`, and its output is
`analysis/power.json`:

```bash
python paper/analysis/power.py --out paper/analysis     # about two minutes
python paper/analysis/figures.py --out paper/figures
python paper/analysis/tables.py --out paper/tables
```

## Build it

```bash
cd paper
cp author.example.tex author.tex   # then put your name, affiliation and email in author.tex
latexmk -pdf main.tex
```

`author.tex` is ignored by git, so your name and email never enter the repository's history. Without
it, the build falls back to the placeholder in `author.example.tex`.

`./package.sh` builds the PDF and writes `arxiv-upload.tar.gz` with `main.tex`, `author.tex`,
`author.example.tex` and the figures, the files arXiv compiles. Both the PDF and the tarball are ignored by git.

## What only you can do

Submitting is an act of authorship, so it has to be done by you, from your own account:

1. **An arXiv account.** Register at arxiv.org with your real name and the email you want on the
   paper. Confirm the email.
2. **An endorsement.** A first submission to a category needs an endorsement from an established
   arXiv author in that category. Since 21 January 2026, an institutional email address alone no
   longer qualifies a new author. When you start a submission to cs.SE, arXiv gives you an
   endorsement code to send to a potential endorser: someone who has published in cs.SE, for example
   an author of work this report cites, or a researcher you know. Ask politely and include the PDF.
3. **The submission.** Upload `arxiv-upload.tar.gz` and check arXiv's rendered PDF page by page. Fill
   in the metadata below, choose a licence (CC BY 4.0 is common, and it allows reuse with credit),
   and certify that you are the author and have the right to submit.
4. **After announcement.** Add the arXiv identifier to the README.

## Metadata to paste

- **Title:** Executable Preconditions versus Text Similarity for Replaying Compiled Agent Programs:
  A Pre-registered Test on Real Lock-file Merges
- **Primary category:** cs.SE (Software Engineering). **Cross-list:** cs.AI.
- **Comments:** 38 pages, 3 figures, 22 tables. Code, data, dataset and pre-registrations:
  https://github.com/Shyboy0499/precondition-library
- **Abstract:** the abstract in `main.tex`, without LaTeX markup, as below. It is 1,788 characters, within arXiv's limit of 1,920.

  > Agents that compile solved tasks into reusable programs must decide when to replay one. We
  > compare executable preconditions, shell probes that must hold on the live state, with text
  > similarity between the request and a program's description, at matched coverage. On states our
  > own injectors built for five git maintenance faults, precondition dispatch mis-fired on 0 of
  > 563 fires while three text scorers mis-fired on 71-90%, but a tree reading only the state
  > matched it. A pre-registered test on 274 real lock-file merges from 11 repositories, labelled
  > by what maintainers committed, falsified the claim that precondition dispatch rarely mis-fires
  > (wrong on 62/150, 10/122 and 132/244 fires): its line-level resolutions expressed 1 of 161
  > maintainer resolutions. Four more registered studies, on 92 fresh repositories, read lock
  > files as package sets. An action computed from a merge's three sides reproduces the maintainer
  > on 0.69 and 0.76 of conflicts, against 0.07 for line unions; firing it only when no package
  > diverges, itself a precondition, roughly halves its mismatch but not below 0.10 (0.35 [0.18,
  > 0.53]); and merges leave lock files inconsistent more often than ordinary commits (0.067
  > [0.003, 0.130]). A registered study of 20 builds on 209 more merges tested refusal: how often
  > a build fires on conflicts nothing can resolve ranges from 1% to 100%, and a state reader
  > given the same refusal evidence declines about as often (primary hypothesis not supported,
  > 0.060 [-0.009, 0.153]). What decided the outcome was the action space and giving the decision
  > the state, not executing checks. We release 1,559 real lock-file conflicts from 109
  > repositories, labelled by maintainers' commits, and lockmerge, a merge driver built on these
  > results. We also mutation-test the graders.

## Zenodo, with or without an endorsement (the report)

**Done:** the report is published as
[doi:10.5281/zenodo.24544472](https://doi.org/10.5281/zenodo.24544472) (version v1; the concept DOI
for every version is 10.5281/zenodo.24544471), and the dataset as
[doi:10.5281/zenodo.24544756](https://doi.org/10.5281/zenodo.24544756). The steps below are kept
for a later version.

Zenodo gives the report a permanent DOI at once and needs no endorsement. Publishing is in your
name and cannot be undone (a record can be versioned, not deleted), so it is done from your own
account at zenodo.org:

1. **New upload.** Choose *Upload* → *New upload* and add `main.pdf` (built with your
   `author.tex`). Give it a descriptive name such as `precondition-dispatch-report-v1.pdf`.
2. **Metadata.**
   - **Resource type:** Publication → Preprint.
   - **Title:** as for arXiv, above.
   - **Creators:** your name and affiliation exactly as in `author.tex`; add an ORCID if you have
     one.
   - **Description:** the abstract above.
   - **Licence:** Creative Commons Attribution 4.0 International, matching arXiv.
   - **Keywords:** agent skill reuse; executable preconditions; dispatch; pre-registration; lock
     files; merge conflicts; mutation testing.
   - **Related works:** *Is supplemented by* →
     `https://github.com/Shyboy0499/precondition-library` (resource type: Software).
   - **Version:** `v1`. **Language:** English.
3. **Preview, then Publish.** Zenodo mints the DOI on publishing. Send it back so the README and
   "Data and code availability" can cite it.
4. **Later, arXiv.** Once endorsed, post the same version to arXiv and add the arXiv identifier
   to the Zenodo record as *Is identical to*.

## TechRxiv, without an endorsement

TechRxiv is IEEE's preprint server for engineering and computer science. It has no endorsement
step. A moderator checks that a preprint is original, in scope and not plagiarised, and posts it
with its own DOI, typically within four business days. Submit from your own account at
techrxiv.org:

1. **Upload** `main.pdf`, built with your `author.tex`.
2. **Metadata.**
   - **Title**, **abstract** and **keywords:** as for arXiv and Zenodo above.
   - **Authors:** your name and affiliation exactly as in `author.tex`.
   - **Category:** computing and processing, software engineering.
   - **Licence:** CC BY 4.0.
   - **Related links:** the repository; the Zenodo DOIs, once you have them.
3. **AI disclosure.** State generative-AI use as the report's "Use of generative AI" section
   does. Keep that section.
4. **After posting.** Send the TechRxiv DOI back so the README and the Zenodo record can link it.

## The dataset on Zenodo

`datasets/lockfile-conflicts/` is a dataset in its own right: 1,559 real lock-file conflicts from
109 repositories, labelled by what maintainers committed. Give it its own Zenodo record, so
others can cite it apart from the report:

1. **New upload** with `conflicts.jsonl`, `conflicts.csv`, `README.md` and `build.py`, from the
   commit you publish (or the zip prepared for you).
2. **Metadata.**
   - **Resource type:** Dataset.
   - **Title:** Real lock-file merge conflicts, labelled by what maintainers committed.
   - **Creators:** as in `author.tex`.
   - **Description:** the opening of `datasets/lockfile-conflicts/README.md`: what a row is, the
     ecosystems table, and that no repository content is included.
   - **Licence:** CC BY 4.0.
   - **Keywords:** lock files; merge conflicts; dependency management; npm; Composer; dataset.
   - **Related works:** *Is supplement to* the report's DOI; *Is supplemented by* the repository.
   - **Version:** `v1`.
3. **Publish**, and send the DOI back for the dataset README's citation line.

## Before you submit, check

- [ ] **Your name and affiliation** in `author.tex`. arXiv lists authors by name, not by username.
- [ ] **The citations.** Each was checked against its source's listing, except that arXiv
      itself cannot be reached from the session that wrote this, so the three 2026 preprints'
      authors come from their HTML versions and citing papers. `ding2026rightfamily` changed title
      and authors between versions: the entry cites v4, "Right Family, Wrong Skill". Glance at each
      abstract page once.
- [ ] **The disclosure.** arXiv does not allow AI tools as authors, and it requires significant use
      of generative AI to be reported. The "Use of generative AI" section does that. Keep it.
- [x] **The commit.** "Data and code availability" names the commit the report describes
      (`a10057c`), so a reader can check out exactly what it reports.
- [ ] **Optional:** archive the repository on Zenodo to get a DOI, and cite it in "Data and code
      availability". A DOI outlives a branch.

## After arXiv: peer review

arXiv is a preprint server: it gives the report a permanent, citable home, but it is not peer
review. Two routes fit this work:

- **Study 1 as a short empirical paper or negative result** at a software-engineering venue that
  takes them, for example a workshop at ICSE or FSE, or MSR's tracks. Check each call for page
  limits, anonymity rules and whether it accepts work already posted to arXiv. Most SE venues do.
- **Study 2 as a registered study's result.** It was registered before its data and has now
  run (`results/refusal-population-2026-11-15/`). Its primary hypothesis was not supported. That
  is a result an empirical venue can publish as a negative result, with its registration as
  evidence that the analysis was fixed in advance.
