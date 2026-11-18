# What the model calls cost, from the provider's dashboard, 2026-11-18

Every run in this repository counts its tokens but reports no money: the provider's rates differ
by peak and off-peak hours, and several runs shared one key at the same time. The owner read the
spend from the provider's usage dashboard (cost in CNY, by model and by day). These are those
figures, and how they divide among the runs.

**Descriptive.** The figures are the dashboard's, as the owner reported them. Nothing here was
computed from a rate table.

## The dashboard

The dashboard covers 20 October to 18 November 2026.

| | CNY |
| --- | --- |
| **total** | **95.49** |
| 15 November, `deepseek-flash` | 63.19 |
| 15 November, `deepseek-v4-pro` | 8.36 |
| 16 November, `deepseek-flash` | 17.62 |
| every other day together, `deepseek-flash` | 6.32 |

The dashboard's days are the provider's, which may not be UTC.

## Which runs it paid for

- **15–16 November, CNY 89.17.** Four runs used the key on these two days:
  - study 2's 20 builds (`results/refusal-population-2026-11-15/builds/`);
  - the LLM judge (`results/judge-2026-11-15/`);
  - run-14 and run-15 (`results/replicates-2026-11-15/`).
- **`deepseek-v4-pro`, CNY 8.36, is run-15 exactly.** It is the only run that used that model.
- **The `deepseek-flash` CNY 80.81 is shared** by study 2's builds, the judge and run-14. The
  dashboard does not split it by run.
  - Divided in proportion to each run's output tokens, it comes to about:
    - study 2's builds: CNY 49 (10.8 million output tokens);
    - the judge: CNY 30 (6.64 million);
    - run-14: CNY 2 (0.51 million).
  - This ignores input tokens and the hour each call was made, so it is an estimate.
  - The judge's own README estimated about CNY 23 from a partial reading.
- **Every other day, CNY 6.32.** These are smaller runs between 20 October and 14 November.
  Spend before 20 October falls outside the dashboard's window and is not known here.

## What it shows

The whole external programme visible on the dashboard cost under CNY 100. The registered study
of 20 builds (study 2) was about half of it.
