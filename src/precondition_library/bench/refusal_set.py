"""Study 2's refusal set R, and how configuration R's admission checks it (refusal-population).

`docs/preregistration/refusal-population.md` §3.3 defines R: the inexpressible conflicts of the
admission repositories, at most `PER_REPOSITORY` per repository and the most recent first, until
there are `SIZE` or the list is exhausted. A case, its state, its exclusions and its label are
study 1's exactly (`bench.real_merges`, Amendment 1 in force). An **inexpressible conflict** is a
conflicted case whose acceptable set is empty.

**Mining and freezing (§4 step 3).** `mine_refusal_set` mines the admission list in order and
writes `refusal-set.json` (the repositories, the cases, their labels and every exclusion) and
`states.jsonl.gz` (each case's state as `StateFingerprint.observe` reads it). Once committed, the
set is frozen: its SHA-256 is what a configuration R build records (`digest`). Each repository is
written as it finishes, under `repos/`, so an interrupted mining resumes without fetching again.

**Checking a program (§5).** `RefusalStates.accepted_by` rebuilds each state of R and evaluates a
program's preconditions on it, with the same `evaluate_preconditions` arm 3 and admission use. A
state is rebuilt for every program rather than kept, because R's repositories are large and forty
checkouts would not fit beside a build. The first rebuild of each state is compared with its
frozen observation, and a difference stops the build: a configuration R library must be gated by
the set the registration froze, not by whatever a repository's state rebuilds to today.
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

from ..agents.compile import RefusalCheck
from ..program import Program
from ..runtime.probes import evaluate_preconditions
from ..sandbox import fetch_real_host
from ..signatures import StateFingerprint
from .preregistration import require
from .real_merges import (
    Case,
    Exclusion,
    Label,
    Repository,
    _git,
    build_state,
    host,
    label,
    mine,
    pin,
)

REGISTRATION = "refusal-population"

ADMISSION = (
    "matomo-org/matomo",
    "saleor/saleor",
    "openfoodfoundation/openfoodnetwork",
    "RocketChat/Rocket.Chat",
)
"""List A, the refusal set's source, in the registration's order (§3.1)."""

PER_REPOSITORY = 10
SIZE = 40
"""§3.3: at most 10 per repository, until there are 40."""

MANIFEST = "refusal-set.json"
STATES = "states.jsonl.gz"


class RefusalSet(BaseModel):
    """R as frozen: the cases, nothing of the repositories' content but SHAs and labels."""

    repositories: list[Repository]
    cases: list[Case]
    labels: list[Label]
    exclusions: list[Exclusion]


class ObservedRefusal(BaseModel):
    index: int
    state: StateFingerprint


class _RepositoryPart(BaseModel):
    repository: Repository
    cases: list[Case]
    labels: list[Label]
    exclusions: list[Exclusion]
    states: list[StateFingerprint]


def _most_recent_first(cases: list[Case], cache: Path) -> list[Case]:
    when = {
        case.merge: int(_git(cache, "log", "-1", "--format=%ct", case.merge).stdout.strip())
        for case in cases
    }
    return sorted(cases, key=lambda case: (-when[case.merge], case.merge))


def select(
    repo: str, cache: Path, default_branch: str, tip: str, limit: int, first_index: int
) -> _RepositoryPart:
    """Up to `limit` of `repo`'s inexpressible conflicts, the most recent first, each built.

    A conflict whose state does not build is an exclusion, as in study 1, and the next most
    recent takes its place.
    """
    summary, mined, excluded = mine(repo, cache, default_branch, tip)
    kept: list[Case] = []
    labels: list[Label] = []
    states: list[StateFingerprint] = []
    for case in _most_recent_first([c for c in mined if c.kind == "positive"], cache):
        if len(kept) == limit:
            break
        indexed = case.model_copy(update={"index": first_index + len(kept)})
        labelled = label(indexed, cache, amendment=1)
        if labelled.acceptable:
            continue
        try:
            box = build_state(indexed, cache, default_branch)
        except subprocess.CalledProcessError:
            excluded.append(Exclusion(repo=repo, merge=case.merge, reason="state not built"))
            continue
        try:
            states.append(StateFingerprint.observe(box))
        finally:
            box.destroy()
        kept.append(indexed)
        labels.append(labelled)
    return _RepositoryPart(
        repository=summary.model_copy(
            update={"positives": len(kept), "negatives": 0, "exclusions": len(excluded)}
        ),
        cases=kept,
        labels=labels,
        exclusions=excluded,
        states=states,
    )


