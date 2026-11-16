"""Learning a program on an existing checkout, end to end with a scripted model (#188).

`learn.learn` solves a copy of the checkout, asks the caller to confirm what the solve
did, compiles it, checks the program fires where it was learned, and admits it through
the harness's two-sided gate (ADR-0026). A harness `diverged` state, opened as a
checkout, is the repository; the model is scripted:

* as the **agent** (offered tools) it runs the commands a person would to merge upstream,
  then calls `finish`;
* as the **compiler** (offered none) it replies with a program's YAML -- the gold program
  for the state, or a deliberately wrong one.

These tests pin each step's stop, and that the checkout itself is never changed.
"""

from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import gold_program

from precondition_library.__main__ import main
from precondition_library.agents.react import FINISH_TOOL
from precondition_library.dispatch import dispatch_report
from precondition_library.learn import admission_seed, learn, render, render_effect
from precondition_library.library import Library
from precondition_library.program import ProgramStatus
from precondition_library.provider import Completion, TokenUsage
from precondition_library.runtime.probes import sandbox_state
from precondition_library.sandbox import Sandbox, run_git
from precondition_library.tasks.faults import FAULTS, build_sandbox

_USAGE = TokenUsage(tokens_in=1, tokens_out=1, uncached_tokens_in=1)
MERGE_COMMANDS = ("git fetch upstream", "git merge --no-edit upstream/main")


def _yaml_of(program) -> str:
    document = program.model_dump(mode="json")
    document.pop("provenance")
    document.pop("status")
    return yaml.safe_dump(document, sort_keys=False)


