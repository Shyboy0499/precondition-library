"""The lock-file oracle study: which computed action reproduces a maintainer's lock file (#306).

Registered in `docs/preregistration/lock-oracle.md` before any of its data was mined. Each
section cited here (§n) is that document's.

**The cases (§3).** Real merges from the registered repositories, mined by
`real_merges.mine` exactly as study 1 mined them, keeping its conflicted cases ("positives"):
merges whose `git merge-tree` conflict includes a lock file. At most `PER_REPOSITORY` per
repository, the most recent that can be labelled. A case whose maintainer's merged lock file
cannot be read (deleted, committed with conflict markers, or not parseable) is passed over and
recorded, since there is nothing to reproduce.

**The label (§4).** Each conflicted lock file is read into its `(package, version)` set
(`lock_actions.packages`), and each of `lock_actions.COMPUTED`'s actions -- take local, take
upstream, the package-level three-way merge, the same unified -- is computed from the base and
the two sides alone: no tool, no registry, so no drift between the merge's date and today. An
action reproduces a case when it gives exactly the maintainer's set on every one of the case's
conflicted lock files. A case is *covered* when some action reproduces it.

**The figures (§6, §7).**

Each figure is a mean over repositories of a per-repository mean over its cases, so a
repository counts once however many cases it gave, and its interval is the 95% t-interval over
the repositories' means (`T_975`, df = repositories - 1). In §8's simulations it supported H1
falsely less often than study 1's percentile bootstrap, and it can be re-derived by hand.

* coverage: the share of a repository's cases covered (H1: the lower end is above `BOUND`);
* per case and action, the Jaccard similarity of the action's set to the maintainer's, the
  smallest over the case's lock files (an unreadable side counts as 0);
* H2: the three-way merge with unification against each side taken whole, as the mean per-case
  Jaccard difference; supported when both lower ends are above 0.

    python -m precondition_library.bench.lock_oracle --out results/lock-oracle-<date>

Mining reads git only; nothing here runs a package manager or model-authored code.
"""

from __future__ import annotations

import argparse
import math
import statistics
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .lock_actions import COMPUTED, ActionResult, computed_actions
from .preregistration import require
from .real_merges import (
    RESOLUTIONS,
    Case,
    Repository,
    _git,
    _lines,
    fetch_real_host,
    host,
    is_lock,
    mine,
    pin,
    produced,
)
from .report import Interval

REGISTRATION = "lock-oracle"

REPOSITORIES: tuple[str, ...] = (
    "phpstan/phpstan-src",
    "huginn/huginn",
    "diaspora/diaspora",
    "rust-lang/rustfmt",
    "pterodactyl/panel",
    "BookStackApp/BookStack",
    "getgrav/grav",
    "Textualize/rich",
    "Textualize/textual",
    "invoiceninja/invoiceninja",
    "bolt/core",
    "snipe/snipe-it",
    "rust-lang/crates.io",
    "openstreetmap/openstreetmap-website",
    "firefly-iii/firefly-iii",
    "wallabag/wallabag",
    "feedbin/feedbin",
    "contao/contao",
    "nightscout/cgm-remote-monitor",
    "MagicMirrorOrg/MagicMirror",
    "otwcode/otwarchive",
    "node-red/node-red",
    "webpack/webpack",
    "consuldemocracy/consuldemocracy",
    "laurent22/joplin",
    "processing/p5.js",
    "loomio/loomio",
)
"""§3.1's list, in the registration's order."""

PER_REPOSITORY = 15
"""§3.3: at most this many conflicted cases from one repository, the most recent."""
TARGET_CASES = 150
MIN_REPOSITORIES = 15
"""§8: below either, the study is underpowered, its estimates are reported and nothing is
decided."""
BOUND = 0.10
"""H1's bound on coverage (§6)."""

MERGE_ACTION = "three_way_unified"
SIDES = ("take_local", "take_upstream")


