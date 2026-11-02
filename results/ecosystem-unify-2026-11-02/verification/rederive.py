"""(Study 4.) Re-read every labelled lock file from git with parsers written here, independently of
bench.lock_actions, and check: (1) the independent sets give the same reproduce verdict per
action and the same Jaccard; (2) how many maintainer sets are empty or tiny; (3) how many
conflicts leave the package sets of both sides equal (a conflict outside the packages)."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

study, hosts = Path(sys.argv[1]), Path(sys.argv[2])
manifest = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in manifest["repositories"]}
cases = {c["index"]: c for c in manifest["cases"]}
rows = [
    json.loads(line) for line in (study / "labels.jsonl").read_text().splitlines() if line.strip()
]


def show(repo, commit, path):
    p = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{path}"],
        capture_output=True,
    )
    return p.stdout.decode("utf-8", "surrogateescape") if p.returncode == 0 else None


def parse(path, text):
    name = path.rsplit("/", 1)[-1]
    if re.search(r"^(<{7}|>{7})( |$)", text, re.MULTILINE):
        return None
    try:
        if name in ("Cargo.lock", "poetry.lock", "uv.lock"):
            return {
                (p["name"], str(p.get("version", "")))
                for p in tomllib.loads(text).get("package", [])
            }
        if name == "composer.lock":
            d = json.loads(text)
            return {
                (p["name"], p["version"])
                for k in ("packages", "packages-dev")
                for p in d.get(k) or []
            }
        if name in ("package-lock.json", "npm-shrinkwrap.json"):
            d = json.loads(text)
            if isinstance(d.get("packages"), dict):
                return {
                    (k.split("node_modules/")[-1], v["version"])
                    for k, v in d["packages"].items()
                    if "node_modules/" in k and "version" in v and not v.get("link")
                }
            out = set()

            def walk(deps):
                for n, v in deps.items():
                    if "version" in v:
                        out.add((n, v["version"]))
                    walk(v.get("dependencies", {}))

            walk(d["dependencies"])
            return out
        if name == "Gemfile.lock":
            return {(m[1], m[2]) for m in re.finditer(r"(?m)^    ([^\s(]+) \(([^)]+)\)\s*$", text)}
        if name == "yarn.lock":
            out, keys = set(), None
            for line in text.splitlines():
                if line and not line[0].isspace() and not line.startswith("#"):
                    keys = (
                        []
                        if line.startswith("__metadata")
                        else [
                            re.sub(r"^(@?[^@]+)@.*$", r"\1", s.strip().strip('"'))
                            for s in line.rstrip(":").split(",")
                        ]
                    )
                else:
                    m = re.match(r'^\s+version:?\s+"?([^"\s]+)"?\s*$', line)
                    if m and keys:
                        out |= {(k, m[1]) for k in keys}
                        keys = None
            return out
        if name == "pnpm-lock.yaml":
            out, inside = set(), False
            for line in text.splitlines():
                if line and not line[0].isspace():
                    inside = line.strip() == "packages:"
                    continue
                m = re.match(r"""^  ['"]?([^\s'"].*?)['"]?:\s*$""", line) if inside else None
                if m:
                    k = m[1].lstrip("/").split("(")[0]
                    n, _, last = k.rpartition("/")
                    out.add(
                        (n, last.split("_")[0])
                        if n and last[:1].isdigit()
                        else (k[: k.rfind("@")], k[k.rfind("@") + 1 :])
                    )
            return out
    except Exception:
        return None
    return None


NPM = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"}


def release(v):
    nums = re.findall(r"\d+", v.split("+", 1)[0].split("-", 1)[0])
    return tuple(int(n) for n in nums[:4])


def unify(path, pairs):
    """Written here from ecosystem-unify.md §4, not imported: within each package's
    compatible range only the highest version."""
    name = path.rsplit("/", 1)[-1]
    best = {}
    for pkg, v in pairs:
        if name in NPM or name == "Cargo.lock":
            r = release(v) + (0, 0)
            key = (pkg, r[:2] if r[0] == 0 else r[:1])
        elif name == "Gemfile.lock":
            m = re.match(r"^[\d.]+(?:\.[a-z]+\d*)?-(.+)$", v)
            key = (pkg, m.group(1) if m else "")
        else:
            key = (pkg,)
        if key not in best or release(v) > release(best[key]):
            best[key] = v
    return {(k[0], v) for k, v in best.items()}


def jac(a, m):
    if a is None:
        return False, 0.0
    u = a | m
    return a == m, (len(a & m) / len(u)) if u else 1.0


agree = disagree = duplicated = one_version = 0
sizes = []
trivial_files = 0
trivial_cases = 0
empty = 0
files_total = 0
for r in rows:
    c = cases[r["index"]]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    case_trivial = True
    for f in r["files"]:
        files_total += 1
        b, local, u, m = (
            parse(f["path"], t) if (t := show(repo, c[k], f["path"])) is not None else None
            for k in ("base", "first", "second", "merge")
        )
        sizes.append(len(m))
        empty += len(m) == 0
        if local is not None and u is not None and local == u:
            trivial_files += 1
        else:
            case_trivial = False
        bb = b or set()
        tw = (
            (bb & local & u) | (local - bb) | (u - bb)
            if local is not None and u is not None
            else None
        )
        mine = {
            "take_local": jac(local, m),
            "take_upstream": jac(u, m),
            "three_way": jac(tw, m),
            "three_way_unified": jac(unify(f["path"], tw) if tw is not None else None, m),
        }
        if tw is not None and f["path"].rsplit("/", 1)[-1] not in NPM:
            names = [p for p, _ in tw]
            duplicated += len(names) != len(set(names))
            one_version += 1
        for x in f["results"]:
            if x["action"] in mine:
                ok = (
                    mine[x["action"]][0] == x["reproduces"]
                    and abs(mine[x["action"]][1] - (x["jaccard"] or 0.0)) < 1e-12
                )
                agree += ok
                disagree += not ok
                if not ok:
                    print(
                        "DIFFER",
                        r["index"],
                        f["path"],
                        x["action"],
                        mine[x["action"]],
                        x["reproduces"],
                        x["jaccard"],
                    )
    trivial_cases += case_trivial
sizes.sort()
print(f"files {files_total}; action verdicts agree {agree}, differ {disagree}")
print(f"maintainer sets: empty {empty}, smallest {sizes[:5]}, median {sizes[len(sizes) // 2]}")
print(
    f"files whose two sides hold the same package set: {trivial_files}; "
    f"cases where every file does: {trivial_cases} of {len(rows)}"
)
print(
    f"one-version files whose plain merge holds two versions of a package: {duplicated} of "
    f"{one_version} (the plain merge cannot match a one-version maintainer file there)"
)
