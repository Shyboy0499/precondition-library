"""The `lockmerge` command.

lockmerge install [--global]          set lockmerge up as git's merge driver for lock files
lockmerge driver %O %A %B %P          what git runs during a merge (set up by `install`)
lockmerge resolve [PATH ...]          finish lock-file conflicts already in the working tree
lockmerge check BASE OURS THEIRS      try a merge on three files and print the result
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from lockmerge import SUPPORTED, Declined, Merged, __version__, merge, supported

DRIVER = "lockmerge"


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if check and done.returncode != 0:
        raise SystemExit(f"lockmerge: git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def _say(message: str) -> None:
    print(f"lockmerge: {message}", file=sys.stderr)


def _report(path: str, outcome: Declined) -> None:
    _say(f"left {path} conflicted:")
    for reason in outcome.reasons[:20]:
        print(f"  - {reason}", file=sys.stderr)
    if len(outcome.reasons) > 20:
        print(f"  - ... and {len(outcome.reasons) - 20} more", file=sys.stderr)
    if Path(path).name == "composer.lock":
        print("  Resolve composer.json, then `composer update --lock`.", file=sys.stderr)
    else:
        print("  Resolve package.json, then `npm install` to regenerate it.", file=sys.stderr)


def _composer_json(lock_path: Path) -> str | None:
    """The merged `composer.json` beside a lock file, if it is readable and conflict-free."""
    candidate = lock_path.with_name("composer.json")
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None
    if "<<<<<<<" in text or ">>>>>>>" in text:
        return None
    return text


# --- driver -------------------------------------------------------------------------------


def driver(base: str, ours: str, theirs: str, path: str) -> int:
    """Git's merge-driver protocol: merge into `ours` in place; 0 when clean, 1 when the file
    is left with conflict markers, exactly as git's own merge would leave it."""
    texts = [Path(p).read_text(encoding="utf-8") for p in (base, ours, theirs)]
    outcome = merge(path, *texts)
    if isinstance(outcome, Merged):
        Path(ours).write_text(outcome.text, encoding="utf-8", newline="")
        _say(f"merged {path}")
        return 0
    subprocess.run(
        ["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", ours, base, theirs],
        check=False,
    )
    _report(path, outcome)
    return 1


# --- install ------------------------------------------------------------------------------


def _command() -> str:
    return f"{shlex.quote(sys.executable)} -m lockmerge driver %O %A %B %P"


def install(*, scope_global: bool, repo: Path) -> int:
    scope = ["--global"] if scope_global else []
    name = "lockmerge: merge lock files by package"
    _git("config", *scope, f"merge.{DRIVER}.name", name, cwd=repo)
    _git("config", *scope, f"merge.{DRIVER}.driver", _command(), cwd=repo)
    if scope_global:
        configured = _git("config", "--global", "core.attributesFile", check=False).strip()
        attributes = (
            Path(configured).expanduser()
            if configured
            else (Path.home() / ".config" / "git" / "attributes")
        )
    else:
        top = _git("rev-parse", "--show-toplevel", cwd=repo).strip()
        attributes = Path(top) / ".gitattributes"
    attributes.parent.mkdir(parents=True, exist_ok=True)
    existing = attributes.read_text(encoding="utf-8") if attributes.exists() else ""
    lines = [f"{name} merge={DRIVER}" for name in SUPPORTED]
    missing = [line for line in lines if line not in existing.splitlines()]
    if missing:
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        attributes.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")
    where = "for every repository (global)" if scope_global else f"in {repo}"
    _say(f"installed {where}; lock-file attributes in {attributes}")
    if not scope_global:
        _say("commit .gitattributes so your team's merges use it too (each person runs install)")
    return 0


# --- resolve ------------------------------------------------------------------------------


def _stage(number: int, path: str, top: Path) -> str:
    done = subprocess.run(
        ["git", "show", f":{number}:{path}"], cwd=top, capture_output=True, check=False
    )
    return done.stdout.decode("utf-8") if done.returncode == 0 else ""


def _changed_names(base: str, theirs: str) -> list[str]:
    """The Composer packages theirs added or moved since the base: what Composer's own guide
    says to `composer update` again on top of ours."""

    def records(text: str) -> dict[str, object]:
        data = json.loads(text) if text.strip() else {}
        return {
            p["name"]: p
            for section in ("packages", "packages-dev")
            for p in data.get(section) or []
        }

    before, after = records(base), records(theirs)
    return sorted(name for name, record in after.items() if before.get(name) != record)


