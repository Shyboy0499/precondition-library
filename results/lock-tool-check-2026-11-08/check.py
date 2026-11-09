"""The ecosystem's own consistency check, as a second oracle beside the maintainer's merge (#297).
Exploratory: it runs on studies 3, 4 and 5's conflicts, which have been seen.

Study 3's oracle asks whether a resolution is the maintainer's package set. This one asks the
ecosystem's tool whether a lock file is consistent with the merge's manifests. It can only judge
a real lock file, so it judges three per conflicted file, each put into the merge's own tree as
committed (`lock_actions._checkout`):

- the maintainer's merged lock file (a control: a tool's check should pass it);
- the first parent's lock file (study 3's `take_local`);
- the second parent's (`take_upstream`).

The checks, none of which installs a package or runs a package's code:

- **npm** (`package-lock.json`): `npm ci --dry-run --ignore-scripts --engine-strict=false`. npm
  refuses with `EUSAGE` when the lock file and `package.json` are out of sync. The engine check
  guards installation, not consistency, so it is off (as in the npm pilot).
- **pnpm** (`pnpm-lock.yaml`): `pnpm install --frozen-lockfile --lockfile-only --ignore-scripts`,
  with the pnpm version the merge's `package.json` declares (as in
  `results/lock-tool-dated-2026-11-08/tool_dated.py`). pnpm refuses with
  `ERR_PNPM_OUTDATED_LOCKFILE` (`ERR_PNPM_FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE` in later
  versions) when the lock file does not match the manifests, and with
  `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH` when it was written under other settings (overrides,
  patches, peer handling) than the merge's; the latter is reported as
  `inconsistent: settings`. pnpm 11 also checks every locked version against its release-age
  policy, which reads registry metadata, so this check is not offline.
- **Composer** (`composer.lock`), offline (`COMPOSER_DISABLE_NETWORK=1`), at two levels:
  - *hash*: `composer validate` says whether the lock file's `content-hash` matches
    `composer.json`. A stale hash is a warning to Composer, not an error.
  - *satisfies*: `composer install --dry-run` says whether the locked set satisfies the root
    requirements and installs, platform requirements aside (`--ignore-platform-reqs`). Composer
    lists each root requirement the lock file misses or does not satisfy, then says the files
    were "incorrectly merged".

The verdict is `consistent`, `inconsistent` (the tool's own refusal for this reason), or
`error: <code>` (the tool failed for another reason, such as the network).

    PYTHONPATH=src python results/lock-tool-check-2026-11-08/check.py \\
        <study> <its real-hosts cache> <scratch> <out.jsonl> [composer|npm|pnpm ...]

A repository missing from the cache is fetched there, one commit at a time.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from precondition_library.bench import lock_actions as la

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lock-tool-dated-2026-11-08"))
from tool_dated import pnpm_binary, pnpm_version, repository  # noqa: E402

FILES = {"composer.lock": "composer", "package-lock.json": "npm", "pnpm-lock.yaml": "pnpm"}
OUTDATED = ("ERR_PNPM_OUTDATED_LOCKFILE", "ERR_PNPM_FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE")


def run(argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=900, env={**os.environ, **env}
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", "timeout")
    except OSError as error:
        return subprocess.CompletedProcess(argv, 126, "", f"cannot run the tool: {error.strerror}")


def check_npm(folder: Path, scratch: Path) -> dict[str, str]:
    ran = run(
        ["npm", "ci", "--dry-run", "--ignore-scripts", "--no-audit", "--no-fund",
         "--no-update-notifier", "--engine-strict=false"],
        folder, {"npm_config_cache": str(scratch / "npm-cache")},
    )  # fmt: skip
    if ran.returncode == 0:
        return {"verdict": "consistent"}
    code = re.search(r"npm error code (\S+)", ran.stderr)
    code = code.group(1) if code else ran.stderr.strip()[-80:]
    in_sync = "in sync" in ran.stderr
    return {"verdict": "inconsistent" if code == "EUSAGE" and in_sync else f"error: {code}"}


def check_pnpm(tree: Path, folder: Path, scratch: Path) -> dict[str, str]:
    version = pnpm_version(tree, folder)
    ran = run(
        [str(pnpm_binary(version, scratch)), "install", "--frozen-lockfile", "--lockfile-only",
         "--ignore-scripts", "--reporter=append-only"],
        folder, {"CI": "1", "npm_config_store_dir": str(scratch / "pnpm-store")},
    )  # fmt: skip
    if ran.returncode == 0:
        return {"verdict": "consistent", "pnpm": version}
    text = ran.stdout + ran.stderr
    code = re.search(r"ERR_PNPM_[A-Z0-9_]+", text)
    code = code.group(0) if code else text.strip()[-80:]
    if code in OUTDATED:
        verdict = "inconsistent"
    elif code == "ERR_PNPM_LOCKFILE_CONFIG_MISMATCH":
        verdict = "inconsistent: settings"
    else:
        verdict = f"error: {code}"
    return {"verdict": verdict, "pnpm": version}


def check_composer(folder: Path, scratch: Path) -> dict[str, str]:
    env = {
        "COMPOSER_HOME": str(scratch / "composer-home"),
        "COMPOSER_CACHE_DIR": str(scratch / "composer-home" / "cache"),
        "COMPOSER_DISABLE_NETWORK": "1",
        "COMPOSER_ALLOW_SUPERUSER": "1",
        "COMPOSER_NO_INTERACTION": "1",
    }
    validate = run(
        ["composer", "validate", "--no-check-all", "--no-check-publish", "--no-check-version",
         "--no-interaction"],
        folder, env,
    )  # fmt: skip
    stale = "lock file is not up to date" in (validate.stdout + validate.stderr)
    install = run(
        ["composer", "install", "--dry-run", "--no-scripts", "--no-plugins",
         "--no-interaction", "--ignore-platform-reqs", "--no-progress"],
        folder, env,
    )  # fmt: skip
    text = install.stdout + install.stderr
    if install.returncode == 0:
        satisfies = "consistent"
    elif (
        "incorrectly merged or the composer.json file is manually edited" in text
        or "does not satisfy" in text
        or "is not present in the lock file" in text
        or "compatible set of packages" in text
        or "could not be resolved" in text
    ):
        satisfies = "inconsistent"
    else:
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        satisfies = f"error: {(lines or [''])[-1][:80]}"
    return {"hash": "inconsistent" if stale else "consistent", "verdict": satisfies}


def main() -> None:
    args = sys.argv[1:]
    study, hosts, scratch, out = (
        Path(args[0]),
        Path(args[1]),
        Path(args[2]).resolve(),
        Path(args[3]),
    )
    tools = set(args[4:]) or set(FILES.values())
    scratch.mkdir(parents=True, exist_ok=True)
    hosts.mkdir(parents=True, exist_ok=True)
    m = json.loads((study / "manifest.json").read_text())
    tips = {r["repo"]: r["tip"] for r in m["repositories"]}
    cases = {c["index"]: c for c in m["cases"]}
    rows, tally = [], Counter()
    for line in (study / "labels.jsonl").read_text().splitlines():
        row = json.loads(line)
        files = [f for f in row["files"] if FILES.get(f["path"].rsplit("/", 1)[-1]) in tools]
        if not files:
            continue
        c = cases[row["index"]]
        repo = repository(hosts, c["repo"], tips[c["repo"]], [c["merge"], c["first"], c["second"]])
        with tempfile.TemporaryDirectory(dir=scratch) as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            la._checkout(repo, c["merge"], tree)  # as committed, attributes aside
            for f in files:
                tool = FILES[f["path"].rsplit("/", 1)[-1]]
                lock = tree / f["path"]
                reproduces = {r["action"]: r["reproduces"] for r in f["results"]}
                verdicts = {}
                for side, commit in (("merge", c["merge"]), ("first", c["first"]),
                                     ("second", c["second"])):  # fmt: skip
                    text = la._show(repo, commit, f["path"])
                    if text is None:
                        verdicts[side] = {"verdict": "error: no lock file on this side"}
                        continue
                    lock.write_text(text)
                    if tool == "npm":
                        verdicts[side] = check_npm(lock.parent, scratch)
                    elif tool == "pnpm":
                        verdicts[side] = check_pnpm(tree, lock.parent, scratch)
                    else:
                        verdicts[side] = check_composer(lock.parent, scratch)
                    tally[(tool, side, verdicts[side]["verdict"].split(":")[0])] += 1
                lock.write_text(la._show(repo, c["merge"], f["path"]) or "")  # as merged
                result = {
                    "index": row["index"],
                    "repo": c["repo"],
                    "path": f["path"],
                    "tool": tool,
                    "check": verdicts,
                    "maintainer_set": {
                        "first": reproduces.get("take_local", False),
                        "second": reproduces.get("take_upstream", False),
                    },
                }
                rows.append(result)
                print(json.dumps(result, sort_keys=True), flush=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    for key, n in sorted(tally.items()):
        print(study.name, *key, n)


if __name__ == "__main__":
    main()
