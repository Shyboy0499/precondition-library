"""lockmerge on composer.lock, and its content-hash against Composer's own algorithm in PHP."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import lockmerge
from lockmerge import Declined, Merged
from lockmerge._composer_constraint import satisfies
from lockmerge.composer import content_hash

PROJECT = {"name": "acme/app", "require": {"php": "^8.1", "monolog/monolog": "^3.0"}}


def _package(name: str, version: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "source": {"type": "git", "reference": f"{name}-{version}"},
        **extra,
    }


def _lock(project: dict[str, Any], packages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "_readme": ["This file locks the dependencies of your project to a known state"],
        "content-hash": content_hash(json.dumps(project)),
        "packages": sorted(packages, key=lambda p: p["name"]),
        "packages-dev": [],
        "aliases": [],
        "minimum-stability": "stable",
        "stability-flags": {},
        "prefer-stable": False,
        "prefer-lowest": False,
        "platform": {"php": "^8.1"},
        "platform-dev": [],
        "plugin-api-version": "2.6.0",
    }


def _text(lock: dict[str, Any]) -> str:
    return json.dumps(lock, indent=4) + "\n"


BASE_PACKAGES = [
    _package("monolog/monolog", "3.5.0", require={"psr/log": "^2.0 || ^3.0"}),
    _package("psr/log", "3.0.0"),
]


def test_only_one_side_changing_composer_json_merges_with_that_sides_hash() -> None:
    base = _lock(PROJECT, BASE_PACKAGES)
    theirs_project = copy.deepcopy(PROJECT)
    theirs_project["require"]["guzzlehttp/guzzle"] = "^7.0"
    ours = copy.deepcopy(base)
    ours["packages"][0] = _package(
        "monolog/monolog", "3.5.0", require={"psr/log": "^2.0 || ^3.0"}, time="2024-01-01"
    )
    theirs = _lock(theirs_project, [*BASE_PACKAGES, _package("guzzlehttp/guzzle", "7.8.1")])
    outcome = lockmerge.merge("composer.lock", _text(base), _text(ours), _text(theirs))
    assert isinstance(outcome, Merged)
    merged = json.loads(outcome.text)
    assert merged["content-hash"] == theirs["content-hash"]
    assert [p["name"] for p in merged["packages"]] == [
        "guzzlehttp/guzzle",
        "monolog/monolog",
        "psr/log",
    ]
    assert merged["packages"][1]["time"] == "2024-01-01"


def test_both_sides_changing_composer_json_needs_the_merged_one() -> None:
    base = _lock(PROJECT, BASE_PACKAGES)
    ours_project, theirs_project = copy.deepcopy(PROJECT), copy.deepcopy(PROJECT)
    ours_project["require"]["symfony/yaml"] = "^7.0"
    theirs_project["require"]["guzzlehttp/guzzle"] = "^7.0"
    ours = _lock(ours_project, [*BASE_PACKAGES, _package("symfony/yaml", "7.0.3")])
    theirs = _lock(theirs_project, [*BASE_PACKAGES, _package("guzzlehttp/guzzle", "7.8.1")])
    texts = (_text(base), _text(ours), _text(theirs))

    declined = lockmerge.merge("composer.lock", *texts)
    assert isinstance(declined, Declined) and "lockmerge resolve" in declined.reasons[0]

    merged_project = copy.deepcopy(PROJECT)
    merged_project["require"]["symfony/yaml"] = "^7.0"
    merged_project["require"]["guzzlehttp/guzzle"] = "^7.0"
    project_text = json.dumps(merged_project, indent=4)
    outcome = lockmerge.merge("composer.lock", *texts, composer_json=project_text)
    assert isinstance(outcome, Merged)
    assert json.loads(outcome.text)["content-hash"] == content_hash(project_text)


def test_one_package_locked_at_two_versions_is_refused() -> None:
    base = _lock(PROJECT, BASE_PACKAGES)
    ours, theirs = copy.deepcopy(base), copy.deepcopy(base)
    ours["packages"][1] = _package("psr/log", "3.0.1")
    theirs["packages"][1] = _package("psr/log", "3.0.2")
    outcome = lockmerge.merge("composer.lock", _text(base), _text(ours), _text(theirs))
    assert isinstance(outcome, Declined) and outcome.diverged
    assert outcome.reasons == ["psr/log: base 3.0.0, ours 3.0.1, theirs 3.0.2"]


def test_a_merge_that_breaks_a_requirement_is_refused() -> None:
    base = _lock(PROJECT, BASE_PACKAGES)
    ours, theirs = copy.deepcopy(base), copy.deepcopy(base)
    ours["packages"][1] = _package("psr/log", "1.1.4")
    ours["packages"][0] = _package("monolog/monolog", "3.5.0", require={"psr/log": "^1.0"})
    theirs["packages"].append(_package("acme/logger", "1.0.0", require={"psr/log": "^3.0"}))
    outcome = lockmerge.merge("composer.lock", _text(base), _text(ours), _text(theirs))
    assert isinstance(outcome, Declined) and outcome.inconsistent


@pytest.mark.parametrize(
    ("version", "constraint", "expected"),
    [
        ("v3.5.0", "^3.0", True),
        ("2.9.0", "^3.0", False),
        ("1.2.9", "~1.2", True),
        ("2.0.0", "~1.2", False),
        ("1.2.9", "~1.2.3", True),
        ("1.3.0", "~1.2.3", False),
        ("0.3.9", "^0.3", True),
        ("0.4.0", "^0.3", False),
        ("5.4.7", "5.4.*", True),
        ("7.1.0", "^6.4 || ^7.0", True),
        ("7.1.0", "^6.4|^7.0", True),
        ("1.5.0", ">=1.0 <2.0", True),
        ("1.5.0", ">=1.0, <1.5", False),
        ("3.0.0-beta1", "^3.0", True),
        ("dev-main", "^3.0", None),
        ("1.0.0", "dev-main as 1.0.x-dev", None),
    ],
)
def test_composer_constraints(version: str, constraint: str, expected: bool | None) -> None:
    assert satisfies(version, constraint) is expected


PHP_HASH = """<?php
$content = json_decode(file_get_contents($argv[1]), true);
$keys = ['name','version','require','require-dev','conflict','replace','provide',
         'minimum-stability','prefer-stable','repositories','extra'];
