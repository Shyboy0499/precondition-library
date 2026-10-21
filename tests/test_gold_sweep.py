"""The graders accept what the gold programs do (ADR-0045).

`bench.gold_sweep` replays each gold program where its own preconditions hold and the state
accepts its resolution, and grades it with the fault's checker. These tests pin:

* each outcome on a crafted program -- not applicable, a gold mis-fire, a refusal, graded ok --
  so a defect cannot read as a pass;
* a sample of states that exposed the four defects of ADR-0045 -- a spaced and a non-ASCII
  lock-file path, a work file upstream edits, a spaced untracked file -- and of the eval block,
  with no defect, so a grader regression or a broken gold program fails CI.

The full sweep is `python -m precondition_library.bench.gold_sweep --seeds held-out` (and
`--seeds eval`, `--real-host`); it exits non-zero on any defect.
"""

from __future__ import annotations

import pytest
from conftest import gold_program

from precondition_library.bench import gold_sweep
from precondition_library.bench.gold_sweep import (
    GRADED_OK,
    MISFIRE,
    NOT_APPLICABLE,
    REFUSED,
    defects,
    sweep,
    sweep_faults,
)
from precondition_library.program import Predicate, Program

MERGE_SEED = 0
"""`diverged` injects its `merge` state at seed 0."""


def _crafted(body: str, *, holds: bool, variant: str) -> Program:
    """The gold `merge` with its body, steps and conditions replaced: `replay` runs argv
    `steps` in preference to a body, so they are cleared."""
    base = gold_program("merge")
    probe = "true" if holds else "false"
    return base.model_copy(
        update={
            "variant": variant,
            "body": body,
            "steps": None,
            "preconditions": [Predicate(name="crafted", description="crafted", probe=probe)],
            "postconditions": [],
        }
    )


@pytest.mark.parametrize(
    ("program", "outcome"),
    [
        (_crafted("true\n", holds=False, variant="merge"), NOT_APPLICABLE),
        (_crafted("true\n", holds=True, variant="discard"), MISFIRE),
        (_crafted("true\n", holds=True, variant="merge"), REFUSED),
        (gold_program("merge"), GRADED_OK),
    ],
    ids=["not-applicable", "mis-fire", "refused", "graded-ok"],
)
def test_each_outcome(program: Program, outcome: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gold_sweep, "load_gold_programs", lambda: {"diverged": {program.variant: program}}
    )
    (row,) = sweep(["diverged"], [MERGE_SEED])
    assert row.outcome == outcome, row.detail
    assert (row in defects([row])) == (outcome in (REFUSED, MISFIRE))


def test_every_measured_family_is_swept() -> None:
    assert set(sweep_faults()) == {
        "branch_renamed",
        "config_renamed",
        "dirty_tree",
        "diverged",
        "lockfile_conflict",
        "submodule_moved",
    }


@pytest.mark.parametrize("fault", sweep_faults())
@pytest.mark.parametrize("seed", [2000, 2001, 3001, 3002, 3006, 3038])
def test_gold_passes_where_it_applies(fault: str, seed: int) -> None:
    """Seeds 3001, 3002, 3006 and 3038 are the held-out states that exposed ADR-0045's
    defects; 2000 and 2001 are eval states."""
    rows = sweep([fault], [seed])
    assert rows, "every fault has gold"
    assert defects(rows) == [], [row.model_dump() for row in defects(rows)]


_REAL_PROJECT_FILES = {
    ".gitignore": "vendor\nnode_modules/\n",
    "HISTORY.md": "History\n=======\n\n1.0\n---\n\n- first release\n",
    "README.rst": "A project\n=========\n\nUsage\n-----\n",
    "docs/guide with space.md": "a path git quotes\n",
    "docs/übersicht.md": "a non-ASCII path\n",
}
"""What a real project's tree holds that the generator's base does not: reST and Markdown
headings underlined with `=` and `-`, an ignored `vendor`, names git quotes."""


@pytest.fixture
def realistic_host(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A local repository standing in for a real host, so CI needs no network."""
    import subprocess

    from precondition_library import sandbox
    from precondition_library.sandbox import RealHost

    monkeypatch.setattr(sandbox, "_REAL_HOSTS", tmp_path / "cache")
    repo = tmp_path / "host"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_DATE": "2025-06-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2025-06-01T00:00:00+00:00",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PATH": __import__("os").environ["PATH"],
    }

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=h", "-c", "user.email=h@example.invalid", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()

    git("-c", "init.defaultBranch=trunk", "init", "-q")
    for relative, content in _REAL_PROJECT_FILES.items():
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(content, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "a real-looking project")
    host = RealHost("example/realistic", repo.as_uri(), git("rev-parse", "HEAD"))
    monkeypatch.setattr(gold_sweep, "host_for_seed", lambda seed: host)
    return host


@pytest.mark.parametrize("fault", sweep_faults())
def test_gold_passes_over_a_realistic_host(fault: str, realistic_host) -> None:
    """The lock-file checker read a heading underline as a conflict marker on every real host
    (ADR-0045); this tree carries one, so a grader that does it again fails here."""
    rows = sweep([fault], [2000, 2001], real_hosts=True)
    assert [row for row in rows if row.outcome == GRADED_OK], "gold applied somewhere"
    assert defects(rows) == [], [row.model_dump() for row in defects(rows)]
