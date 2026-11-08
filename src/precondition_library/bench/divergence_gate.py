"""Study 5: does refusing where a package diverges make the package-level merge rarely wrong?

Registered in `docs/preregistration/divergence-gate.md` before any of its data was mined. Each
section cited here (§n) is that document's.

After seeing studies 3 and 4, `results/lock-anatomy-2026-11-04/` found that a conflicted lock
file's merge mostly works when no package *diverges* (both sides changed its versions, to
different versions) and mostly fails when one does. The rule it suggests is a precondition a
dispatcher can execute: fire the predicted per-ecosystem merge on a conflict only if no package
diverges in any of its conflicted lock files, and refuse otherwise (the *gate*).

**The cases and labels (§3, §4)** are study 3's, made by the same code: `lock_oracle`'s mining,
its cap of 15 conflicted cases per repository, and its per-file computed actions. The *predicted*
merge is study 4's (`ecosystem_unify.predicted`).

Per repository where the gate fires (§6):

* **H1 (primary):** the mean over repositories of the gate's mismatch, m_gate, is above 0.10:
  the gate does not make the merge rarely wrong.
* **H2:** the mean of m_always − m_gate is above 0: the gate lowers the merge's mismatch.
* **H3:** within repositories, on cases whose conflicted lock files are all one-version, the merge
  reproduces more often where nothing diverges: a Mantel-Haenszel risk difference, with a
  percentile bootstrap over repositories.

    python -m precondition_library.bench.divergence_gate --out results/divergence-gate-<date>

Mining reads git only; nothing here runs a package manager or model-authored code.
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from . import lock_actions as la
from .ecosystem_unify import family, predicted
from .lock_oracle import (
    CaseLabel,
    Estimate,
    Interval,
    OracleExclusion,
    covered,
    estimate,
    label_repository,
    t_975,
)
from .preregistration import require
from .real_merges import Case, Repository, fetch_real_host, host, mine, pin

REGISTRATION = "divergence-gate"

REPOSITORIES: tuple[str, ...] = (
    "Kovah/LinkAce",
    "krayin/laravel-crm",
    "PrivateBin/PrivateBin",
    "cachethq/cachet",
    "coollabsio/coolify",
    "bagisto/bagisto",
    "phpbb/phpbb",
    "Attendize/Attendize",
    "pelican-dev/panel",
    "Part-DB/Part-DB-server",
    "elabftw/elabftw",
    "lobsters/lobsters",
    "paperless-ngx/paperless-ngx",
    "ProcessMaker/processmaker",
    "penpot/penpot",
    "PrefectHQ/prefect",
    "DFE-Digital/apply-for-teacher-training",
    "nextcloud/polls",
    "TryGhost/Ghost",
    "nextcloud/activity",
)
"""§3.1's list, in the registration's order."""

MIN_REPOSITORIES = 15
"""§9 rule 1: below this many repositories where the gate fires, the study is underpowered."""
BOUND = 0.10
"""H1's bound: study 1's "rarely mis-fires"."""
RESAMPLES = 2000
SEED = 20261108
"""H3's bootstrap (§6)."""


# --- divergence (§4) --------------------------------------------------------------------------


def by_name(pairs: set[la.Package]) -> dict[str, frozenset[str]]:
    """A lock file's packages, as each name's set of versions."""
    names: dict[str, set[str]] = defaultdict(set)
    for name, version in pairs:
        names[name].add(version)
    return {name: frozenset(versions) for name, versions in names.items()}


def divergent(base: set[la.Package], local: set[la.Package], upstream: set[la.Package]) -> int:
    """How many packages both sides changed from the base, to different versions."""
    b, lo, up = by_name(base), by_name(local), by_name(upstream)
    none: frozenset[str] = frozenset()
    count = 0
    for name in set(b) | set(lo) | set(up):
        was, mine, theirs = b.get(name, none), lo.get(name, none), up.get(name, none)
        count += mine != was and theirs != was and mine != theirs
    return count


def _read(cache: Path, commit: str, path: str) -> set[la.Package]:
    text = la._show(cache, commit, path)
    return (la.packages(path, text) if text is not None else None) or set()


class GateFile(BaseModel):
    path: str
    family: str
    divergent: int
    predicted_reproduces: bool


class GateCase(BaseModel):
    index: int
    repo: str
    files: list[GateFile]
    diverges: bool
    """A package diverges in some conflicted lock file: the gate refuses."""
    predicted_reproduces: bool
    """The predicted merge gives the maintainer's set on every conflicted lock file."""
    one_version: bool
    """Every conflicted lock file is in the one-version family (H3's cases)."""


def gate_case(case: Case, label: CaseLabel, cache: Path) -> GateCase:
    """The case's divergence, read from git at its base and two sides (§4)."""
    files = []
    for f in label.files:
        done = {r.action: r.reproduces for r in f.results}
        sides = [_read(cache, commit, f.path) for commit in (case.base, case.first, case.second)]
        files.append(
            GateFile(
                path=f.path,
                family=family(f.path),
                divergent=divergent(*sides),
                predicted_reproduces=done[predicted(f.path)],
            )
        )
    return GateCase(
        index=label.index,
        repo=label.repo,
        files=files,
        diverges=any(f.divergent for f in files),
        predicted_reproduces=all(f.predicted_reproduces for f in files),
        one_version=all(f.family == "one-version" for f in files),
    )