$r = [];
foreach (array_intersect($keys, array_keys($content)) as $k) { $r[$k] = $content[$k]; }
if (isset($content['config']['platform'])) {
    $r['config']['platform'] = $content['config']['platform'];
}
ksort($r);
echo md5(json_encode($r, 0));
"""


@pytest.mark.skipif(shutil.which("php") is None, reason="php is not installed")
@pytest.mark.parametrize(
    "project",
    [
        PROJECT,
        {"require": {}, "extra": {}, "name": "a/b"},
        {
            "require": {"ext-json": "*"},
            "repositories": [{"type": "vcs", "url": "https://x.test/r"}],
        },
        {"require": {"a/é": "^1"}, "config": {"platform": {"php": "8.1.0"}, "sort-packages": True}},
        {"require": {"a/b": "^1"}, "extra": {"0": "zero", "1": "one"}, "prefer-stable": True},
        {"description": "not hashed", "autoload": {"psr-4": {"App\\\\": "src/"}}},
    ],
)
def test_content_hash_matches_composers_php(project: dict[str, Any], tmp_path: Path) -> None:
    """Composer 2's `Locker::getContentHash`, run by PHP, gives the same hash."""
    script = tmp_path / "hash.php"
    script.write_text(PHP_HASH, encoding="utf-8")
    source = tmp_path / "composer.json"
    text = json.dumps(project, indent=4, ensure_ascii=False)
    source.write_text(text, encoding="utf-8")
    done = subprocess.run(
        ["php", str(script), str(source)], capture_output=True, text=True, check=True
    )
    assert content_hash(text) == done.stdout.strip()
