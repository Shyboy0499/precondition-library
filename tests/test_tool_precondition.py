"""Study 6's checks, rules, statistics and decisions (`tool-precondition.md`)."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from precondition_library.bench import lock_check
from precondition_library.bench import tool_precondition as tp

# --- reading each tool's answer --------------------------------------------------------------


def test_npm_out_of_sync_is_inconsistent_and_other_failures_are_errors() -> None:
    sync = (
        "npm error code EUSAGE\nnpm error `npm ci` can only install packages when your "
        "package.json and package-lock.json or npm-shrinkwrap.json are in sync."
    )
    assert lock_check.npm_verdict(0, "") == {"verdict": "consistent"}
    assert lock_check.npm_verdict(1, sync) == {"verdict": "inconsistent"}
    assert lock_check.npm_verdict(1, "npm error code ERESOLVE\n") == {"verdict": "error: ERESOLVE"}
    # EUSAGE for another reason is not an out-of-sync verdict
    assert lock_check.npm_verdict(1, "npm error code EUSAGE\nbad flag") == {
        "verdict": "error: EUSAGE"
    }


def test_pnpm_reads_both_outdated_codes_and_settings_mismatch() -> None:
    assert lock_check.pnpm_verdict(1, " ERR_PNPM_OUTDATED_LOCKFILE  x")["verdict"] == "inconsistent"
    assert (
        lock_check.pnpm_verdict(1, "[ERR_PNPM_FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE] x")["verdict"]
        == "inconsistent"
    )
    assert (
        lock_check.pnpm_verdict(1, "ERR_PNPM_LOCKFILE_CONFIG_MISMATCH")["verdict"]
        == "inconsistent: settings"
    )
    assert lock_check.pnpm_verdict(1, "ERR_PNPM_BROKEN_LOCKFILE")["verdict"].startswith("error")


def test_composer_reads_the_hash_and_the_requirements_separately() -> None:
    stale = "- The lock file is not up to date with the latest changes in composer.json"
    merged_badly = (
        '- Required package "psr/log" is in the lock file as "3.0.2" but that does not satisfy '
        'your constraint "^99.0".\nThis usually happens when composer files are incorrectly '
        "merged or the composer.json file is manually edited."
    )
    assert lock_check.composer_verdict("valid", 0, "") == {
        "hash": "consistent",
        "verdict": "consistent",
    }
    assert lock_check.composer_verdict(stale, 0, "") == {
        "hash": "inconsistent",
        "verdict": "consistent",
    }
    assert lock_check.composer_verdict(stale, 4, merged_badly)["verdict"] == "inconsistent"
    missing = '- Required package "x/y" is not present in the lock file.'
    assert lock_check.composer_verdict("", 4, missing)["verdict"] == "inconsistent"
    assert lock_check.composer_verdict("", 1, "In Foo.php line 3:\n  boom")["verdict"] == (
        "error: boom"
    )


def test_kind_folds_details_into_three_verdicts() -> None:
    assert lock_check.kind({"verdict": "inconsistent: settings"}) == "inconsistent"
    assert lock_check.kind({"verdict": "error: E403"}) == "error"
    assert lock_check.kind({"verdict": "consistent", "hash": "inconsistent"}) == "consistent"


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ({"packageManager": "pnpm@11.2.2+sha512.abc"}, "11.2.2"),
        ({"devEngines": {"packageManager": {"name": "pnpm", "version": "12.16.1"}}}, "12.16.1"),
        ({"packageManager": "pnpm@9.15.0"}, lock_check.PNPM_FALLBACK),  # before minimumReleaseAge
        ({"packageManager": "yarn@4.1.0"}, lock_check.PNPM_FALLBACK),
        ({}, lock_check.PNPM_FALLBACK),
    ],
)
def test_the_declared_pnpm_is_used_from_10_16(
    tmp_path: Path, manifest: dict, expected: str
) -> None:
    (tmp_path / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert lock_check.pnpm_version(tmp_path, tmp_path) == expected


def test_only_the_three_checked_lock_files_have_a_tool() -> None:
    assert lock_check.tool_for("app/composer.lock") == "composer"
    assert lock_check.tool_for("package-lock.json") == "npm"
    assert lock_check.tool_for("web/pnpm-lock.yaml") == "pnpm"
    assert lock_check.tool_for("yarn.lock") is None
    assert lock_check.tool_for("Gemfile.lock") is None


# --- the rules and statistics ----------------------------------------------------------------

OK = {"verdict": "consistent"}
BAD = {"verdict": "inconsistent"}
ERR = {"verdict": "error: E403"}


def row(
    repo: str = "o/r",
    *,
    divergent: int = 0,
    merge_right: bool = False,
    local: bool = False,
    upstream: bool = False,
    merged=OK,
    first=OK,
    second=OK,
    own=(OK, OK, OK),
    tool: str = "npm",
) -> tp.ToolFile:
    return tp.ToolFile(
        index=0,
        repo=repo,
        path="package-lock.json",
        tool=tool,
        divergent=divergent,
        predicted_reproduces=merge_right,
        local_reproduces=local,
        upstream_reproduces=upstream,
        check={"merge": merged, "first": first, "second": second},
        own=dict(zip(tp.OWN, own, strict=True)),
    )


def test_the_check_accepts_a_side_only_when_it_alone_passes_and_both_were_judged() -> None:
    assert tp.accepted(row(first=OK, second=BAD)) == "first"
    assert tp.accepted(row(first=BAD, second={"verdict": "inconsistent: settings"})) is None
    assert tp.accepted(row(first=BAD, second=OK)) == "second"
    assert tp.accepted(row(first=OK, second=OK)) is None
    assert tp.accepted(row(first=OK, second=ERR)) is None


def test_rule_d_fires_the_merge_where_nothing_diverges_and_else_the_accepted_side() -> None:
    calm = row(divergent=0, merge_right=True, first=BAD, second=OK, upstream=False)
    assert tp.decide(calm, "D") == (True, True)  # the gate comes first
    split = row(divergent=3, merge_right=True, first=BAD, second=OK, upstream=True)
    assert tp.decide(split, "D") == (True, True)
    assert tp.decide(split, "B") == (False, True)
    undecided = row(divergent=3, first=OK, second=OK, local=True)
    assert tp.decide(undecided, "D")[0] is False
    assert tp.decide(undecided, "F") == (True, True)  # the control takes the first parent's
    assert tp.decide(undecided, "A") == (True, False)


def test_h1_compares_each_repositorys_merged_files_with_its_own_ordinary_commits() -> None:
    rows = [
        row("a", merged=BAD, own=(OK, OK, OK)),
        row("a", merged=OK, own=(OK, BAD, OK)),
        row("b", merged=OK, own=(OK, OK, OK)),
        row("c", merged=ERR, own=(OK, OK, OK)),  # no judged merged file: no figure
    ]
    gaps = tp.inconsistency_gaps(rows)
    assert set(gaps) == {"a", "b"}
    assert gaps["a"] == pytest.approx(1 / 2 - 1 / 6)
    assert gaps["b"] == 0.0


def test_rule_d_mismatch_is_per_repository_over_its_fires() -> None:
    rows = [
        row("a", divergent=0, merge_right=False),
        row("a", divergent=0, merge_right=True),
        row("a", divergent=2, first=OK, second=OK),  # refused: no fire
        row("b", divergent=2, first=OK, second=OK),  # never fires
    ]
    assert tp.rule_d_mismatch(rows) == {"a": 0.5}


def test_a_reverse_is_a_tie_break_away_from_a_right_first_parent() -> None:
    lost = row(divergent=1, first=BAD, second=OK, local=True, upstream=False)
    won = row(divergent=1, first=BAD, second=OK, local=False, upstream=True)
    kept = row(divergent=1, first=OK, second=BAD, local=True)
    assert tp.tie_files([lost, won, kept, row(divergent=0, first=OK, second=BAD)]) == [
        lost,
        won,
        kept,
    ]
    assert [tp.reverse(r) for r in (lost, won, kept)] == [True, False, False]


def test_wilson_and_mcnemar_match_known_values() -> None:
    w = tp.wilson(0, 176)
    assert w.low == pytest.approx(0.0, abs=1e-12)
    assert w.high == pytest.approx(0.0213, abs=5e-4)
    assert tp.mcnemar(20, 0) == pytest.approx(2 / 2**20)
    assert tp.mcnemar(5, 5) == 1.0
    assert tp.mcnemar(0, 0) == 1.0


# --- the decisions (§9) ----------------------------------------------------------------------


def study(repositories: int, *, broken: float, d_wrong: float, reverse: bool, seed: int = 1):
    """A synthetic study: each repository has merged files that fail at `broken`, ordinary
    commits that never fail, rule D fires wrong at `d_wrong`, and two tie-break files."""
    rng = random.Random(seed)
    rows = []
    for i in range(repositories):
        repo = f"o/r{i}"
        for _ in range(6):
            rows.append(
                row(
                    repo,
                    divergent=0,
                    merge_right=rng.random() >= d_wrong,
                    merged=BAD if rng.random() < broken else OK,
                )
            )
        for _ in range(2):
            rows.append(
                row(repo, divergent=1, first=BAD, second=OK, local=reverse, upstream=not reverse)
            )
    return rows


def test_a_powered_study_with_broken_merges_supports_h1_h2_and_h3() -> None:
    found = tp.report(study(20, broken=0.5, d_wrong=0.4, reverse=False), [])
    assert not found.underpowered
    assert found.h1.outcome == "supported"
    assert found.h2.outcome == "supported"
    assert found.h3_tie_files == 40 and found.h3_reverse == 0
    assert found.h3_outcome == "supported"


def test_sound_merges_and_a_rarely_wrong_rule_d_are_reported_against_h1_and_h2() -> None:
    found = tp.report(study(20, broken=0.0, d_wrong=0.0, reverse=False), [])
    assert found.h1.outcome.startswith("not supported")
    assert found.h2.outcome == "not supported: the interval lies below 0.1"
    assert found.h3_outcome == "supported"


def test_tie_breaks_that_lose_to_the_first_parent_are_reported_against_h3() -> None:
    found = tp.report(study(20, broken=0.5, d_wrong=0.4, reverse=True), [])
    assert found.h3_reverse == found.h3_tie_files == 40
    assert found.h3_outcome == "not supported"


def test_fewer_than_fifteen_repositories_decide_nothing() -> None:
    found = tp.report(study(14, broken=0.5, d_wrong=0.4, reverse=False), [])
    assert found.underpowered
    for outcome in (found.h1.outcome, found.h2.outcome, found.h3_outcome):
        assert outcome.startswith("not decided")


def test_h3_needs_twenty_tie_break_files() -> None:
    rows = [r for r in study(20, broken=0.5, d_wrong=0.4, reverse=False) if r.divergent == 0]
    rows += [row("o/r0", divergent=1, first=BAD, second=OK, upstream=True)] * 19
    found = tp.report(rows, [])
    assert found.h3_outcome.startswith("not decided")


def test_the_report_counts_merges_that_made_or_inherited_an_inconsistency() -> None:
    rows = [
        row(merged=BAD, own=(OK, OK, OK)),
        row(merged=BAD, own=(BAD, OK, OK)),
        row(merged=BAD, own=(ERR, OK, OK)),
        row(merged=OK, own=(BAD, OK, OK)),
    ]
    found = tp.report(rows, [])
    assert found.made_by_merge == {
        "both parents passed": 1,
        "a parent failed": 1,
        "a parent could not be judged": 1,
    }
    assert found.base_rates["npm"] == {
        "merged_rejected": 3,
        "merged_judged": 4,
        "ordinary_rejected": 2,
        "ordinary_judged": 11,
    }


# --- which cases -----------------------------------------------------------------------------


def _case(conflicted: list[str], first: str = "HEAD") -> tp.Case:
    return tp.Case(
        index=0, repo="o/r", kind="positive", merge="m", first=first, second="s", base="b",
        conflicted=conflicted,
    )  # fmt: skip


def test_only_conflicts_with_a_checkable_lock_file_are_cases() -> None:
    assert tp.checkable(_case(["src/a.php", "composer.lock"]))
    assert tp.checkable(_case(["web/pnpm-lock.yaml"]))
    assert not tp.checkable(_case(["yarn.lock", "Gemfile.lock"]))


def test_a_lock_file_with_a_merge_attribute_at_the_first_parent_is_named(tmp_path: Path) -> None:
    from precondition_library.sandbox import run_git

    run_git(("init", "-q"), cwd=tmp_path)
    (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "composer.lock").write_text("{}\n", encoding="utf-8")
    run_git(("add", "-A"), cwd=tmp_path)
    run_git(("commit", "-q", "-m", "plain"), cwd=tmp_path)
    plain = run_git(("rev-parse", "HEAD"), cwd=tmp_path).stdout.strip()
    (tmp_path / ".gitattributes").write_text("package-lock.json binary\n", encoding="utf-8")
    run_git(("add", "-A"), cwd=tmp_path)
    run_git(("commit", "-q", "-m", "binary"), cwd=tmp_path)
    marked = run_git(("rev-parse", "HEAD"), cwd=tmp_path).stdout.strip()

    both = ["composer.lock", "package-lock.json"]
    assert tp.merge_attribute(tmp_path, _case(both, first=plain)) is None
    assert (
        tp.merge_attribute(tmp_path, _case(both, first=marked)) == "package-lock.json: merge=unset"
    )
    assert tp.merge_attribute(tmp_path, _case(["composer.lock"], first=marked)) is None


# --- the registration ------------------------------------------------------------------------


def test_the_repositories_are_ones_no_earlier_study_mined_or_counted() -> None:
    from precondition_library.bench import divergence_gate as dg
    from precondition_library.bench import ecosystem_unify as eu
    from precondition_library.bench import lock_oracle as lo
    from precondition_library.bench import preregistration, refusal_set, refusal_study
    from precondition_library.bench import real_merges as rm

    seen = {*rm.PILOT, *rm.CONFIRMATORY, *refusal_set.ADMISSION, *refusal_study.EVALUATION}
    seen |= set(lo.REPOSITORIES) | set(eu.REPOSITORIES) | set(dg.REPOSITORIES)
    for name in (
        "lock-oracle-feasibility.jsonl",
        "ecosystem-unify-feasibility.jsonl",
        "divergence-gate-feasibility.jsonl",
    ):
        counted = preregistration.REPOSITORY / "docs/preregistration" / name
        seen |= {json.loads(line)["repo"] for line in counted.read_text().splitlines()}
    assert tp.REPOSITORIES
    assert len(set(tp.REPOSITORIES)) == len(tp.REPOSITORIES)
    assert not {s.lower() for s in seen} & {r.lower() for r in tp.REPOSITORIES}


def test_on_the_exploratory_data_the_module_gives_its_figures() -> None:
    """`results/lock-tool-check-2026-11-08/` as study 6 would read it (§4)."""
    from precondition_library.bench import preregistration

    root = preregistration.REPOSITORY / "results"
    gates = {}
    for study in ("study-3", "study-4"):
        anatomy = root / "lock-anatomy-2026-11-04" / f"{study}.jsonl"
        for line in anatomy.read_text().splitlines():
            f = json.loads(line)
            gates[(study, f["index"], f["path"])] = (
                f["kinds"].get("divergent", 0),
                f["predicted_reproduces"],
            )
    for line in (root / "divergence-gate-2026-11-08" / "gates.jsonl").read_text().splitlines():
        case = json.loads(line)
        for f in case["files"]:
            gates[("study-5", case["index"], f["path"])] = (
                f["divergent"],
                f["predicted_reproduces"],
            )
    rows = []
    folder = root / "lock-tool-check-2026-11-08"
    for study in ("study-3", "study-4", "study-5"):
        own = {}
        for line in (folder / f"{study}.own.jsonl").read_text().splitlines():
            r = json.loads(line)
            own[(r["index"], r["path"])] = r["own_tree"]
        for line in (folder / f"{study}.jsonl").read_text().splitlines():
            r = json.loads(line)
            divergent, predicted = gates[(study, r["index"], r["path"])]
            rows.append(
                tp.ToolFile(
                    index=r["index"],
                    repo=f"{study}:{r['repo']}",
                    path=r["path"],
                    tool=r["tool"],
                    divergent=divergent,
                    predicted_reproduces=predicted,
                    local_reproduces=r["maintainer_set"]["first"],
                    upstream_reproduces=r["maintainer_set"]["second"],
                    check=r["check"],
                    own=own[(r["index"], r["path"])],
                )
            )
    found = tp.report(rows, [])
    assert (found.files, found.repositories_with_a_file) == (610, 45)
    assert (found.rules["D"].fires, found.rules["D"].wrong) == (423, 134)
    assert (found.rules["B"].fires, found.rules["B"].wrong) == (247, 69)
    assert (found.h3_tie_files, found.h3_reverse) == (176, 0)
    assert found.tie_gain["better"] == 20
    assert found.made_by_merge["both parents passed"] == 61
    assert found.h1.estimate is not None
    assert found.h1.estimate.statistic == pytest.approx(0.125, abs=5e-4)
    assert [found.h1.outcome, found.h2.outcome, found.h3_outcome] == ["supported"] * 3


# --- running and resuming --------------------------------------------------------------------


def _result(repo: str, n: int) -> tp.RepositoryResult:
    cases = [
        _case(["composer.lock"]).model_copy(update={"repo": repo, "index": i}) for i in range(n)
    ]
    labels = [
        tp.CaseLabel(
            index=i,
            repo=repo,
            merge=f"m{i}",
            only_locks_conflicted=True,
            files=[],
            reproduces={},
            jaccard={},
            covered=False,
        )  # fmt: skip
        for i in range(n)
    ]
    rows = [row(repo).model_copy(update={"index": i}) for i in range(n)]
    summary = tp.Repository(
        repo=repo, url="u", default_branch="main", tip="t", licence="MIT",
        two_parent_merges=n, positives=n, negatives=0, exclusions=0,
    )  # fmt: skip
    return tp.RepositoryResult(
        repo=repo, summary=summary, cases=cases, labels=labels, rows=rows, exclusions=[],
        attributed=[],
    )  # fmt: skip


def test_a_stopped_run_resumes_from_its_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tp, "require", lambda name: tmp_path)
    computed: list[str] = []
    cache = tmp_path / "cache"

    def failing(repo: str, scratch: Path):
        computed.append(repo)
        if repo == "o/b":
            raise RuntimeError("the worker stopped")
        cache.mkdir(exist_ok=True)
        return _result(repo, 2), cache

    with pytest.raises(RuntimeError):
        tp.run(tmp_path / "out", tmp_path / "s", ("o/a", "o/b"), prune=True, compute=failing)
    assert computed == ["o/a", "o/b"]
    assert not (tmp_path / "out").exists()
    assert not cache.exists(), "pruned once o/a was checkpointed"

    computed.clear()

    def working(repo: str, scratch: Path):
        computed.append(repo)
        return _result(repo, 3), tmp_path / "cache"

    found = tp.run(tmp_path / "out", tmp_path / "s", ("o/a", "o/b"), compute=working)
    assert computed == ["o/b"], "o/a came from its checkpoint"
    assert found.files == 5
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert [c["index"] for c in manifest["cases"]] == [0, 1, 2, 3, 4]
    files = [json.loads(x) for x in (tmp_path / "out" / "files.jsonl").read_text().splitlines()]
    assert [(f["repo"], f["index"]) for f in files] == [
        ("o/a", 0), ("o/a", 1), ("o/b", 2), ("o/b", 3), ("o/b", 4),
    ]  # fmt: skip


def test_the_study_refuses_without_its_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from precondition_library.bench import preregistration

    monkeypatch.setitem(preregistration.REGISTRATIONS, tp.REGISTRATION, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError):
        tp.run(tmp_path / "out", tmp_path / "s", repositories=())
    assert not (tmp_path / "out").exists()
