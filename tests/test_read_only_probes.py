"""A probe must only read: one that changes the sandbox is refused (issue #10).

The guard permits writes inside the sandbox because bodies need them, so before this a
precondition such as `git reset --hard` ran and corrupted the state every later probe and
the episode observed. `evaluate_predicate` now snapshots the sandbox around each probe;
a probe that changed it is reported as not holding, flagged `refused`, and names what it
changed. Admission treats a refused precondition as a defect rather than as a "no", so a
mutating probe cannot pass the negative side by rejecting everything.

Every case runs against a real sandbox, never a mock: the property is about what a
shell command does to a real repository.
"""

from __future__ import annotations

import os
import time

import pytest
from test_episode_runner import DISCARD_SEED, _discard_program

from precondition_library.agents.compile import admit
from precondition_library.program import Predicate
from precondition_library.runtime import probes
from precondition_library.runtime.probes import bindings, evaluate_predicate, evaluate_predicates


def _probe(command: str) -> Predicate:
    return Predicate(name="under-test", description="a probe under test", probe=command)


@pytest.mark.parametrize(
    ("command", "part"),
    [
        ("echo written > probe-wrote-this.txt", "working tree"),
        ("git branch probe-made-this", "refs"),
        ("git config probe.touched yes", "config"),
        ("git checkout -q -b probe-moved-head", "HEAD"),
        ("git rm -q --cached app.py", "index"),
    ],
)
def test_a_probe_that_changes_the_sandbox_is_refused(command: str, part: str, make_sandbox) -> None:
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    result = evaluate_predicate(_probe(command), box, bindings(box))
    assert result.ok is False
    assert result.refused is True
    assert "changed the sandbox" in result.observed and part in result.observed


def test_a_guard_refusal_is_flagged_as_a_refusal(make_sandbox) -> None:
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    result = evaluate_predicate(_probe("curl -s http://example.invalid/x"), box, bindings(box))
    assert result.ok is False and result.refused is True


def test_reading_is_not_refused_even_when_git_refreshes_the_index(make_sandbox) -> None:
    """`git status` rewrites the index's stat cache; that is not a change to the state."""
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    for command in ("git status --porcelain", "git log --oneline -1", "test -f app.py"):
        result = evaluate_predicate(_probe(command), box, bindings(box))
        assert result.refused is False, f"{command!r} only reads, but was refused"
        assert result.ok is True


def test_refusals_are_counted_on_the_combined_verdict(make_sandbox) -> None:
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    verdict = evaluate_predicates(
        [_probe("test -f app.py"), _probe("git branch probe-made-this")],
        box,
        kind="precondition",
    )
    assert verdict.ok is False
    assert verdict.refusals == 1


def test_admission_rejects_a_program_whose_precondition_writes() -> None:
    """A mutating probe reads as "no" everywhere; admission must not take that as a pass."""
    base = _discard_program()
    writes = Predicate(
        name="writes_a_branch",
        description="Creates a branch while checking.",
        probe="git branch probe-side-effect && true",
    )
    program = _discard_program(
        id="mutating-precondition", preconditions=[*base.preconditions, writes]
    )
    admitted, reason = admit(program, "diverged", seeds=[DISCARD_SEED])
    assert admitted is False
    assert "was refused" in reason and "changed the sandbox" in reason


def test_the_compile_prompt_states_the_rule() -> None:
    """The seventh live run's first program fetched with `--prune` in a precondition and
    was refused; the model is told the rule it is held to, and who fetches."""
    from precondition_library.agents.compile import SYSTEM_PROMPT

    assert "must only read" in SYSTEM_PROMPT
    assert "Fetching is the body's job" in SYSTEM_PROMPT


def test_the_compile_prompt_says_how_to_check_absence() -> None:
    """The eighth live run's `stash_entry_consumed` expected exit 1 and a pattern from
    `git stash list`, which exits 0 and can only require presence."""
    from precondition_library.agents.compile import SYSTEM_PROMPT

    assert "can only require that something is present" in SYSTEM_PROMPT
    assert "! git stash list | grep -q" in SYSTEM_PROMPT


# --- the snapshot reads a file again only when its stat moved (#296) --------------------------


def _counting_reads(monkeypatch) -> list[str]:
    read: list[str] = []
    original = probes._file_sha256

    def counted(path: str) -> bytes:
        read.append(path)
        return original(path)

    monkeypatch.setattr(probes, "_file_sha256", counted)
    return read


def test_a_warm_snapshot_equals_a_cold_one_and_reads_nothing_unchanged(
    make_sandbox, monkeypatch
) -> None:
    """On Windows, where ctime is the creation time, nothing is kept and every file is read."""
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    monkeypatch.setattr(probes, "_RACY_NS", -1)  # every file is old enough to keep
    probes._DIGESTS.clear()
    cold = probes.sandbox_state(box)
    keeps = os.name != "nt"
    assert (str(box.work / "app.py") in probes._DIGESTS) == keeps
    read = _counting_reads(monkeypatch)
    assert probes.sandbox_state(box) == cold
    assert (read == []) == keeps


def test_a_rewrite_that_restores_size_and_mtime_is_still_seen(make_sandbox, monkeypatch) -> None:
    """ctime moves on every write and cannot be set back, so the kept digest is not used.
    (On Windows nothing is kept, and the file is read again.)"""
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    monkeypatch.setattr(probes, "_RACY_NS", -1)
    probes._DIGESTS.clear()
    target = box.work / "app.py"
    text = target.read_bytes()
    before = probes.sandbox_state(box)
    stat = target.stat()
    time.sleep(0.05)  # past any timestamp tick, so the rewrite's ctime differs
    target.write_bytes(text.swapcase())  # same length, other bytes
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert target.stat().st_size == stat.st_size and target.stat().st_mtime_ns == stat.st_mtime_ns
    assert target.read_bytes() != text
    after = probes.sandbox_state(box)
    assert after["working tree"] != before["working tree"]


def test_a_file_changed_within_the_racy_window_is_not_kept(make_sandbox) -> None:
    """A digest is kept only for a file whose ctime was already old when it was read, so a
    second write in the same clock tick can never be answered from the cache."""
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    fresh = box.work / "written-just-now.txt"
    fresh.write_text("now\n", encoding="utf-8")
    probes.sandbox_state(box)
    assert str(fresh) not in probes._DIGESTS