# --- labelling (§4) -----------------------------------------------------------------------


class FileLabel(BaseModel):
    path: str
    results: list[ActionResult]
    line_union: bool
    """Either of study 1's line unions reproduces the maintainer's file line for line: the
    formulation this study replaces, kept for the contrast (§7, descriptive)."""


class CaseLabel(BaseModel):
    index: int
    repo: str
    merge: str
    only_locks_conflicted: bool
    files: list[FileLabel]
    reproduces: dict[str, bool]
    """Per computed action: it reproduces every one of the case's conflicted lock files."""
    jaccard: dict[str, float]
    """Per computed action: its smallest Jaccard over the case's lock files, 0 where unread."""
    covered: bool


class OracleExclusion(BaseModel):
    repo: str
    merge: str
    reason: Literal[
        "criss-cross", "submodule or binary conflict", "state not built", "merged lock file unread"
    ]


def ecosystem(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def label_case(case: Case, cache: Path) -> CaseLabel | None:
    """The case's label, or None when a maintainer's merged lock file cannot be read (§3.5)."""
    locks = [path for path in case.conflicted if is_lock(path)]
    files: list[FileLabel] = []
    for path in locks:
        results = computed_actions(
            cache,
            merge=case.merge,
            first=case.first,
            second=case.second,
            base=case.base,
            path=path,
        )
        if any(r.error == "merge's file unread" for r in results):
            return None
        versions = [_lines(cache, c, path) for c in (case.base, case.first, case.second)]
        merged = _lines(cache, case.merge, path)
        line_union = any(produced(r, *versions) == merged for r in RESOLUTIONS)
        files.append(FileLabel(path=path, results=results, line_union=line_union))
    reproduces = {
        action: all(r.reproduces for f in files for r in f.results if r.action == action)
        for action in COMPUTED
    }
    jaccard = {
        action: min((r.jaccard or 0.0) for f in files for r in f.results if r.action == action)
        for action in COMPUTED
    }
    return CaseLabel(
        index=case.index,
        repo=case.repo,
        merge=case.merge,
        only_locks_conflicted=len(locks) == len(case.conflicted),
        files=files,
        reproduces=reproduces,
        jaccard=jaccard,
        covered=any(reproduces.values()),
    )


# --- the figures (§6, §7) -------------------------------------------------------------------


class Estimate(BaseModel):
    statistic: float
    interval: Interval | None


class Decision(BaseModel):
    rule: str
    outcome: str


class Report(BaseModel):
    cases: int
    repositories_with_a_case: int
    per_repository: dict[str, int]
    exclusions: dict[str, int]
    underpowered: bool
    underpowered_because: list[str]
    coverage: Estimate
    """H1's statistic."""
    merge_minus_local: Estimate
    merge_minus_upstream: Estimate
    """H2's two statistics."""
    pooled_coverage: float
    """Descriptive: the share of all cases covered, each case counted once."""
    action_share: dict[str, float]
    """Descriptive: the share of cases each computed action reproduces."""
    median_jaccard: dict[str, float]
    """Descriptive: each action's median per-case Jaccard."""
    line_union_share: float
    """Descriptive: the share of cases study 1's line unions reproduce on every lock file."""
    by_ecosystem: dict[str, dict[str, int]]
    """Descriptive: per lock-file name, its conflicted files, and those some action reproduces."""
    decisions: list[Decision]


T_975 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)  # fmt: skip
"""Student's t at 0.975 for 1 to 30 degrees of freedom; past 30, the value for 30, which is
slightly wider than the exact one."""


def t_975(df: int) -> float:
    return T_975[min(df, len(T_975)) - 1]


PerCase = Callable[[CaseLabel], float]


def covered(row: CaseLabel) -> float:
    return float(row.covered)


def merge_minus(side: str) -> PerCase:
    def value(row: CaseLabel) -> float:
        return row.jaccard[MERGE_ACTION] - row.jaccard[side]

    return value


