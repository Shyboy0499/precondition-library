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

from pathlib import Path

import pytest
from conftest import gold_programs

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
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.signatures import StateFingerprint
from precondition_library.similarity import lexical_similarity
from precondition_library.tasks.faults import build_sandbox
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
from precondition_library.tasks.registry import ambiguous_intents
from precondition_library.tasks.spec import HELD_OUT_SEED_BASE

PLANNED_SEEDS = [*SMOKE_SEEDS, *TUNE_SEEDS, *EVAL_SEEDS]

HELD_OUT_AXES = {
    "dirty_tree": lambda seed: paths_for_seed(seed).upstream_file,
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
    assert summary.pairs == 2 * len(HELD_OUT_SEEDS[:2])
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
