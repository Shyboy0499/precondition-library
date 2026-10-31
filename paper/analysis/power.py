"""Monte Carlo power of study 2's registered tests (refusal-population §7–§9), for the report.

A design analysis, not a result: nothing here reads study 2's data, which does not exist yet.
Each simulated study draws the evaluation set at the registered targets and 10 builds per
configuration, then applies the registered statistic and decision rule: a hypothesis is
supported when its 95% two-level bootstrap interval's lower bound is above 0 (H1–H3) or above
-0.10 (H4).

**The generating model.** A case `i` in repository `r` is fired on by build `b` with probability
`logistic(a_b + u_r + v_i)`. Each build's `a_b` is drawn as `N(logit(m), s_build)`, each
repository's `u_r` as `N(0, s_repo)` and each case's `v_i` as `N(0, s_case)`. A control is one
dispatcher, so it is one draw. `s_build` is calibrated on study 1: its three libraries fired on
22.5%, 5.6% and 81.9% of the inexpressible conflicts, whose logits have a standard deviation of
2.2. The repository and case spreads have no such anchor and are varied.

**The bootstrap.** `bootstrap` is the registered `refusal_population.two_level_bootstrap`
vectorised: each resample draws the repositories with replacement, then each configuration's
builds with replacement, and the interval is the same floor/ceil percentile. `validate` checks it
against the registered code on simulated studies before any power is computed: the point
estimates must be identical, and the interval ends within Monte Carlo error.

    python paper/analysis/power.py --out paper/analysis
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from precondition_library.bench import refusal_population as rp

RESAMPLES = rp.BOOTSTRAP_RESAMPLES
BUILDS = 10
REPOSITORIES = (30, 25, 15, 10, 8, 7, 5)
"""Inexpressible conflicts per evaluation repository: 100 from 7 repositories, the largest at
the cap's edge. Clean cases are spread in the same proportions, 60 in all."""
CLEAN = (18, 15, 9, 6, 5, 4, 3)
STUDY_1_LOGITS = [math.log(p / (1 - p)) for p in (0.225, 0.056, 0.819)]
S_BUILD = float(np.std(STUDY_1_LOGITS, ddof=1))
S_CLEAN_BUILD = float(
    np.std([math.log(p / (1 - p)) for p in (87 / 113, 112 / 113, 112 / 113)], ddof=1)
)


def logit(p: float) -> float:
    return math.log(p / (1 - p))


@dataclass(frozen=True)
class World:
    """One scenario's truth."""

    zero_centre: float
    """Configuration 0's build centre, as a fire rate on the logit's scale."""
    refusal_centre: float
    control_zero: float
    control_refusal: float
    clean_zero: float = 0.91
    """Right-fire rate on clean cases; study 1's libraries were right on 87, 112 and 112 of
    113 clean cases."""
    clean_refusal: float = 0.91
    s_build: float = S_BUILD
    s_clean_build: float = 1.0
    """The builds' spread on clean cases. Study 1's right rates there (87, 112 and 112 of 113)
    have logits with a standard deviation of 2.0, `S_CLEAN_BUILD`."""
    s_repo: float = 0.5
    s_case: float = 0.5

    def realised(self) -> dict[str, float]:
        """Each dispatcher's expected rate, and each hypothesis's true difference: a centre is
        not a mean once builds, repositories and cases vary on the logit scale."""
        rng = np.random.default_rng(0)
        cases = self.s_repo**2 + self.s_case**2

        def mean(centre: float, s: float) -> float:
            z = rng.normal(logit(centre), math.sqrt(s**2 + cases), 400_000)
            return float((1 / (1 + np.exp(-z))).mean())

        rates = {
            "zero": mean(self.zero_centre, self.s_build),
            "refusal": mean(self.refusal_centre, self.s_build),
            "control_zero": mean(self.control_zero, 0.0),
            "control_refusal": mean(self.control_refusal, 0.0),
            "zero_clean": mean(self.clean_zero, self.s_clean_build),
            "refusal_clean": mean(self.clean_refusal, self.s_clean_build),
        }
        return {
            **rates,
            "h1": rates["control_refusal"] - rates["refusal"],
            "h2": rates["control_zero"] - rates["zero"],
            "h3": rates["zero"] - rates["refusal"],
            "h4": rates["refusal_clean"] - rates["zero_clean"],
        }


@dataclass
class Study:
    """One simulated study, in the shape the registered statistics read."""

    repo_of_inexpressible: np.ndarray
    repo_of_clean: np.ndarray
    zero: np.ndarray
    """Builds by inexpressible cases: fired or not."""
    refusal: np.ndarray
    control_zero: np.ndarray
    control_refusal: np.ndarray
    zero_clean: np.ndarray
    """Builds by clean cases: right or not."""
    refusal_clean: np.ndarray


def _probabilities(rng: np.random.Generator, centre: float, s_build: float, base: np.ndarray):
    builds = rng.normal(logit(centre), s_build, size=(BUILDS, 1))
    return 1 / (1 + np.exp(-(builds + base)))


