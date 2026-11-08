# Did `.gitattributes` change any case of studies 1, 3, 4 or 5? 2026-11-08

**A validity check, prompted by study 5** (`results/divergence-gate-2026-11-08/README.md`).

Study 1's mining (`real_merges.mine`) is shared by every lock-file study since. It runs
`git merge-tree` in a cache with no checked-out HEAD, so no repository's `.gitattributes` applies.
A maintainer merging in a working tree gets them. One attribute changes a merge, `merge`:

- a lock file declared `binary` or `-merge` conflicts whenever both sides changed it;
- `merge=<driver>` hands the file to a custom driver.

`audit.py` asks git for that attribute on every case of the four studies' manifests:

```bash
python results/mining-attributes-2026-11-08/audit.py <study> <caches> <clones> <out.jsonl>
```

For each case it reads, at the case's first parent (the tree the maintainer merged into):

- **for a conflicted case,** each conflicted lock file;
- **for a clean case** (study 1's negatives), each lock file both sides changed.

The command is `git check-attr --source=<first parent> merge -- <path>`. Studies 4 and 5 were
read from their own caches. Studies 1 and 3 were read from blobless clones, which fetch only the
`.gitattributes` blobs git asks for.

## Result

| study | cases | `merge` attribute set on a case's lock file |
| --- | ---: | ---: |
| 1 (`real-merges-2026-10-26/stage-B`) | 274 | 2 |
| 3 (`lock-oracle-2026-11-02`) | 360 | 0 |
| 4 (`ecosystem-unify-2026-11-02`) | 266 | 0 |
| 5 (`divergence-gate-2026-11-08`) | 223 | 1 |
| **all** | **1,123** | **3** |

Each study's file (`study-1.jsonl` … `study-5.jsonl`) gives every case's attribute for every lock
file it turns on.

### The three cases

| study | case | repository | kind | attribute | under it |
| --- | ---: | --- | --- | --- | --- |
| 1 | 101 | `nextcloud/server` | conflict | `package-lock.json merge=binary` | a binary conflict, which the registration excludes |
| 1 | 104 | `nextcloud/server` | clean merge | `package-lock.json merge=binary` | a binary conflict, so not a clean case |
| 5 | 222 | `nextcloud/activity` | conflict | `package-lock.json binary` | a binary conflict, which the registration excludes |

### What they change

- **Study 5: no decision changes.** Its one case has a divergent package, so the gate refuses it,
  and it enters none of H1–H3. Without it, the pooled "always" figure is 126/222 rather than
  127/223.
- **Study 1: no decision of rule 2 changes.** Recomputed from `stage-B/labels.jsonl` and
  `decisions.jsonl`, precondition dispatch's wrong fires reproduce the registered 62/150, 10/122
  and 132/244. Without the two cases, as the table below shows, each library's decision stands.
  H1–H3's bootstrap intervals were not recomputed. They move by two of 274 cases.

| library | as registered | without cases 101 and 104 | rule 2 |
| --- | --- | --- | --- |
| 1 | 62/150, Wilson lower 0.338 | 60/148, lower 0.330 | falsified either way |
| 2 | 10/122, lower 0.045 | 8/120, lower 0.034 | not falsified either way |
| 3 | 132/244, lower 0.478 | 131/242, lower 0.478 | falsified either way |

## Limits

- **Attributes are read from the first parent.** A maintainer's local `.git/info/attributes` or
  global attributes can add more, and no repository records those.
- **A driver like `merge=binary` is git's built-in one.** No case used a custom driver, which
  would need the maintainer's configuration to replay.
- **The next registration should read attributes from the first parent when mining,** or exclude
  such cases explicitly.
