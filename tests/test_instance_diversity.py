"""Two seeds that select the same resolution must build different environments.

Issue #86's property, pinned directly. It was **false** before ADR-0005 landed:
the injectors selected among three hand-authored state shapes per measurable fault
and the seed chose *which* shape, not the shape's content, so `diverged` seeds 0
and 4 both resolved to `merge` and built byte-identical environments -- not even
the commit SHAs differed, because the sandbox pins author and committer dates and
identities. A new seed that landed on an already-seen resolution was therefore not
a new environment.

The change that lands #86 parameterises each state shape along declared Tier 1
axes (`file body content`, `local commit count and subject`, `conflict hunk
position`) and draws one value per axis from the seed, so same-resolution seeds
now differ in content. This module keeps the direct pin:

* `test_same_resolution_seeds_build_different_environments` builds two real
  sandboxes per resolution -- `tasks.faults.build_sandbox`, never a mock -- and
  asserts their content signatures differ.
* `test_every_resolution_reaches_four_real_environments` builds four real
  sandboxes per resolution, one per distinct drawn instance identity, and asserts
  they are four real environments. That is the owner's approved target (4 per
  resolution, 36 across the three measurable faults) measured from sandboxes rather
  than from the drawn identity alone.

The signature is the working tree's file bodies, names and counts, the conflict
positions, the submodule paths and the branch wiring, and it excludes commit SHAs
on purpose: a difference in SHAs alone is not a new environment (#86), so the pin
must not be satisfiable by re-stamping commits. The sandbox's
`test_instance_diversity` sibling check that identity maps one-to-one onto the
signature -- distinct `instance_for_seed` values build distinct real environments
-- is the `bench/instance_diversity.py` measurement, run over all 60 plan seeds.

Only the faults whose intent is ambiguous are covered, because they are the only
ones with a resolution to be the same or different. The two faults in
`EXCLUDED_FROM_BENCHMARK` have no resolution (`variant_for_seed` is `None`), so
grouping their seeds by one would assert a property about a label that does not
exist.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from precondition_library.bench.instance_diversity import environment_axes, instance_signature
from precondition_library.bench.splits import EVAL_SEEDS, SMOKE_SEEDS, TUNE_SEEDS
from precondition_library.tasks.faults import FAULTS
from precondition_library.tasks.registry import ambiguous_intents

PLAN_SEEDS: tuple[int, ...] = (*SMOKE_SEEDS, *TUNE_SEEDS, *EVAL_SEEDS)

MEASURABLE_FAULTS: tuple[str, ...] = tuple(sorted(intent.fault for intent in ambiguous_intents()))

TARGET_INSTANCES_PER_RESOLUTION = 4
"""The owner's approved target: four independent instances per resolution.

