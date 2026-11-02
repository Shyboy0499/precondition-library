"""Study 4: does the ecosystem's resolver predict which package-level merge a maintainer kept?

Registered in `docs/preregistration/ecosystem-unify.md` before any of its data was mined. Each
section cited here (§n) is that document's.

Study 3 found, exploratorily, that unifying versions in the package-level three-way merge helped
in lock files whose resolver installs one version of a package and hurt in npm's family, where
compatible duplicates coexist. This study tests that on repositories nobody here has mined.

**The cases and labels (§3, §4)** are study 3's, made by the same code: `lock_oracle`'s mining,
its cap of 15 conflicted cases per repository, and its per-file computed actions.

**The unit (§6)** is a *discordant file*: a conflicted lock file on which exactly one of
`three_way` and `three_way_unified` gives the maintainer's package set. The *predicted* merge is
the unified one for the one-version family (`ONE_VERSION`) and the plain one for npm's
(`NPM_FAMILY`). Each repository with a discordant file votes for the prediction if the predicted
merge wins more of its discordant files than it loses, against it if it loses more, and not at
all on a tie.

* **H1 (primary):** every discordant file counts.
* **H2:** only the one-version family's files count.
* **H3:** only npm's family's files count.

Each is supported when the prediction wins more votes than it loses and the exact two-sided
sign test over the votes gives p < 0.05 (§9). H4 replicates study 3's H1: mean coverage over
repositories, with `lock_oracle`'s t-interval, above 0.10.

    python -m precondition_library.bench.ecosystem_unify --out results/ecosystem-unify-<date>

Mining reads git only; nothing here runs a package manager or model-authored code.
"""

from __future__ import annotations

import argparse
import math
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from .lock_oracle import (
    CaseLabel,
    Estimate,
    OracleExclusion,
    covered,
    estimate,
    label_repository,
)
from .preregistration import require
from .real_merges import Case, Repository, fetch_real_host, host, mine, pin

REGISTRATION = "ecosystem-unify"

REPOSITORIES: tuple[str, ...] = (
    "rubyforgood/human-essentials",
    "fatfreecrm/fat_free_crm",
    "rubyforgood/casa",
    "element-hq/element-desktop",
    "mautic/mautic",
    "glpi-project/glpi",
    "joomla/joomla-cms",
    "humhub/humhub",
    "cypress-io/cypress",
    "akaunting/akaunting",
    "espocrm/espocrm",
    "pixelfed/pixelfed",
    "matrix-org/matrix-react-sdk",
    "Leantime/leantime",
    "element-hq/element-web",
    "SuiteCRM/SuiteCRM",
    "rust-lang/rustlings",
    "civicrm/civicrm-core",
    "strapi/strapi",
    "storybookjs/storybook",
)
"""§3.1's list, in the registration's order."""

NPM_FAMILY = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
ONE_VERSION = (
    "composer.lock",
    "Gemfile.lock",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
)
"""The two families of §4. Every lock file study 1 counts is in exactly one."""

MIN_REPOSITORIES = 12
"""§9 rule 1: below this many repositories with a case, the study is underpowered."""
MIN_VOTES = 6
"""The fewest votes with which the sign test can reach p < 0.05 (2 · 2⁻⁶ = 0.031)."""
BOUND = 0.10
"""H4's bound, study 3's."""


def family(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name in NPM_FAMILY:
        return "npm"
    if name in ONE_VERSION:
        return "one-version"
    raise ValueError(f"{path} is in neither family")


def predicted(path: str) -> str:
    """The merge the ecosystem's resolver predicts the maintainer kept."""
    return "three_way" if family(path) == "npm" else "three_way_unified"


def discordant(row: CaseLabel) -> list[tuple[str, int]]:
    """The case's discordant files: (family, +1 if the predicted merge won, −1 if it lost)."""
    found = []
    for f in row.files:
        done = {r.action: r.reproduces for r in f.results}
        if done["three_way"] != done["three_way_unified"]:
            found.append((family(f.path), 1 if done[predicted(f.path)] else -1))
    return found


HYPOTHESES = {"H1": ("one-version", "npm"), "H2": ("one-version",), "H3": ("npm",)}
"""Which families' discordant files each sign-test hypothesis counts."""


def votes(rows: Sequence[CaseLabel], families: Sequence[str]) -> dict[str, int]:
    """Each repository's vote: +1 for the prediction, −1 against; repositories that tie or have
    no discordant file in `families` are left out."""
    tally: Counter[str] = Counter()
    seen: set[str] = set()
    for row in rows:
        for fam, won in discordant(row):
            if fam in families:
                tally[row.repo] += won
                seen.add(row.repo)
    return {repo: (1 if tally[repo] > 0 else -1) for repo in sorted(seen) if tally[repo]}


def sign_p(up: int, down: int) -> float:
    """The exact two-sided sign test."""
    n = up + down
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(up, down) + 1)) / 2**n
    return min(1.0, 2 * tail)


