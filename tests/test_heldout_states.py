"""The held-out stage measures states no library saw (issue #263).

Arm 3's zero mis-fire rate was measured on states the injectors produce, which is also
where admission tested every program. `bench.heldout` measures a block whose states draw a
path set no shipped seed draws. These tests pin the two halves that make it mean anything:

* **No shipped state moved.** Every seed below `HELD_OUT_SEED_BASE` -- the whole admission
  search included -- still draws the shipped path set, so every committed figure stays
  recomputable from the code that produced it.
* **The block is genuinely held out.** It is disjoint from the plan's blocks, and each fault
  the stage measures declares an axis that actually moves a real state.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from conftest import gold_program, gold_programs

from precondition_library.bench.heldout import (
    HELD_OUT_FAULTS,
    WORDING_LIMIT,
    WrongFire,
    run_held_out,
)
from precondition_library.bench.splits import (
    EVAL_SEEDS,
    HELD_OUT_SEEDS,
    SMOKE_SEEDS,
    TUNE_SEEDS,
)
from precondition_library.library import Library
from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.runtime.probes import bindings, evaluate_preconditions, substitute
from precondition_library.runtime.replay import replay
from precondition_library.signatures import StateFingerprint
from precondition_library.similarity import lexical_similarity
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.faults.branch_renamed import (
    HELD_OUT_BRANCH_NAMES,
    NEW_BRANCH_NAMES,
    renamed_branch_for_seed,
)
from precondition_library.tasks.faults.branch_renamed import (
    INTENT as BRANCH_RENAMED_INTENT,
)
from precondition_library.tasks.faults.branch_renamed import (
    SPEC as BRANCH_RENAMED,
)
from precondition_library.tasks.faults.dirty_tree import (
    HELD_OUT_PATHS,
    SHIPPED_PATHS,
    paths_for_seed,
)
from precondition_library.tasks.faults.dirty_tree import (
    INTENT as DIRTY_TREE_INTENT,
)
from precondition_library.tasks.faults.dirty_tree import (
    SPEC as DIRTY_TREE,
)
from precondition_library.tasks.faults.diverged import (
    HELD_OUT_SHAPES as DIVERGED_HELD_OUT_SHAPES,
)
from precondition_library.tasks.faults.diverged import (
    INTENT as DIVERGED_INTENT,
)
from precondition_library.tasks.faults.diverged import (
    SHIPPED_SHAPE as DIVERGED_SHIPPED_SHAPE,
)
from precondition_library.tasks.faults.diverged import (
    SPEC as DIVERGED,
)
from precondition_library.tasks.faults.diverged import (
    shape_for_seed as diverged_shape_for_seed,
)
from precondition_library.tasks.faults.lockfile_conflict import (
    HELD_OUT_LOCK_PATHS,
    LOCK_PATH,
    lock_path_for_seed,
)
from precondition_library.tasks.faults.lockfile_conflict import (
    INTENT as LOCKFILE_INTENT,
)
from precondition_library.tasks.faults.lockfile_conflict import (
    SPEC as LOCKFILE,
)
from precondition_library.tasks.faults.submodule_moved import (
    HELD_OUT_SUBMODULE_PATHS,
    SUBMODULE_PATH,
    submodule_path_for_seed,
)
from precondition_library.tasks.faults.submodule_moved import (
    INTENT as SUBMODULE_INTENT,
)
from precondition_library.tasks.faults.submodule_moved import (
    SPEC as SUBMODULE_MOVED,
)
from precondition_library.tasks.registry import ambiguous_intents
from precondition_library.tasks.spec import HELD_OUT_SEED_BASE

PLANNED_SEEDS = [*SMOKE_SEEDS, *TUNE_SEEDS, *EVAL_SEEDS]

HELD_OUT_AXES = {
    "dirty_tree": lambda seed: paths_for_seed(seed).upstream_file,
    "diverged": lambda seed: diverged_shape_for_seed(seed),
    "lockfile_conflict": lambda seed: lock_path_for_seed(seed),
    "branch_renamed": lambda seed: (
        renamed_branch_for_seed(seed) if seed >= HELD_OUT_SEED_BASE else "shipped"
    ),
    "submodule_moved": lambda seed: submodule_path_for_seed(seed),
}
"""Per fault, the held-out axis it declares, as a function of a seed.