class Scripted:
    """The agent runs `commands` then finishes; the compiler replies `program_yaml`."""

    def __init__(self, program_yaml: str, commands=MERGE_COMMANDS, *, never_finish=False):
        self.program_yaml = program_yaml
        self.turns = [list(commands)]
        self.never_finish = never_finish
        self.compiles = 0
        self._ids = itertools.count(1)

    def _call(self, name: str, **arguments: str) -> dict:
        return {
            "id": f"call_{next(self._ids)}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }

    def complete(self, *, system: str, messages: list[dict], tools=None) -> Completion:
        if tools:
            if self.never_finish:
                calls = [self._call("run_git", command="git status")]
            elif self.turns:
                calls = [self._call("run_git", command=c) for c in self.turns.pop(0)]
            else:
                calls = [self._call(FINISH_TOOL, summary="merged upstream")]
            return Completion(tool_calls=calls, usage=_USAGE, model="scripted")
        self.compiles += 1
        return Completion(text=self.program_yaml, usage=_USAGE, model="scripted")


def _merge_seed() -> int:
    return next(s for s in range(200) if FAULTS["diverged"].variant_for_seed(s) == "merge")


@pytest.fixture
def merge_state(tmp_path):
    """A merge-labelled `diverged` state as a standalone repository, the way a user's is.

    Copied out of the harness: `sandbox.create` replaces a sandbox when the same
    `(seed, faults)` is built again in one process, and the harness gate does build
    `diverged` sandboxes -- a "checkout" that was itself a harness sandbox would be
    rebuilt under the test. The copy's `upstream` remote is re-pointed at its own copy
    of the upstream repository.
    """
    box = build_sandbox(_merge_seed(), ["diverged"])
    try:
        repo_root = tmp_path / "users-repo"
        shutil.copytree(box.root, repo_root, symlinks=True)
    finally:
        box.destroy()
    work = repo_root / "work"
    run_git(("remote", "set-url", "upstream", str(repo_root / "upstream.git")), cwd=work)
    return Sandbox(root=repo_root, work=work, upstream=repo_root / "upstream.git")


def _learn(box, tmp_path: Path, model: Scripted, *, confirm=lambda effect: True):
    return learn(
        tmp_path / "library",
        box.work,
        request="sync my fork with upstream",
        fault="diverged",
        provider=model,
        confirm=confirm,
        fetch=False,
        scratch=tmp_path,
    )


def test_a_confirmed_solve_is_learned_admitted_and_marked(merge_state, tmp_path) -> None:
    before = sandbox_state(merge_state)
    model = Scripted(_yaml_of(gold_program("merge")))
    shown = []
    outcome = _learn(merge_state, tmp_path, model, confirm=lambda e: shown.append(e) or True)

    assert outcome.admitted, render(outcome)
    assert outcome.solve == "success" and outcome.tool_calls == 2
    assert shown and shown[0] == outcome.effect and outcome.effect.commits, "a merge commit"
    assert outcome.variant == "merge" and "admitted" in (outcome.gate_reason or "")
    (stored,) = Library(tmp_path / "library").load_all()
    assert stored.id == outcome.program_id and stored.status is ProgramStatus.ADMITTED
    assert stored.provenance.learned_on == "checkout"
    assert sandbox_state(merge_state) == before, "the solve ran on a copy"

    report = dispatch_report(tmp_path / "library", merge_state.work, fetch=False, scratch=tmp_path)
    assert report.fires == stored.id, "the learned program fires on the checkout it was learned on"


def test_declining_compiles_nothing(merge_state, tmp_path) -> None:
    model = Scripted(_yaml_of(gold_program("merge")))
    outcome = _learn(merge_state, tmp_path, model, confirm=lambda effect: False)
    assert not outcome.admitted and outcome.confirmed is False
    assert outcome.stopped and outcome.stopped.startswith("not confirmed")
    assert model.compiles == 0
    assert not (tmp_path / "library").exists() or not Library(tmp_path / "library").load_all()


def test_a_solve_that_never_finishes_asks_nothing(merge_state, tmp_path) -> None:
    model = Scripted("unused", never_finish=True)
    outcome = _learn(merge_state, tmp_path, model, confirm=lambda e: pytest.fail("not asked"))
    assert outcome.solve == "fail" and outcome.effect is None
    assert "did not declare the task done" in (outcome.stopped or "")
    assert model.compiles == 0


def test_a_program_that_does_not_fire_where_it_was_learned_is_not_admitted(
    merge_state, tmp_path
) -> None:
    """The model compiles the wrong resolution: rebase's preconditions need disjoint files."""
    model = Scripted(_yaml_of(gold_program("rebase")))
    outcome = _learn(merge_state, tmp_path, model)
    assert not outcome.admitted
    assert "do not hold on the checkout it was learned on" in (outcome.stopped or "")
    assert outcome.gate_reason is None, "the harness gate was never reached"


def test_the_harness_gate_still_rejects_a_program_that_fires_everywhere(
    merge_state, tmp_path
) -> None:
    """It holds here and its replay works here -- and the harness refuses it all the same."""
    loose = gold_program("merge").model_copy(deep=True)
    # Names the parameters the steps use, and holds on any repository with an upstream.
    everywhere = "git rev-parse --verify {upstream_remote}/{upstream_branch}"
    loose.preconditions[0] = loose.preconditions[0].model_copy(update={"probe": everywhere})
    loose = loose.model_copy(update={"preconditions": loose.preconditions[:1]})
    model = Scripted(_yaml_of(loose))
    outcome = _learn(merge_state, tmp_path, model)
    assert not outcome.admitted
    assert (outcome.stopped or "").startswith("the harness gate rejected it")
    assert "clean sandbox" in (outcome.gate_reason or "")
    assert not Library(tmp_path / "library").load_all()


def test_an_unknown_family_is_refused_before_anything_runs(merge_state, tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown family"):
        learn(
            tmp_path / "library",
            merge_state.work,
            request="r",
            fault="not_a_fault",
            provider=Scripted("unused"),
            confirm=lambda e: True,
            fetch=False,
            scratch=tmp_path,
        )


def test_the_admission_seed_is_a_state_of_the_programs_own_resolution() -> None:
    for variant in ("merge", "rebase", "discard"):
        seed = admission_seed("diverged", variant)
        assert seed is not None and FAULTS["diverged"].variant_for_seed(seed) == variant
    assert admission_seed("diverged", "no-such-resolution") is None
    assert admission_seed("diverged", None) is None


def test_the_effect_reads_as_text(merge_state, tmp_path) -> None:
    model = Scripted(_yaml_of(gold_program("merge")))
    seen = []
    _learn(merge_state, tmp_path, model, confirm=lambda e: seen.append(e) or False)
    text = render_effect(seen[0])
    assert text.startswith("the agent's solve, on a copy: HEAD ") and "+ " in text


# --- the command ---------------------------------------------------------------


def _argv(repo: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "learn",
        "--repo",
        str(repo),
        "--library",
        str(tmp_path / "library"),
        "--fault",
        "diverged",
        "--request",
        "sync my fork with upstream",
        "--api-key-env",
        "LEARN_TEST_KEY",
        "--no-fetch",
        *extra,
    ]


def test_the_command_asks_and_a_no_learns_nothing(merge_state, tmp_path, monkeypatch, capsys):
    secret = "sk-learn-test-not-a-real-key"
    monkeypatch.setenv("LEARN_TEST_KEY", secret)
    seen: dict = {}

    def make_provider(key: str, model: str) -> Scripted:
        seen.update(key=key, model=model)
        return Scripted(_yaml_of(gold_program("merge")))

    asked: list[str] = []
    code = main(
        _argv(merge_state.work, tmp_path),
        answer=lambda prompt: asked.append(prompt) or "n",
        make_provider=make_provider,
    )
    out = capsys.readouterr().out
    assert code == 1
    assert seen["key"] == secret, "the key is read from the named variable"
    assert asked and "should it be learned?" in asked[0]
    assert "the agent's solve, on a copy" in out and "not learned: not confirmed" in out
    assert secret not in out


def test_yes_skips_the_question(merge_state, tmp_path, monkeypatch, capsys) -> None:
    """A wrong resolution stops at the cheap check, before the harness gate."""
    monkeypatch.setenv("LEARN_TEST_KEY", "k")
    code = main(
        _argv(merge_state.work, tmp_path, "--yes", "--json"),
        answer=lambda prompt: pytest.fail("--yes must not ask"),
        make_provider=lambda key, model: Scripted(_yaml_of(gold_program("rebase"))),
    )
    printed = json.loads(capsys.readouterr().out)
    assert code == 1 and printed["confirmed"] is True and printed["admitted"] is False
    assert "do not hold on the checkout it was learned on" in printed["stopped"]


def test_the_family_must_be_a_measured_one(merge_state, tmp_path) -> None:
    argv = _argv(merge_state.work, tmp_path)
    argv[argv.index("diverged")] = "dirty_tree"
    with pytest.raises(SystemExit):
        main(argv, make_provider=lambda key, model: pytest.fail("never built"))
