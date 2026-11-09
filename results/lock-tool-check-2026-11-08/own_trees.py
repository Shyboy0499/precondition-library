"""Was a maintainer's inconsistent merge inherited, or made by the merge? (#297, exploratory)

`check.py` found one maintainer merge in seven committed in a state the ecosystem's tool
rejects. That figure means little without a base rate: how often is a lock file inconsistent at
an ordinary commit? This checks each conflicted file's lock file at the merge's two parents and
at their merge base, **each in its own commit's tree**, with the same checks as `check.py`.

- A parent or base whose own lock file fails is a commit that already shipped an inconsistent
  lock file; the base rate.
- A merge that fails while both parents pass in their own trees is an inconsistency the merge
  introduced.

    PYTHONPATH=src python results/lock-tool-check-2026-11-08/own_trees.py \\
        <study> <its real-hosts cache> <scratch> <out.jsonl>
"""

import json
import sys
import tempfile
from pathlib import Path

from check import FILES, check_composer, check_npm, check_pnpm

from precondition_library.bench import lock_actions as la

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lock-tool-dated-2026-11-08"))
from tool_dated import repository  # noqa: E402


def check(tool: str, tree: Path, folder: Path, scratch: Path) -> dict[str, str]:
    if tool == "npm":
        return check_npm(folder, scratch)
    if tool == "pnpm":
        return check_pnpm(tree, folder, scratch)
    return check_composer(folder, scratch)


def main() -> None:
    study, hosts, scratch, out = (
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        Path(sys.argv[3]).resolve(),
        Path(sys.argv[4]),
    )
    scratch.mkdir(parents=True, exist_ok=True)
    hosts.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((study / "manifest.json").read_text())
    tips = {r["repo"]: r["tip"] for r in manifest["repositories"]}
    cases = {c["index"]: c for c in manifest["cases"]}
    rows = []
    for line in (study / "labels.jsonl").read_text().splitlines():
        row = json.loads(line)
        files = [f["path"] for f in row["files"] if f["path"].rsplit("/", 1)[-1] in FILES]
        if not files:
            continue
        c = cases[row["index"]]
        commits = {"first": c["first"], "second": c["second"], "base": c["base"]}
        repo = repository(hosts, c["repo"], tips[c["repo"]], list(commits.values()))
        verdicts: dict[str, dict[str, dict[str, str]]] = {path: {} for path in files}
        for side, commit in commits.items():
            with tempfile.TemporaryDirectory(dir=scratch) as tmp:
                tree = Path(tmp) / "tree"
                tree.mkdir()
                la._checkout(repo, commit, tree)
                for path in files:
                    lock = tree / path
                    if not lock.is_file():
                        verdicts[path][side] = {"verdict": "error: no lock file at this commit"}
                        continue
                    tool = FILES[path.rsplit("/", 1)[-1]]
                    verdicts[path][side] = check(tool, tree, lock.parent, scratch)
        for path in files:
            result = {
                "index": row["index"],
                "repo": c["repo"],
                "path": path,
                "tool": FILES[path.rsplit("/", 1)[-1]],
                "own_tree": verdicts[path],
            }
            rows.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


if __name__ == "__main__":
    main()
