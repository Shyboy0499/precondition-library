"""lockmerge's npm ranges against npm's own `semver` package, on a grid of versions and ranges."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lockmerge._semver import satisfies

VERSIONS = [
    "0.0.1",
    "0.0.2",
    "0.1.0",
    "0.1.5",
    "0.2.0",
    "1.0.0",
    "1.0.1",
    "1.2.3",
    "1.2.4",
    "1.3.0",
    "1.9.9",
    "2.0.0",
    "2.0.0-beta.1",
    "2.0.0-0",
    "1.2.3-alpha",
    "1.2.4-rc.1",
    "3.4.5",
    "10.0.0",
]
RANGES = [
    "*",
    "",
    "1",
    "1.x",
    "1.2",
    "1.2.x",
    "1.2.3",
    "=1.2.3",
    "v1.2.3",
    "^1.2.3",
    "^0.1.0",
    "^0.0.1",
    "^1.2",
    "^1",
    "~1.2.3",
    "~1.2",
    "~1",
    ">=1.2.3",
    ">1.2.3",
    "<2.0.0",
    "<=1.2.3",
    ">1",
    "<=1.2",
    ">=1.2.3 <2.0.0",
    ">= 1.2.3 < 2.0.0",
    "1.2.3 - 2.0.0",
    "1.2 - 2",
    "1 || 3",
    "^1.2.3 || ^3.0.0",
    "^2.0.0-beta.0",
    ">=1.2.3-alpha <1.3.0",
    "~1.2.4-rc.0",
    "x",
    "1.2.*",
]
NODE = """
const semver = require(process.argv[1]);
const pairs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(pairs.map(([v, r]) => semver.satisfies(v, r))));
"""


def _npm_semver() -> Path | None:
    npm = shutil.which("npm")
    if npm is None or shutil.which("node") is None:
        return None
    root = Path(npm).resolve().parents[1]
    for candidate in (
        root / "node_modules" / "semver",
        root / "lib" / "node_modules" / "npm" / "node_modules" / "semver",
    ):
        if (candidate / "package.json").exists():
            return candidate
    return None


@pytest.mark.skipif(_npm_semver() is None, reason="node and npm's semver are not available (#385)")
def test_satisfies_agrees_with_npms_semver_on_every_pair() -> None:
    pairs = [(v, r) for v in VERSIONS for r in RANGES]
    done = subprocess.run(
        ["node", "-e", NODE, str(_npm_semver())],
        input=json.dumps(pairs),
        capture_output=True,
        text=True,
        check=True,
    )
    expected = json.loads(done.stdout)
    disagreements = [
        (v, r, mine, theirs)
        for (v, r), theirs in zip(pairs, expected, strict=True)
        if (mine := satisfies(v, r)) is not None and mine != theirs
    ]
    assert not disagreements
    unread = [(v, r) for v, r in pairs if satisfies(v, r) is None]
    assert not unread


def test_ranges_it_cannot_read_are_not_judged() -> None:
    assert satisfies("1.0.0", "git+https://github.com/a/b.git#v1") is None
    assert satisfies("1.0.0", "file:../local") is None
    assert satisfies("1.0.0", "latest") is None
    assert satisfies("not-a-version", "^1.0.0") is None


def test_an_npm_alias_is_judged_by_its_range() -> None:
    assert satisfies("4.17.21", "npm:lodash@^4.17.0") is True
    assert satisfies("3.10.1", "npm:lodash@^4.17.0") is False