# --- the figures (§6, §7) ---------------------------------------------------------------------


def _mean_interval(values: Sequence[float]) -> Estimate:
    centre = statistics.fmean(values)
    if len(values) < 2:
        return Estimate(statistic=centre, interval=None)
    half = t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return Estimate(statistic=centre, interval=Interval(low=centre - half, high=centre + half))


def _by_repository(rows: Sequence[GateCase]) -> dict[str, list[GateCase]]:
    grouped: dict[str, list[GateCase]] = defaultdict(list)
    for row in rows:
        grouped[row.repo].append(row)
    return dict(sorted(grouped.items()))


def mismatches(rows: Sequence[GateCase]) -> dict[str, tuple[float, float]]:
    """Per repository where the gate fires: (m_always, m_gate)."""
    found = {}
    for repo, group in _by_repository(rows).items():
        fires = [row for row in group if not row.diverges]
        if fires:
            m_always = sum(not row.predicted_reproduces for row in group) / len(group)
            m_gate = sum(not row.predicted_reproduces for row in fires) / len(fires)
            found[repo] = (m_always, m_gate)
    return found


def mantel_haenszel(groups: Sequence[Sequence[GateCase]]) -> float | None:
    """H3's statistic over repositories (`groups`): on one-version cases, the share the merge
    reproduces where nothing diverges minus where something does, weighted within each
    repository by n_calm · n_split / (n_calm + n_split). None if no repository has both kinds."""
    num = den = 0.0
    for group in groups:
        calm = [row.predicted_reproduces for row in group if row.one_version and not row.diverges]
        split = [row.predicted_reproduces for row in group if row.one_version and row.diverges]
        if calm and split:
            weight = len(calm) * len(split) / (len(calm) + len(split))
            num += weight * (sum(calm) / len(calm) - sum(split) / len(split))
            den += weight
    return num / den if den else None


def bootstrap(
    rows: Sequence[GateCase], resamples: int = RESAMPLES, seed: int = SEED
) -> Estimate | None:
    """H3's estimate with its 95% percentile interval over repositories resampled with
    replacement; None if the statistic is undefined, and no interval if fewer than 90% of the
    resamples define it."""
    groups = list(_by_repository(rows).values())
    centre = mantel_haenszel(groups)
    if centre is None:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        value = mantel_haenszel([rng.choice(groups) for _ in groups])
        if value is not None:
            values.append(value)
    if len(values) < 0.9 * resamples:
        return Estimate(statistic=centre, interval=None)
    values.sort()
    low = values[int(0.025 * len(values))]
    high = values[min(len(values) - 1, int(0.975 * len(values)))]
    return Estimate(statistic=centre, interval=Interval(low=low, high=high))


def _wilson(k: int, n: int) -> Interval:
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return Interval(low=max(0.0, centre - half), high=min(1.0, centre + half))


class Pooled(BaseModel):
    fires: int
    wrong: int
    mismatch: float
    interval: Interval


def pooled(rows: Sequence[GateCase], gate: bool) -> Pooled:
    fired = [row for row in rows if not (gate and row.diverges)]
    wrong = sum(not row.predicted_reproduces for row in fired)
    return Pooled(
        fires=len(fired),
        wrong=wrong,
        mismatch=wrong / len(fired),
        interval=_wilson(wrong, len(fired)),
    )


class Hypothesis(BaseModel):
    estimate: Estimate | None
    outcome: str


class Report(BaseModel):
    cases: int
    repositories_with_a_case: int
    repositories_where_the_gate_fires: int
    per_repository: dict[str, int]
    exclusions: dict[str, int]
    underpowered: bool
    h1: Hypothesis
    """The mean over repositories of m_gate."""
    h2: Hypothesis
    """The mean over repositories of m_always − m_gate."""
    h3: Hypothesis
    """The one-version Mantel-Haenszel risk difference."""
    always: Pooled
    gate: Pooled
    """Descriptive, §7: pooled over cases, with Wilson intervals."""
    gate_fire_share: float
    files_by_family: dict[str, dict[str, list[int]]]
    """Descriptive, §7: per family, for files with no divergent package and with some, the
    files and those the predicted merge reproduces."""
    coverage: Estimate
    """Descriptive, §7: study 3's coverage, some computed action reproducing every file."""


def _decide(found: Estimate | None, bound: float, powered: bool, against: str) -> str:
    if not powered:
        return "not decided: the study is underpowered"
    if found is None or found.interval is None:
        return "not decided: the interval is undefined"
    if found.interval.low > bound:
        return "supported"
    if found.interval.high < bound:
        return f"not supported: {against}"
    return "not supported"


