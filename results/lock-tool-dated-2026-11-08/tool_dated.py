"""Pilot (exploratory, seen data): pnpm's and Composer's own tools, held to the merge's date, on
the `pnpm-lock.yaml` and `composer.lock` files no computed action reproduced (#336).

The npm pilot (`results/lock-tool-dated-2026-11-03/`) used `npm --before`. pnpm and Composer
have no such option, but each can refuse versions younger than an age. The age is set to the
time since the merge was committed, so the tool sees only versions released before the merge.

For each file: the merge's whole tree as committed (`lock_actions._checkout`, which unlike
`git archive` ignores the repository's `export-ignore`), with the lock file replaced by one
side's, then the tool.

**pnpm.** pnpm 10.16+ has `minimumReleaseAge`, in minutes:

    pnpm install --lockfile-only --ignore-scripts --no-frozen-lockfile \\
        --config.minimum-release-age=<minutes>

The pnpm version is the one the merged `package.json` declares (`packageManager`, or
`devEngines.packageManager`), fetched from npm into `<scratch>/pnpms/`. Without one, or below
10.16, it is pnpm 10.28.0. A repository's own `minimumReleaseAgeExclude` still applies.

**Composer.** The `cotonet/soak-time` plugin drops versions released fewer than
`extra.soak-time-hours` hours ago (whole hours since the merge, rounded down, so up to an hour
after the merge is admitted). It dates a version by its release date, which Packagist takes from
the tag. A branch version such as `dev-main` is dated by the branch's latest commit, so packages
the starting lock pins to a branch are exempt (`extra.soak-time-whitelist`) and stay at their
locked commit unless updated. Composer's documented way to settle a conflicted `composer.lock`
is to take one side's and update the packages the other side changed:

    composer update --no-install --no-scripts --no-audit -W --minimal-changes <packages>

`<packages>` are the root requirements (`require` and `require-dev`, platform packages aside)
whose constraint differs between the side's `composer.json` and the merge's, or that only one of
them has. If there are none, the side's lock file already fits the merged manifest and is the
answer. Extensions and libraries are not checked (`--ignore-platform-req=ext-*`, `lib-*`). The
PHP version is, as this container's PHP 8.3; if any problem names it, the run is repeated with
`--ignore-platform-reqs` and the outcome is marked "(php ignored)".

Neither tool installs or runs any package's code. The result's (package, version) set is
compared with the maintainer's.

    PYTHONPATH=src python results/lock-tool-dated-2026-11-08/tool_dated.py \\
        <study> <its real-hosts cache> <scratch> <pnpm|composer> [limit] [--sanity]

A repository missing from the cache is fetched there, one commit at a time. `--sanity` starts
from the maintainer's merged lock file. pnpm should leave it as it is, and Composer is run with
`--lock`, which resolves with every package held to its lock. Either way the result should be
the maintainer's set, and a failure means the tool cannot load the merge's own resolution here.

Composer must find the plugin: `COMPOSER_HOME` names a home where `cotonet/soak-time` is
installed globally and allowed.
"""

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from precondition_library.bench import lock_actions as la

FILES = {"pnpm": "pnpm-lock.yaml", "composer": "composer.lock"}
PNPM_FALLBACK = "10.28.0"
PLATFORM = re.compile(r"^(php|php-64bit|hhvm|ext-.*|lib-.*|composer|composer-.*)$")


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=True, check=True
    ).stdout


