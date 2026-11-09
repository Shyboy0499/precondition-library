"""Study 6: the ecosystem's own check, as evidence that merges break lock files and as a
precondition after the divergence gate.

Registered in `docs/preregistration/tool-precondition.md` before any of its data was mined. Each
section cited here (§n) is that document's.

`results/lock-tool-check-2026-11-08/` ran each ecosystem's consistency check (`lock_check`) on
studies 3-5's conflicted `composer.lock`, `package-lock.json` and `pnpm-lock.yaml` files, after
seeing them. It found two things this study tests on repositories nobody here had mined:

* **H1 (primary):** a maintainer's merged lock file fails the check more often than the
  repository's ordinary commits' lock files fail it in their own trees. Per repository, the
  difference of the two rejection rates; its mean over repositories is above 0.
* **H2:** rule D, a precondition dispatcher, is not rarely wrong. Rule D fires the predicted
  merge where no package diverges (study 5's gate); otherwise it takes the one side whose lock
  file alone passes the check; otherwise it refuses. The mean over repositories of its mismatch
  is above 0.10.
* **H3:** the check's tie-break never loses to taking the first parent's file. On files where a
  package diverges and the check accepts exactly one side, the share where the first parent's
  file is the maintainer's set and the accepted side is not has a Wilson upper bound below 0.10.

    python -m precondition_library.bench.tool_precondition --out results/tool-precondition-<date>

Mining reads git. The checks run the ecosystems' tools on trees as committed, with their install
and lifecycle scripts off, so no package's or project's code runs.
"""

from __future__ import annotations

import argparse
import math
import shutil
import statistics
import subprocess
import tempfile
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from . import lock_actions as la
from . import lock_check
from .divergence_gate import gate_case
from .lock_oracle import CaseLabel, Estimate, Interval, OracleExclusion, label_repository, t_975
from .preregistration import require
from .real_merges import Case, Repository, fetch_real_host, host, mine, pin

REGISTRATION = "tool-precondition"

REPOSITORIES: tuple[str, ...] = (
    "appwrite/appwrite",
    "filamentphp/filament",
    "woocommerce/woocommerce",
    "thorsten/phpMyFAQ",
    "activepieces/activepieces",
    "akeneo/pim-community-dev",
    "Infisical/infisical",
    "louislam/uptime-kuma",
    "nocodb/nocodb",
    "TriliumNext/Notes",
    "ToolJet/ToolJet",
    "Hubs-Foundation/hubs",
    "hoppscotch/hoppscotch",
    "umami-software/umami",
    "Sylius/Sylius",
    "cryptpad/cryptpad",
    "firefly-iii/data-importer",
    "statamic/cms",
    "payloadcms/payload",
    "SuiteCRM/SuiteCRM-Core",
    "formbricks/formbricks",
    "ampache/ampache",
    "nextcloud/nextcloud-vue",
    "SolidInvoice/SolidInvoice",
    "Ctrlpanel-gg/panel",
)
"""§3.1, in mining order."""

MIN_REPOSITORIES = 15
"""§9 rule 1: below this many repositories with a figure, no hypothesis is decided."""

BOUND = 0.10
"""Study 1's "rarely mis-fires" (H2)."""

REVERSE_BOUND = 0.10
"""H3: the Wilson upper bound the reverse share must fall below (§8 sets it)."""

MIN_TIE_FILES = 20
"""H3 is not decided on fewer tie-break files."""

SIDES = ("merge", "first", "second")
OWN = ("first", "second", "base")


class ToolFile(BaseModel):
    """One conflicted lock file a check exists for, and everything the analysis reads (§4)."""

    index: int
    repo: str
    path: str
    tool: str
    divergent: int
    predicted_reproduces: bool
    local_reproduces: bool
    upstream_reproduces: bool
    check: dict[str, dict[str, str]]
    """The check of the merged file and each side's file, each in the merge's tree."""
    own: dict[str, dict[str, str]]
    """The check of the first parent's, second parent's and merge base's own lock file, each in
    its own commit's tree."""