Keyed exactly on `HELD_OUT_FAULTS`: a fault added to the stage without an axis here fails
`test_every_held_out_fault_declares_a_held_out_axis`, which is the point -- measuring the
shipped states again under a new seed block would look like a held-out result and not be one."""


def _admit(library: Library, program: Program) -> None:
    library.add(program)
    library.set_status(program.id, ProgramStatus.ADMITTED)


def _gold_library(root: Path) -> Library:
    library = Library(root, evaluate_preconditions=evaluate_preconditions)
    for intent in ambiguous_intents():
        for program in gold_programs(intent.name):
            _admit(library, program)
    return library


def test_the_block_is_disjoint_from_every_planned_one() -> None:
    """No held-out seed is a seed the plan, or admission's search, could have built."""
    assert all(seed >= HELD_OUT_SEED_BASE for seed in HELD_OUT_SEEDS)
    assert max(PLANNED_SEEDS) < HELD_OUT_SEED_BASE
    assert not set(HELD_OUT_SEEDS) & set(PLANNED_SEEDS)


def test_every_seed_below_the_base_draws_the_shipped_paths() -> None:
    """The shipped state is what every seed below the base draws, enumerated exhaustively.

    `range(HELD_OUT_SEED_BASE)` rather than the plan's blocks: admission's own seed search
    scans an unlisted prefix of seeds, and the property that matters is about all of them.
    """
    for seed in [*range(HELD_OUT_SEED_BASE), *PLANNED_SEEDS]:
        assert paths_for_seed(seed) is SHIPPED_PATHS, f"seed {seed} moved off the shipped paths"
    for seed in HELD_OUT_SEEDS:
        assert paths_for_seed(seed) in HELD_OUT_PATHS, f"seed {seed} is not held out"


def test_every_held_out_fault_declares_a_held_out_axis() -> None:
    """Each fault the stage measures draws something new, and only above the base."""
    assert set(HELD_OUT_AXES) == set(HELD_OUT_FAULTS)
    for fault, axis in HELD_OUT_AXES.items():
        assert axis(2000) == axis(0), f"{fault}: a planned seed must draw the shipped value"
        assert len({axis(seed) for seed in HELD_OUT_SEEDS}) > 1, (
            f"{fault}: the held-out block draws one value, so the axis is not varied"
        )


def test_a_held_out_state_is_the_shipped_shape_at_new_paths() -> None:
    """One real sandbox: new paths, same resolution, and no held-out path in the shipped state.

    The label is the fault's own rule reading the observed fingerprint, so this also pins that
    moving the paths does not relabel the state -- which is what the whole comparison rests on.
    """
    held_out = build_sandbox(HELD_OUT_SEEDS[0], ["dirty_tree"])
    try:
        observed = StateFingerprint.observe(held_out)
    finally:
        held_out.destroy()
    paths = paths_for_seed(HELD_OUT_SEEDS[0])
    assert paths.upstream_file in observed.upstream_touched_files
    assert paths.tracked_file in observed.dirty_files
    if observed.untracked_upstream_collisions:
        assert paths.untracked_path in observed.untracked_upstream_collisions
    assert DIRTY_TREE_INTENT.correct_variant(observed) is not None
    assert (
        DIRTY_TREE_INTENT.correct_variant(observed).id  # type: ignore[union-attr]
        == DIRTY_TREE.variant_for_seed(HELD_OUT_SEEDS[0])
    )

    shipped = build_sandbox(EVAL_SEEDS[0], ["dirty_tree"])
    try:
        shipped_observed = StateFingerprint.observe(shipped)
    finally:
        shipped.destroy()
    touched = set(
        shipped_observed.upstream_touched_files
        + shipped_observed.dirty_files
        + shipped_observed.untracked_upstream_collisions
    )
    for pool in HELD_OUT_PATHS:
        assert not touched & {pool.upstream_file, pool.tracked_file, pool.untracked_path}, (
            "a shipped state carries a held-out path, so the frozen libraries have seen it"
        )


@pytest.fixture(scope="module")
def held_out_run(tmp_path_factory) -> tuple[Path, object]:
    library_root = tmp_path_factory.mktemp("heldout") / "gold"
    _gold_library(library_root)
    out = tmp_path_factory.mktemp("heldout") / "run"
    summary = run_held_out(
        library_root,
        out,
        similarity=lexical_similarity,
        scorer_id={"scorer": "lexical"},
        source="the gold library",
        seeds=HELD_OUT_SEEDS[:2],
        plot=False,
    )
    return out, summary