def simulate(world: World, rng: np.random.Generator) -> Study:
    repo_inexpressible = np.repeat(np.arange(len(REPOSITORIES)), REPOSITORIES)
    repo_clean = np.repeat(np.arange(len(CLEAN)), CLEAN)
    repo_effect = rng.normal(0, world.s_repo, size=len(REPOSITORIES))
    base = repo_effect[repo_inexpressible] + rng.normal(0, world.s_case, len(repo_inexpressible))
    base_clean = repo_effect[repo_clean] + rng.normal(0, world.s_case, len(repo_clean))

    def control(rate: float) -> np.ndarray:
        p = 1 / (1 + np.exp(-(logit(rate) + base)))
        return rng.random(len(base)) < p

    return Study(
        repo_of_inexpressible=repo_inexpressible,
        repo_of_clean=repo_clean,
        zero=rng.random((BUILDS, len(base)))
        < _probabilities(rng, world.zero_centre, world.s_build, base),
        refusal=rng.random((BUILDS, len(base)))
        < _probabilities(rng, world.refusal_centre, world.s_build, base),
        control_zero=control(world.control_zero),
        control_refusal=control(world.control_refusal),
        zero_clean=rng.random((BUILDS, len(base_clean)))
        < _probabilities(rng, world.clean_zero, world.s_clean_build, base_clean),
        refusal_clean=rng.random((BUILDS, len(base_clean)))
        < _probabilities(rng, world.clean_refusal, world.s_clean_build, base_clean),
    )


def _per_repo(matrix: np.ndarray, repo: np.ndarray, repos: int) -> np.ndarray:
    """Counts per repository: builds (or one row) by repositories."""
    rows = np.atleast_2d(matrix).astype(float)
    return np.stack([rows[:, repo == r].sum(axis=1) for r in range(repos)], axis=1)


def bootstrap(study: Study, rng: np.random.Generator, resamples: int = RESAMPLES) -> dict:
    """Every hypothesis's statistic and interval, by the registered two-level bootstrap."""
    repos = len(REPOSITORIES)
    n_inexpressible = np.bincount(study.repo_of_inexpressible, minlength=repos).astype(float)
    n_clean = np.bincount(study.repo_of_clean, minlength=repos).astype(float)
    fires = {
        "zero": _per_repo(study.zero, study.repo_of_inexpressible, repos),
        "refusal": _per_repo(study.refusal, study.repo_of_inexpressible, repos),
        "control_zero": _per_repo(study.control_zero, study.repo_of_inexpressible, repos),
        "control_refusal": _per_repo(study.control_refusal, study.repo_of_inexpressible, repos),
        "zero_clean": _per_repo(study.zero_clean, study.repo_of_clean, repos),
        "refusal_clean": _per_repo(study.refusal_clean, study.repo_of_clean, repos),
    }
    # Each resample: repository multiplicities, then each configuration's build multiplicities.
    drawn = rng.multinomial(repos, [1 / repos] * repos, size=resamples)
    weights_zero = rng.multinomial(BUILDS, [1 / BUILDS] * BUILDS, size=resamples) / BUILDS
    weights_refusal = rng.multinomial(BUILDS, [1 / BUILDS] * BUILDS, size=resamples) / BUILDS

    def rate(counts: np.ndarray, denominators: np.ndarray, multiplicity: np.ndarray) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            return (counts @ multiplicity.T) / (denominators @ multiplicity.T)

    every = np.ones((1, repos))
    point = {name: rate(value, n_inexpressible, every) for name, value in fires.items()}
    point["zero_clean"] = rate(fires["zero_clean"], n_clean, every)
    point["refusal_clean"] = rate(fires["refusal_clean"], n_clean, every)
    resampled = {
        name: rate(value, n_clean if name.endswith("clean") else n_inexpressible, drawn)
        for name, value in fires.items()
    }

    def builds_mean(per_build: np.ndarray, weights: np.ndarray | None) -> np.ndarray:
        if weights is None:
            return per_build.mean(axis=0)
        return (per_build * weights.T).sum(axis=0)

    statistics = {
        "h1": lambda v, wz, wr: v["control_refusal"][0] - builds_mean(v["refusal"], wr),
        "h2": lambda v, wz, wr: v["control_zero"][0] - builds_mean(v["zero"], wz),
        "h3": lambda v, wz, wr: builds_mean(v["zero"], wz) - builds_mean(v["refusal"], wr),
        "h4": lambda v, wz, wr: (
            builds_mean(v["refusal_clean"], wr) - builds_mean(v["zero_clean"], wz)
        ),
    }
    out = {}
    for name, statistic in statistics.items():
        estimate = float(statistic(point, None, None)[0])
        values = statistic(resampled, weights_zero, weights_refusal)
        values = np.sort(values[~np.isnan(values)])
        if len(values) < resamples // 2:
            out[name] = (estimate, None, None)
            continue
        low = values[math.floor(0.025 * (len(values) - 1))]
        high = values[math.ceil(0.975 * (len(values) - 1))]
        out[name] = (estimate, float(low), float(high))
    return out


def supported(found: dict) -> dict:
    bounds = {"h1": 0.0, "h2": 0.0, "h3": 0.0, "h4": -rp.H4_MARGIN}
    return {
        name: found[name][1] is not None and found[name][1] > bound
        for name, bound in bounds.items()
    }