class SignTest(BaseModel):
    files_won: int
    files_lost: int
    """Discordant files the predicted merge won and lost, over all repositories (descriptive)."""
    votes_for: int
    votes_against: int
    ties: int
    p: float
    outcome: str


def sign_test(rows: Sequence[CaseLabel], families: Sequence[str], powered: bool) -> SignTest:
    by_repo = votes(rows, families)
    won = lost = 0
    repos_with: set[str] = set()
    for row in rows:
        for fam, result in discordant(row):
            if fam in families:
                repos_with.add(row.repo)
                won += result > 0
                lost += result < 0
    up = sum(v > 0 for v in by_repo.values())
    down = sum(v < 0 for v in by_repo.values())
    p = sign_p(up, down)
    if not powered:
        outcome = "not decided: the study is underpowered"
    elif up + down < MIN_VOTES:
        outcome = f"not decided: {up + down} votes, fewer than {MIN_VOTES}"
    elif up > down and p < 0.05:
        outcome = "supported"
    else:
        outcome = "not supported"
    return SignTest(
        files_won=won,
        files_lost=lost,
        votes_for=up,
        votes_against=down,
        ties=len(repos_with) - up - down,
        p=p,
        outcome=outcome,
    )


class Report(BaseModel):
    cases: int
    repositories_with_a_case: int
    per_repository: dict[str, int]
    exclusions: dict[str, int]
    underpowered: bool
    tests: dict[str, SignTest]
    coverage: Estimate
    """H4."""
    h4: str
    ecosystem_share: float
    """Descriptive: the share of cases the predicted merge reproduces on every lock file."""
    action_share: dict[str, float]


def report(
    rows: Sequence[CaseLabel],
    exclusions: Sequence[OracleExclusion],
    *,
    min_repositories: int = MIN_REPOSITORIES,
) -> Report:
    if not rows:
        raise ValueError("no case was labelled; there is nothing to report")
    per_repository = Counter(row.repo for row in rows)
    powered = len(per_repository) >= min_repositories
    found = estimate(rows, covered)
    if not powered:
        h4 = "not decided: the study is underpowered"
    elif found.interval is not None and found.interval.low > BOUND:
        h4 = "supported"
    else:
        h4 = "not supported"
    ecosystem = sum(
        all(
            next(r.reproduces for r in f.results if r.action == predicted(f.path))
            for f in row.files
        )
        for row in rows
    )
    return Report(
        cases=len(rows),
        repositories_with_a_case=len(per_repository),
        per_repository=dict(sorted(per_repository.items())),
        exclusions=dict(sorted(Counter(e.reason for e in exclusions).items())),
        underpowered=not powered,
        tests={name: sign_test(rows, fams, powered) for name, fams in HYPOTHESES.items()},
        coverage=found,
        h4=h4,
        ecosystem_share=ecosystem / len(rows),
        action_share={
            a: sum(row.reproduces[a] for row in rows) / len(rows) for a in rows[0].reproduces
        },
    )


def text(found: Report) -> str:
    lines = [
        f"{found.cases} cases from {found.repositories_with_a_case} repositories"
        + (f"; excluded: {found.exclusions}" if found.exclusions else ""),
        "",
        "hypothesis  files won/lost  votes for/against/tied  sign-test p  outcome",
    ]
    for name, t in found.tests.items():
        lines.append(
            f"{name:<10}  {t.files_won:>5}/{t.files_lost:<8} {t.votes_for:>5}/{t.votes_against}/"
            f"{t.ties:<14} {t.p:>10.4f}  {t.outcome}"
        )
    interval = found.coverage.interval
    lines += [
        "",
        f"H4 coverage {found.coverage.statistic:.3f} "
        + (f"[{interval.low:.3f}, {interval.high:.3f}]" if interval else "[undefined]")
        + f": {found.h4}",
        f"the predicted merge reproduces {found.ecosystem_share:.3f} of cases; "
        + ", ".join(f"{a} {v:.3f}" for a, v in found.action_share.items()),
    ]
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
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "labels.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in labels), "utf-8"
    )
    (out / "report.json").write_text(found.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(text(found), encoding="utf-8")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.ecosystem_unify")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(text(run(args.out)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
