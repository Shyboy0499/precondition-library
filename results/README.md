# Results, by question

Every measurement this project has made, one dated folder each. A folder is never edited after
its result is committed: a later run of the same thing gets a new folder, and its README says
what it changes. Each folder's README states what was run, the command, what may and may not be
claimed, and how to recompute its figures.

The folders stay in one flat list because frozen pre-registrations, the paper and the
decision records link to them by path. This page is the map.

## Graded by labels someone else made: real merges

The pre-registered studies run on public repositories nobody here had mined, graded by what the
maintainers committed. Code: `src/precondition_library/studies/`.

| study | question | folder |
| --- | --- | --- |
| 1 | Does precondition dispatch reproduce maintainers' lock-file merges better than text similarity? | [real-merges-2026-10-26](real-merges-2026-10-26/) |
| 2 | Is refusal a property of the method or of one build? | registration and refusal set R: [refusal-population-2026-11-01](refusal-population-2026-11-01/); the 20 builds and the registered result (H1 not supported): [refusal-population-2026-11-15](refusal-population-2026-11-15/) |
| 3 | Which computed action reproduces a maintainer's lock file? | [lock-oracle-2026-11-02](lock-oracle-2026-11-02/) |
| 4 | Does the ecosystem's resolver predict which package-level merge maintainers kept? | [ecosystem-unify-2026-11-02](ecosystem-unify-2026-11-02/) |
| 5 | Does refusing where a package diverges make the merge rarely wrong? | [divergence-gate-2026-11-08](divergence-gate-2026-11-08/) |
| 6 | The ecosystem's own check as a precondition | [tool-precondition-2026-11-09](tool-precondition-2026-11-09/) |

**Around them, exploratory or descriptive:**

- Lock-file conflicts: [lock-actions-2026-10-27](lock-actions-2026-10-27/) (study 1's stage A
  conflicts), [lock-uncovered-2026-11-02](lock-uncovered-2026-11-02/) (where no computed action
  matches), [lock-anatomy-2026-11-04](lock-anatomy-2026-11-04/) (what a conflict is made of).
- The ecosystem's tools: [lock-tool-dated-2026-11-03](lock-tool-dated-2026-11-03/) (npm, pinned
  to the merge's date), [lock-tool-dated-2026-11-08](lock-tool-dated-2026-11-08/) (pnpm and
  Composer), [lock-tool-check-2026-11-08](lock-tool-check-2026-11-08/) (their consistency check).
- Audits of the mining: [archive-attributes-2026-11-08](archive-attributes-2026-11-08/),
  [mining-attributes-2026-11-08](mining-attributes-2026-11-08/).
- What study 6's check could see: [manifest-leak-2026-11-11](manifest-leak-2026-11-11/),
  [manifest-merge-2026-11-11](manifest-merge-2026-11-11/).
- A project's own tests as a judge: [project-tests-pilot-2026-11-14](project-tests-pilot-2026-11-14/).

## Graded by this project's own labels: the synthetic benchmark

States built by this project's fault injectors, graded by its own rules. Code:
`src/precondition_library/experiment/`.

- **The primary result (Figure 1).** [replicates-2026-10-05](replicates-2026-10-05/): three
  replicate libraries, with the lexical, embedding and reranker arm 2.
  [replicates-2026-11-15](replicates-2026-11-15/): a six-family build and a second compiling model.
- **Arm 2's other scorers and dispatchers.** [judge-2026-11-15](judge-2026-11-15/) (an LLM that
  reads the state), [hybrid-2026-10-11](hybrid-2026-10-11/) (retrieve by text, gate by
  preconditions).
- **Controls that read the state.** [state-classifier-2026-10-26](state-classifier-2026-10-26/),
  [probe-classifier-2026-11-02](probe-classifier-2026-11-02/).
- **States no library saw.** [heldout-2026-10-10](heldout-2026-10-10/),
  [heldout-2026-10-16](heldout-2026-10-16/), [heldout-2026-10-18](heldout-2026-10-18/) (lock files
  at new paths), [heldout-2026-10-19](heldout-2026-10-19/) (new branch names and submodule paths),
  [realhost-2026-10-20](realhost-2026-10-20/) (real repositories' histories),
  [heldout-2026-11-16](heldout-2026-11-16/) (the lock-file paths again, on the 22 libraries built
  since the compile prompt changed),
  [lock-path-perturbation-2026-11-16](lock-path-perturbation-2026-11-16/) (which checks know lock
  files only by name, and what a build-time test at unseen paths would refuse).
- **What a fire does, and why arm 3 sits out.** [consequences-2026-10-21](consequences-2026-10-21/),
  [consequences-heldout-2026-10-21](consequences-heldout-2026-10-21/),
  [consequences-realhost-2026-10-21](consequences-realhost-2026-10-21/),
  [abstentions-2026-10-12](abstentions-2026-10-12/).

## The tool it produced

[lockmerge-2026-11-25](lockmerge-2026-11-25/): `lockmerge`, the lock-file merge driver, replayed
on the 895 real `package-lock.json` and `composer.lock` conflicts of studies 1 and 3–6 and graded
against each maintainer's commit (exploratory; a development set).

## What it cost

[api-cost-2026-11-18](api-cost-2026-11-18/): the provider's dashboard, CNY 95.49 in all, divided
among the runs.

## Checks on the instruments

Code: `src/precondition_library/audits/`.

- The graders under mutation: [grader-mutation-2026-10-28](grader-mutation-2026-10-28/),
  [grader-mutation-2026-10-31](grader-mutation-2026-10-31/).
- The graders on generated states: [grader-properties-2026-10-26](grader-properties-2026-10-26/).
