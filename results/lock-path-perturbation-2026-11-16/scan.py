"""Every precondition in every committed library that recognises lock files by a fixed list of names.

Run from the repository root:

    python results/lock-path-perturbation-2026-11-16/scan.py > scan.json

`any_lock_suffix` says whether the probe also accepts any name ending in `.lock` (a glob, a
regular expression or a Python suffix test), so that an unseen `*.lock` name still counts.
"""

import json
import re
import sys
from pathlib import Path

import yaml

# Two or more of these names in one probe means it carries a closed list of lock-file names.
NAMES = [
    "deps.lock", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "poetry.lock", "Pipfile.lock", "uv.lock", "go.sum", "Gemfile.lock",
    "composer.lock",
]


# `*.lock`, `[^/]*\.lock`, `[^/]+\.lock`, or Python's `.endswith(".lock")`.
SUFFIX = re.compile(r'\*\.lock|\[\^/\][*+]\\?\.lock|endswith\("\.lock"\)')


def named(probe: str) -> list[str]:
    plain = probe.replace("\\.", ".")
    return [n for n in NAMES if n in plain]


def main() -> None:
    hits = []
    libraries = sorted({p.parent.parent for p in Path("results").glob("*/**/program.yaml")
                        if p.parent.parent.name.startswith("library")})
    for library in libraries:
        for program in sorted(library.glob("*/program.yaml")):
            spec = yaml.safe_load(program.read_text(encoding="utf-8"))
            for pre in spec.get("preconditions") or []:
                found = named(pre.get("probe") or "")
                if len(found) >= 2:
                    hits.append({"library": str(library), "program": program.parent.name,
                                 "precondition": pre["name"], "names": found,
                                 "any_lock_suffix": bool(SUFFIX.search(pre["probe"])),
                                 "probe": pre["probe"], "expect_exit": pre.get("expect_exit")})
    json.dump({"libraries": len(libraries), "hits": hits}, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
