# Did `git archive` leave files out of the trees tools ran in? 2026-11-08

**A validity check.** It was prompted by the dated-tool pilot of the same day
(`results/lock-tool-dated-2026-11-08/`).

Every run of an ecosystem's tool so far has put the tool in the merge's tree, extracted with
`git archive` (`lock_actions._checkout`, and `npm_dated.py`). `git archive` applies the
repository's own attributes:

- **`export-ignore`** leaves a file out;
- **`export-subst`** rewrites `$Format:…$` placeholders.

A maintainer merging in a working tree has every file as committed.

The pilot found the problem on `PrivateBin/PrivateBin`. Its `.gitattributes` marks
`composer.json` and `composer.lock` `export-ignore`, so Composer found no manifest.

## The fix

`lock_actions._checkout` now writes every blob as committed, from `git ls-tree` and
`git cat-file --batch`. Submodules are left empty, as a fresh clone leaves them. Both of the
day's new scripts use it. The test is
`tests/test_lock_actions.py::test_the_merges_tree_keeps_files_its_own_attributes_leave_out_of_archives`.

## Were earlier results affected?

`audit.py` compares, for each merge an earlier result ran a tool in, `git archive`'s files with
the commit's blobs:

```bash
python results/archive-attributes-2026-11-08/audit.py <out.jsonl> \
    stage-A=results/real-merges-2026-10-26/stage-A:<cache> \
    study-3=results/lock-oracle-2026-11-02:<cache> study-4=results/ecosystem-unify-2026-11-02:<cache>
```

| result | merges a tool ran in | with files left out | with a manifest or lock file left out or rewritten |
| --- | ---: | ---: | ---: |
| `lock-actions-2026-10-27` (stage A's `reconcile_*` and `regenerate`) | 30 | 13 | **0** |
| `lock-tool-dated-2026-11-03`, study 3's files | 37 | 10 | **0** |
| `lock-tool-dated-2026-11-03`, study 4's files | 14 | 0 | **0** |

No file was rewritten. The files left out are tests, CI configuration, Docker files, docs and
the source of some packages:

- `contao/contao`: 735 files of `core-bundle`, and others;
- `bolt/core`: `tests/`, `config/`, `public/`;
- `tauri-apps/tauri` and `helix-editor/helix`: a few files under `core/`, `tooling/`, `contrib/`;
- `firefly-iii/firefly-iii`: `.github/`.

None is a manifest, lock file or tool configuration (`package.json`, `.npmrc`, `Cargo.toml`,
`pyproject.toml`, `.yarnrc*` or a toolchain file). npm, cargo and yarn resolve from those, so
**no earlier result changes**. `audit.jsonl` gives every case.

## Limits

- **A dropped source file could matter** only to a tool that builds the project. npm and yarn
  ran with `--ignore-scripts`, and `cargo update` and `poetry lock` resolve without building
  the project.
- **The audit reads attributes from the merge commit.** As in
  `results/mining-attributes-2026-11-08/`, a maintainer's own `.git/info/attributes` is not
  recorded anywhere.
