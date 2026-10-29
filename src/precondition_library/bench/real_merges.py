"""Dispatch on real lock-file merges, labelled by the maintainers (#296, ADR-0048).

Every state measured before this was built by this project's injectors and labelled by its own
rules (#294). Here the states are merge commits in public repositories whose two sides conflicted
in a lock file, and the label is what the maintainer committed. The study is pre-registered
(`docs/preregistration/real-merges.md`), and nothing in this module builds a case before
`preregistration.require("real-merges")` has passed.

**Mining (§3).** A repository is fetched once, whole, at its default branch's tip, through the
real-host cache (`sandbox.fetch_real_host`, ADR-0043). A positive is a two-parent merge with one
merge base whose `git merge-tree --write-tree` conflict includes a lock file. A negative is one
where both sides changed the same lock file and the merge is clean, the most recent first, as many
as the repository has positives. A criss-cross merge, or a conflict in a submodule or a binary
file, is an exclusion, counted and reported. Nothing else is dropped.

**The label (§4).** For each conflicted lock file, the merge base's, the two parents' and the
merge's versions are read as multisets of lines. `take_upstream` produces upstream's lines plus the
lines the local side added; `keep_local` the local lines plus the lines upstream added. A
resolution is acceptable where what it produces is the maintainer's file, for every conflicted
lock file, and only lock files conflicted. The set can be empty, and such a case stays in.

**The state (§3.4).** A checkout of the first parent, on the default branch's name, tracking
upstream's default branch at the second parent, with the whole history reachable. Upstream's bare
repository borrows the cache's objects, so no case copies a repository.

**The arms (§5).** Arm 3 and lexical arm 2 run through `bench.library_pairs`' own deciders, per
committed library; the state-reading control is `bench.state_classifier`, fit as committed. Only
SHAs, paths and derived labels are written, never a repository's content (ADR-0043).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..library import Library
from ..runtime.probes import evaluate_preconditions
from ..sandbox import _SANDBOX_DIR, RealHost, Sandbox, fetch_real_host, run_git
from ..signatures import StateFingerprint, TaskSignature
from ..tasks.faults.lockfile_conflict import INTENT
from .admit_set import admit_seeds
from .coverage import (
    OperatingPoint,
    PairOutcome,
    _fires,
    matched_comparison,
    operating_point,
    sweep,
)
from .heldout import HELD_OUT_FAULTS
from .library_pairs import _decide, _measured_intents, _unthresholded
from .preregistration import REPOSITORY, require
from .real_merge_inference import (
    Clustered,
    Decision,
    Inference,
    matched_test,
    refusal_test,
)
from .real_merge_inference import decide as decide_rules
from .rescore import scorer
from .state_classifier import StateClassifier, _states

REGISTRATION = "real-merges"

PILOT = (
    "sharkdp/bat",
    "sharkdp/fd",
    "alacritty/alacritty",
    "python-poetry/poetry",
    "helix-editor/helix",
    "tauri-apps/tauri",
)
"""Stage A's repositories, in the registration's order (§3.1)."""

CONFIRMATORY = (
    "phpmyadmin/phpmyadmin",
    "jupyterlab/jupyterlab",
    "babel/babel",
    "nextcloud/server",
    "jupyter/notebook",
    "voila-dashboards/voila",
    "composer/composer",
    "nushell/nushell",
    "rust-lang/cargo",
    "servo/servo",
    "jupyter-widgets/ipywidgets",
    "bokeh/bokeh",
    "holoviz/panel",
    "pypa/pipenv",
    "gfx-rs/wgpu",
    "wasmerio/wasmer",
    "paritytech/substrate",
    "ruffle-rs/ruffle",
)
"""Stage B's repositories, in the registration's order: §3.1's ten, then Amendment 1's eight."""

LOCK_FILES = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "Gemfile.lock",
    "composer.lock",
)
"""The final path components the registration counts as lock files (§3.2)."""

RESOLUTIONS = ("take_upstream", "keep_local")
LIBRARIES = tuple(
    Path("results/replicates-2026-10-05") / run / "library-two-sided"
    for run in ("run-11", "run-12", "run-13")
)
"""The committed libraries, one replicate each (§5)."""

WHOLE_HISTORY = 1_000_000
"""A fetch depth past any listed repository's history, so every merge base is reachable."""

_SUBMODULE_MODE = "160000"
_SUBMODULE_ADVICE = "Recursive merging with submodules"
"""How git (2.43) begins the free-text advice it appends to `merge-tree --messages` after a
submodule conflict, outside the `-z` message format."""


