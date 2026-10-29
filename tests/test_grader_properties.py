"""The graders, on repository states Hypothesis generates rather than seeds pick (#299).

ADR-0045's four grader defects were found by accident: each refused a correct resolution on a
path or a file content no seed happened to draw. Here the path-sensitive faults are driven with
generated values, through their own injectors, gold programs and checkers:

* `lockfile_conflict` with the lock file at a generated path, in a file whose header holds lines
  that look like conflict markers but are not git's;
* `dirty_tree` with all three of its paths generated.

The paths draw from what a shell must quote: spaces, `$`, quotes, backticks, `&`, `;`,
parentheses, `#`, non-ASCII letters, leading dots, deep nesting. Characters a Windows checkout
cannot hold are left out, so the suite runs on both CI platforms.

Two invariants hold for every draw:

* **a correct gold resolution passes** both of the episode's clauses -- the recorded state over
  the change surface, then the fault's checker -- as `bench.gold_sweep` grades it;
* **a discarding resolution fails** -- upstream's lock file taken whole, dropping the local
  dependency; the dirty work reset away.

`HYPOTHESIS_PROFILE=thorough` runs 300 examples per property instead of CI's fixed handful.
"""

from __future__ import annotations

import os
import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from precondition_library.bench.gold import load_gold_programs
from precondition_library.runtime.replay import replay
from precondition_library.sandbox import Sandbox, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import FAULTS, build_sandbox
from precondition_library.tasks.faults import dirty_tree as dirty
from precondition_library.tasks.faults import lockfile_conflict as lock
from precondition_library.tasks.invariants import recorded_state_intact
from precondition_library.tasks.spec import GroundTruth

settings.register_profile(
    "ci",
    max_examples=10,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "thorough",
    max_examples=300,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(10)),
    *(f"lpt{i}" for i in range(10)),
}
"""Names Windows will not create, with or without an extension."""

_SHELL_SPECIAL = " $'`&;()#!~-_.,=+@%"
"""Characters a shell must be told to leave alone, all of them valid in a Windows path."""


def _segment_ok(segment: str) -> bool:
    return (
        segment not in (".", "..")
        and segment.casefold() != ".git"
        and segment.split(".", 1)[0].casefold() not in _RESERVED
        and segment == segment.rstrip(" .")
        and segment == segment.lstrip(" ")
        and not segment.startswith("-")
    )


segments = st.text(
    alphabet=st.characters(
        categories=("L", "N"), include_characters=_SHELL_SPECIAL, max_codepoint=0x24F
    ),
    min_size=1,
    max_size=8,
).filter(_segment_ok)
"""One path component: letters (Latin with accents), digits and shell-special characters."""

directories = st.lists(segments, min_size=0, max_size=4)


def _join(*parts: str) -> str:
    return "/".join(parts)


@st.composite
def lock_paths(draw: st.DrawFn) -> str:
    """Where the lock file lives: under up to four generated directories, named `*.lock`."""
    return _join(*draw(directories), draw(segments) + ".lock")


NOT_MARKERS = st.sampled_from(
    [
        "=======",
        "======= heading",
        "<<<<<<<<",
        "<<<<<<",
        "<<<<<<<x",
        ">>>>>>>>>",
        ">>>>>>>-",
        "||||||| ",
        "||||||",
        "|||||||x",
        "# <<<<<<< not at the start",
    ]
).filter(lambda line: not re.match(lock._MARKER_PATTERN, line))
"""Lines that look like a conflict's markers and are not, by the definition git and the
checker share (ADR-0045): a start, end or base marker is seven characters, then a space or the
end of the line. `||||||| ` is one, so the filter drops it."""


def _grade(fault: str, seed: int, box: Sandbox) -> GroundTruth:
    """Both of the episode's clauses, the recorded state first, as `bench.gold_sweep` grades."""
    surface = FAULTS[fault].change_surface_for_seed(seed)
    intact = recorded_state_intact(box, surface=surface)
    return intact if not intact.ok else FAULTS[fault].check(box)


