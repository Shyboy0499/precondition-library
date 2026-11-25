# lockmerge

**Stop hand-fixing `package-lock.json` and `composer.lock` merge conflicts, safely.**

`lockmerge` is a git merge driver. When two branches both change a lock file, it merges the file
**package by package**: whatever both sides kept, plus each side's additions, upgrades and
removals. It merges only when that is safe. If a package was changed differently on both
branches, or the merge would break a dependency, it leaves the conflict to you and names the
packages:

```text
$ git merge feature
lockmerge: merged package-lock.json          ← the usual case: two branches, different packages

$ git merge renovate/all
lockmerge: left package-lock.json conflicted:
  - eslint: base 8.56.0, ours 8.57.0, theirs 9.0.0
  Resolve package.json, then `npm install` to regenerate it.
```

Zero dependencies, Python 3.10+. Supports `package-lock.json` / `npm-shrinkwrap.json` (lockfile
formats 1–3) and `composer.lock`.

## Install

```bash
pipx install "git+https://github.com/Shyboy0499/precondition-library#subdirectory=lockmerge"
```

Or use `pip install` with the same URL. Then, inside a repository:

```bash
lockmerge install            # this repository: git config + .gitattributes
lockmerge install --global   # or every repository on this machine
```

`install` registers the driver in git's config and adds three lines to `.gitattributes`:

```text
package-lock.json merge=lockmerge
npm-shrinkwrap.json merge=lockmerge
composer.lock merge=lockmerge
```

Commit `.gitattributes` so your team gets it. Each person runs `lockmerge install` once, because
git never runs a merge driver it was not told about. Anyone who hasn't installed it just gets
git's normal merge.

## Use

During `git merge`, `git rebase`, `git cherry-pick` or `git pull`, lock files merge on their own
when they safely can. Nothing else to do.

**Already in a conflicted merge?** (for example, before you installed the driver):

```bash
lockmerge resolve                # merge every conflicted lock file that is safe to merge, and stage it
lockmerge resolve --regenerate   # ...and hand the unsafe ones to npm or Composer (see below)
```

**Try it without git:**

```bash
lockmerge check base.json ours.json theirs.json --name package-lock.json
```

## What it refuses, and why

`lockmerge` would rather leave a conflict than guess. It declines a file when:

1. **One package was changed differently on both sides.** For example, `eslint` was moved to
   8.57.0 on one branch and 9.0.0 on the other. No merge of the files can know which you want,
   or whether either works with the rest. This is the most common case: two dependency-bot
   updates.
2. **The merged file would break a dependency neither side broke.** For example, one branch
   upgrades a shared package to 2.x while the other adds a package that needs 1.x. Each record
   merges cleanly; the tree they form does not install.
3. **The project's own requirements would be unmet.** No package in `package.json` may be
   missing or out of range. This holds even when one side's lock file was already out of date.
4. **The two sides use different lockfile formats.** One branch upgraded npm.
5. **For `composer.lock`: both branches changed `composer.json`.** Composer's `content-hash` is
   a fingerprint of `composer.json`, so it can only come from the merged one. Merge
   `composer.json`, then run `lockmerge resolve`, which reads it and computes the hash exactly
   as Composer does.

A package recorded two ways at **the same version** is not a conflict. Examples: different
`dev`/`optional` flags, a sha1 versus a sha512 hash, or extra fields a newer npm writes.
`lockmerge` keeps every field and the stronger hash. It marks a package dev-only or optional only
if both sides did, so `npm ci --omit=dev` never drops something production needs.

### `--regenerate`

For the files it declines, `lockmerge resolve --regenerate` does what npm's and Composer's own
guides recommend:

- **npm:** start from your side's lock file and run
  `npm install --package-lock-only --ignore-scripts` against the merged `package.json`.
- **Composer:** start from your side's `composer.lock` and run `composer update <the packages
  the other branch changed> --no-install`.

These reach the registry and may pick newer versions than either branch had, which is why they
are opt-in.

## How well it works

We replayed **895 real lock-file conflicts** from 68 open-source repositories. Each was graded
against what the project's maintainer actually committed
([measurements](../results/lockmerge-2026-11-25/README.md)).

| | merged automatically | valid for the merged manifest | same packages as the maintainer |
| --- | --- | --- | --- |
| `package-lock.json`, during `git merge` | 63 of 374 (17%) | 60 of 63 | 45 of 63 |
| `composer.lock`, during `git merge` | 15 of 521 (3%) | 14 of 15 | 12 of 15 |
| `composer.lock`, with `lockmerge resolve` | 187 of 521 (36%) | 175 of 187 | 140 of 187 |

- **When it merges, the result is valid.** "Valid" means it passes npm's (`npm ci`'s) or
  Composer's lock-file consistency rules for the merged manifest, checked offline. Every merge
  that failed came from a conflict whose maintainer had committed an invalid file too.
- **When it differs from the maintainer, it's because it kept both sides' changes.** The
  maintainer either dropped one side's change or re-ran the package manager and picked up newer
  versions.
- **It merges a minority of conflicts.** Most real conflicts move the same package two ways, and
  for those it tells you which packages, instead of guessing.

**Caveat:** these figures come from the same conflicts the rules were refined on. A test on
repositories it hasn't seen is the next step.

## How it differs from the alternatives

| tool | what it does on a lock-file conflict |
| --- | --- |
| git's default | conflict markers in a generated file |
| `npm install` / `npm-merge-driver` / `pnpm install` | re-resolves from `package.json`: always "resolves", may change versions you didn't touch |
| Composer's guide | take one side, re-run `composer update` for the other side's packages |
| **lockmerge** | merges exactly what each branch changed, when that's provably safe; otherwise says which packages conflict, and can fall back to the package manager |

## Where it comes from

`lockmerge` is the practical result of a research project on a broader question: when an agent
or tool reuses a saved fix, should it decide by description or by checking the current state?
Its registered studies of real lock-file conflicts found the following.

- Merging lock files as **sets of packages** reproduces the maintainer on about two conflicts in
  three, where line-based merging manages about one in fourteen.
- Firing the merge **only when no package diverges** roughly halves its error.
- The ecosystem's own consistency check catches what remains.

`lockmerge` is that gate made into a tool. The studies, the data and the paper are in this
repository ([README](../README.md)).

## Uninstall

```bash
git config --unset-all merge.lockmerge.driver   # add --global if you installed globally
git config --unset-all merge.lockmerge.name
```

Then delete the three `merge=lockmerge` lines from `.gitattributes`, and `pipx uninstall
lockmerge`.

MIT licensed.