def test_the_stage_reads_the_library_and_reports_its_digest(held_out_run) -> None:
    """A figure computed from a library that moved is not a figure."""
    out, summary = held_out_run
    assert summary.library_hash_before == summary.library_hash_after
    assert (out / "summary.json").is_file()
    assert (out / "summary.txt").is_file()
    assert (out / "heldout.json").is_file()
    assert (out / "primary" / "figure1.csv").is_file()


def test_the_stage_measures_the_held_out_block_and_not_the_plan(held_out_run) -> None:
    """Two seeds: the fault-free negative and the fault's own state, per seed."""
    _, summary = held_out_run
    assert summary.seeds == list(HELD_OUT_SEEDS[:2])
    assert summary.faults == list(HELD_OUT_FAULTS)
    # Per seed and fault: the fault-free negative and the fault's own state.
    assert summary.pairs == 2 * len(HELD_OUT_FAULTS) * len(HELD_OUT_SEEDS[:2])
    assert not set(summary.seeds) & set(EVAL_SEEDS)


def test_the_stage_reports_the_instances_the_block_builds(held_out_run) -> None:
    """The number an independence claim is read at, from the injectors' own draw."""
    _, summary = held_out_run
    assert summary.distinct_instances == {
        fault: len({DIRTY_TREE.instance_for_seed(seed) for seed in HELD_OUT_SEEDS[:2]})
        for fault in HELD_OUT_FAULTS
    }
    assert all(1 <= count <= len(summary.seeds) for count in summary.distinct_instances.values())


def test_the_stage_refuses_the_win_wording(held_out_run) -> None:
    """The shipped floor is a statement about the shipped states and does not transfer."""
    _, summary = held_out_run
    assert summary.wording == WORDING_LIMIT
    assert "may not say" in summary.wording


def test_an_existing_output_directory_is_refused(tmp_path) -> None:
    library_root = tmp_path / "gold"
    _gold_library(library_root)
    out = tmp_path / "taken"
    out.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        run_held_out(
            library_root,
            out,
            similarity=lexical_similarity,
            scorer_id={"scorer": "lexical"},
            source="the gold library",
            seeds=HELD_OUT_SEEDS[:1],
            plot=False,
        )


def test_an_unknown_fault_is_refused(tmp_path) -> None:
    library_root = tmp_path / "gold"
    _gold_library(library_root)
    with pytest.raises(ValueError, match="unknown faults"):
        run_held_out(
            library_root,
            tmp_path / "out",
            similarity=lexical_similarity,
            scorer_id={"scorer": "lexical"},
            source="the gold library",
            faults=("not_a_fault",),
            seeds=HELD_OUT_SEEDS[:1],
            plot=False,
        )


