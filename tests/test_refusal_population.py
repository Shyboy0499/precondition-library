"""Study 2's registered statistics, build order and Control-R (refusal-population §5–§9)."""

from __future__ import annotations

import pytest

from precondition_library.bench import refusal_population as rp
from precondition_library.bench.admit_set import ADMIT_SET
from precondition_library.bench.build_library import _episode_plan, permuted_plan

# Four cases in two repositories: two inexpressible conflicts, two clean merges.
CASES = [
    rp.Case(index=0, repo="a", kind="inexpressible"),
    rp.Case(index=1, repo="a", kind="clean"),
    rp.Case(index=2, repo="b", kind="inexpressible"),
    rp.Case(index=3, repo="b", kind="clean"),
]


def _fires(inexpressible: tuple[bool, bool], clean_right: tuple[bool, bool]) -> rp.Decisions:
    return {
        0: rp.Fire(fired=inexpressible[0], right=False),
        2: rp.Fire(fired=inexpressible[1], right=False),
        1: rp.Fire(fired=True, right=clean_right[0]),
        3: rp.Fire(fired=True, right=clean_right[1]),
    }


CONTROL = _fires((True, True), (True, True))  # fires on everything
DECLINER = _fires((False, False), (True, True))
HALF = _fires((True, False), (True, False))


def test_the_rates_count_their_own_kind_of_case() -> None:
    assert rp.fire_rate(HALF, CASES) == 0.5
    assert rp.clean_right_rate(HALF, CASES) == 0.5
    assert rp.fire_rate(CONTROL, CASES) == 1.0
    assert rp.fire_rate(HALF, [c for c in CASES if c.kind == "clean"]) is None


def test_a_case_drawn_twice_counts_twice() -> None:
    assert rp.fire_rate(HALF, [CASES[0], CASES[0], CASES[2]]) == pytest.approx(2 / 3)


def test_the_statistics_by_hand() -> None:
    # f(control) = 1; the builds' f are 0 and 0.5, so the mean difference is (1 + 0.5) / 2.
    assert rp.against_control([DECLINER, HALF], CONTROL, CASES) == 0.75
    # mean f(0) = (1 + 0.5) / 2 = 0.75, mean f(R) = 0: H3's statistic is 0.75.
    assert rp.between_configurations([CONTROL, HALF], [DECLINER, DECLINER], CASES) == 0.75
    # mean right(R) = 1, mean right(0) = (1 + 0.5) / 2: no cost, a gain of 0.25.
    assert rp.clean_cost([CONTROL, HALF], [DECLINER, DECLINER], CASES) == 0.25


def test_identical_builds_and_cases_give_a_zero_width_interval() -> None:
    cases = [rp.Case(index=i, repo=f"r{i}", kind="inexpressible") for i in range(4)]
    build = {i: rp.Fire(fired=False, right=False) for i in range(4)}
    control = {i: rp.Fire(fired=True, right=False) for i in range(4)}
    found = rp.two_level_bootstrap(
        cases, [[build] * 5], lambda c, g: rp.against_control(g[0], control, c)
    )
    assert found.statistic == 1.0
    assert found.interval is not None and found.interval.low == found.interval.high == 1.0
    assert found.resamples == rp.BOOTSTRAP_RESAMPLES and found.skipped == 0


def test_the_bootstrap_is_deterministic_and_brackets_its_statistic() -> None:
    first = rp.estimate(CASES, [CONTROL, HALF], [DECLINER, HALF], CONTROL, CONTROL)
    again = rp.estimate(CASES, [CONTROL, HALF], [DECLINER, HALF], CONTROL, CONTROL)
    assert first == again
    for estimate in (first.h1, first.h2, first.h3, first.h4):
        assert estimate.interval is not None
        assert estimate.interval.low <= estimate.statistic <= estimate.interval.high


def _hypotheses(h1: float, h2: float, h3: float, h4: float) -> rp.Hypotheses:
    def at(low: float) -> rp.Estimate:
        return rp.Estimate(
            statistic=low + 0.1,
            interval=rp.Interval(low=low, high=low + 0.2),
            resamples=rp.BOOTSTRAP_RESAMPLES,
            skipped=0,
        )

    return rp.Hypotheses(h1=at(h1), h2=at(h2), h3=at(h3), h4=at(h4))


