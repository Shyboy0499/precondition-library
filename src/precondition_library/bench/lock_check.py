"""The ecosystems' own consistency checks on a lock file in a tree (#297, study 6).

Each check asks the ecosystem's tool whether a lock file is consistent with the manifests beside
it, and none installs a package or runs a package's code:

* **npm** (`package-lock.json`): `npm ci --dry-run --ignore-scripts --engine-strict=false`. npm
  refuses with `EUSAGE` when the lock file and `package.json` are out of sync. The engine check
  guards installation, not consistency, so it is off.
* **pnpm** (`pnpm-lock.yaml`): `pnpm install --frozen-lockfile --lockfile-only --ignore-scripts`,
  with the pnpm version the tree's `package.json` declares (10.28.0 without one). pnpm refuses
  with `ERR_PNPM_OUTDATED_LOCKFILE` (`ERR_PNPM_FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE` in later
  versions) when the lock file does not match the manifests. It refuses with
  `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH` when the file was written under other settings, reported as
  `inconsistent: settings`.
* **Composer** (`composer.lock`), with no network: `composer validate` for the `content-hash`, and
  `composer install --dry-run --ignore-platform-reqs` for whether the locked set satisfies every
  root requirement and installs.

A verdict is `consistent`, `inconsistent` (the tool's own refusal for this reason) or
`error: <code>` (the tool failed for another reason). The code is the one
`results/lock-tool-check-2026-11-08/check.py` ran, made a library so study 6 can register it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

FILES = {"composer.lock": "composer", "package-lock.json": "npm", "pnpm-lock.yaml": "pnpm"}
"""The lock files a check exists for, and the tool that judges each."""

PNPM_FALLBACK = "10.28.0"
OUTDATED = ("ERR_PNPM_OUTDATED_LOCKFILE", "ERR_PNPM_FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE")
TIMEOUT = 900.0

Verdict = dict[str, str]


def tool_for(path: str) -> str | None:
    return FILES.get(path.rsplit("/", 1)[-1])


def kind(verdict: Verdict) -> str:
    """`consistent`, `inconsistent` or `error`, whatever the detail."""
    v = verdict["verdict"]
    if v == "consistent":
        return "consistent"
    return "inconsistent" if v.startswith("inconsistent") else "error"


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT,
            env={**os.environ, **env},
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", "timeout")
    except OSError as error:
        return subprocess.CompletedProcess(argv, 126, "", f"cannot run the tool: {error.strerror}")


# --- reading each tool's answer --------------------------------------------------------------


def npm_verdict(returncode: int, stderr: str) -> Verdict:
    if returncode == 0:
        return {"verdict": "consistent"}
    found = re.search(r"npm error code (\S+)", stderr)
    code = found.group(1) if found else stderr.strip()[-80:]
    if code == "EUSAGE" and "in sync" in stderr:
        return {"verdict": "inconsistent"}
    return {"verdict": f"error: {code}"}


def pnpm_verdict(returncode: int, output: str) -> Verdict:
    if returncode == 0:
        return {"verdict": "consistent"}
    found = re.search(r"ERR_PNPM_[A-Z0-9_]+", output)
    code = found.group(0) if found else output.strip()[-80:]
    if code in OUTDATED:
        return {"verdict": "inconsistent"}
    if code == "ERR_PNPM_LOCKFILE_CONFIG_MISMATCH":
        return {"verdict": "inconsistent: settings"}
    return {"verdict": f"error: {code}"}


def composer_verdict(validate_output: str, returncode: int, install_output: str) -> Verdict:
    stale = "lock file is not up to date" in validate_output
    if returncode == 0:
        satisfies = "consistent"
    elif any(
        phrase in install_output
        for phrase in (
            "incorrectly merged or the composer.json file is manually edited",
            "does not satisfy",
            "is not present in the lock file",
            "compatible set of packages",
            "could not be resolved",
        )
    ):
        satisfies = "inconsistent"
    else:
        satisfies = f"error: {composer_error(install_output)}"
    return {"hash": "inconsistent" if stale else "consistent", "verdict": satisfies}


_COMPOSER_THREW = re.compile(r"^In (\S+\.php) line (\d+):$")


def composer_error(output: str) -> str:
    """Where Composer failed, without its message. Composer prints an exception as
    `In <file>.php line <n>:`, then the message, then the command's usage line. The message often
    names packages, which no record writes, so an exception is recorded by the place Composer
    threw it, as npm's and pnpm's errors are by their codes. Output with no exception gives its
    last line that is not the usage line, cut to 80 characters."""
    lines = [x.strip() for x in output.splitlines() if x.strip()]
    for line in lines:
        threw = _COMPOSER_THREW.match(line)
        if threw:
            return f"{threw[1]} line {threw[2]}"
    told = [x for x in lines if not re.match(r"^[a-z-]+ \[--", x)]
    return (told or [""])[-1][:80]


# --- running each tool -----------------------------------------------------------------------


def pnpm_version(tree: Path, folder: Path) -> str:
    """The pnpm the folder's `package.json`, or the tree's, declares through `packageManager` or
    `devEngines.packageManager`, if it is 10.16 or later; otherwise `PNPM_FALLBACK`."""
    for manifest in (folder / "package.json", tree / "package.json"):
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        declared = data.get("packageManager") or ""
        engine = (data.get("devEngines") or {}).get("packageManager") or {}
        if isinstance(declared, str) and declared.startswith("pnpm@"):
            version = declared[len("pnpm@") :]
        elif isinstance(engine, dict) and engine.get("name") == "pnpm":
            version = str(engine.get("version") or "")
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
    pnpm 12 and later ship a native binary in `@pnpm/exe.<platform>`, called directly."""
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