def repository_means(rows: Sequence[CaseLabel], value: PerCase) -> list[float]:
    repos = sorted({row.repo for row in rows})
    return [statistics.fmean(value(row) for row in rows if row.repo == repo) for repo in repos]


def estimate(rows: Sequence[CaseLabel], value: PerCase) -> Estimate:
    """The mean of the repositories' means, with its 95% t-interval; no interval from one."""
    means = repository_means(rows, value)
    centre = statistics.fmean(means)
    if len(means) < 2:
        return Estimate(statistic=centre, interval=None)
    half = t_975(len(means) - 1) * statistics.stdev(means) / math.sqrt(len(means))
    return Estimate(statistic=centre, interval=Interval(low=centre - half, high=centre + half))


def decide(
    coverage_: Estimate, local: Estimate, upstream: Estimate, because: list[str]
) -> list[Decision]:
    """§9's rules, in order."""
    if because:
        return [Decision(rule="1 power", outcome="underpowered: " + ", ".join(because))]
    decisions = [Decision(rule="1 power", outcome="powered")]
    h1 = coverage_.interval is not None and coverage_.interval.low > BOUND
    decisions.append(
        Decision(
            rule="2 H1",
            outcome=("supported" if h1 else "not supported")
            + f": coverage {coverage_.statistic:.3f}, lower end "
            + (f"{coverage_.interval.low:.3f}" if coverage_.interval else "undefined")
            + f" against {BOUND}",
        )
    )
    h2 = all(e.interval is not None and e.interval.low > 0 for e in (local, upstream))
    decisions.append(
        Decision(
            rule="3 H2",
            outcome=("supported" if h2 else "not supported")
            + f": merge minus local {local.statistic:+.3f}, minus upstream "
            + f"{upstream.statistic:+.3f}",
        )
    )
    return decisions


def report(
    rows: Sequence[CaseLabel],
    exclusions: Sequence[OracleExclusion],
    *,
    targets: tuple[int, int] = (TARGET_CASES, MIN_REPOSITORIES),
) -> Report:
    if not rows:
        raise ValueError("no case was labelled; there is nothing to report")
    per_repository = Counter(row.repo for row in rows)
    because = []
    if len(rows) < targets[0]:
        because.append(f"{len(rows)} cases, below {targets[0]}")
    if len(per_repository) < targets[1]:
        because.append(f"{len(per_repository)} repositories, below {targets[1]}")
    found = estimate(rows, covered)
    local = estimate(rows, merge_minus("take_local"))
    upstream = estimate(rows, merge_minus("take_upstream"))
    by_ecosystem: dict[str, dict[str, int]] = {}
    for row in rows:
        for f in row.files:
            counts = by_ecosystem.setdefault(ecosystem(f.path), {"files": 0, "reproduced": 0})
            counts["files"] += 1
            counts["reproduced"] += any(r.reproduces for r in f.results)
    return Report(
        cases=len(rows),
        repositories_with_a_case=len(per_repository),
        per_repository=dict(sorted(per_repository.items())),
        exclusions=dict(sorted(Counter(e.reason for e in exclusions).items())),
        underpowered=bool(because),
        underpowered_because=because,
        coverage=found,
        merge_minus_local=local,
        merge_minus_upstream=upstream,
        pooled_coverage=sum(r.covered for r in rows) / len(rows),
        action_share={a: sum(r.reproduces[a] for r in rows) / len(rows) for a in COMPUTED},
        median_jaccard={a: statistics.median(r.jaccard[a] for r in rows) for a in COMPUTED},
        line_union_share=sum(all(f.line_union for f in r.files) for r in rows) / len(rows),
        by_ecosystem=dict(sorted(by_ecosystem.items())),
        decisions=decide(found, local, upstream, because),
    )