def test_a_wrong_fire_is_reported_with_the_pair_it_happened_on(tmp_path) -> None:
    """The falsification path: a fire the held-out state does not accept is recorded.

    The gold programs agree with the labelling rules, so a gold run's file is empty -- which
    the vacuum already reports. This pins the other branch with a program whose preconditions
    hold everywhere and which declares `stash`: on a held-out `aside` state that is a mis-fire,
    and the record must name the pair's own label and request.
    """
    library = Library(tmp_path / "always", evaluate_preconditions=evaluate_preconditions)
    library.add(
        Program(
            id="always-fires-stash",
            intent="keep uncommitted work and sync",
            preconditions=[Predicate(name="always", description="holds everywhere", probe="true")],
            body="true",
            postconditions=[Predicate(name="always", description="holds everywhere", probe="true")],
            variant="stash",
            provenance=Provenance(
                compiled_from_task="a test",
                model="none",
                compiler_version="0.0.0",
                episode_id="test",
                fault="dirty_tree",
            ),
        )
    )
    library.set_status("always-fires-stash", ProgramStatus.ADMITTED)

    out = tmp_path / "run"
    summary = run_held_out(
        library.root,
        out,
        similarity=lexical_similarity,
        scorer_id={"scorer": "lexical"},
        source="an always-firing library",
        seeds=[seed for seed in HELD_OUT_SEEDS if DIRTY_TREE.variant_for_seed(seed) != "stash"][:1],
        plot=False,
    )
    assert summary.arm3_fires > 0, "the program fires everywhere, so arm 3 cannot have abstained"
    assert summary.arm3_wrong > 0, "firing `stash` on another resolution's state is a mis-fire"
    lines = [
        WrongFire.model_validate_json(line)
        for line in (out / "wrong_fires.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(lines) == summary.arm3_wrong
    assert all(fire.fired_variant == "stash" for fire in lines)
    assert all(fire.seed in HELD_OUT_SEEDS for fire in lines), "a record names its seed"
    assert all(fire.correct_variant != "stash" for fire in lines)
    assert all(fire.task_text for fire in lines), "a record must name the request it answered"
    assert "wrong" in (out / "summary.txt").read_text(encoding="utf-8")


def test_a_path_with_a_space_survives_the_fingerprint() -> None:
    """The axis' first finding: a git path list split on whitespace tears one path in two.

    Seed 3006 is a held-out `same_file` state whose upstream file has a space in it, so the
    tracked edit and upstream's commit are the same path. Reading `git diff --name-only` with
    `str.split()` made `upstream_touched_files` disagree with `dirty_files` about that file, the
    state read as `disjoint`, and `build_sandbox` refused the build as mislabelled before the
    label could even be compared (ADR-0005 decision 3) -- the invariant doing its job, on a
    defect in the fingerprint rather than in the injector. This is the regression test.
    """
    seed = 3006
    paths = paths_for_seed(seed)
    assert " " in paths.upstream_file, "this test is about a space in a path"
    assert DIRTY_TREE.variant_for_seed(seed) == "commit", "the state whose two sides are one file"
    box = build_sandbox(seed, ["dirty_tree"])
    try:
        observed = StateFingerprint.observe(box)
    finally:
        box.destroy()
    assert observed.dirty_files == [paths.upstream_file], "one path, not two entries"
    assert paths.upstream_file in observed.upstream_touched_files
    assert set(observed.dirty_files) & set(observed.upstream_touched_files) == {
        paths.upstream_file
    }, "the two sides are one file, which is what makes the state `commit`"
    correct = DIRTY_TREE_INTENT.correct_variant(observed)
    assert correct is not None
    assert correct.id == DIRTY_TREE.variant_for_seed(seed)
    for collision in observed.untracked_upstream_collisions:
        assert collision == paths.untracked_path, "an untracked path with a space stays whole"


def test_a_clean_held_out_block_leaves_the_wrong_fire_file_empty(tmp_path) -> None:
    """The gold library, so the file is empty and its length still tracks the count."""
    library_root = tmp_path / "gold"
    _gold_library(library_root)
    out = tmp_path / "run"
    summary = run_held_out(
        library_root,
        out,
        similarity=lexical_similarity,
        scorer_id={"scorer": "lexical"},
        source="the gold library",
        seeds=HELD_OUT_SEEDS[:1],
        plot=False,
    )
    lines = (out / "wrong_fires.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == summary.arm3_wrong
    assert summary.arm3_wrong == 0


def test_the_change_surface_is_the_seeds_own_paths() -> None:
    """A shipped seed may commit only the shipped paths; a held-out seed only its own.

    The grader reads this surface on every episode, so a union over the held-out pool would let
    a shipped `dirty_tree` episode rewrite `README.md` or `.gitattributes` and still be graded
    intact. Every other fault's surface does not depend on the seed.
    """
    from precondition_library.tasks.faults import FAULTS

    shipped = DIRTY_TREE.change_surface_for_seed(0)
    assert shipped == DIRTY_TREE.change_surface
    assert SHIPPED_PATHS.upstream_file in shipped
    for held_out in HELD_OUT_PATHS:
        for path in (held_out.upstream_file, held_out.tracked_file, held_out.untracked_path):
            if path not in (
                SHIPPED_PATHS.upstream_file,
                SHIPPED_PATHS.tracked_file,
                SHIPPED_PATHS.untracked_path,
            ):
                assert path not in shipped
    for seed in HELD_OUT_SEEDS[: len(HELD_OUT_PATHS)]:
        paths = paths_for_seed(seed)
        surface = DIRTY_TREE.change_surface_for_seed(seed)
        assert {paths.upstream_file, paths.tracked_file, paths.untracked_path} <= set(surface)
    for name, fault in FAULTS.items():
        if name not in HELD_OUT_FAULTS:
            assert fault.change_surface_for_seed(HELD_OUT_SEEDS[0]) == fault.change_surface


def test_every_shipped_diverged_seed_keeps_the_shipped_shape() -> None:
    """Below the base, the shape is the shipped one and the identity carries no shape (#263)."""
    for seed in [*range(HELD_OUT_SEED_BASE), *PLANNED_SEEDS]:
        assert diverged_shape_for_seed(seed) is DIVERGED_SHIPPED_SHAPE, seed
        assert "/shape=" not in DIVERGED.instance_for_seed(seed), seed
    for seed in HELD_OUT_SEEDS:
        assert diverged_shape_for_seed(seed) in DIVERGED_HELD_OUT_SHAPES, seed
        assert "/shape=" in DIVERGED.instance_for_seed(seed), seed


def test_a_held_out_diverged_state_changes_shape_and_keeps_its_label() -> None:
    """More upstream commits, an upstream-only file, more local commits; the same resolution."""
    seed = HELD_OUT_SEEDS[0]
    shape = diverged_shape_for_seed(seed)
    box = build_sandbox(seed, ["diverged"])
    try:
        observed = StateFingerprint.observe(box)
    finally:
        box.destroy()
    assert observed.upstream_ahead == shape.upstream_commits > 1
    assert shape.upstream_only_file in observed.upstream_touched_files
    assert len(observed.upstream_touched_files) == 2
    assert not observed.sync_would_conflict
    label = DIVERGED_INTENT.correct_variant(observed)
    assert label is not None and label.id == DIVERGED.variant_for_seed(seed)


def test_a_held_out_diverged_seed_widens_the_surface_by_its_own_file_only() -> None:
    assert DIVERGED.change_surface_for_seed(0) == DIVERGED.change_surface
    for seed in HELD_OUT_SEEDS[: len(DIVERGED_HELD_OUT_SHAPES)]:
        extra = diverged_shape_for_seed(seed).upstream_only_file
        assert DIVERGED.change_surface_for_seed(seed) == (*DIVERGED.change_surface, extra)


def test_every_shipped_lockfile_seed_keeps_the_shipped_path() -> None:
    """Below the base the file is `deps.lock` and the identity carries no path (#263)."""
    for seed in [*range(HELD_OUT_SEED_BASE), *PLANNED_SEEDS]:
        assert lock_path_for_seed(seed) == LOCK_PATH, seed
        assert "/path=" not in LOCKFILE.instance_for_seed(seed), seed
        assert LOCKFILE.change_surface_for_seed(seed) == LOCKFILE.change_surface, seed
    for seed in HELD_OUT_SEEDS:
        assert lock_path_for_seed(seed) in HELD_OUT_LOCK_PATHS, seed
        assert LOCKFILE.instance_for_seed(seed).endswith(f"/path={lock_path_for_seed(seed)}")
        assert LOCKFILE.change_surface_for_seed(seed) == (lock_path_for_seed(seed),)


def test_the_held_out_block_meets_every_lockfile_path_in_every_resolution() -> None:
    """Each path is drawn under both labels, so no path is read on one resolution only."""
    pairs = {(lock_path_for_seed(s), LOCKFILE.variant_for_seed(s)) for s in HELD_OUT_SEEDS}
    assert pairs == {
        (path, variant)
        for path in HELD_OUT_LOCK_PATHS
        for variant in ("take_upstream", "keep_local")
    }


@pytest.mark.parametrize("seed", HELD_OUT_SEEDS[: len(HELD_OUT_LOCK_PATHS)])
def test_a_held_out_lockfile_state_keeps_its_label_and_resolves_at_its_path(seed: int) -> None:
    """Each held-out path, built for real: the conflict is seen there, and its fix passes there.

    The non-ASCII path is the regression test for the fingerprint: `git diff --name-only`
    without `-z` printed it as an escaped string, the three-way read found no such file, and the
    conflict went unseen, so `build_sandbox` refused the state as mislabelled (ADR-0039). The
    gold body, with `deps.lock` replaced by the seed's path, then shows the checker grades the
    file where the state put it.
    """
    path = lock_path_for_seed(seed)
    variant = LOCKFILE.variant_for_seed(seed)
    box = build_sandbox(seed, ["lockfile_conflict"])
    try:
        observed = StateFingerprint.observe(box)
        assert observed.merge_conflicted_files == [path]
        assert observed.sync_would_conflict
        label = LOCKFILE_INTENT.correct_variant(observed)
        assert label is not None and label.id == variant
        assert not LOCKFILE.check(box).ok, "the injected state is not already resolved"
        body = gold_program(variant, "sync_through_a_conflicting_lockfile").body
        command = substitute(body.replace("deps.lock", '"$LOCK"'), bindings(box))
        done = subprocess.run(
            ["bash", "-c", command],
            cwd=box.work,
            env={**os.environ, "LOCK": path},
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr
        verdict = LOCKFILE.check(box)
        assert verdict.ok, verdict.detail
    finally:
        box.destroy()


def test_the_gold_lockfile_programs_refuse_a_file_they_do_not_rebuild() -> None:
    """The gold bodies rebuild `deps.lock` by name, so on a held-out path they must not fire.

    Before they required the file, every `git show <rev>:deps.lock` read nothing on such a
    state, the removal checks held vacuously, and `take_upstream` fired on every held-out
    `keep_local` state -- 15 wrong fires of 40 over the held-out block (ADR-0039).
    """
    seeds = [s for s in HELD_OUT_SEEDS if LOCKFILE.variant_for_seed(s) == "keep_local"][:2]
    for seed in seeds:
        box = build_sandbox(seed, ["lockfile_conflict"])
        try:
            for program in gold_programs("sync_through_a_conflicting_lockfile"):
                verdict = evaluate_preconditions(program, box)
                assert not verdict.ok, f"{program.variant} fired at {lock_path_for_seed(seed)}"
        finally:
            box.destroy()


def test_every_shipped_seed_keeps_its_branch_name_and_submodule_path() -> None:
    """Below the base both draws are the shipped ones, and identities carry no held-out value."""
    for seed in [*range(HELD_OUT_SEED_BASE), *PLANNED_SEEDS]:
        assert renamed_branch_for_seed(seed) in NEW_BRANCH_NAMES, seed
        assert submodule_path_for_seed(seed) == SUBMODULE_PATH, seed
        assert "/path=" not in SUBMODULE_MOVED.instance_for_seed(seed), seed
        assert SUBMODULE_MOVED.change_surface_for_seed(seed) == SUBMODULE_MOVED.change_surface
    for seed in HELD_OUT_SEEDS:
        assert renamed_branch_for_seed(seed) in HELD_OUT_BRANCH_NAMES, seed
        assert submodule_path_for_seed(seed) in HELD_OUT_SUBMODULE_PATHS, seed
        assert SUBMODULE_MOVED.instance_for_seed(seed).endswith(
            f"/path={submodule_path_for_seed(seed)}"
        )


@pytest.mark.parametrize(
    ("fault", "axis", "pool"),
    [
        (BRANCH_RENAMED, renamed_branch_for_seed, HELD_OUT_BRANCH_NAMES),
        (SUBMODULE_MOVED, submodule_path_for_seed, HELD_OUT_SUBMODULE_PATHS),
    ],
    ids=["branch_renamed", "submodule_moved"],
)
def test_the_held_out_block_meets_every_value_under_every_resolution(fault, axis, pool) -> None:
    resolutions = {fault.variant_for_seed(seed) for seed in range(64)}
    met = {(axis(seed), fault.variant_for_seed(seed)) for seed in HELD_OUT_SEEDS}
    assert met == {(value, resolution) for value in pool for resolution in resolutions}


_HELD_OUT_GOLD = [
    (fault, intent, seed)
    for fault, intent in (
        (BRANCH_RENAMED, BRANCH_RENAMED_INTENT),
        (SUBMODULE_MOVED, SUBMODULE_INTENT),
    )
    for seed in HELD_OUT_SEEDS[:4]
]


@pytest.mark.parametrize(
    ("fault", "intent", "seed"),
    _HELD_OUT_GOLD,
    ids=[f"{fault.name}-{seed}" for fault, _, seed in _HELD_OUT_GOLD],
)
def test_gold_resolves_a_held_out_state_at_its_own_name_or_path(fault, intent, seed) -> None:
    """The gold programs bind the name and path they are given, so the checker grades the
    held-out value the state uses, and the label the fault declares is the one replay needs."""
    box = build_sandbox(seed, [fault.name])
    try:
        observed = StateFingerprint.observe(box)
        label = intent.correct_variant(observed)
        assert label is not None and label.id == fault.variant_for_seed(seed)
        assert not fault.check(box).ok, "the injected state is not already resolved"
        result = replay(gold_program(label.id, intent.name), box)
        verdict = fault.check(box)
    finally:
        box.destroy()
    assert result.ok, result.reason
    assert verdict.ok, verdict.detail
