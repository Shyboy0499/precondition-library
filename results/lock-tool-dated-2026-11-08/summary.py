"""The tables of `tool_dated.py`'s logs.

    python -I results/lock-tool-dated-2026-11-08/summary.py results/lock-tool-dated-2026-11-08

Each log line is one file: its case, repository, path, merge date and the outcome from each
side. A failure is put under one cause, read from the tool's message.
"""

import ast
import re
import sys
from collections import Counter
from pathlib import Path

CAUSES = (
    ("a branch dependency (dev-*): only its current head is served", r"dev-|\.x-dev|-dev\b"),
    ("a host the network policy blocks", r"403|curl error 56|Forbidden"),
    ("a package outside the update is held to its lock", r"locked to version .* not requested"),
    ("no composer.json beside the lock file", r"no composer\.json"),
    ("the declared pnpm predates minimumReleaseAge", r"UNSUPPORTED_ENGINE"),
    ("Composer's own error on an old lock file", r"Overwriting requires|without a lock file"),
    ("the manifest requires a Composer version", r"requires composer "),
)


def cause(message: str) -> str:
    for label, pattern in CAUSES:
        if re.search(pattern, message):
            return label
    return "the requirements do not resolve with the date's versions"


def read(log: Path) -> list[tuple[int, str, str, dict[str, str]]]:
    rows = []
    for line in log.read_text("utf-8").splitlines():
        match = re.match(r"^(\d+) (\S+) (\S+) (\S+) (\{.*\})$", line)
        if match:
            rows.append((int(match[1]), match[2], match[3], ast.literal_eval(match[5])))
    return rows


def main() -> None:
    folder = Path(sys.argv[1])
    for tool in ("composer", "pnpm"):
        for kind in ("sanity", "run"):
            title = "sanity (the merged lock file)" if kind == "sanity" else "from each side"
            print(f"## {tool}, {title}")
            print("| study | files | reproduced (some side) | near only | failed on every side |")
            print("| --- | ---: | ---: | ---: | ---: |")
            causes: Counter = Counter()
            untouched: Counter = Counter()
            jaccards: list[float] = []
            total = Counter()
            for study in ("study-3", "study-4", "study-5"):
                suffix = ".sanity.log" if kind == "sanity" else ".log"
                log = folder / f"{study}.{tool}{suffix}"
                if not log.exists():
                    continue
                rows = read(log)
                counts = Counter()
                for _, _, _, outcome in rows:
                    values = list(outcome.values())
                    counts["files"] += 1
                    if any(v.startswith("reproduces") for v in values):
                        counts["reproduced"] += 1
                    elif any(v.startswith("jaccard") for v in values):
                        counts["near"] += 1
                        jaccards.append(
                            max(float(v.split()[1]) for v in values if v.startswith("jaccard"))
                        )
                    else:
                        counts["failed"] += 1
                    for v in values:
                        if v.startswith("failed"):
                            causes[cause(v)] += 1
                        if "nothing to update" in v:
                            untouched["sides"] += 1
                total.update(counts)
                print(
                    f"| {study} | {counts['files']} | {counts['reproduced']} | {counts['near']} "
                    f"| {counts['failed']} |"
                )
            print(
                f"| **all** | **{total['files']}** | **{total['reproduced']}** "
                f"| **{total['near']}** | **{total['failed']}** |"
            )
            if jaccards:
                jaccards.sort()
                print(f"near only: median best Jaccard {jaccards[len(jaccards) // 2]:.3f}")
            if untouched:
                print(
                    f"sides whose lock file already fits the merged manifest: {untouched['sides']}"
                    " (none is the maintainer's set: the files were chosen for that)"
                )
            print("failed runs by cause (one per side):")
            for label, n in causes.most_common():
                print(f"  {n} x {label}")
            print()


if __name__ == "__main__":
    main()
