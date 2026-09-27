"""Two seeds that select the same resolution must build different environments.

Issue #86's property, pinned directly. It is **false today**, and the failing case
is the issue's own measurement: `diverged` seeds 0 and 4 both resolve to `merge`,
and the two sandboxes are byte-identical. The injectors select among three
hand-authored state shapes per measurable fault and the seed chooses *which*
shape, not the shape's content; because the sandbox pins author and committer
dates and identities, not even the commit SHAs differ. So a new seed that lands
on an already-seen resolution is not a new environment.

The test builds two real sandboxes per resolution -- `tasks.faults.build_sandbox`,
never a mock -- and asserts their content signatures differ. The signature is the
working tree's file bodies, names and counts, the conflict positions, the
submodule paths and the branch wiring, and it excludes commit SHAs on purpose: a
difference in SHAs alone is not a new environment (#86), so the pin must not be
satisfiable by re-stamping commits.

**Why `xfail(strict=True)` is the honest vehicle.** The property does not hold
yet, and a test that fails cannot merge. The strict marker lets CI carry the
failing case without hiding it: a fix that gives the injectors diversity makes the
body pass, pytest reports it as an unexpected pass, and strict turns that into a
failure -- which is the reminder to delete this marker. The test therefore flips
to a real, unmarked pass in the change that lands #86, and cannot quietly become
a passing test whose marker nobody removed.

Only the two faults whose intent is ambiguous are covered, because they are the
only ones with a resolution to be the same or different. The three faults in
`EXCLUDED_FROM_BENCHMARK` have no resolution (`variant_for_seed` is `None`), so
grouping their seeds by one would assert a property about a label that does not
exist -- and two of those faults already vary content by seed, which would make
the assertion pass for a reason unrelated to resolution diversity.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from precondition_library.bench.instance_diversity import instance_signature
from precondition_library.bench.splits import EVAL_SEEDS, SMOKE_SEEDS, TUNE_SEEDS
from precondition_library.tasks.faults import FAULTS
from precondition_library.tasks.registry import ambiguous_intents

PLAN_SEEDS: tuple[int, ...] = (*SMOKE_SEEDS, *TUNE_SEEDS, *EVAL_SEEDS)

MEASURABLE_FAULTS: tuple[str, ...] = tuple(sorted(intent.fault for intent in ambiguous_intents()))


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
            if len(seeds) >= 2:
                cases.append((fault, resolution, seeds[0], seeds[1]))
    return cases


CASES = _same_resolution_cases()
CASE_IDS = [f"{fault}-{resolution}-{a}-{b}" for fault, resolution, a, b in CASES]


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "issue #86: the injectors vary which state a seed selects, not the state's "
        "content, so two seeds selecting one resolution build byte-identical "
        "environments. Delete this marker in the change that adds instance diversity."
    ),
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
    environment, or it is the same observation counted twice.
    """
    first = make_sandbox(seed_a, [fault])
    second = make_sandbox(seed_b, [fault])
    assert instance_signature(first) != instance_signature(second), (
        f"{fault}/{resolution}: seeds {seed_a} and {seed_b} select the same "
        f"resolution and built identical environments (issue #86)"
    )