ADR-0005 fixes the approach and leaves the count to "whatever the declared draw
yields"; the target is the number the work is judged against (4 x 9 resolutions =
36 environments since `dirty_tree` was registered, ADR-0027).
"""


def _same_resolution_cases() -> list[tuple[str, str, int, int]]:
    """`(fault, resolution, seed_a, seed_b)` for every resolution two seeds share.

    Derived from the injector's own `variant_for_seed` and the pre-registered
    seeds, so a case cannot name a resolution the injector does not make correct
    at those seeds.
    """
    cases: list[tuple[str, str, int, int]] = []
    for fault in MEASURABLE_FAULTS:
        spec = FAULTS[fault]
        by_resolution: dict[str, list[int]] = defaultdict(list)
        for seed in PLAN_SEEDS:
            resolution = spec.variant_for_seed(seed)
            if resolution is not None:
                by_resolution[resolution].append(seed)
        for resolution, seeds in sorted(by_resolution.items()):
            # The first later seed that draws a different instance: one that draws the
            # same identity is a replay of the same environment by design (ADR-0005),
            # which `dirty_tree/aside`'s four-value draw makes likely among few seeds.
            other = next(
                (
                    s
                    for s in seeds[1:]
                    if spec.instance_for_seed(s) != spec.instance_for_seed(seeds[0])
                ),
                None,
            )
            if other is not None:
                cases.append((fault, resolution, seeds[0], other))
    return cases


CASES = _same_resolution_cases()
CASE_IDS = [f"{fault}-{resolution}-{a}-{b}" for fault, resolution, a, b in CASES]

RESOLUTIONS: list[tuple[str, str]] = sorted(
    {(fault, resolution) for fault, resolution, _, _ in CASES}
)
RESOLUTION_IDS = [f"{fault}-{resolution}" for fault, resolution in RESOLUTIONS]


def _first_seed_per_instance(fault: str, resolution: str, count: int) -> list[int]:
    """The first `count` plan seeds that draw distinct instance identities.

    One seed per distinct `instance_for_seed` value, in plan order, so the seeds
    returned are the plan's own and no two of them claim the same instance. A
    resolution with fewer than `count` distinct instances returns fewer, and the
    test that calls this fails on the shortfall rather than silently building a
    smaller sample.
    """
    spec = FAULTS[fault]
    chosen: dict[str, int] = {}
    for seed in PLAN_SEEDS:
        if spec.variant_for_seed(seed) != resolution:
            continue
        chosen.setdefault(spec.instance_for_seed(seed), seed)
        if len(chosen) == count:
            break
    return list(chosen.values())


def test_every_measurable_resolution_has_two_plan_seeds() -> None:
    """The pin is only meaningful if each resolution is actually selected twice.

    If a resolution had one seed in the plan, the "same resolution" comparison
    would have no pair and the case would silently vanish from the parametrisation
    rather than fail. This makes that state a failure instead.
    """
    resolutions = {(fault, resolution) for fault, resolution, _, _ in CASES}
    # Compared against the intents' declared variants, not a hardcoded list, so a
    # resolution added to a fault without a second plan seed fails here.
    expected = {
        (intent.fault, variant.id) for intent in ambiguous_intents() for variant in intent.variants
    }
    assert resolutions == expected, (
        f"resolutions without a same-resolution seed pair: {sorted(expected - resolutions)}"
    )


@pytest.mark.parametrize(("fault", "resolution", "seed_a", "seed_b"), CASES, ids=CASE_IDS)
def test_same_resolution_seeds_build_different_environments(
    fault: str, resolution: str, seed_a: int, seed_b: int, make_sandbox
) -> None:
    """Two seeds selecting one resolution must be different environments.

    `instance_signature` compares file bodies, names, counts, conflict positions,
    submodule paths and branch wiring, and deliberately **excludes commit SHAs**:
    issue #86's finding is that a difference in SHAs alone is not a new
    environment, so a signature that moved only when a SHA did would let cosmetic
    variation pass as diversity. The property is what the mismatch comparison's
    unit of analysis needs: a second observation of a resolution has to be a second
    environment, or it is the same observation counted twice. The pair is two seeds
    whose drawn instance identities differ; a seed repeating an identity is a replay
    of the same environment by design, and `occurrence_roles` counts it as one.

    This passed as a strict `xfail` before the axis draw landed; the marker was
    deleted in the change that made it pass, and it passes for the real reason --
    the two drawn instances have different file-body signatures -- not because the
    comparison was loosened.
    """
    first = make_sandbox(seed_a, [fault])
    second = make_sandbox(seed_b, [fault])
    assert instance_signature(first) != instance_signature(second), (
        f"{fault}/{resolution}: seeds {seed_a} and {seed_b} select the same "
        f"resolution and built identical environments (issue #86)"
    )


@pytest.mark.parametrize(
    ("fault", "resolution"),
    RESOLUTIONS,
    ids=RESOLUTION_IDS,
)
def test_declared_axes_are_the_axes_actually_drawn(fault: str, resolution: str) -> None:
    """The per-resolution axis declaration must be real, not prose (ADR-0005 §2).

    Every declared axis must take at least two values over the plan seeds that
    select the resolution -- an axis declared but never drawn is decoration -- and
    the draw must move no axis the resolution did not declare, since an undeclared
    axis is one whose safety nobody checked. The values must also come from the
    declared pool, so the declaration and the injector cannot drift apart.
    """
    spec = FAULTS[fault]
    seeds = [seed for seed in PLAN_SEEDS if spec.variant_for_seed(seed) == resolution]
    declared = spec.axes_for_resolution(resolution)
    assert declared, f"{fault}/{resolution}: no axis declared, so nothing can vary"
    for axis, pool in declared.items():
        assert len(pool) >= 2, f"{fault}/{resolution}: axis {axis!r} has a single value"
        values = {spec.drawn_axes_for_seed(seed)[axis] for seed in seeds}
        assert values <= set(pool), (
            f"{fault}/{resolution}: axis {axis!r} drew {sorted(values - set(pool))}, "
            f"which is outside its declared pool {sorted(pool)}"
        )
        assert len(values) >= 2, (
            f"{fault}/{resolution}: declared axis {axis!r} never varies over the "
            f"{len(seeds)} plan seed(s) that select the resolution"
        )
    assert set(spec.drawn_axes_for_seed(seeds[0])) == set(declared), (
        f"{fault}/{resolution}: the draw moves an axis the resolution did not declare"
    )


@pytest.mark.parametrize(
    ("fault", "resolution"),
    RESOLUTIONS,
    ids=RESOLUTION_IDS,
)
def test_every_resolution_reaches_four_real_environments(
    fault: str, resolution: str, make_sandbox
) -> None:
    """Every resolution must reach the approved target of four real environments.

    Real sandboxes, one per distinct drawn instance identity, compared by
    `instance_signature`. This is what ADR-0005's "the count is measured and
    reported" means for the target: the drawn identity says how many instances the
    seeds *claim*, and this says how many the sandboxes *are*. A draw that changed
    an identity without changing the environment would fail here.
    """
    seeds = _first_seed_per_instance(fault, resolution, TARGET_INSTANCES_PER_RESOLUTION)
    assert len(seeds) == TARGET_INSTANCES_PER_RESOLUTION, (
        f"{fault}/{resolution}: the plan seeds draw {len(seeds)} distinct instance "
        f"identit(ies), fewer than the target of {TARGET_INSTANCES_PER_RESOLUTION}"
    )
    signatures = {instance_signature(make_sandbox(seed, [fault])) for seed in seeds}
    assert len(signatures) == TARGET_INSTANCES_PER_RESOLUTION, (
        f"{fault}/{resolution}: {len(seeds)} distinct instance identities built "
        f"{len(signatures)} distinct environments, so the draw is not a real draw"
    )


@pytest.mark.parametrize(
    "resolution",
    sorted(resolution for fault, resolution in RESOLUTIONS if fault == "submodule_moved"),
)
def test_gitlinks_are_compared_by_the_content_they_name(resolution: str, make_sandbox) -> None:
    """A gitlink enters the signature as nested blobs, never as a nested commit id.

    `submodule_moved/init`'s instances differ only behind the upstream gitlink, and
    a gitlink's object id is a commit id -- the SHA-level identity #86 refuses as a
    new environment. ADR-0006 counts those instances because the link names
    different content, so the signature has to witness that content: every gitlink
    is expanded into the nested commit's blob lines, none is left unresolved, and
    two distinct instances still differ once no commit id is in the comparison.
    """
    seeds = _first_seed_per_instance("submodule_moved", resolution, 2)
    trees = [
        environment_axes(make_sandbox(seed, ["submodule_moved"]))["upstream tree"] for seed in seeds
    ]
    for seed, tree in zip(seeds, trees, strict=True):
        assert not [line for line in tree if line.startswith("160000 ")], (
            f"seed {seed}: a gitlink's commit id is still in the signature"
        )
        assert not [line for line in tree if "unresolved" in line], (
            f"seed {seed}: a gitlink could not be resolved to nested content"
        )
    if resolution == "init":
        nested = [{line for line in tree if line.startswith("gitlink ")} for tree in trees]
        assert all(nested) and nested[0] != nested[1], (
            f"init seeds {seeds}: the nested content behind the gitlink does not differ, "
            f"so the instances would be distinct by commit id alone"
        )