def is_lock(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in LOCK_FILES


# --- mining (§3) -----------------------------------------------------------------------------


class Case(BaseModel):
    """One merge the registration admits, with the SHAs it is rebuilt from and nothing else."""

    index: int
    repo: str
    kind: Literal["positive", "negative"]
    merge: str
    first: str
    second: str
    base: str
    conflicted: list[str]
    """Every path `git merge-tree` leaves conflicted; empty on a negative."""


class Exclusion(BaseModel):
    repo: str
    merge: str
    reason: Literal["criss-cross", "submodule or binary conflict", "state not built"]


class Repository(BaseModel):
    repo: str
    url: str
    default_branch: str
    tip: str
    licence: str
    """The licence file's own name for itself, as its first lines give it; never its text."""
    two_parent_merges: int
    positives: int
    negatives: int
    exclusions: int


class Manifest(BaseModel):
    stage: Literal["A", "B"]
    repositories: list[Repository]
    cases: list[Case]
    exclusions: list[Exclusion]


def _git(cache: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Read the cache. Harness-side, so not under the scrubbed environment graded code gets."""
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(cache), *argv],
        capture_output=True,
        text=True,
        check=check,
        encoding="utf-8",
        errors="surrogateescape",
    )


def pin(repo: str) -> tuple[str, str]:
    """The default branch's name and tip SHA, read from the remote once, on the day it is mined."""
    listed = subprocess.run(
        ["git", "ls-remote", "--symref", f"https://github.com/{repo}.git", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    branch = next(line.split()[1] for line in listed if line.startswith("ref:"))
    tip = next(line.split()[0] for line in listed if not line.startswith("ref:"))
    return branch.removeprefix("refs/heads/"), tip


def host(repo: str, tip: str) -> RealHost:
    return RealHost(
        name=repo, url=f"https://github.com/{repo}.git", commit=tip, depth=WHOLE_HISTORY
    )


_LICENCES = (
    ("Apache License", "Apache"),
    ("MIT License", "MIT"),
    ("Permission is hereby granted, free of charge", "MIT"),
    ("GNU GENERAL PUBLIC LICENSE", "GPL"),
    ("GNU LESSER GENERAL PUBLIC LICENSE", "LGPL"),
    ("GNU AFFERO GENERAL PUBLIC LICENSE", "AGPL"),
    ("Mozilla Public License", "MPL"),
    ("BSD", "BSD"),
)


def _entries(cache: Path, treeish: str) -> list[tuple[str, str]]:
    """`(type, name)` for each entry of a tree, `type` being git's (`blob`, `tree`, `commit`)."""
    listed = _git(cache, "ls-tree", "-z", treeish).stdout.split("\0")
    return [(line.split(" ", 2)[1], line.split("\t", 1)[1]) for line in listed if line]


def licence(cache: Path, tip: str) -> str:
    """Which licence the tip's licence files name, from their opening lines.

    A top-level licence entry may be a directory, as REUSE lays one out (`LICENSES/`, one file
    per licence); its files are read one level down. Recorded in the manifest, decides nothing.
    """
    paths = []
    for kind, name in _entries(cache, tip):
        if not name.upper().startswith(("LICENSE", "LICENCE", "COPYING")):
            continue
        if kind == "blob":
            paths.append(name)
        elif kind == "tree":
            inner = _entries(cache, f"{tip}:{name}")
            paths.extend(f"{name}/{leaf}" for leaf_kind, leaf in inner if leaf_kind == "blob")
    found = []
    for path in sorted(paths):
        head = _git(cache, "cat-file", "blob", f"{tip}:{path}").stdout[:2000]
        kind = next((label for marker, label in _LICENCES if marker in head), "unrecognised")
        found.append(f"{path}: {kind}")
    return "; ".join(found) or "no licence file at the tip"


def _merge_bases(cache: Path, first: str, second: str) -> list[str]:
    return _git(cache, "merge-base", "--all", first, second, check=False).stdout.split()


class _MergeTree(BaseModel):
    tree: str
    """The tree the merge writes, conflict markers included where it conflicts."""
    clean: bool
    conflicted: list[str]
    submodule_or_binary: bool


def merge_tree(cache: Path, first: str, second: str) -> _MergeTree:
    """`git merge-tree --write-tree -z --messages`, which writes nothing, parsed.

    After the tree come the conflicted entries, `<mode> <oid> <stage>\\t<path>`, an empty entry,
    then each message as a path count, the paths, a type and the text. When a submodule
    conflicted, git then appends free text, outside that format, advising how to merge
    submodules by hand; it is read as the submodule conflict it reports, and any other text
    there is refused rather than skipped.
    """
    result = _git(
        cache, "merge-tree", "--write-tree", "-z", "--messages", first, second, check=False
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"merge-tree {first} {second}: {result.stderr.strip()}")
    head, _, messages = result.stdout.partition("\0\0")
    entries = head.split("\0")[1:]
    paths = sorted({entry.split("\t", 1)[1] for entry in entries if "\t" in entry})
    submodule = any(entry.startswith(_SUBMODULE_MODE + " ") for entry in entries)
    fields = messages.split("\0")
    binary = False
    position = 0
    while position < len(fields) and fields[position]:
        if not fields[position].isdigit():
            if not fields[position].startswith(_SUBMODULE_ADVICE):
                raise RuntimeError(
                    f"merge-tree {first} {second}: unexpected message {fields[position][:80]!r}"
                )
            submodule = True
            break
        count = int(fields[position])
        kind = fields[position + 1 + count]
        binary |= kind == "CONFLICT (binary)"
        position += count + 3
    return _MergeTree(
        tree=head.split("\0", 1)[0],
        clean=result.returncode == 0,
        conflicted=paths,
        submodule_or_binary=submodule or binary,
    )


def _changed_locks(cache: Path, base: str, tip: str) -> set[str]:
    names = _git(cache, "diff", "--no-renames", "--name-only", base, tip).stdout.splitlines()
    return {path for path in names if is_lock(path)}


def mine(
    repo: str, cache: Path, default_branch: str, tip: str
) -> tuple[Repository, list[Case], list[Exclusion]]:
    """Every case and exclusion `repo` yields at `tip` (§3.2, §3.3, §3.5), indices unassigned."""
    listed = _git(cache, "rev-list", "--merges", "--parents", tip).stdout.splitlines()
    two_parent = [line.split() for line in listed if len(line.split()) == 3]
    positives: list[Case] = []
    clean: list[tuple[int, Case]] = []
    excluded: list[Exclusion] = []
    for merge, first, second in two_parent:
        bases = _merge_bases(cache, first, second)
        if not bases or not (
            _changed_locks(cache, bases[0], first) & _changed_locks(cache, bases[0], second)
        ):
            # Neither a positive (a lock conflict needs both sides to change it) nor a negative.
            # A criss-cross merge is screened against its first base, so only one whose sides
            # both changed a lock file pays for a merge-tree.
            continue
        tree = merge_tree(cache, first, second)
        lock_conflict = any(is_lock(path) for path in tree.conflicted)
        if len(bases) > 1:
            if lock_conflict:
                excluded.append(Exclusion(repo=repo, merge=merge, reason="criss-cross"))
            continue
        case = Case(
            index=-1,
            repo=repo,
            kind="positive",
            merge=merge,
            first=first,
            second=second,
            base=bases[0],
            conflicted=tree.conflicted,
        )
        if lock_conflict:
            if tree.submodule_or_binary:
                excluded.append(
                    Exclusion(repo=repo, merge=merge, reason="submodule or binary conflict")
                )
            else:
                positives.append(case)
        elif tree.clean:
            when = int(_git(cache, "log", "-1", "--format=%ct", merge).stdout.strip())
            clean.append((when, case.model_copy(update={"kind": "negative"})))
    clean.sort(key=lambda item: (-item[0], item[1].merge))
    negatives = [case for _, case in clean[: len(positives)]]
    summary = Repository(
        repo=repo,
        url=f"https://github.com/{repo}",
        default_branch=default_branch,
        tip=tip,
        licence=licence(cache, tip),
        two_parent_merges=len(two_parent),
        positives=len(positives),
        negatives=len(negatives),
        exclusions=len(excluded),
    )
    return summary, positives + negatives, excluded


def mine_stage(stage: Literal["A", "B"], repos: Sequence[str]) -> Manifest:
    """Pin, fetch and mine each repository in order; index the cases in manifest order."""
    require(REGISTRATION)
    repositories: list[Repository] = []
    cases: list[Case] = []
    exclusions: list[Exclusion] = []
    for repo in repos:
        branch, tip = pin(repo)
        summary, mined, excluded = mine(repo, fetch_real_host(host(repo, tip)), branch, tip)
        repositories.append(summary)
        cases.extend(mined)
        exclusions.extend(excluded)
    return Manifest(
        stage=stage,
        repositories=repositories,
        cases=[case.model_copy(update={"index": i}) for i, case in enumerate(cases)],
        exclusions=exclusions,
    )


# --- the label (§4) --------------------------------------------------------------------------

DescriptiveClass = Literal[
    "took local",
    "took upstream",
    "matches take_upstream",
    "matches keep_local",
    "regenerated",
    "other",
    "clean merge reproduced",
    "clean merge changed",
]


class Label(BaseModel):
    index: int
    acceptable: list[str]
    """The resolutions that reproduce the maintainer's lock files; empty when none does."""
    descriptive: DescriptiveClass | None
    """The §4 class of a conflicted case. A clean case's under Amendment 1 says whether the
    maintainer's tree is the clean merge's; under the original text it is `None`."""


def _lines(cache: Path, commit: str, path: str) -> Counter[str]:
    shown = _git(cache, "cat-file", "blob", f"{commit}:{path}", check=False)
    return Counter(shown.stdout.splitlines()) if shown.returncode == 0 else Counter()


def produced(
    resolution: str, base: Counter[str], local: Counter[str], upstream: Counter[str]
) -> Counter[str]:
    """What a resolution leaves in one lock file, as a multiset of lines (§4's table)."""
    if resolution == "take_upstream":
        return upstream + (local - base)
    if resolution == "keep_local":
        return local + (upstream - base)
    raise ValueError(f"no such resolution: {resolution}")


def label(case: Case, cache: Path, *, amendment: int = 1) -> Label:
    """The maintainer's label on `case`, under the registration as amended `amendment` times.

    `amendment=0` is the original text, under which stage A was measured: a clean case
    ("negative") accepts nothing. Amendment 1 (A2) accepts `merge` there when the maintainer's
    tree is the one the clean merge writes.
    """
    if case.kind == "negative":
        if amendment == 0:
            return Label(index=case.index, acceptable=[], descriptive=None)
        written = merge_tree(cache, case.first, case.second).tree
        committed = _git(cache, "rev-parse", f"{case.merge}^{{tree}}").stdout.strip()
        reproduced = written == committed
        return Label(
            index=case.index,
            acceptable=["merge"] if reproduced else [],
            descriptive="clean merge reproduced" if reproduced else "clean merge changed",
        )
    locks = [path for path in case.conflicted if is_lock(path)]
    versions = [
        tuple(
            _lines(cache, commit, path)
            for commit in (case.base, case.first, case.second, case.merge)
        )
        for path in locks
    ]
    # What the maintainer did to the lock files, resolution by resolution. Acceptability also
    # needs every conflicted path to be a lock file; the descriptive class does not, since it
    # says what happened to the lock files whatever else conflicted.
    matches = [
        resolution
        for resolution in RESOLUTIONS
        if all(produced(resolution, b, local, u) == m for b, local, u, m in versions)
    ]
    only_locks = len(locks) == len(case.conflicted)
    acceptable = matches if only_locks else []
    descriptive: DescriptiveClass
    if all(m == local for _, local, _, m in versions):
        descriptive = "took local"
    elif all(m == u for _, _, u, m in versions):
        descriptive = "took upstream"
    elif "take_upstream" in matches:
        descriptive = "matches take_upstream"
    elif "keep_local" in matches:
        descriptive = "matches keep_local"
    elif any(set(m) - set(b) - set(local) - set(u) for b, local, u, m in versions):
        descriptive = "regenerated"
    else:
        descriptive = "other"
    return Label(index=case.index, acceptable=acceptable, descriptive=descriptive)


# --- the state (§3.4) ------------------------------------------------------------------------


def build_state(case: Case, cache: Path, default_branch: str) -> Sandbox:
    """A checkout of the first parent tracking upstream's default branch at the second."""
    root = _SANDBOX_DIR / "real-merges" / f"{case.merge[:16]}-{os.getpid()}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    upstream = root / "upstream.git"
    work = root / "work"
    run_git(("init", "-q", "--bare", "--template=", str(upstream)), cwd=root)
    (upstream / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (upstream / "objects" / "info" / "alternates").write_text(
        f"{(cache / 'objects').resolve()}\n", encoding="utf-8"
    )
    if (cache / "shallow").is_file():
        shutil.copyfile(cache / "shallow", upstream / "shallow")
    run_git(("update-ref", f"refs/heads/{default_branch}", case.second), cwd=upstream)
    run_git(("symbolic-ref", "HEAD", f"refs/heads/{default_branch}"), cwd=upstream)
    run_git(("clone", "-q", "-o", "upstream", str(upstream), str(work)), cwd=root)
    run_git(("reset", "-q", "--hard", case.first), cwd=work)
    return Sandbox(
        root=root,
        work=work,
        upstream=upstream,
        recorded={"real-merge": f"{case.repo}@{case.merge}"},
    )


# --- the arms (§5) ---------------------------------------------------------------------------


class Decisions(BaseModel):
    """What every dispatcher fired on one case; scores only for the swept dispatchers."""

    index: int
    rule: str | None
    """The intent's own rule's label on the observed state, recorded beside the maintainer's."""
    arm3: list[str | None]
    """Per replicate: the variant of the first program whose preconditions hold."""
    arm2: list[tuple[str | None, float | None]]
    """Per replicate: the lexical top program's variant and score."""
    control: tuple[str | None, float]


def control_classifier() -> StateClassifier:
    """`bench.state_classifier` fit exactly as committed, on the build's 56 states."""
    training = _states(HELD_OUT_FAULTS, {fault: admit_seeds(fault) for fault in HELD_OUT_FAULTS})
    return StateClassifier(_measured_intents(HELD_OUT_FAULTS)).fit([s for _, _, s in training])


def libraries(root: Path) -> list[Library]:
    similarity, _ = scorer("lexical")
    return [
        Library(root / path, similarity=similarity, evaluate_preconditions=evaluate_preconditions)
        for path in LIBRARIES
    ]


def decide(
    case: Case,
    box: Sandbox,
    loaded: Sequence[Library],
    classifier: StateClassifier,
) -> Decisions:
    state = StateFingerprint.observe(box)
    request = INTENT.task_text(case.index)
    signature = TaskSignature(intent=request, fingerprint=state, target=str(box.work))
    arm3: list[str | None] = []
    arm2: list[tuple[str | None, float | None]] = []
    for library in loaded:
        arm3.append(_decide(library, box).arm3)
        ranked = _unthresholded(library).match_semantic(signature, limit=len(library.load_all()))
        arm2.append((ranked[0].program.variant, ranked[0].score) if ranked else (None, None))
    resolved = INTENT.correct_variant(state)
    return Decisions(
        index=case.index,
        rule=resolved.id if resolved is not None else None,
        arm3=arm3,
        arm2=arm2,
        control=classifier.decide(INTENT, state),
    )


# --- the figures (§6) ------------------------------------------------------------------------


def outcome(lab: Label, fired: str | None, score: float | None) -> PairOutcome:
    """A pair outcome with the maintainer's label: a fire is right only if it is acceptable."""
    return PairOutcome(
        correct_variant=lab.acceptable[0] if lab.acceptable else None,
        acceptable_variants=tuple(lab.acceptable),
        fired_variant=fired,
        score=score if fired is not None else None,
        informed=False,
    )


class ReplicateFigures(BaseModel):
    library: str
    arm3: OperatingPoint
    arm2_matched: OperatingPoint | None
    control_matched: OperatingPoint | None
    arm3_fires_on_positives: int
    fires_on_inexpressible: dict[str, int]
    """On conflicted cases with nothing acceptable, how many each dispatcher fired on: arm 3 at
    its own point, arm 2 and the control at their matched thresholds (Amendment 1, A3)."""


class Disagreement(BaseModel):
    """A positive on which the intent's rule and the maintainer's commit disagree."""

    index: int
    repo: str
    merge: str
    rule: str | None
    maintainer: list[str]
    descriptive: str | None


class StageReport(BaseModel):
    stage: Literal["A", "B"]
    positives: int
    negatives: int
    expressible: int
    """Positives with a non-empty acceptable set."""
    descriptive: dict[str, int]
    rule_disagreements: list[Disagreement]
    replicates: list[ReplicateFigures]
    control: OperatingPoint
    arm3_positive_share: float | None
    """`c` in §8: the share of positives arm 3 fires on, pooled over replicates."""


def figures(
    manifest: Manifest, labels: Sequence[Label], decided: Sequence[Decisions]
) -> StageReport:
    by_index = {lab.index: lab for lab in labels}
    cases = {case.index: case for case in manifest.cases}
    positives = [d for d in decided if cases[d.index].kind == "positive"]
    replicates = []
    fired_on_positives = 0
    for r, path in enumerate(LIBRARIES):
        arm3 = [outcome(by_index[d.index], d.arm3[r], None) for d in decided]
        arm2 = [outcome(by_index[d.index], *d.arm2[r]) for d in decided]
        control = [outcome(by_index[d.index], *d.control) for d in decided]
        point = operating_point(arm3)
        fires = sum(d.arm3[r] is not None for d in positives)
        fired_on_positives += fires
        matchable = point.coverage.numerator > 0
        arm2_matched = (
            matched_comparison(sweep(arm2), point).arm2
            if matchable and any(o.fired_variant for o in arm2)
            else None
        )
        control_matched = (
            matched_comparison(sweep(control), point).arm2
            if matchable and any(o.fired_variant for o in control)
            else None
        )
        inexpressible = [
            i
            for i, d in enumerate(decided)
            if cases[d.index].kind == "positive" and not by_index[d.index].acceptable
        ]
        on_inexpressible = {"arm 3": sum(_fires(arm3[i], None) for i in inexpressible)}
        for name, outcomes, matched in (
            ("arm 2", arm2, arm2_matched),
            ("control", control, control_matched),
        ):
            if matched is not None:
                on_inexpressible[name] = sum(
                    _fires(outcomes[i], matched.threshold) for i in inexpressible
                )
        replicates.append(
            ReplicateFigures(
                library=str(path),
                arm3=point,
                arm2_matched=arm2_matched,
                control_matched=control_matched,
                arm3_fires_on_positives=fires,
                fires_on_inexpressible=on_inexpressible,
            )
        )
    disagreements = [
        Disagreement(
            index=d.index,
            repo=cases[d.index].repo,
            merge=cases[d.index].merge,
            rule=d.rule,
            maintainer=by_index[d.index].acceptable,
            descriptive=by_index[d.index].descriptive,
        )
        for d in positives
        if (d.rule is None) != (not by_index[d.index].acceptable)
        or (d.rule is not None and d.rule not in by_index[d.index].acceptable)
    ]
    return StageReport(
        stage=manifest.stage,
        positives=len(positives),
        negatives=len(decided) - len(positives),
        expressible=sum(bool(by_index[d.index].acceptable) for d in positives),
        descriptive=dict(
            sorted(Counter(str(by_index[d.index].descriptive) for d in positives).items())
        ),
        rule_disagreements=disagreements,
        replicates=replicates,
        control=operating_point([outcome(by_index[d.index], *d.control) for d in decided]),
        arm3_positive_share=(
            fired_on_positives / (len(positives) * len(LIBRARIES)) if positives else None
        ),
    )


# --- the stage -------------------------------------------------------------------------------


def run_pilot(out: Path, root: Path = REPOSITORY) -> StageReport:
    """Stage A: mine, label, build and decide every pilot case, then write its figures to `out`.

    Stage B is sized from this stage's arm-3 share (§8), so it is a separate step, run once
    this one's figures are committed.
    """
    require(REGISTRATION)
    if out.exists():
        raise ValueError(f"{out} already exists; a stage writes a fresh directory")
    manifest = mine_stage("A", PILOT)
    branches = {r.repo: r.default_branch for r in manifest.repositories}
    caches = {r.repo: fetch_real_host(host(r.repo, r.tip)) for r in manifest.repositories}
    loaded = libraries(root)
    classifier = control_classifier()
    labels: list[Label] = []
    decided: list[Decisions] = []
    for case in manifest.cases:
        # Stage A was measured under the original text; Amendment 1 came after it (A7).
        labels.append(label(case, caches[case.repo], amendment=0))
        try:
            box = build_state(case, caches[case.repo], branches[case.repo])
        except subprocess.CalledProcessError:
            manifest.exclusions.append(
                Exclusion(repo=case.repo, merge=case.merge, reason="state not built")
            )
            labels.pop()
            continue
        try:
            decided.append(decide(case, box, loaded, classifier))
        finally:
            box.destroy()
    report = figures(manifest, labels, decided)
    out.mkdir(parents=True)
    for name, model in (("manifest", manifest), ("report", report)):
        (out / f"{name}.json").write_text(model.model_dump_json(indent=2) + "\n", "utf-8")
    for name, rows in (("labels", labels), ("decisions", decided)):
        (out / f"{name}.jsonl").write_text(
            "".join(row.model_dump_json() + "\n" for row in rows), "utf-8"
        )
    (out / "summary.txt").write_text(text(report), encoding="utf-8")
    return report


# --- Amendment 1: stage A relabelled, and stage B -------------------------------------------

TARGET_CASES = 247
"""Stage B's size, Amendment 1 A4: `ceil(144 / c)` with stage A's `c` = 77/132."""
MIN_REPOSITORIES = 8
CAP_SHARE = 0.25


class Verdicts(BaseModel):
    """One replicate's registered tests (§7, Amendment 1 A3) and §9's decisions."""

    library: str
    h1: Inference
    h2: Inference
    h3: Inference
    decisions: list[Decision]


class ConfirmatoryReport(BaseModel):
    figures: StageReport
    repositories: list[Repository]
    cases: int
    repositories_with_a_case: int
    underpowered: bool
    verdicts: list[Verdicts]
    h1_supported: bool
    """H1 holds only if it is supported in every replicate (§7)."""
    h2_supported: bool
    h3_supported: bool


def _rows(
    manifest: Manifest,
    labels: Sequence[Label],
    decided: Sequence[Decisions],
    replicate: int,
    other: Literal["arm 2", "control"],
) -> list[Clustered]:
    by_index = {lab.index: lab for lab in labels}
    cases = {case.index: case for case in manifest.cases}
    rows = []
    for d in decided:
        lab = by_index[d.index]
        fired, score = d.arm2[replicate] if other == "arm 2" else d.control
        rows.append(
            Clustered(
                repo=cases[d.index].repo,
                arm3=outcome(lab, d.arm3[replicate], None),
                other=outcome(lab, fired, score),
                inexpressible_conflict=cases[d.index].kind == "positive" and not lab.acceptable,
            )
        )
    return rows


def verdicts(
    manifest: Manifest,
    labels: Sequence[Label],
    decided: Sequence[Decisions],
    *,
    underpowered: bool,
) -> list[Verdicts]:
    """H1, H2 and H3 for each replicate, and §9's rules applied to them in order."""
    out = []
    for r, path in enumerate(LIBRARIES):
        against_arm2 = _rows(manifest, labels, decided, r, "arm 2")
        against_control = _rows(manifest, labels, decided, r, "control")
        h1, h2 = matched_test(against_arm2), matched_test(against_control)
        out.append(
            Verdicts(
                library=str(path),
                h1=h1,
                h2=h2,
                h3=refusal_test(against_control),
                decisions=decide_rules(
                    [row.arm3 for row in against_arm2], h1, h2, underpowered=underpowered
                ),
            )
        )
    return out


def _supported(test: Inference, underpowered: bool) -> bool:
    return not underpowered and test.interval is not None and test.interval.low > 0


def relabel_pilot(stage: Path, out: Path) -> ConfirmatoryReport:
    """Stage A under Amendment 1's labels, from its committed decisions: exploratory (A7).

    Nothing is re-dispatched; only the clean cases' labels change. The tests are computed the
    way stage B's are, and the result is marked underpowered so no verdict can be read from it.
    """
    require(REGISTRATION)
    if out.exists():
        raise ValueError(f"{out} already exists; the relabel writes a fresh directory")
    manifest = Manifest.model_validate_json((stage / "manifest.json").read_text("utf-8"))
    decided = [
        Decisions.model_validate_json(line)
        for line in (stage / "decisions.jsonl").read_text("utf-8").splitlines()
    ]
    caches = {r.repo: fetch_real_host(host(r.repo, r.tip)) for r in manifest.repositories}
    kept = {d.index for d in decided}
    labels = [
        label(case, caches[case.repo], amendment=1) for case in manifest.cases if case.index in kept
    ]
    report = _confirmatory_report(manifest, labels, decided, underpowered=True)
    out.mkdir(parents=True)
    (out / "labels.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in labels), "utf-8"
    )
    (out / "report.json").write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(confirmatory_text(report), encoding="utf-8")
    return report


def _confirmatory_report(
    manifest: Manifest,
    labels: Sequence[Label],
    decided: Sequence[Decisions],
    *,
    underpowered: bool,
) -> ConfirmatoryReport:
    tested = verdicts(manifest, labels, decided, underpowered=underpowered)
    with_a_case = {case.repo for case in manifest.cases if case.index in {d.index for d in decided}}
    return ConfirmatoryReport(
        figures=figures(manifest, labels, decided),
        repositories=manifest.repositories,
        cases=len(decided),
        repositories_with_a_case=len(with_a_case),
        underpowered=underpowered,
        verdicts=tested,
        h1_supported=all(_supported(v.h1, underpowered) for v in tested),
        h2_supported=all(_supported(v.h2, underpowered) for v in tested),
        h3_supported=all(_supported(v.h3, underpowered) for v in tested),
    )


def _capped(cases: list[Case], cache: Path, cap: int) -> list[Case]:
    """At most `cap` of one repository's cases: the most recent, conflicted and clean equal."""
    if len(cases) <= cap:
        return cases

    def recent(kind: str) -> list[Case]:
        chosen = [case for case in cases if case.kind == kind]
        when = {
            case.merge: int(_git(cache, "log", "-1", "--format=%ct", case.merge).stdout.strip())
            for case in chosen
        }
        return sorted(chosen, key=lambda case: (-when[case.merge], case.merge))[: cap // 2]

    return recent("positive") + recent("negative")


def run_confirmatory(out: Path, root: Path = REPOSITORY) -> ConfirmatoryReport:
    """Stage B, under Amendment 1: mine the confirmatory list in order to `TARGET_CASES`.

    Each repository is mined, labelled, built and decided in turn, written under `out/repos/`,
    and its cache deleted before the next is fetched, so the disk holds one history at a time.
    A repository already written is read back instead of mined again, so an interrupted run
    resumes where it stopped.
    """
    require(REGISTRATION)
    done = out / "repos"
    done.mkdir(parents=True, exist_ok=True)
    loaded = libraries(root)
    classifier = control_classifier()
    cap = int(CAP_SHARE * TARGET_CASES)
    repositories: list[Repository] = []
    cases: list[Case] = []
    exclusions: list[Exclusion] = []
    labels: list[Label] = []
    decided: list[Decisions] = []
    for repo in CONFIRMATORY:
        if len(decided) >= TARGET_CASES and len({c.repo for c in cases}) >= MIN_REPOSITORIES:
            break
        written = done / f"{repo.replace('/', '__')}.json"
        if written.is_file():
            part = _RepositoryPart.model_validate_json(written.read_text("utf-8"))
        else:
            part = _mine_and_decide(repo, len(cases), cap, loaded, classifier)
            written.write_text(part.model_dump_json() + "\n", "utf-8")
        repositories.append(part.repository)
        cases.extend(part.cases)
        exclusions.extend(part.exclusions)
        labels.extend(part.labels)
        decided.extend(part.decisions)
    manifest = Manifest(stage="B", repositories=repositories, cases=cases, exclusions=exclusions)
    underpowered = (
        len(decided) < TARGET_CASES
        or len({c.repo for c in cases if c.index in {d.index for d in decided}}) < MIN_REPOSITORIES
    )
    report = _confirmatory_report(manifest, labels, decided, underpowered=underpowered)
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    for name, rows in (("labels", labels), ("decisions", decided)):
        (out / f"{name}.jsonl").write_text(
            "".join(row.model_dump_json() + "\n" for row in rows), "utf-8"
        )
    (out / "report.json").write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(confirmatory_text(report), encoding="utf-8")
    return report


class _RepositoryPart(BaseModel):
    repository: Repository
    cases: list[Case]
    exclusions: list[Exclusion]
    labels: list[Label]
    decisions: list[Decisions]


def _mine_and_decide(
    repo: str,
    first_index: int,
    cap: int,
    loaded: Sequence[Library],
    classifier: StateClassifier,
) -> _RepositoryPart:
    branch, tip = pin(repo)
    pinned = host(repo, tip)
    cache = fetch_real_host(pinned)
    try:
        summary, mined, excluded = mine(repo, cache, branch, tip)
        kept = _capped(mined, cache, cap)
        kept = [case.model_copy(update={"index": first_index + i}) for i, case in enumerate(kept)]
        labels: list[Label] = []
        decided: list[Decisions] = []
        for case in kept:
            try:
                box = build_state(case, cache, branch)
            except subprocess.CalledProcessError:
                excluded.append(
                    Exclusion(repo=case.repo, merge=case.merge, reason="state not built")
                )
                continue
            try:
                labels.append(label(case, cache, amendment=1))
                decided.append(decide(case, box, loaded, classifier))
            finally:
                box.destroy()
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    return _RepositoryPart(
        repository=summary.model_copy(
            update={
                "positives": sum(c.kind == "positive" for c in kept),
                "negatives": sum(c.kind == "negative" for c in kept),
                "exclusions": len(excluded),
            }
        ),
        cases=kept,
        exclusions=excluded,
        labels=labels,
        decisions=decided,
    )


def confirmatory_text(report: ConfirmatoryReport) -> str:
    lines = [text(report.figures).rstrip("\n")]
    lines.append(
        f"  cases {report.cases} from {report.repositories_with_a_case} repositories; "
        f"underpowered: {report.underpowered}"
    )
    for v in report.verdicts:
        lines.append(f"  {v.library}:")
        for name, test in (("H1", v.h1), ("H2", v.h2), ("H3", v.h3)):
            interval = (
                f"[{test.interval.low:+.3f}, {test.interval.high:+.3f}]"
                if test.interval is not None
                else "undefined"
            )
            statistic = f"{test.statistic:+.3f}" if test.statistic is not None else "undefined"
            lines.append(
                f"    {name}: {statistic}, 95% interval {interval}, McNemar b/c "
                f"{test.discordant[0]}/{test.discordant[1]}, p {test.p_value}"
            )
        for decision in v.decisions:
            lines.append(f"    rule {decision.rule}: {decision.outcome}")
    lines.append(
        f"  supported in every replicate: H1 {report.h1_supported}, H2 {report.h2_supported}, "
        f"H3 {report.h3_supported}"
    )
    return "\n".join(lines) + "\n"


def text(report: StageReport) -> str:
    lines = [
        f"Real lock-file merges, stage {report.stage} (#296; registered in "
        "docs/preregistration/real-merges.md)",
        f"  positives {report.positives}, negatives {report.negatives}; expressible "
        f"{report.expressible}/{report.positives}",
        f"  classes: {report.descriptive}",
        f"  rule against maintainer: {len(report.rule_disagreements)} disagreements",
    ]
    for figures_ in report.replicates:
        point = figures_.arm3
        lines.append(
            f"  {figures_.library}: arm 3 fires {point.coverage.numerator}/"
            f"{point.coverage.denominator} ({figures_.arm3_fires_on_positives} on positives), "
            f"wrong {point.mismatch.numerator}"
        )
        for name, matched in (
            ("arm 2", figures_.arm2_matched),
            ("control", figures_.control_matched),
        ):
            if matched is not None:
                lines.append(
                    f"    {name} at matched coverage: fires {matched.coverage.numerator}, "
                    f"wrong {matched.mismatch.numerator}"
                )
    control = report.control
    lines.append(
        f"  control at every fire: fires {control.coverage.numerator}/"
        f"{control.coverage.denominator}, wrong {control.mismatch.numerator}"
    )
    lines.append(f"  arm 3's share of positives fired on (c, §8): {report.arm3_positive_share}")
    return "\n".join(lines) + "\n"


# --- the observed states, recorded after a run (ADR-0052) -------------------------------------


class ObservedState(BaseModel):
    """One case's state as `StateFingerprint.observe` reads it, rebuilt from the manifest."""

    index: int
    state: StateFingerprint
    control_matches: bool
    """The registered control's decision on the rebuilt state equals the one the run recorded:
    the control is deterministic and reads nothing but the state, so a mismatch means the
    state did not rebuild as it was."""


def observe_states(stage: Path) -> list[ObservedState]:
    """Rebuild every case of a finished stage and record its observed state in `states.jsonl`.

    A run records what each dispatcher fired, not the state it fired on, so a control added
    later (the library-scoped one, an LLM judge) could only be measured by mining again. Each
    row is appended as its case is observed, and cases already written are skipped, so a
    stopped run resumes. One repository's history is fetched at a time and removed after.
    """
    manifest = Manifest.model_validate_json((stage / "manifest.json").read_text("utf-8"))
    recorded = {
        row.index: row
        for row in (
            Decisions.model_validate_json(line)
            for line in (stage / "decisions.jsonl").read_text("utf-8").splitlines()
            if line.strip()
        )
    }
    out = stage / "states.jsonl"
    written = (
        [ObservedState.model_validate_json(line) for line in out.read_text("utf-8").splitlines()]
        if out.exists()
        else []
    )
    done = {row.index for row in written}
    repositories = {repository.repo: repository for repository in manifest.repositories}
    classifier = control_classifier()
    with out.open("a", encoding="utf-8") as rows:
        for repo in dict.fromkeys(case.repo for case in manifest.cases):
            todo = [c for c in manifest.cases if c.repo == repo and c.index not in done]
            if not todo:
                continue
            repository = repositories[repo]
            cache = fetch_real_host(host(repo, repository.tip))
            try:
                for case in todo:
                    box = build_state(case, cache, repository.default_branch)
                    try:
                        state = StateFingerprint.observe(box)
                    finally:
                        box.destroy()
                    control = classifier.decide(INTENT, state)
                    row = ObservedState(
                        index=case.index,
                        state=state,
                        control_matches=tuple(control) == tuple(recorded[case.index].control),
                    )
                    written.append(row)
                    rows.write(row.model_dump_json() + "\n")
                    rows.flush()
            finally:
                shutil.rmtree(cache, ignore_errors=True)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.real_merges")
    parser.add_argument("--stage", choices=("A", "B"), default="A")
    parser.add_argument(
        "--relabel-pilot",
        type=Path,
        default=None,
        metavar="STAGE_A_DIR",
        help="recompute stage A under Amendment 1's labels, exploratory (A7)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="default: results/real-merges-<today>/stage-<x>"
    )
    parser.add_argument(
        "--observe-states",
        type=Path,
        default=None,
        metavar="STAGE_DIR",
        help="rebuild a finished stage's cases and record each observed state (states.jsonl)",
    )
    args = parser.parse_args(argv)
    if args.observe_states is not None:
        observed = observe_states(args.observe_states)
        mismatched = sum(not row.control_matches for row in observed)
        print(f"{len(observed)} states recorded; control differs on {mismatched}")
        return 1 if mismatched else 0
    if args.relabel_pilot is not None:
        out = args.out or args.relabel_pilot / "amendment-1-exploratory"
        print(confirmatory_text(relabel_pilot(args.relabel_pilot, out)), end="")
        return 0
    out = args.out or Path(f"results/real-merges-{date.today().isoformat()}/stage-{args.stage}")
    if args.stage == "B":
        print(confirmatory_text(run_confirmatory(out)), end="")
    else:
        print(text(run_pilot(out)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
