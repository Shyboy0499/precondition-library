# The technical report, and how to submit it

`main.tex` is a self-contained technical report on the project's results: the synthetic primary
result, study 1 on real lock-file merges (including the falsified claim), the grader checks, and
study 2's registered design. It has no figures to build and no BibTeX step.

## Build it

```bash
cd paper
cp author.example.tex author.tex   # then put your name, affiliation and email in author.tex
latexmk -pdf main.tex
```

`author.tex` is ignored by git, so your name and email never enter the repository's history. Without
it, the build falls back to the placeholder in `author.example.tex`.

`./package.sh` builds the PDF and writes `arxiv-upload.tar.gz` with `main.tex`, `author.tex` and
`author.example.tex`, the files arXiv compiles. Both the PDF and the tarball are ignored by git.

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
- **Comments:** 8 pages, 2 tables. Code, data and pre-registrations:
  https://github.com/Shyboy0499/precondition-library
- **Abstract:** use the abstract in `main.tex`, without LaTeX markup.

## Before you submit, check

- [ ] **Your name and affiliation** in `author.tex`. arXiv lists authors by name, not by username.
- [ ] **The citations.** Each was checked against its source's listing, except that arXiv
      itself cannot be reached from the session that wrote this, so the three 2026 preprints'
      authors come from their HTML versions and citing papers. `ding2026rightfamily` changed title
      and authors between versions: the entry cites v4, "Right Family, Wrong Skill". Glance at each
      abstract page once.
- [ ] **The disclosure.** arXiv does not allow AI tools as authors, and it requires significant use
      of generative AI to be reported. The "Use of generative AI" section does that. Keep it.
- [ ] **The commit.** The report cites commit `b1ddfd1`. If you change results before submitting,
      update the commit.
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