def check(tree: Path, path: str, scratch: Path) -> Verdict:
    """The ecosystem's check of the lock file at `path` in `tree`, as it stands there."""
    tool = tool_for(path)
    folder = (tree / path).parent
    scratch.mkdir(parents=True, exist_ok=True)
    if tool == "npm":
        ran = _run(
            ["npm", "ci", "--dry-run", "--ignore-scripts", "--no-audit", "--no-fund",
             "--no-update-notifier", "--engine-strict=false"],
            folder, {"npm_config_cache": str(scratch / "npm-cache")},
        )  # fmt: skip
        return npm_verdict(ran.returncode, ran.stderr)
    if tool == "pnpm":
        version = pnpm_version(tree, folder)
        ran = _run(
            [str(pnpm_binary(version, scratch)), "install", "--frozen-lockfile", "--lockfile-only",
             "--ignore-scripts", "--reporter=append-only"],
            folder, {"CI": "1", "npm_config_store_dir": str(scratch / "pnpm-store")},
        )  # fmt: skip
        return {**pnpm_verdict(ran.returncode, ran.stdout + ran.stderr), "pnpm": version}
    if tool == "composer":
        env = {
            "COMPOSER_HOME": str(scratch / "composer-home"),
            "COMPOSER_CACHE_DIR": str(scratch / "composer-home" / "cache"),
            "COMPOSER_DISABLE_NETWORK": "1",
            "COMPOSER_ALLOW_SUPERUSER": "1",
            "COMPOSER_NO_INTERACTION": "1",
        }
        validate = _run(
            ["composer", "validate", "--no-check-all", "--no-check-publish",
             "--no-check-version", "--no-interaction"],
            folder, env,
        )  # fmt: skip
        install = _run(
            ["composer", "install", "--dry-run", "--no-scripts", "--no-plugins",
             "--no-interaction", "--ignore-platform-reqs", "--no-progress"],
            folder, env,
        )  # fmt: skip
        return composer_verdict(
            validate.stdout + validate.stderr, install.returncode, install.stdout + install.stderr
        )
    raise ValueError(f"no check for {path}")
