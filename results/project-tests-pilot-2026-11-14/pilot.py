"""Can a project's own tests judge a lock-file resolution? A pilot (#297's third oracle).

The owner approved a sandboxed pilot on 2026-11-13: a few repositories whose test suites can
run without databases or services, a handful of merges, install scripts off, tests offline. It
reports what is feasible. It is not a study, and it decides nothing.

For each case (a merge whose conflict includes a lock file) it builds three trees:
- **maintainer:** the merge's tree, as committed;
- **first** and **second:** the same tree with the conflicted lock file replaced by that
  parent's.

The other files, manifests included, are the maintainer's, so the question is the one #297
asks: does this lock file work in the project as the maintainer merged it? In each tree it:
1. **installs** with the network on and every lifecycle script off:
   - npm: `npm ci --ignore-scripts`;
   - Composer: `composer install --no-scripts --no-plugins`, retried with
     `--ignore-platform-reqs` if the platform refuses;
2. **runs the project's tests with no network** (`unshare -n`, loopback only), under a time
   limit, with the command in `COMMANDS`.

The maintainer's tree is tested twice, to see whether the suite is deterministic.

Trees are written from the commit's blobs (`read-tree` and `checkout-index`), not with
`git archive`, which leaves out files marked `export-ignore`, test directories among them.

    python -I results/project-tests-pilot-2026-11-14/pilot.py <out.jsonl> <scratch> [npm|composer]

Appends one row per tree and attempt, and resumes from the rows already written. If the
maintainer's own tree does not install, or its tests time out, the case's other trees are
skipped. Test output is reduced to the exit code, the duration, and the suite's own summary
lines, matched by `SUMMARY`. No package name is written; a failing run's last lines go to the
local log only.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 1200
CASES = (
    # (study, repository, case index, lock file): studies 3 and 6, one case per repository,
    # chosen so that exactly one parent's file is the maintainer's set.
    ("study-6", "louislam/uptime-kuma", 105, "package-lock.json"),
    ("study-6", "nextcloud/nextcloud-vue", 326, "package-lock.json"),
    ("study-3", "node-red/node-red", 288, "package-lock.json"),
    ("study-3", "getgrav/grav", 77, "composer.lock"),
    ("study-6", "filamentphp/filament", 16, "composer.lock"),
)
COMMANDS = {
    # The project's own unit tests, from its package.json or composer.json scripts; end-to-end
    # suites that need a browser or services are left out.
    "louislam/uptime-kuma": ["npm", "run", "test-backend"],
    "nextcloud/nextcloud-vue": ["npx", "--no-install", "vitest", "run"],
    "node-red/node-red": ["npx", "--no-install", "grunt", "simplemocha:core"],
    "getgrav/grav": ["vendor/bin/codecept", "run", "unit"],
    "filamentphp/filament": [
        "vendor/bin/pest", "--configuration=phpunit.sqlite.xml", "--exclude-group=commands",
    ],
}  # fmt: skip
STUDIES = {
    "study-6": ("tool-precondition-2026-11-09", "files.jsonl"),
    "study-3": ("lock-oracle-2026-11-02", None),
}
# Run in a new network namespace with only the loopback interface, brought up as
# `ip link set lo up` would: tests can serve and reach 127.0.0.1, and nothing else.
LOOPBACK = (
    "import fcntl, os, socket, struct, sys\n"
    "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
    "flags = struct.unpack('16sh', fcntl.ioctl(s, 0x8913, struct.pack('16sh', b'lo', 0)))[1]\n"
    "fcntl.ioctl(s, 0x8914, struct.pack('16sh', b'lo', flags | 1))\n"
    "os.execvp(sys.argv[1], sys.argv[1:])\n"
)
SUMMARY = re.compile(
    r"(^\s*(Tests?|Test Files|Assertions)\b.*$|^\s*ℹ (tests|pass|fail|skipped|todo) \d+.*$|"
    r"^\s*\d+ (passing|failing|pending)\b.*$|^OK \(.*$|^FAILURES!.*$|^ERRORS!.*$)",
    re.MULTILINE,
)


def git(repo: Path, *argv: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "--git-dir", str(repo), *argv], check=True, **kwargs)


def case_record(study: str, repo: str, index: int, path: str) -> tuple[dict, dict]:
    folder, files = STUDIES[study]
    manifest = json.loads((ROOT / "results" / folder / "manifest.json").read_text("utf-8"))
    case = next(c for c in manifest["cases"] if c["repo"] == repo and c["index"] == index)
    if files:
        rows = (ROOT / "results" / folder / files).read_text("utf-8").splitlines()
        row = next(r for r in map(json.loads, rows) if r["index"] == index and r["path"] == path)
        label = {"first": row["local_reproduces"], "second": row["upstream_reproduces"]}
    else:
        rows = (ROOT / "results" / "lock-tool-check-2026-11-08" / f"{study}.jsonl").read_text(
            "utf-8"
        )
        row = next(
            r
            for r in map(json.loads, rows.splitlines())
            if r["index"] == index and r["path"] == path
        )
        label = row["maintainer_set"]
    return case, label


def repository(cache: Path, repo: str, shas: list[str]) -> Path:
    path = cache / (repo.replace("/", "__") + ".git")
    if not path.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
        git(path, "remote", "add", "origin", f"https://github.com/{repo}.git")
    git(path, "fetch", "-q", "--depth=1", "--no-tags", "origin", *shas)
    return path


def tree(repo: Path, commit: str, into: Path, lock: str, lock_from: str) -> None:
    """The commit's tree as committed, with `lock` taken from `lock_from`."""
    into.mkdir(parents=True)
    index = into.parent / f"{into.name}.index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    git(repo, "read-tree", commit, env=env)
    git(repo, "--work-tree", str(into), "checkout-index", "-a", "-f", env=env)
    index.unlink()
    blob = git(repo, "show", f"{lock_from}:{lock}", capture_output=True).stdout
    (into / lock).write_bytes(blob)