def _gold(fault: str, box: Sandbox):  # noqa: ANN202 - a Program
    intent = next(i for i in _intents() if i.fault == fault)
    variant = intent.correct_variant(StateFingerprint.observe(box))
    assert variant is not None, "every injected state is labelled"
    return load_gold_programs()[fault][variant.id]


def _intents():  # noqa: ANN202
    from precondition_library.tasks.registry import ambiguous_intents

    return ambiguous_intents()


SHIPPED_SEEDS = st.integers(min_value=0, max_value=59)
"""A shipped seed chooses the state's shape -- which resolution it needs -- and the generated
values replace what the seed would otherwise have chosen for its path and content."""


@given(seed=SHIPPED_SEEDS, path=lock_paths(), filler=st.lists(NOT_MARKERS, max_size=3))
def test_lockfile_gold_passes_and_taking_upstream_whole_fails(
    seed: int, path: str, filler: list[str]
) -> None:
    header = lock._HEADER + "".join(f"{line}\n" for line in filler)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(lock, "lock_path_for_seed", lambda _seed: path)
        patch.setattr(lock, "_HEADER", header)

        box = build_sandbox(seed, ["lockfile_conflict"])
        try:
            assert box.recorded["lock-path"] == path
            program = _gold("lockfile_conflict", box)
            result = replay(program, box)
            verdict = _grade("lockfile_conflict", seed, box)
            assert verdict.ok, f"gold {program.variant} at {path!r}: {verdict.detail} ({result})"
        finally:
            box.destroy()

        box = build_sandbox(seed, ["lockfile_conflict"])
        try:
            work = box.work
            run_git(("merge", "-q", "--no-commit", "upstream/main"), cwd=work, check=False)
            run_git(("checkout", "--theirs", "--", path), cwd=work)
            run_git(("add", "--", path), cwd=work)
            run_git(("commit", "-q", "--no-edit"), cwd=work)
            verdict = _grade("lockfile_conflict", seed, box)
            assert not verdict.ok, f"taking upstream's {path!r} whole dropped a dependency"
        finally:
            box.destroy()


@st.composite
def dirty_paths(draw: st.DrawFn) -> dirty._Paths:
    """Three distinct paths, none a directory of another, under a fresh generated directory, so
    none is already in the base tree."""
    root = draw(segments.filter(lambda s: s.casefold() not in {"docs", "notes"}))
    chosen = draw(
        st.lists(
            st.builds(lambda d, n: _join(root, *d, n), directories, segments),
            min_size=3,
            max_size=3,
            unique_by=str.casefold,
        ).filter(
            lambda ps: (
                not any(
                    a.casefold().startswith(b.casefold() + "/") for a in ps for b in ps if a != b
                )
                and not any(
                    (a + dirty.ASIDE_SUFFIX).casefold() == b.casefold() for a in ps for b in ps
                )
            )
        )
    )
    return dirty._Paths(*chosen)


@given(seed=SHIPPED_SEEDS, paths=dirty_paths())
def test_dirty_tree_gold_passes_and_discarding_the_work_fails(
    seed: int, paths: dirty._Paths
) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(dirty, "paths_for_seed", lambda _seed: paths)

        box = build_sandbox(seed, ["dirty_tree"])
        try:
            assert box.recorded["untracked_path"] == paths.untracked_path
            assert box.recorded["work-path"] in (paths.upstream_file, paths.tracked_file)
            program = _gold("dirty_tree", box)
            result = replay(program, box)
            verdict = _grade("dirty_tree", seed, box)
            assert verdict.ok, f"gold {program.variant} at {paths}: {verdict.detail} ({result})"
        finally:
            box.destroy()

        box = build_sandbox(seed, ["dirty_tree"])
        try:
            work = box.work
            run_git(("reset", "-q", "--hard", "upstream/main"), cwd=work)
            run_git(("clean", "-q", "-fd"), cwd=work)
            verdict = _grade("dirty_tree", seed, box)
            assert not verdict.ok, f"discarding the work at {paths} passed"
        finally:
            box.destroy()
