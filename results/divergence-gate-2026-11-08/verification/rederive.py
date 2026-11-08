"""Re-derive every conflicted file's divergence with `results/lock-anatomy-2026-11-04/anatomy.py`,
which classifies packages with its own code, and compare it with `gates.jsonl`.

    PYTHONPATH=src python results/divergence-gate-2026-11-08/verification/rederive.py <real-hosts>

The lock-file readers are the project's (`lock_actions`), checked by study 3's independent
parsers on 1,236 verdicts. Here the divergence count, the family and the predicted merge's verdict
are compared file by file.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "results/divergence-gate-2026-11-08"
ANATOMY = ROOT / "results/lock-anatomy-2026-11-04/anatomy.py"

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "anatomy.jsonl"
    subprocess.run([sys.executable, str(ANATOMY), str(STUDY), sys.argv[1], str(out)], check=True)
    anatomy = {(r["index"], r["path"]): r for r in map(json.loads, out.read_text().splitlines())}
files = mismatches = 0
for line in (STUDY / "gates.jsonl").read_text().splitlines():
    case = json.loads(line)
    for f in case["files"]:
        files += 1
        a = anatomy.pop((case["index"], f["path"]))
        same = (
            a["kinds"].get("divergent", 0) == f["divergent"]
            and a["family"] == f["family"]
            and a["predicted_reproduces"] == f["predicted_reproduces"]
        )
        if not same:
            mismatches += 1
            print("mismatch:", case["index"], f["path"])
print(f"{files} files compared, {mismatches} mismatches, {len(anatomy)} left unmatched")
sys.exit(1 if mismatches or anatomy else 0)