# --- which cases (§3.2) ----------------------------------------------------------------------


def checkable(case: Case) -> bool:
    """The conflict includes a lock file a check exists for. Other cases are left out before
    the cap, so they do not take its places."""
    return any(lock_check.tool_for(path) for path in case.conflicted)


def merge_attribute(cache: Path, case: Case) -> str | None:
    """The `merge` attribute git gives a conflicted checkable lock file at the first parent, the
    tree the maintainer merged into, if any is set (`results/mining-attributes-2026-11-08/`)."""
    for path in case.conflicted:
        if not lock_check.tool_for(path):
            continue
        shown = subprocess.run(
            ["git", "-C", str(cache), "check-attr", f"--source={case.first}", "merge", "--", path],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        value = shown.rsplit(": ", 1)[-1].strip()
        if value != "unspecified":
            return f"{path}: merge={value}"
    return None


# --- running the checks (§4) -----------------------------------------------------------------


def _in_merge_tree(cache: Path, case: Case, path: str, scratch: Path) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        tree = Path(tmp) / "tree"
        tree.mkdir()
        la._checkout(cache, case.merge, tree)
        lock = tree / path
        for side, commit in zip(SIDES, (case.merge, case.first, case.second), strict=True):
            text = la._show(cache, commit, path)
            if text is None:
                found[side] = {"verdict": "error: no lock file on this side"}
                continue
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(text, encoding="utf-8", errors="surrogateescape")
            found[side] = lock_check.check(tree, path, scratch)
    return found


def _in_own_trees(cache: Path, case: Case, paths: Sequence[str], scratch: Path) -> dict:
    found: dict[str, dict[str, dict[str, str]]] = {path: {} for path in paths}
    for side, commit in zip(OWN, (case.first, case.second, case.base), strict=True):
        with tempfile.TemporaryDirectory(dir=scratch) as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            la._checkout(cache, commit, tree)
            for path in paths:
                if (tree / path).is_file():
                    found[path][side] = lock_check.check(tree, path, scratch)
                else:
                    found[path][side] = {"verdict": "error: no lock file at this commit"}
    return found


def tool_files(case: Case, label: CaseLabel, cache: Path, scratch: Path) -> list[ToolFile]:
    """Every conflicted lock file of the case a check exists for, checked (§4)."""
    scratch.mkdir(parents=True, exist_ok=True)
    gate = {f.path: f for f in gate_case(case, label, cache).files}
    checked = [f for f in label.files if lock_check.tool_for(f.path)]
    own = _in_own_trees(cache, case, [f.path for f in checked], scratch)
    rows = []
    for f in checked:
        done = {r.action: r.reproduces for r in f.results}
        rows.append(
            ToolFile(
                index=label.index,
                repo=label.repo,
                path=f.path,
                tool=lock_check.tool_for(f.path) or "",
                divergent=gate[f.path].divergent,
                predicted_reproduces=gate[f.path].predicted_reproduces,
                local_reproduces=done["take_local"],
                upstream_reproduces=done["take_upstream"],
                check=_in_merge_tree(cache, case, f.path, scratch),
                own=own[f.path],
            )
        )
    return rows


# --- the rules and figures (§6, §7) ----------------------------------------------------------


def accepted(row: ToolFile) -> str | None:
    """The side whose file alone passes the check, both sides judged; else None."""
    kinds = {side: lock_check.kind(row.check[side]) for side in ("first", "second")}
    passes = [side for side, k in kinds.items() if k == "consistent"]
    if len(passes) == 1 and "error" not in kinds.values():
        return passes[0]
    return None


def _right(row: ToolFile, side: str) -> bool:
    return row.local_reproduces if side == "first" else row.upstream_reproduces


RULES = {
    "A": "the merge, always",
    "B": "the gate's merge, else refuse",
    "C": "the side the check alone accepts, else refuse",
    "D": "the gate's merge; else the side the check alone accepts; else refuse",
    "F": "control: the gate's merge; else the first parent's file",
}


def decide(row: ToolFile, rule: str) -> tuple[bool, bool]:
    """(fires, right) for one file under a rule (§6)."""
    gate = row.divergent == 0
    side = accepted(row)
    if rule == "A":
        return True, row.predicted_reproduces
    if rule == "B":
        return gate, row.predicted_reproduces
    if rule == "C":
        return side is not None, side is not None and _right(row, side)
    if rule == "D":
        if gate:
            return True, row.predicted_reproduces
        return side is not None, side is not None and _right(row, side)
    if rule == "F":
        return True, row.predicted_reproduces if gate else row.local_reproduces
    raise ValueError(rule)


def by_repository(rows: Sequence[ToolFile]) -> dict[str, list[ToolFile]]:
    found: dict[str, list[ToolFile]] = defaultdict(list)
    for row in rows:
        found[row.repo].append(row)
    return dict(found)


def _rate(verdicts: Sequence[dict[str, str]]) -> tuple[int, int]:
    judged = [lock_check.kind(v) for v in verdicts if lock_check.kind(v) != "error"]
    return sum(k == "inconsistent" for k in judged), len(judged)


def inconsistency_gaps(rows: Sequence[ToolFile]) -> dict[str, float]:
    """H1: per repository with a judged merged file and a judged ordinary check, the merged
    files' rejection rate minus its ordinary commits'."""
    gaps = {}
    for repo, files in by_repository(rows).items():
        bad, n = _rate([r.check["merge"] for r in files])
        base_bad, base_n = _rate([r.own[s] for r in files for s in OWN])
        if n and base_n:
            gaps[repo] = bad / n - base_bad / base_n
    return gaps


def rule_d_mismatch(rows: Sequence[ToolFile]) -> dict[str, float]:
    """H2: per repository where rule D fires, its wrong fires over its fires."""
    found = {}
    for repo, files in by_repository(rows).items():
        fires = [right for r in files for fire, right in [decide(r, "D")] if fire]
        if fires:
            found[repo] = sum(not right for right in fires) / len(fires)
    return found


def tie_files(rows: Sequence[ToolFile]) -> list[ToolFile]:
    """H3's files: a package diverges, and the check accepts exactly one side."""
    return [r for r in rows if r.divergent > 0 and accepted(r) is not None]


def reverse(row: ToolFile) -> bool:
    """The first parent's file is the maintainer's set, and the accepted side's is not."""
    side = accepted(row)
    return side is not None and row.local_reproduces and not _right(row, side)


def wilson(k: int, n: int) -> Interval:
    if n == 0:
        return Interval(low=math.nan, high=math.nan)
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return Interval(low=centre - half, high=centre + half)


def mean_interval(values: Sequence[float]) -> Estimate | None:
    if len(values) < 2:
        return None
    centre = statistics.fmean(values)
    half = t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return Estimate(statistic=centre, interval=Interval(low=centre - half, high=centre + half))


def mcnemar(b: int, c: int) -> float:
    """The exact two-sided McNemar test: a binomial test of b against b + c at one half."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


class Pooled(BaseModel):
    fires: int
    wrong: int
    coverage: float
    mismatch: Estimate | None


class Hypothesis(BaseModel):
    estimate: Estimate | None
    repositories: int
    outcome: str


class Report(BaseModel):
    registration: str
    repositories_with_a_file: int
    files: int
    underpowered: bool
    h1: Hypothesis
    h2: Hypothesis
    h3_tie_files: int
    h3_reverse: int
    h3_upper: float | None
    h3_outcome: str
    rules: dict[str, Pooled]
    tie_gain: dict[str, float]
    base_rates: dict[str, dict[str, int]]
    made_by_merge: dict[str, int]
    composer_hash_stale: dict[str, int]
    exclusions: list[OracleExclusion]


def _mean_decision(found: Estimate | None, bound: float, powered: bool) -> str:
    if not powered:
        return "not decided: underpowered (§9 rule 1)"
    if found is None or found.interval is None:
        return "not decided: fewer than two repositories"
    if found.interval.low > bound:
        return "supported"
    if found.interval.high < bound:
        return f"not supported: the interval lies below {bound}"
    return "not supported"


def report(rows: Sequence[ToolFile], exclusions: Sequence[OracleExclusion]) -> Report:
    gaps = inconsistency_gaps(rows)
    mismatch = rule_d_mismatch(rows)
    powered = min(len(gaps), len(mismatch)) >= MIN_REPOSITORIES
    h1 = mean_interval(list(gaps.values()))
    h2 = mean_interval(list(mismatch.values()))
    ties = tie_files(rows)
    backwards = sum(reverse(r) for r in ties)
    upper = wilson(backwards, len(ties)).high if ties else None
    if not powered:
        h3_outcome = "not decided: underpowered (§9 rule 1)"
    elif len(ties) < MIN_TIE_FILES:
        h3_outcome = f"not decided: fewer than {MIN_TIE_FILES} tie-break files"
    elif upper is not None and upper < REVERSE_BOUND:
        h3_outcome = "supported"
    else:
        h3_outcome = "not supported"
    rules = {}
    for rule in RULES:
        decided = [decide(r, rule) for r in rows]
        fires = sum(f for f, _ in decided)
        wrong = sum(f and not right for f, right in decided)
        interval = wilson(wrong, fires)
        rules[rule] = Pooled(
            fires=fires,
            wrong=wrong,
            coverage=fires / len(rows) if rows else math.nan,
            mismatch=Estimate(statistic=wrong / fires, interval=interval) if fires else None,
        )
    better = sum(_right(r, accepted(r) or "first") and not r.local_reproduces for r in ties)
    worse = sum(reverse(r) for r in ties)
    base: dict[str, dict[str, int]] = {}
    made: Counter = Counter()
    for tool in sorted({r.tool for r in rows}):
        files = [r for r in rows if r.tool == tool]
        merged_bad, merged_n = _rate([r.check["merge"] for r in files])
        own_bad, own_n = _rate([r.own[s] for r in files for s in OWN])
        base[tool] = {
            "merged_rejected": merged_bad,
            "merged_judged": merged_n,
            "ordinary_rejected": own_bad,
            "ordinary_judged": own_n,
        }
    for r in rows:
        if lock_check.kind(r.check["merge"]) != "inconsistent":
            continue
        parents = [lock_check.kind(r.own[s]) for s in ("first", "second")]
        if parents == ["consistent", "consistent"]:
            made["both parents passed"] += 1
        elif "inconsistent" in parents:
            made["a parent failed"] += 1
        else:
            made["a parent could not be judged"] += 1
    composer = [r for r in rows if r.tool == "composer"]
    hashes = {
        "merged_stale": sum(r.check["merge"].get("hash") == "inconsistent" for r in composer),
        "merged": len(composer),
        "ordinary_stale": sum(
            r.own[s].get("hash") == "inconsistent" for r in composer for s in OWN
        ),
        "ordinary": sum(bool(r.own[s].get("hash")) for r in composer for s in OWN),
    }
    return Report(
        registration=REGISTRATION,
        repositories_with_a_file=len(by_repository(rows)),
        files=len(rows),
        underpowered=not powered,
        h1=Hypothesis(
            estimate=h1, repositories=len(gaps), outcome=_mean_decision(h1, 0.0, powered)
        ),
        h2=Hypothesis(
            estimate=h2, repositories=len(mismatch), outcome=_mean_decision(h2, BOUND, powered)
        ),
        h3_tie_files=len(ties),
        h3_reverse=backwards,
        h3_upper=upper,
        h3_outcome=h3_outcome,
        rules=rules,
        tie_gain={"better": better, "worse": worse, "mcnemar_p": mcnemar(better, worse)},
        base_rates=base,
        made_by_merge=dict(made),
        composer_hash_stale=hashes,
        exclusions=list(exclusions),
    )


def _estimate(found: Estimate | None) -> str:
    if found is None:
        return "-"
    if found.interval is None:
        return f"{found.statistic:.3f}"
    return f"{found.statistic:.3f} [{found.interval.low:.3f}, {found.interval.high:.3f}]"


def text(found: Report) -> str:
    lines = [
        f"study 6 ({found.registration}): {found.files} files from "
        f"{found.repositories_with_a_file} repositories"
        + (" -- UNDERPOWERED, nothing decided" if found.underpowered else ""),
        f"H1 merged minus ordinary rejection rate, mean over {found.h1.repositories} "
        f"repositories: {_estimate(found.h1.estimate)}: {found.h1.outcome}",
        f"H2 rule D's mismatch, mean over {found.h2.repositories} repositories: "
        f"{_estimate(found.h2.estimate)}: {found.h2.outcome}",
        f"H3 reverse on {found.h3_tie_files} tie-break files: {found.h3_reverse}, Wilson upper "
        f"{found.h3_upper if found.h3_upper is None else round(found.h3_upper, 3)}: "
        f"{found.h3_outcome}",
        "rules, pooled over files:",
    ]
    for rule, label in RULES.items():
        p = found.rules[rule]
        lines.append(
            f"  {rule} {label}: {p.wrong}/{p.fires} wrong, coverage {p.coverage:.2f}, "
            f"mismatch {_estimate(p.mismatch)}"
        )
    gain = found.tie_gain
    lines.append(
        f"tie-break against the first parent's file: better {gain['better']:.0f}, worse "
        f"{gain['worse']:.0f}, McNemar p {gain['mcnemar_p']:.3g}"
    )
    for tool, rates in found.base_rates.items():
        lines.append(
            f"{tool}: merged rejected {rates['merged_rejected']}/{rates['merged_judged']}, "
            f"ordinary rejected {rates['ordinary_rejected']}/{rates['ordinary_judged']}"
        )
    lines.append(f"rejected merged files: {found.made_by_merge}")
    lines.append(f"Composer content-hash: {found.composer_hash_stale}")
    return "\n".join(lines) + "\n"


class AttributeExclusion(BaseModel):
    """A case left out because a conflicted checkable lock file has a `merge` attribute at the
    first parent: a maintainer's working tree would not have merged it as text (§3.2)."""

    repo: str
    merge: str
    attribute: str


class Manifest(BaseModel):
    registration: str
    repositories: list[Repository]
    cases: list[Case]
    exclusions: list[OracleExclusion]
    attribute_exclusions: list[AttributeExclusion]


class RepositoryResult(BaseModel):
    """One repository's mining, labels and checks, with case indices local to it. Written to the
    checkpoint as soon as the repository is done, so a run that stops resumes from the next."""

    repo: str
    summary: Repository
    cases: list[Case]
    labels: list[CaseLabel]
    rows: list[ToolFile]
    exclusions: list[OracleExclusion]
    attributed: list[AttributeExclusion]


def repository_result(repo: str, scratch: Path) -> tuple[RepositoryResult, Path]:
    """Mine, label and check one repository (§3, §4); also returns its cache."""
    branch, tip = pin(repo)
    cache = fetch_real_host(host(repo, tip))
    summary, mined, excluded = mine(repo, cache, branch, tip)
    kept, attributed = [], []
    for case in mined:
        if case.kind != "positive" or not checkable(case):
            continue
        attribute = merge_attribute(cache, case)
        if attribute:
            attributed.append(
                AttributeExclusion(repo=case.repo, merge=case.merge, attribute=attribute)
            )
        else:
            kept.append(case)
    labelled, unread = label_repository(kept, cache)
    exclusions = [OracleExclusion(repo=e.repo, merge=e.merge, reason=e.reason) for e in excluded]
    cases, labels, rows = [], [], []
    for index, (case, label) in enumerate(labelled):
        case = case.model_copy(update={"index": index})
        label = label.model_copy(update={"index": index})
        cases.append(case)
        labels.append(label)
        rows += tool_files(case, label, cache, scratch)
    result = RepositoryResult(
        repo=repo,
        summary=summary,
        cases=cases,
        labels=labels,
        rows=rows,
        exclusions=exclusions + list(unread),
        attributed=attributed,
    )
    return result, cache


def _checkpoint(scratch: Path, position: int, repo: str) -> Path:
    return scratch / "checkpoint" / f"{position:02d}-{repo.replace('/', '__')}.json"


def run(
    out: Path,
    scratch: Path,
    repositories: Sequence[str] = REPOSITORIES,
    *,
    prune: bool = False,
    compute=repository_result,
) -> Report:
    """Mine, label, check and report every registered repository, into a fresh `out`.

    Each repository's result is checkpointed under `<scratch>/checkpoint/` when it is done, and a
    run that finds a checkpoint uses it instead of mining the repository again, so a run that
    stops can be resumed with the same arguments. A checkpoint holds the repository's pinned tip,
    so a resumed run reads the same history. With `prune`, a repository's cache and the npm
    cache are deleted once its checkpoint is written; neither changes any figure."""
    require(REGISTRATION)
    if out.exists():
        raise ValueError(f"{out} already exists; the study writes a fresh directory")
    scratch.mkdir(parents=True, exist_ok=True)
    results: list[RepositoryResult] = []
    for position, repo in enumerate(repositories):
        saved = _checkpoint(scratch, position, repo)
        if saved.is_file():
            result = RepositoryResult.model_validate_json(saved.read_text("utf-8"))
            print(f"{repo}: {len(result.cases)} cases (from the checkpoint)", flush=True)
        else:
            result, cache = compute(repo, scratch)
            saved.parent.mkdir(parents=True, exist_ok=True)
            partial = saved.with_suffix(".partial")
            partial.write_text(result.model_dump_json(), "utf-8")
            partial.replace(saved)
            if prune:
                shutil.rmtree(cache, ignore_errors=True)
                shutil.rmtree(scratch / "npm-cache", ignore_errors=True)
            print(f"{repo}: {len(result.cases)} cases", flush=True)
        results.append(result)
    cases: list[Case] = []
    labels: list[CaseLabel] = []
    rows: list[ToolFile] = []
    exclusions: list[OracleExclusion] = []
    attributed: list[AttributeExclusion] = []
    for result in results:
        offset = len(cases)
        cases += [c.model_copy(update={"index": c.index + offset}) for c in result.cases]
        labels += [x.model_copy(update={"index": x.index + offset}) for x in result.labels]
        rows += [r.model_copy(update={"index": r.index + offset}) for r in result.rows]
        exclusions += result.exclusions
        attributed += result.attributed
    manifest = Manifest(
        registration=REGISTRATION,
        repositories=[r.summary for r in results],
        cases=cases,
        exclusions=exclusions,
        attribute_exclusions=attributed,
    )
    found = report(rows, exclusions)
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "labels.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in labels), "utf-8"
    )
    (out / "files.jsonl").write_text("".join(row.model_dump_json() + "\n" for row in rows), "utf-8")
    (out / "report.json").write_text(found.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(text(found), encoding="utf-8")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.tool_precondition")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete each repository's cache and the npm cache once it is checkpointed",
    )
    args = parser.parse_args(argv)
    print(text(run(args.out, args.scratch, prune=args.prune)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
