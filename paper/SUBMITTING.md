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
- **Comments:** 34 pages, 3 figures, 20 tables. Code, data and pre-registrations:
  https://github.com/Shyboy0499/precondition-library
- **Abstract:** the abstract in `main.tex`, without LaTeX markup, as below. It is 1,895 characters, within arXiv's limit of 1,920.

  > Agents that compile solved tasks into reusable programs must decide when to replay one. We
  > compare two ways of deciding at matched coverage: executable preconditions, shell probes that
  > must hold on the live state, and text similarity between the request and each program's
  > description. On states built by our own injectors for five git maintenance faults,
  > precondition dispatch mis-fired on 0 of 563 fires across three independently built libraries,
  > while three text scorers mis-fired on 71-90% of theirs. But a decision tree that only reads
  > the state matched it, and the request carried no information about the state by construction.
  > A pre-registered test on 274 real lock-file merges from 11 repositories, labelled by what
  > maintainers committed, falsified the claim that precondition dispatch rarely mis-fires: it was
  > wrong on 62 of 150, 10 of 122 and 132 of 244 fires. Its margin came from merges without a
  > conflict; on conflicts, the library's line-level resolutions could express 1 of 161 maintainer
  > resolutions. Two further registered studies, on 47 fresh repositories, read lock files as
  > package sets. An action computed from a merge's three sides reproduces the maintainer on 0.69
  > and 0.76 of a repository's conflicts, against 0.07 for line unions, and the ecosystem's
  > resolver predicts which merge maintainers keep (91 of 91 discordant files). Exploratory
  > analysis shows why: half of lock-file conflicts involve no package both sides changed
  > differently. Firing the merge only when none diverges, itself a precondition, roughly halves
  > its mismatch; a fifth registered study, on 20 more repositories, confirms it stays above 0.10
  > (0.35 [0.18, 0.53]). We mutation-test the graders behind every figure, run a Monte Carlo power
  > analysis that amended a registered study before its data existed, and compare the design with
  > a deployed executability gate and a skill-retrieval risk benchmark.

## Zenodo, with or without an endorsement

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
      (`93a7d7e`), so a reader can check out exactly what it reports.
- [ ] **Optional:** archive the repository on Zenodo to get a DOI, and cite it in "Data and code
      availability". A DOI outlives a branch.

## After arXiv: peer review

arXiv is a preprint server: it gives the report a permanent, citable home, but it is not peer
review. Two routes fit this work:

- **Study 1 as a short empirical paper or negative result** at a software-engineering venue that
  takes them, for example a workshop at ICSE or FSE, or MSR's tracks. Check each call for page
  limits, anonymity rules and whether it accepts work already posted to arXiv. Most SE venues do.
- **Study 2 as a registered report.** It is registered and no data exists yet, which is what that
  format reviews. MSR and ESEM have run registered-report tracks, so check their current calls
  before the build runs.