def repository(hosts: Path, repo: str, tip: str, shas: list[str]) -> Path:
    """The study's cache of `repo`. If it is missing, a bare repository is made there, and each
    commit the case needs is fetched alone (`--depth=1`)."""
    path = hosts / f"{tip}-1000000.git"
    if not path.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
        git(path, "remote", "add", "origin", f"https://github.com/{repo}.git")
    for sha in shas:
        if subprocess.run(
            ["git", "-C", str(path), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True
        ).returncode:
            git(path, "fetch", "-q", "--depth=1", "--no-tags", "origin", sha)
    return path


# --- pnpm ----------------------------------------------------------------------------------


def pnpm_version(tree: Path, folder: Path) -> str:
    for manifest in (folder / "package.json", tree / "package.json"):
        if not manifest.exists():
            continue
        data = json.loads(manifest.read_text())
        declared = data.get("packageManager") or ""
        engine = (data.get("devEngines") or {}).get("packageManager") or {}
        if declared.startswith("pnpm@"):
            version = declared[len("pnpm@") :]
        elif isinstance(engine, dict) and engine.get("name") == "pnpm":
            version = engine.get("version") or ""
        else:
            continue
        version = version.split("+", 1)[0]
        if re.fullmatch(r"\d+\.\d+\.\d+", version):
            major, minor, _ = (int(x) for x in version.split("."))
            if (major, minor) >= (10, 16):
                return version
    return PNPM_FALLBACK


def pnpm_binary(version: str, scratch: Path) -> Path:
    """pnpm `version`, installed into `<scratch>/pnpms/` without running its install script.
    pnpm 12 and later ship a native binary in `@pnpm/exe.<platform>`, which that script would
    link; it is called directly."""
    prefix = scratch / "pnpms" / version
    modules = prefix / "node_modules"
    if not (modules / "pnpm").exists():
        subprocess.run(
            ["npm", "install", "--silent", "--ignore-scripts", "--no-audit", "--no-fund",
             "--prefix", str(prefix), f"pnpm@{version}"],
            cwd=scratch, check=True,
        )  # fmt: skip
    native = modules / "@pnpm" / "exe.linux-x64" / "pnpm"
    return native if native.exists() else modules / ".bin" / "pnpm"


def run_pnpm(tree: Path, folder: Path, minutes: int, scratch: Path) -> tuple[bool, str]:
    version = pnpm_version(tree, folder)
    ran = subprocess.run(
        [str(pnpm_binary(version, scratch)), "install", "--lockfile-only", "--ignore-scripts",
         "--no-frozen-lockfile", f"--config.minimum-release-age={minutes}",
         "--reporter=append-only"],
        cwd=folder, capture_output=True, text=True, timeout=900,
        env={**os.environ, "CI": "1", "npm_config_store_dir": str(scratch / "pnpm-store")},
    )  # fmt: skip
    if ran.returncode == 0:
        return True, f" (pnpm {version})"
    errors = [x.strip() for x in (ran.stdout + ran.stderr).splitlines() if "ERR_PNPM" in x]
    return False, f"pnpm {version}: " + (errors[:1] or [ran.stderr.strip()[-160:]])[0][:160]


# --- Composer ------------------------------------------------------------------------------


def requirements(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    data = json.loads(text)
    found = {}
    for key in ("require", "require-dev"):
        for name, constraint in (data.get(key) or {}).items():
            if not PLATFORM.match(name.lower()):
                found[name.lower()] = f"{key} {constraint}"
    return found


def to_update(side_manifest: str | None, merged_manifest: str | None) -> list[str]:
    side, merged = requirements(side_manifest), requirements(merged_manifest)
    return sorted(n for n in side.keys() | merged.keys() if side.get(n) != merged.get(n))


def branch_pinned(lock_text: str) -> list[str]:
    data = json.loads(lock_text)
    names = []
    for key in ("packages", "packages-dev"):
        for package in data.get(key) or []:
            version = str(package.get("version", ""))
            if version.startswith("dev-") or version.endswith("-dev"):
                names.append(package["name"])
    return sorted(set(names))


def run_composer(folder: Path, hours: int, update: list[str] | None) -> tuple[bool, str]:
    """`update` None means `--lock` (the sanity run). An empty list means nothing to run."""
    if update == []:
        return True, " (nothing to update)"
    manifest = folder / "composer.json"
    if not manifest.exists():
        return False, "no composer.json beside the lock file in the merge's tree"
    data = json.loads(manifest.read_text())
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    lock = folder / "composer.lock"
    exempt = branch_pinned(lock.read_text()) if lock.exists() else []
    data["extra"] = {**extra, "soak-time-hours": hours, "soak-time-whitelist": exempt}
    manifest.write_text(json.dumps(data, indent=4))
    base = ["composer", "update", "--no-install", "--no-scripts", "--no-audit", "--no-interaction",
            "--no-progress"]  # fmt: skip
    base += ["--lock"] if update is None else ["-W", "--minimal-changes", *update]
    note = ""
    for platform in (
        ["--ignore-platform-req=ext-*", "--ignore-platform-req=lib-*"],
        ["--ignore-platform-reqs"],
    ):
        ran = subprocess.run(
            [*base, *platform], cwd=folder, capture_output=True, text=True, timeout=900,
            env={**os.environ, "COMPOSER_ALLOW_SUPERUSER": "1", "COMPOSER_NO_INTERACTION": "1"},
        )  # fmt: skip
        if ran.returncode == 0:
            return True, note
        if "your php version" not in ran.stderr.lower():
            break
        note = " (php ignored)"
    lines = [x.strip() for x in ran.stderr.splitlines() if x.strip()]
    exception = [b for a, b in zip(lines, lines[1:]) if a.startswith("In ") and "line" in a]
    problem = next(
        (x for x in lines if x.startswith("- ") and "satisfiable by" not in x),
        next(
            (x for x in lines if "curl error" in x or "could not" in x.lower()),
            (exception or lines or [""])[-1],
        ),
    )
    if problem.startswith("[") and exception:  # an exception's class, then its message
        problem = next((b for a, b in zip(lines, lines[1:]) if a == problem), problem)
    return False, problem[:160]


# --- the pilot -----------------------------------------------------------------------------


def main() -> None:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    study, hosts, scratch, tool = Path(args[0]), Path(args[1]), Path(args[2]).resolve(), args[3]
    limit = int(args[4]) if len(args) > 4 else 10**9
    sanity = "--sanity" in flags
    scratch.mkdir(parents=True, exist_ok=True)
    hosts.mkdir(parents=True, exist_ok=True)
    m = json.loads((study / "manifest.json").read_text())
    tips = {r["repo"]: r["tip"] for r in m["repositories"]}
    cases = {c["index"]: c for c in m["cases"]}
    rows = []
    for line in (study / "labels.jsonl").read_text().splitlines():
        row = json.loads(line)
        for f in row["files"]:
            if f["path"].rsplit("/", 1)[-1] == FILES[tool] and not any(
                r["reproduces"] for r in f["results"]
            ):
                rows.append((row, cases[row["index"]], f))
    count: Counter = Counter()
    now = dt.datetime.now(dt.UTC)
    for row, c, f in rows[:limit]:
        repo = repository(hosts, c["repo"], tips[c["repo"]], [c["merge"], c["first"], c["second"]])
        when = git(repo, "log", "-1", "--format=%cI", c["merge"]).strip()
        age = now - dt.datetime.fromisoformat(when)
        merged_text = la._show(repo, c["merge"], f["path"]) or ""
        merged = la.packages(f["path"], merged_text) or set()
        manifest_path = f["path"][: -len("composer.lock")] + "composer.json"
        outcome = {}
        for side in ("merge",) if sanity else ("first", "second"):
            start = merged_text if sanity else la._show(repo, c[side], f["path"])
            with tempfile.TemporaryDirectory(dir=scratch) as tmp:
                tree = Path(tmp) / "tree"
                tree.mkdir()
                la._checkout(repo, c["merge"], tree)  # as committed, attributes aside
                lock = tree / f["path"]
                if start is None:
                    lock.unlink(missing_ok=True)
                else:
                    lock.write_text(start)
                try:
                    if tool == "pnpm":
                        ok, note = run_pnpm(
                            tree, lock.parent, int(age.total_seconds() // 60), scratch
                        )
                    else:
                        update = (
                            None
                            if sanity
                            else to_update(
                                la._show(repo, c[side], manifest_path),
                                la._show(repo, c["merge"], manifest_path),
                            )
                        )
                        ok, note = run_composer(
                            lock.parent, int(age.total_seconds() // 3600), update
                        )
                except subprocess.TimeoutExpired:
                    ok, note = False, "timeout"
                got = la.packages(f["path"], lock.read_text()) if ok and lock.exists() else None
            if got is None:
                outcome[side] = f"failed: {note}"
            elif got == merged:
                outcome[side] = "reproduces" + note
            else:
                jaccard = len(got & merged) / len(got | merged) if got | merged else 1.0
                outcome[side] = f"jaccard {jaccard:.3f}" + note
        count["files"] += 1
        count["reproduced from some side"] += any(
            v.startswith("reproduces") for v in outcome.values()
        )
        count["tool failed on every side"] += all(v.startswith("failed") for v in outcome.values())
        print(row["index"], c["repo"], f["path"], when[:10], outcome, flush=True)
    print(study.name, tool, "sanity" if sanity else "", dict(count))


if __name__ == "__main__":
    main()