def text(found: Report) -> str:
    def interval(e: Estimate) -> str:
        return f"[{e.interval.low:.3f}, {e.interval.high:.3f}]" if e.interval else "[undefined]"

    lines = [
        f"{found.cases} cases from {found.repositories_with_a_case} repositories"
        + (f"; excluded: {found.exclusions}" if found.exclusions else ""),
        f"coverage (H1): {found.coverage.statistic:.3f} {interval(found.coverage)}"
        f" (pooled over cases: {found.pooled_coverage:.3f})",
        f"merge minus local (H2): {found.merge_minus_local.statistic:+.3f} "
        f"{interval(found.merge_minus_local)}",
        f"merge minus upstream (H2): {found.merge_minus_upstream.statistic:+.3f} "
        f"{interval(found.merge_minus_upstream)}",
        "",
        "action                share  median Jaccard",
    ]
    for action in COMPUTED:
        lines.append(
            f"{action:<20}  {found.action_share[action]:.3f}  {found.median_jaccard[action]:.3f}"
        )
    lines.append(f"{'line unions (study 1)':<20}  {found.line_union_share:.3f}")
    lines += ["", "lock file             files  reproduced"]
    for name, counts in found.by_ecosystem.items():
        lines.append(f"{name:<20}  {counts['files']:>5}  {counts['reproduced']:>10}")
    lines += ["", *(f"{d.rule}: {d.outcome}" for d in found.decisions)]
    return "\n".join(lines) + "\n"


# --- the run (§3, §5) ------------------------------------------------------------------------


class Manifest(BaseModel):
    registration: str
    repositories: list[Repository]
    cases: list[Case]
    exclusions: list[OracleExclusion]


def recent(cases: list[Case], cache: Path) -> list[Case]:
    """`cases`, the most recent merge first (by committer date, then SHA)."""
    when = {
        case.merge: int(_git(cache, "log", "-1", "--format=%ct", case.merge).stdout.strip())
        for case in cases
    }
    return sorted(cases, key=lambda case: (-when[case.merge], case.merge))


def label_repository(
    cases: Sequence[Case], cache: Path, cap: int = PER_REPOSITORY
) -> tuple[list[tuple[Case, CaseLabel]], list[OracleExclusion]]:
    """The repository's conflicted cases labelled most recent first, until `cap` are labelled
    (§3.3); each one passed over for an unreadable merged lock file is recorded (§3.5)."""
    labelled: list[tuple[Case, CaseLabel]] = []
    excluded: list[OracleExclusion] = []
    for case in recent([c for c in cases if c.kind == "positive"], cache):
        if len(labelled) == cap:
            break
        found = label_case(case, cache)
        if found is None:
            excluded.append(
                OracleExclusion(repo=case.repo, merge=case.merge, reason="merged lock file unread")
            )
        else:
            labelled.append((case, found))
    return labelled, excluded


def write(out: Path, manifest: Manifest, labels: Sequence[CaseLabel], found: Report) -> None:
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "labels.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in labels), "utf-8"
    )
    (out / "report.json").write_text(found.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(text(found), encoding="utf-8")


def run(out: Path, repositories: Sequence[str] = REPOSITORIES) -> Report:
    """Mine, label and report every registered repository, into a fresh `out`."""
    require(REGISTRATION)
    if out.exists():
        raise ValueError(f"{out} already exists; the study writes a fresh directory")
    summaries: list[Repository] = []
    cases: list[Case] = []
    labels: list[CaseLabel] = []
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
            cases.append(case.model_copy(update={"index": index}))
            labels.append(label.model_copy(update={"index": index}))
        print(f"{repo}: {len(labelled)} cases", flush=True)
    manifest = Manifest(
        registration=REGISTRATION, repositories=summaries, cases=cases, exclusions=exclusions
    )
    found = report(labels, exclusions)
    write(out, manifest, labels, found)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.lock_oracle")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(text(run(args.out)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