def regenerate(path: str, stages: list[str], top: Path) -> bool:
    """Ours' lock file, brought in line with the merged manifest by the package manager itself,
    as npm and Composer document for conflicts a merge cannot settle. Needs the merged
    manifest in the working tree and the package manager on PATH; reaches its registry."""
    lock = top / path
    manifest = lock.with_name("composer.json" if lock.name == "composer.lock" else "package.json")
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        _say(f"cannot regenerate {path}: {manifest.name} is missing")
        return False
    if "<<<<<<<" in text or ">>>>>>>" in text:
        _say(f"cannot regenerate {path}: resolve {manifest.name} first")
        return False
    lock.write_text(stages[1], encoding="utf-8", newline="")
    if lock.name == "composer.lock":
        names = _changed_names(stages[0], stages[2])
        command = ["composer", "update", *names, "--no-install", "--no-scripts", "--no-plugins"]
        command.append("--no-interaction")
    else:
        command = ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit"]
        command.append("--no-fund")
    _say(f"regenerating {path}: {' '.join(command)}")
    try:
        done = subprocess.run(command, cwd=lock.parent, check=False)
    except FileNotFoundError:
        _say(f"cannot regenerate {path}: {command[0]} is not installed")
        return False
    return done.returncode == 0


def resolve(
    paths: Sequence[str], *, add: bool, repo: Path, regenerate_declined: bool = False
) -> int:
    top = Path(_git("rev-parse", "--show-toplevel", cwd=repo).strip())
    unmerged = sorted(
        {line.split("\t", 1)[1] for line in _git("ls-files", "-u", cwd=top).splitlines()}
    )
    targets = [p for p in unmerged if supported(p) and (not paths or p in paths)]
    if not targets:
        _say("no conflicted lock files")
        return 0
    failed = 0
    for path in targets:
        stages = [_stage(n, path, top) for n in (1, 2, 3)]
        composer_json = _composer_json(top / path) if Path(path).name == "composer.lock" else None
        outcome = merge(path, *stages, composer_json=composer_json)
        if isinstance(outcome, Merged):
            (top / path).write_text(outcome.text, encoding="utf-8", newline="")
            if add:
                _git("add", "--", path, cwd=top)
            _say(f"resolved {path}" + (" and staged it" if add else ""))
        elif regenerate_declined and regenerate(path, stages, top):
            if add:
                _git("add", "--", path, cwd=top)
            _say(
                f"regenerated {path} with the package manager (not merged: "
                f"{outcome.reasons[0] if outcome.reasons else 'declined'})"
            )
        else:
            failed += 1
            _report(path, outcome)
    return 1 if failed else 0


# --- check --------------------------------------------------------------------------------


def check(
    base: Path, ours: Path, theirs: Path, *, name: str, composer_json: Path | None, out: Path | None
) -> int:
    texts = [p.read_text(encoding="utf-8") if p.exists() else "" for p in (base, ours, theirs)]
    project = composer_json.read_text(encoding="utf-8") if composer_json else None
    outcome = merge(name, *texts, composer_json=project)
    if isinstance(outcome, Merged):
        if out:
            out.write_text(outcome.text, encoding="utf-8", newline="")
        else:
            sys.stdout.write(outcome.text)
        _say(f"would merge {name}")
        return 0
    _report(name, outcome)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lockmerge", description="Merge lock files by package; refuse when unsafe."
    )
    parser.add_argument("--version", action="version", version=f"lockmerge {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    p_install = commands.add_parser("install", help="set lockmerge up as git's merge driver")
    p_install.add_argument("--global", dest="scope_global", action="store_true")
    p_install.add_argument("--repo", type=Path, default=Path.cwd())

    p_driver = commands.add_parser("driver", help="the merge driver git runs (%%O %%A %%B %%P)")
    for name in ("base", "ours", "theirs", "path"):
        p_driver.add_argument(name)

    p_resolve = commands.add_parser("resolve", help="resolve conflicted lock files in place")
    p_resolve.add_argument("paths", nargs="*")
    p_resolve.add_argument("--no-add", dest="add", action="store_false")
    p_resolve.add_argument("--repo", type=Path, default=Path.cwd())
    p_resolve.add_argument(
        "--regenerate",
        action="store_true",
        help="when a file cannot be merged safely, start from ours and let npm or Composer "
        "bring it in line with the merged manifest (needs the registry)",
    )

    p_check = commands.add_parser("check", help="try a merge on three files")
    p_check.add_argument("base", type=Path)
    p_check.add_argument("ours", type=Path)
    p_check.add_argument("theirs", type=Path)
    p_check.add_argument("--name", help="the lock file's name (default: OURS's file name)")
    p_check.add_argument("--composer-json", type=Path)
    p_check.add_argument("-o", "--out", type=Path)

    args = parser.parse_args(argv)
    if args.command == "install":
        return install(scope_global=args.scope_global, repo=args.repo)
    if args.command == "driver":
        return driver(args.base, args.ours, args.theirs, args.path)
    if args.command == "resolve":
        return resolve(
            args.paths, add=args.add, repo=args.repo, regenerate_declined=args.regenerate
        )
    return check(
        args.base,
        args.ours,
        args.theirs,
        name=args.name or args.ours.name,
        composer_json=args.composer_json,
        out=args.out,
    )