def run(argv: list[str], cwd: Path, env: dict, offline: bool) -> tuple[int, float, str]:
    """Run in a new process group, so that a timeout kills every process the command
    started, not only the first."""
    started = time.monotonic()
    command = (["unshare", "-n", sys.executable, "-I", "-c", LOOPBACK] if offline else []) + argv
    process = subprocess.Popen(
        command, cwd=cwd, env={**os.environ, **env}, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
    )  # fmt: skip
    try:
        output, _ = process.communicate(timeout=TIMEOUT)
        code = process.returncode
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        code = 124
    text = (output or b"").decode("utf-8", "replace")
    return code, round(time.monotonic() - started, 1), text


def install(folder: Path, tool: str, scratch: Path) -> tuple[bool, str]:
    if tool == "npm":
        env = {"npm_config_cache": str(scratch / "npm-cache"), "CI": "1"}
        for _ in range(2):  # once more on failure: npm's git cache can race with itself
            code, _, out = run(
                ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], folder, env, False
            )
            if code == 0:
                break
        found = re.search(r"npm error code (\S+)", out)
        return code == 0, "ok" if code == 0 else f"npm error {found[1] if found else code}"
    env = {
        "COMPOSER_HOME": str(scratch / "composer-home"),
        "COMPOSER_ALLOW_SUPERUSER": "1",
        "COMPOSER_NO_INTERACTION": "1",
    }
    base = ["composer", "install", "--no-scripts", "--no-plugins", "--no-progress"]
    code, _, out = run(base, folder, env, False)
    if code == 0:
        return True, "ok"
    code, _, out = run([*base, "--ignore-platform-reqs"], folder, env, False)
    return code == 0, "ok, platform requirements ignored" if code == 0 else f"composer {code}"


def main() -> None:
    out, scratch = Path(sys.argv[1]), Path(sys.argv[2])
    only = sys.argv[3] if len(sys.argv) > 3 else None  # "npm" or "composer"
    scratch.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text("utf-8").splitlines():
            r = json.loads(line)
            done.add((r["repo"], r["variant"], r["attempt"]))
    for study, repo_name, index, lock in CASES:
        tool = "npm" if lock.endswith("package-lock.json") else "composer"
        if only and tool != only:
            continue
        case, label = case_record(study, repo_name, index, lock)
        repo = repository(
            scratch / "cache", repo_name, [case["merge"], case["first"], case["second"]]
        )
        for variant, attempt in (("maintainer", 1), ("maintainer", 2), ("first", 1), ("second", 1)):
            if (repo_name, variant, attempt) in done:
                continue
            where = scratch / "trees" / f"{repo_name.replace('/', '__')}-{variant}-{attempt}"
            if where.exists():
                shutil.rmtree(where)
            source = case["merge"] if variant == "maintainer" else case[variant]
            tree(repo, case["merge"], where, lock, source)
            folder = (where / lock).parent
            ok, note = install(folder, tool, scratch)
            row = {
                "study": study, "repo": repo_name, "index": index, "path": lock,
                "variant": variant, "attempt": attempt,
                "maintainers_set": True if variant == "maintainer" else label[variant],
                "install": note,
            }  # fmt: skip
            if ok:
                env = {"CI": "1", "TZ": "UTC", "NO_COLOR": "1", "FORCE_COLOR": "0"}
                code, seconds, output = run(COMMANDS[repo_name], folder, env, True)
                row |= {
                    "exit": code,
                    "seconds": seconds,
                    "summary": [m.group(0).strip()[:160] for m in SUMMARY.finditer(output)][-6:],
                }
                if code:
                    # The last lines of a failing run go to the local log only: they may name
                    # packages.
                    print(f"TAIL {repo_name} {variant}: {output.strip()[-1500:]}", file=sys.stderr)
            with out.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            print(json.dumps(row), flush=True)
            shutil.rmtree(where)
            if variant == "maintainer" and attempt == 1 and (not ok or row["exit"] == 124):
                # The maintainer's own tree cannot be installed or tested in time, so the
                # project's tests cannot judge the parents' files here either.
                break


if __name__ == "__main__":
    main()