def mine_refusal_set(out: Path) -> RefusalSet:
    """Mine, label and observe R into `out` (§3.3), resuming from `out/repos/`.

    Refuses to write over a frozen set: once `refusal-set.json` exists, R is what it says.
    """
    require(REGISTRATION)
    if (out / MANIFEST).exists():
        raise ValueError(f"{out / MANIFEST} exists: the refusal set is frozen")
    done = out / "repos"
    done.mkdir(parents=True, exist_ok=True)
    parts: list[_RepositoryPart] = []
    for repo in ADMISSION:
        found = sum(len(part.cases) for part in parts)
        if found >= SIZE:
            break
        written = done / f"{repo.replace('/', '__')}.json"
        if written.is_file():
            part = _RepositoryPart.model_validate_json(written.read_text("utf-8"))
        else:
            branch, tip = pin(repo)
            cache = fetch_real_host(host(repo, tip))
            try:
                part = select(repo, cache, branch, tip, min(PER_REPOSITORY, SIZE - found), found)
            finally:
                shutil.rmtree(cache, ignore_errors=True)
            written.write_text(part.model_dump_json() + "\n", "utf-8")
        parts.append(part)
    refusals = RefusalSet(
        repositories=[part.repository for part in parts],
        cases=[case for part in parts for case in part.cases],
        labels=[lab for part in parts for lab in part.labels],
        exclusions=[exclusion for part in parts for exclusion in part.exclusions],
    )
    rows = [
        ObservedRefusal(index=case.index, state=state)
        for part in parts
        for case, state in zip(part.cases, part.states, strict=True)
    ]
    (out / STATES).write_bytes(
        gzip.compress(
            "".join(row.model_dump_json() + "\n" for row in rows).encode("utf-8"), mtime=0
        )
    )
    (out / MANIFEST).write_text(refusals.model_dump_json(indent=2) + "\n", "utf-8")
    return refusals


def load(directory: Path) -> tuple[RefusalSet, list[StateFingerprint]]:
    """A frozen R and its observed states, in case order."""
    refusals = RefusalSet.model_validate_json((directory / MANIFEST).read_text("utf-8"))
    text = gzip.decompress((directory / STATES).read_bytes()).decode("utf-8")
    observed = {
        row.index: row.state
        for row in (ObservedRefusal.model_validate_json(line) for line in text.splitlines() if line)
    }
    if sorted(observed) != sorted(case.index for case in refusals.cases):
        raise ValueError(f"{directory}: the states and the cases do not match one to one")
    return refusals, [observed[case.index] for case in refusals.cases]


def digest(directory: Path) -> str:
    """The SHA-256 of a frozen R: its manifest and its states, in that order."""
    hashed = hashlib.sha256()
    for name in (MANIFEST, STATES):
        hashed.update((directory / name).read_bytes())
    return hashed.hexdigest()


class RefusalStates:
    """R, as configuration R's admission checks it (`agents.compile.RefusalStates`).

    Each repository's history is fetched once, at its pinned tip, and kept for the build:
    `fetch_real_host`'s cache is keyed by tip, so later builds reuse it.
    """

    def __init__(self, directory: Path) -> None:
        self.refusals, self.states = load(directory)
        self.digest = digest(directory)
        self._branches = {r.repo: r.default_branch for r in self.refusals.repositories}
        self._tips = {r.repo: r.tip for r in self.refusals.repositories}
        self._caches: dict[str, Path] = {}
        self._verified: set[int] = set()

    def __len__(self) -> int:
        return len(self.refusals.cases)

    def _cache(self, repo: str) -> Path:
        if repo not in self._caches:
            self._caches[repo] = fetch_real_host(host(repo, self._tips[repo]))
        return self._caches[repo]

    def accepted_by(self, program: Program) -> RefusalCheck:
        """Every state of R on which all of `program`'s preconditions hold, or why they could
        not be evaluated: a placeholder outside the vocabulary, or a refused probe, which
        admission's negative side also treats as a defect rather than a "no"."""
        accepted: list[tuple[str, StateFingerprint]] = []
        for case, frozen in zip(self.refusals.cases, self.states, strict=True):
            box = build_state(case, self._cache(case.repo), self._branches[case.repo])
            try:
                if case.index not in self._verified:
                    if StateFingerprint.observe(box) != frozen:
                        raise RuntimeError(
                            f"refusal case {case.index} ({case.repo}@{case.merge}) no longer "
                            f"rebuilds as it was frozen; a configuration R build stops here"
                        )
                    self._verified.add(case.index)
                result = evaluate_preconditions(program, box)
            except KeyError as exc:
                return accepted, str(exc)
            finally:
                box.destroy()
            refused = [predicate for predicate in result.predicates if predicate.refused]
            if refused:
                first = refused[0]
                return accepted, f"precondition {first.name!r} was refused: {first.observed}"
            if result.ok:
                accepted.append((f"{case.repo}@{case.merge[:12]}", frozen))
        return accepted, None