def report(
    rows: Sequence[GateCase],
    labels: Sequence[CaseLabel],
    exclusions: Sequence[OracleExclusion],
    *,
    min_repositories: int = MIN_REPOSITORIES,
) -> Report:
    if not rows:
        raise ValueError("no case was labelled; there is nothing to report")
    per_repository = Counter(row.repo for row in rows)
    found = mismatches(rows)
    powered = len(found) >= min_repositories
    h1 = _mean_interval([gate for _, gate in found.values()]) if found else None
    h2 = _mean_interval([always - gate for always, gate in found.values()]) if found else None
    h3 = bootstrap(rows)
    files: dict[str, dict[str, list[int]]] = {
        fam: {"none diverges": [0, 0], "some diverges": [0, 0]} for fam in ("npm", "one-version")
    }
    for row in rows:
        for f in row.files:
            cell = files[f.family]["some diverges" if f.divergent else "none diverges"]
            cell[0] += 1
            cell[1] += f.predicted_reproduces
    return Report(
        cases=len(rows),
        repositories_with_a_case=len(per_repository),
        repositories_where_the_gate_fires=len(found),
        per_repository=dict(sorted(per_repository.items())),
        exclusions=dict(sorted(Counter(e.reason for e in exclusions).items())),
        underpowered=not powered,
        h1=Hypothesis(
            estimate=h1,
            outcome=_decide(h1, BOUND, powered, "the gate makes the merge rarely wrong"),
        ),
        h2=Hypothesis(
            estimate=h2, outcome=_decide(h2, 0.0, powered, "the gate raises the merge's mismatch")
        ),
        h3=Hypothesis(
            estimate=h3,
            outcome=_decide(h3, 0.0, powered, "the merge does better where a package diverges"),
        ),
        always=pooled(rows, gate=False),
        gate=pooled(rows, gate=True),
        gate_fire_share=sum(not row.diverges for row in rows) / len(rows),
        files_by_family=files,
        coverage=estimate(labels, covered),
    )


def _estimate(found: Estimate | None) -> str:
    if found is None:
        return "undefined"
    interval = found.interval
    return f"{found.statistic:.3f} " + (
        f"[{interval.low:.3f}, {interval.high:.3f}]" if interval else "[undefined]"
    )


def text(found: Report) -> str:
    lines = [
        f"{found.cases} cases from {found.repositories_with_a_case} repositories; the gate fires"
        f" in {found.repositories_where_the_gate_fires}"
        + (f"; excluded: {found.exclusions}" if found.exclusions else ""),
        "",
        f"H1 mean m_gate            {_estimate(found.h1.estimate)}: {found.h1.outcome}",
        f"H2 mean m_always - m_gate {_estimate(found.h2.estimate)}: {found.h2.outcome}",
        f"H3 one-version MH         {_estimate(found.h3.estimate)}: {found.h3.outcome}",
        "",
        f"pooled: always {found.always.wrong}/{found.always.fires} "
        f"({found.always.mismatch:.3f}); gate {found.gate.wrong}/{found.gate.fires} "
        f"({found.gate.mismatch:.3f} [{found.gate.interval.low:.3f}, "
        f"{found.gate.interval.high:.3f}]); the gate fires on {found.gate_fire_share:.3f} of cases",
    ]
    for fam, cells in found.files_by_family.items():
        lines.append(
            f"{fam}: "
            + "; ".join(f"{kind} {hit}/{n}" for kind, (n, hit) in cells.items())
            + " files reproduced"
        )
    lines.append(f"coverage {_estimate(found.coverage)}")
    return "\n".join(lines) + "\n"


class Manifest(BaseModel):
    registration: str
    repositories: list[Repository]
    cases: list[Case]
    exclusions: list[OracleExclusion]


def run(out: Path, repositories: Sequence[str] = REPOSITORIES) -> Report:
    """Mine, label and report every registered repository, into a fresh `out`."""
    require(REGISTRATION)
    if out.exists():
        raise ValueError(f"{out} already exists; the study writes a fresh directory")
    summaries: list[Repository] = []
    cases: list[Case] = []
    labels: list[CaseLabel] = []
    gates: list[GateCase] = []
    exclusions: list[OracleExclusion] = []
    for repo in repositories:
        branch, tip = pin(repo)
        cache = fetch_real_host(host(repo, tip))
        summary, mined, excluded = mine(repo, cache, branch, tip)
        labelled, unread = label_repository(mined, cache)
        summaries.append(summary)
        exclusions += [
            OracleExclusion(repo=e.repo, merge=e.merge, reason=e.reason) for e in excluded
        ]
        exclusions += unread
        for case, label in labelled:
            index = len(cases)
            case = case.model_copy(update={"index": index})
            label = label.model_copy(update={"index": index})
            cases.append(case)
            labels.append(label)
            gates.append(gate_case(case, label, cache))
        print(f"{repo}: {len(labelled)} cases", flush=True)
    manifest = Manifest(
        registration=REGISTRATION, repositories=summaries, cases=cases, exclusions=exclusions
    )
    found = report(gates, labels, exclusions)
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "labels.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in labels), "utf-8"
    )
    (out / "gates.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in gates), "utf-8"
    )
    (out / "report.json").write_text(found.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(text(found), encoding="utf-8")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.divergence_gate")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(text(run(args.out)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
