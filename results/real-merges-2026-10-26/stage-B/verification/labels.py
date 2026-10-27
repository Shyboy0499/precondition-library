"""Independent check of stage B's cases and labels for fetched repositories, from git alone.

Follows docs/preregistration/real-merges.md §3.2-§4 and Amendment 1 (A2). Imports nothing
from the project."""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

LOCKS = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "Gemfile.lock",
    "composer.lock",
}


def is_lock(p):
    return p.rsplit("/", 1)[-1] in LOCKS


def git(repo, *a, ok=(0,)):
    r = subprocess.run(
        ["git", "-C", str(repo), *a],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    if r.returncode not in ok:
        raise RuntimeError(f"{a}: {r.stderr}")
    return r


def lines(repo, rev, path):
    r = git(repo, "cat-file", "blob", f"{rev}:{path}", ok=(0, 128))
    return Counter(r.stdout.splitlines(keepends=True)) if r.returncode == 0 else Counter()


def mtree(repo, a, b):
    r = git(repo, "merge-tree", "--write-tree", "--name-only", "-z", a, b, ok=(0, 1))
    head = r.stdout.split("\0\0", 1)[0].split("\0")
    return r.returncode, head[0], sorted(set(p for p in head[1:] if p))


def changed_locks(repo, base, tip):
    return {
        p
        for p in git(repo, "diff", "--no-renames", "--name-only", base, tip).stdout.splitlines()
        if is_lock(p)
    }


out = Path(sys.argv[1])
repos_dir = Path(sys.argv[2])
only = sys.argv[3:]
manifest = json.load(open(out / "manifest.json"))
labels = {r["index"]: r for r in map(json.loads, open(out / "labels.jsonl"))}
summ = {r["repo"]: r for r in manifest["repositories"]}
problems = 0
for name in only:
    repo = repos_dir / (name.replace("/", "_") + ".git")
    cases = [c for c in manifest["cases"] if c["repo"] == name]
    agree = Counter()
    for c in cases:
        parents = git(repo, "rev-list", "--parents", "-n1", c["merge"]).stdout.split()[1:]
        bases = git(repo, "merge-base", "--all", c["first"], c["second"]).stdout.split()
        assert parents == [c["first"], c["second"]] and bases == [c["base"]], c["index"]
        rc, tree, conflicted = mtree(repo, c["first"], c["second"])
        tree_of_merge = git(repo, "rev-parse", f"{c['merge']}^{{tree}}").stdout.strip()
        if c["kind"] == "positive":
            assert rc == 1 and any(is_lock(p) for p in conflicted), c["index"]
            assert conflicted == sorted(c["conflicted"]), (c["index"], conflicted, c["conflicted"])
            locks = [p for p in conflicted if is_lock(p)]
            B, L, U, M = (
                {f: lines(repo, rev, f) for f in locks}
                for rev in (c["base"], c["first"], c["second"], c["merge"])
            )
            acc = []
            if all(is_lock(p) for p in conflicted):
                if all(U[f] + (L[f] - B[f]) == M[f] for f in locks):
                    acc.append("take_upstream")
                if all(L[f] + (U[f] - B[f]) == M[f] for f in locks):
                    acc.append("keep_local")
            if all(M[f] == L[f] for f in locks):
                cls = "took local"
            elif all(M[f] == U[f] for f in locks):
                cls = "took upstream"
            elif "take_upstream" in acc:
                cls = "matches take_upstream"
            elif "keep_local" in acc:
                cls = "matches keep_local"
            elif any(
                any(line not in B[f] and line not in L[f] and line not in U[f] for line in M[f])
                for f in locks
            ):
                cls = "regenerated"
            else:
                cls = "other"
        else:
            assert rc == 0, c["index"]
            assert changed_locks(repo, c["base"], c["first"]) & changed_locks(
                repo, c["base"], c["second"]
            ), c["index"]
            acc = ["merge"] if tree_of_merge == tree else []
            cls = labels[c["index"]]["descriptive"]
        got = labels[c["index"]]
        ok = sorted(acc) == sorted(got["acceptable"]) and cls == got["descriptive"]
        agree[ok] += 1
        if not ok:
            problems += 1
            print(
                "  DISAGREE",
                c["index"],
                c["kind"],
                "mine",
                acc,
                cls,
                "theirs",
                got["acceptable"],
                got["descriptive"],
            )
    # re-mine: count positives / candidate negatives / criss-cross over the whole history
    tip = summ[name]["tip"]
    merges = [
        line.split()
        for line in git(repo, "rev-list", "--merges", "--parents", tip).stdout.splitlines()
    ]
    two = [m for m in merges if len(m) == 3]
    pos = neg = criss = sub = 0
    for m, a, b in two:
        bases = git(repo, "merge-base", "--all", a, b, ok=(0, 1)).stdout.split()
        if not bases:
            continue
        if not (changed_locks(repo, bases[0], a) & changed_locks(repo, bases[0], b)):
            continue
        if len(bases) > 1:
            criss += 1
            continue
        rc, _, conflicted = mtree(repo, a, b)
        if rc == 1 and any(is_lock(p) for p in conflicted):
            pos += 1
        elif rc == 0:
            neg += 1
    s = summ[name]
    print(
        f"{name}: cases {len(cases)} labels agree {agree[True]}/{len(cases)};"
        f" two-parent merges {len(two)} (reported {s['two_parent_merges']});"
        f" re-mined positives {pos} (kept {s['positives']}),"
        f" clean candidates {neg} (kept {s['negatives']} = min(positives, candidates)?),"
        f" criss-cross {criss} (excl {s['exclusions']})"
    )
print("problems", problems)