def _registered(study: Study) -> rp.Hypotheses:
    """The same study through the registered code."""
    cases = [
        rp.Case(index=i, repo=f"r{r}", kind="inexpressible")
        for i, r in enumerate(study.repo_of_inexpressible)
    ]
    offset = len(cases)
    cases += [
        rp.Case(index=offset + i, repo=f"r{r}", kind="clean")
        for i, r in enumerate(study.repo_of_clean)
    ]

    def decisions(fired: np.ndarray, right: np.ndarray) -> rp.Decisions:
        found = {i: rp.Fire(fired=bool(f), right=False) for i, f in enumerate(fired)}
        found.update({offset + i: rp.Fire(fired=True, right=bool(x)) for i, x in enumerate(right)})
        return found

    nothing = np.zeros(len(study.repo_of_clean), dtype=bool)
    zero = [decisions(study.zero[b], study.zero_clean[b]) for b in range(BUILDS)]
    refusal = [decisions(study.refusal[b], study.refusal_clean[b]) for b in range(BUILDS)]
    return rp.estimate(
        cases,
        zero,
        refusal,
        decisions(study.control_zero, nothing),
        decisions(study.control_refusal, nothing),
    )


def validate(rng: np.random.Generator, studies: int = 3) -> list[dict]:
    """The vectorised bootstrap against the registered code: identical point estimates, and
    interval ends within Monte Carlo error (the two draw their resamples differently)."""
    rows = []
    for k in range(studies):
        study = simulate(World(0.37, 0.15 + 0.1 * k, 0.99, 0.6), rng)
        mine = bootstrap(study, rng)
        theirs = _registered(study)
        for name in ("h1", "h2", "h3", "h4"):
            registered = getattr(theirs, name)
            assert registered.statistic is not None and registered.interval is not None
            assert abs(mine[name][0] - registered.statistic) < 1e-12, (name, mine, registered)
            rows.append(
                {
                    "study": k,
                    "hypothesis": name,
                    "statistic": registered.statistic,
                    "registered_interval": [registered.interval.low, registered.interval.high],
                    "vectorised_interval": [mine[name][1], mine[name][2]],
                }
            )
            assert abs(mine[name][1] - registered.interval.low) < 0.03, rows[-1]
            assert abs(mine[name][2] - registered.interval.high) < 0.03, rows[-1]
    return rows


def power(world: World, studies: int, rng: np.random.Generator) -> dict:
    hits = {"h1": 0, "h2": 0, "h3": 0, "h4": 0}
    for _ in range(studies):
        for name, ok in supported(bootstrap(simulate(world, rng), rng)).items():
            hits[name] += ok
    return {name: count / studies for name, count in hits.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--studies", type=int, default=400)
    parser.add_argument("--nulls", type=int, default=2000)
    args = parser.parse_args()
    rng = np.random.default_rng(20261031)
    checks = validate(rng)
    grid = []

    def run(world: World, studies: int, kind: str) -> None:
        grid.append(
            {
                "kind": kind,
                "world": asdict(world),
                "realised": world.realised(),
                "studies": studies,
                "power": power(world, studies, rng),
            }
        )

    # H1, the primary test: Control-R's fire rate against configuration R's build centre.
    for s_build in (S_BUILD, 1.0):
        for control_refusal in (0.99, 0.7, 0.5, 0.3):
            for refusal_centre in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5):
                world = World(0.37, refusal_centre, 0.99, control_refusal, s_build=s_build)
                run(world, args.studies, "h1")
    # H3 and H4 together: configuration R lowers the fire rate, and costs clean merges or not.
    for s_clean in (1.0, S_CLEAN_BUILD):
        for clean_refusal in (0.91, 0.85, 0.76):
            for refusal_centre in (0.37, 0.2, 0.1, 0.05):
                world = World(
                    0.37,
                    refusal_centre,
                    0.99,
                    0.5,
                    clean_refusal=clean_refusal,
                    s_clean_build=s_clean,
                )
                run(world, args.studies, "h3-h4")
    # Sensitivity to the spreads with no anchor in study 1.
    for s_repo, s_case in ((0.0, 0.0), (1.0, 0.5), (0.5, 1.5)):
        run(World(0.37, 0.1, 0.99, 0.5, s_repo=s_repo, s_case=s_case), args.studies, "spread")
    # The nulls, with more studies: H1 with Control-R and R's builds both at 0.5, and H3 with
    # both configurations' builds alike. A supported hypothesis there is a false positive.
    for s_build in (S_BUILD, 1.0):
        run(World(0.37, 0.5, 0.99, 0.5, s_build=s_build), args.nulls, "null h1")
        run(World(0.37, 0.37, 0.99, 0.5, s_build=s_build), args.nulls, "null h3")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "power.json").write_text(
        json.dumps(
            {
                "studies_per_world": args.studies,
                "resamples": RESAMPLES,
                "s_build_from_study_1": S_BUILD,
                "s_clean_build_from_study_1": S_CLEAN_BUILD,
                "validation": checks,
                "grid": grid,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
