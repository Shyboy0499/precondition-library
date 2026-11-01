# Study 2's independent recomputation (refusal-population §10)

§10 requires an independent recomputation of every figure, by code that does not import the
project, as study 1's `verification/` did. This one was written and tested **before any of study
2's data existed**, against the files `bench.refusal_study evaluate` writes. So it could not be
fitted to the results.

```bash
python -I results/refusal-population-2026-11-01/verification/recompute.py \
  results/refusal-population-2026-11-01
```

It uses the standard library only and runs with `-I`, so the project cannot be imported even by
accident. From `manifest.json`, `labels.jsonl`, `decisions.jsonl` and `builds.json` it recomputes:

- each case's kind, the counts, and the number of valid builds per configuration;
- each control's fire rate;
- each build's fire rate, clean right rate, and margin over its control;
- H1–H4's statistics;
- H1–H4's 95% two-level bootstrap intervals, with its own seed (20261101, not the registered 0),
  so agreement cannot depend on drawing the same resamples. Interval ends are compared within
  0.03.
- whether the study is underpowered, and §9's decisions in order, with Amendment 1's three
  outcomes for H4.

It prints every comparison and exits 1 on any disagreement. The tests run it on an end-to-end
run of the fixture history, on that run with two figures altered (both caught), and on a
synthetic study past rule 1 (`tests/test_refusal_study.py`). Its output on study 2's data will be
committed here as `recompute.out`.