def test_an_underpowered_study_decides_nothing() -> None:
    decided = rp.decide(
        _hypotheses(0.5, 0.5, 0.5, 0.0), underpowered=True, zero=[HALF], refusal=[HALF], cases=CASES
    )
    assert [d.rule for d in decided] == ["1 power"]
    assert "nothing decided" in decided[0].outcome


def test_the_rules_in_order_and_the_cost_outcome() -> None:
    decided = rp.decide(
        _hypotheses(0.2, -0.1, 0.3, -0.2),
        underpowered=False,
        zero=[HALF],
        refusal=[HALF],
        cases=CASES,
    )
    outcomes = {d.rule: d.outcome for d in decided}
    assert [d.rule for d in decided] == [
        "1 power",
        "2 applicability",
        "3 H1",
        "4 H2",
        "5 H3 and H4",
    ]
    assert outcomes["3 H1"].startswith("supported")
    assert outcomes["4 H2"] == "not supported"
    assert "at the cost of clean merges" in outcomes["5 H3 and H4"]


def test_a_configuration_that_never_fires_is_not_tested() -> None:
    silent = {c.index: rp.Fire(fired=False, right=False) for c in CASES}
    decided = rp.decide(
        _hypotheses(0.5, 0.5, 0.5, 0.0),
        underpowered=False,
        zero=[HALF],
        refusal=[silent],
        cases=CASES,
    )
    outcomes = {d.rule: d.outcome for d in decided}
    assert "configuration R fires on no case" in outcomes["2 applicability"]
    assert outcomes["3 H1"] == "not tested"
    assert outcomes["5 H3 and H4"] == "not tested"
    assert outcomes["4 H2"].startswith("supported")


def test_the_spread() -> None:
    found = rp.spread([0.2, 0.4, 0.6, 0.8])
    assert found["mean"] == pytest.approx(0.5)
    assert (found["min"], found["max"]) == (0.2, 0.8)
    assert found["sd"] == pytest.approx(0.2581988897)
    assert found["iqr"] == pytest.approx(0.3)


# --- the build order (§5) ------------------------------------------------------------------------


FAULTS = sorted(ADMIT_SET)


def _shape(plan: dict) -> list:
    """Each fault's resolutions in order, each with its seeds in order."""
    return [
        (fault, [(group[0][1], [seed for seed, _, _ in group]) for group in plan[fault]])
        for fault in FAULTS
    ]


def test_a_build_order_permutes_each_faults_plan_and_nothing_else() -> None:
    registered = _episode_plan(FAULTS, None)
    for order in range(5):
        permuted = permuted_plan(registered, FAULTS, order)
        assert set(permuted) == set(registered)
        for fault in FAULTS:
            for group in permuted[fault]:
                assert len({resolution for _, resolution, _ in group}) == 1, (
                    "a resolution's seeds stay together"
                )

            def seeds(plan: dict, fault: str = fault) -> dict:
                return {g[0][1]: sorted(seed for seed, _, _ in g) for g in plan[fault]}

            assert seeds(permuted) == seeds(registered)
            assert len(permuted[fault]) == len(registered[fault])


def test_a_build_order_is_deterministic_and_orders_differ() -> None:
    registered = _episode_plan(FAULTS, None)
    assert _shape(permuted_plan(registered, FAULTS, 3)) == _shape(
        permuted_plan(registered, FAULTS, 3)
    )
    orders = {repr(_shape(permuted_plan(registered, FAULTS, b))) for b in range(10)}
    assert len(orders) == 10, "each of the ten build indices gives its own order"


def test_permuting_leaves_the_registered_plan_as_it_was() -> None:
    registered = _episode_plan(FAULTS, None)
    before = _shape(registered)
    permuted_plan(registered, FAULTS, 7)
    assert _shape(registered) == before


def test_the_live_option_parses() -> None:
    from precondition_library.bench import live

    base = ["--api-key-env", "UNUSED", "--out", "x"]
    assert live._parser().parse_args([*base, "--build-order", "4"]).build_order == 4
    assert live._parser().parse_args(base).build_order is None
