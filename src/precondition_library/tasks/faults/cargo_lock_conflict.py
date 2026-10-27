"""Fault: both sides changed a real `Cargo.lock`'s dependencies, so a sync conflicts in it (#306).

The lock-shaped fault (`lockfile_conflict`) was a toy format, and on real merges its line unions
reproduced no maintainer's resolution (stage A, 0 of 30). Read package by package, the real
merges have answers -- a package-level three-way merge, a side reconciled by the tool -- and
which answer is right depends on what each side did (`results/lock-actions-2026-10-27/`). This
fault builds that situation for real: a Rust crate whose dependencies are vendored in the
repository (a cargo "directory source"), so `cargo` resolves with no network, and a genuine
`Cargo.lock` written by cargo itself.

## Three states, each with a different right action

Chosen so git really conflicts in `Cargo.lock` -- bumping two unrelated crates merges cleanly --
and so the same action is not right in all three:

* ``both_added``: each side adds a different dependency. Both land at the same place in the lock
  (the crate's dependency list and the end of the package list). The package-level merge is
  right, and so is either side reconciled by cargo.
* ``same_crate_bumped``: both sides move ``birch`` to different versions, and upstream also
  moves ``alder``. Right: the package-level merge with each crate unified to its highest
  compatible version. Taking either side loses the other's bump.
* ``local_removed``: the local side drops ``birch``; upstream moves ``birch`` and ``alder``.
  Right: upstream's lock reconciled by cargo against the merged manifest, which drops
  ``birch``. The package-level merge keeps upstream's ``birch``, which nothing requires any more.

## The checker

1. upstream's tip is contained in the local branch;
2. no conflict marker remains in a tracked file;
3. the committed `Cargo.lock` resolves exactly the expected `(package, version)` set, recorded
   at injection by construction of the state;
4. cargo accepts that lock for the merged manifest as it stands:
   `cargo metadata --locked --offline`, the ecosystem's own check (#297).

Cargo runs harness-side here, in the injector and the checker, with the operator's toolchain.
Whether a *learned program* may call cargo is a separate decision about what the sandbox
exposes, recorded when the intent needs it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ...sandbox import (
    Sandbox,
    git_out,
    provide_rust_toolchain,
    record_base,
    run_git,
    tip_contained,
)
from ...signatures import CARGO_LOCK, StateFingerprint
from ..intent import IntentSpec, ResolutionVariant, sample_index
from ..spec import FaultSpec, GroundTruth

LOCK = "Cargo.lock"
MANIFEST = "Cargo.toml"
CRATE = "app"

BASE_VENDORED: dict[str, tuple[str, ...]] = {"alder": ("1.0.0",), "birch": ("0.2.0",)}
"""What the shared ancestor vendors. Cargo resolves from the vendored versions and nothing else,
so a side moves a crate on by vendoring a newer release, as a registry gains one.

`cargo update -p <crate> --precise <older>` is silently ignored for a source-replaced registry
(cargo 1.94 exits 0 and changes nothing), so versions are chosen by what is available, never
by `--precise`."""

ADDED: dict[str, tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]] = {
    "both_added": ({"cedar": ("1.0.0",)}, {"dogwood": ("1.0.0",)}),
    "same_crate_bumped": ({"birch": ("0.2.3",)}, {"birch": ("0.2.1",), "alder": ("1.1.0",)}),
    "local_removed": ({}, {"birch": ("0.2.1",), "alder": ("1.1.0",)}),
}
"""Per state, the releases (local, upstream) each side vendors."""

INJECTED_STATES = ("both_added", "same_crate_bumped", "local_removed")
_STATE_SALT = "cargo_lock_conflict:state"

_MARKER_PATTERN = r"^(<{7}|>{7}|\|{7})( |$)"
"""Git's start, end and base markers, as `lockfile_conflict` matches them (ADR-0045)."""

_CONFIG = (
    '[source.crates-io]\nreplace-with = "vendored"\n\n[source.vendored]\ndirectory = "vendor"\n'
)


def state_for_seed(seed: int) -> str:
    return INJECTED_STATES[sample_index(seed, _STATE_SALT, len(INJECTED_STATES))]


def cargo_environment() -> dict[str, str]:
    """The operator's toolchain, offline. Harness-side only: never handed to graded code."""
    keep = ("PATH", "HOME", "RUSTUP_HOME", "CARGO_HOME", "LANG", "TMPDIR", "SystemRoot")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env.update(
        CARGO_NET_OFFLINE="true",
        RUSTUP_TOOLCHAIN=os.environ.get("RUSTUP_TOOLCHAIN", "stable"),
        CARGO_TERM_COLOR="never",
    )
    return env


def cargo(work: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cargo", *args, "--offline"],
        cwd=work,
        env=cargo_environment(),
        capture_output=True,
        text=True,
        check=check,
    )


def _manifest(dependencies: dict[str, str]) -> str:
    lines = [f'{name} = "{requirement}"' for name, requirement in dependencies.items()]
    return (
        f'[package]\nname = "{CRATE}"\nversion = "0.1.0"\nedition = "2021"\n\n'
        "[dependencies]\n" + "".join(f"{line}\n" for line in lines)
    )


def _vendor(work: Path, crates: dict[str, tuple[str, ...]]) -> None:
    """Make these versions available, as a registry gaining releases would."""
    for name, versions in crates.items():
        for version in versions:
            for relative, content in _vendored_files(name, version).items():
                path = work / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")


def _vendored_files(name: str, version: str) -> dict[str, str]:
    root = f"vendor/{name}-{version}"
    return {
        f"{root}/Cargo.toml": (
            f'[package]\nname = "{name}"\nversion = "{version}"\nedition = "2021"\n'
        ),
        f"{root}/src/lib.rs": "",
        f"{root}/.cargo-checksum.json": '{"files":{},"package":null}',
    }


def _commit(work: Path, message: str) -> str:
    run_git(("add", "-A"), cwd=work)
    run_git(("commit", "-q", "-m", message), cwd=work)
    return git_out("rev-parse", "HEAD", cwd=work)


def packages_of(text: str) -> set[tuple[str, str]]:
    """A `Cargo.lock`'s resolved `(package, version)` pairs (as `bench.lock_actions` reads it)."""
    import tomllib

    data = tomllib.loads(text)
    return {(str(p["name"]), str(p["version"])) for p in data.get("package", [])}


EXPECTED: dict[str, set[tuple[str, str]]] = {
    "both_added": {
        (CRATE, "0.1.0"),
        ("alder", "1.0.0"),
        ("birch", "0.2.0"),
        ("cedar", "1.0.0"),
        ("dogwood", "1.0.0"),
    },
    "same_crate_bumped": {(CRATE, "0.1.0"), ("alder", "1.1.0"), ("birch", "0.2.3")},
    "local_removed": {(CRATE, "0.1.0"), ("alder", "1.1.0")},
}
"""What a right resolution of each state resolves, by construction of the state."""


# --- the intent (#306): rules over the package-level fingerprint fields ---------------------
#
# Pinned against `check` by replaying each resolution in each state
# (`tests/test_cargo_lock_conflict.py`), as `lockfile_conflict`'s are.

STATE_VARIANT = {
    "both_added": "reconcile_upstream_lock",
    "same_crate_bumped": "keep_local_bumps",
    "local_removed": "reconcile_upstream_lock",
}
"""The resolution each state is labelled with: what `INTENT`'s rules decide."""


def cargo_lock_conflicts(state: StateFingerprint) -> bool:
    """The family's situation: both sides committed, and `Cargo.lock` is what conflicts."""
    return state.sync_would_conflict and any(
        path.rsplit("/", 1)[-1] == CARGO_LOCK for path in state.merge_conflicted_files
    )


VARIANTS = [
    ResolutionVariant(
        id="keep_local_bumps",
        decided_by=lambda s: cargo_lock_conflicts(s) and bool(s.lock_bumped_by_both),
        accepted_by=cargo_lock_conflicts,
        rationale=(
            "Keeping the local lock and moving on each crate upstream moved keeps every "
            "version either side chose, so it is right whatever the two sides did."
        ),
    ),
    ResolutionVariant(
        id="reconcile_upstream_lock",
        decided_by=lambda s: cargo_lock_conflicts(s) and not s.lock_bumped_by_both,
        accepted_by=lambda s: cargo_lock_conflicts(s) and not s.lock_bumped_by_both,
        rationale=(
            "Where no crate was moved by both sides, upstream's lock reconciled by cargo against "
            "the merged manifest keeps upstream's versions and takes the local side's manifest."
        ),
    ),
    ResolutionVariant(
        id="reconcile_local_lock",
        decided_by=lambda s: False,
        accepted_by=lambda s: (
            cargo_lock_conflicts(s)
            and not s.lock_bumped_by_both
            and not s.lock_removed_here_changed_upstream
            and not s.lock_moved_upstream_only
        ),
        rationale=(
            "The local lock reconciled by cargo is right only where upstream moved no crate the "
            "local side kept, since cargo keeps the versions a lock already names."
        ),
    ),
]

INTENT = IntentSpec(
    name="sync_through_a_conflicting_cargo_lock",
    fault="cargo_lock_conflict",
    phrasings=[
        "Bring this branch up to date with upstream. We both changed our Rust dependencies.",
        "The sync stopped on a Cargo.lock conflict. Get it through without losing a version "
        "either side chose.",
        "Merge upstream into this branch and leave Cargo.lock consistent with Cargo.toml.",
        "Upstream and I both moved crates on. Catch my branch up properly.",
        "Cargo.lock conflicts when I sync. Resolve it the way this project expects.",
    ],
    naming_markers=["Cargo.lock", "cargo"],
    variants=VARIANTS,
    variant_phrasings={
        "keep_local_bumps": ["we both bumped the same crate, and I want my version kept"],
        "reconcile_upstream_lock": ["upstream's lock is the one to start from"],
        "reconcile_local_lock": ["my lock is the one to start from"],
    },
)


class CargoLockConflictFault(FaultSpec):
    name = "cargo_lock_conflict"
    change_surface = (MANIFEST, LOCK)

    def change_surface_for_seed(self, seed: int) -> tuple[str, ...]:
        """The manifest, the lock, and the releases either side vendored at this seed's state."""
        local_adds, upstream_adds = ADDED[state_for_seed(seed)]
        vendored = [
            path
            for adds in (local_adds, upstream_adds)
            for name, versions in adds.items()
            for version in versions
            for path in _vendored_files(name, version)
        ]
        return (MANIFEST, LOCK, *vendored)

    description = "Both sides changed a real Cargo.lock's dependencies, so a sync conflicts in it"

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        work = sandbox.work
        state = state_for_seed(seed)
        if not provide_rust_toolchain(sandbox):
            raise RuntimeError(f"{self.name} needs a Rust toolchain (cargo) on this host")

        # The shared ancestor, committed and published *before* the base is recorded: the
        # vendored crates, the crate depending on alder and birch, and the lock cargo writes for
        # it. It is the layout both sides start from, not part of the fault, so the change
        # surface stays what the sides change (as `dirty_tree`'s preparatory commit does).
        _vendor(work, BASE_VENDORED)
        (work / ".cargo").mkdir(exist_ok=True)
        (work / ".cargo" / "config.toml").write_text(_CONFIG, encoding="utf-8")
        (work / "src").mkdir(exist_ok=True)
        (work / "src" / "lib.rs").write_text("", encoding="utf-8")
        (work / MANIFEST).write_text(_manifest({"alder": "1.0", "birch": "0.2"}), "utf-8")
        cargo(work, "generate-lockfile")
        _commit(work, "chore: vendor dependencies and lock them")
        run_git(("push", "-q", "upstream", "main"), cwd=work)
        common = record_base(sandbox, fault=self.name)
        local_adds, upstream_adds = ADDED[state]

        # The local side.
        _vendor(work, local_adds)
        if state == "both_added":
            (work / MANIFEST).write_text(
                _manifest({"cedar": "1.0", "alder": "1.0", "birch": "0.2"}), "utf-8"
            )
            cargo(work, "update", "--workspace")
        elif state == "same_crate_bumped":
            cargo(work, "update", "-p", "birch")
        else:
            (work / MANIFEST).write_text(_manifest({"alder": "1.0"}), "utf-8")
            cargo(work, "update", "--workspace")
        local_tip = _commit(work, "deps: local change")
        sandbox.recorded["local-tip"] = local_tip

        # Upstream, from the same ancestor, published.
        run_git(("reset", "-q", "--hard", common), cwd=work)
        _vendor(work, upstream_adds)
        if state == "both_added":
            (work / MANIFEST).write_text(
                _manifest({"alder": "1.0", "birch": "0.2", "dogwood": "1.0"}), "utf-8"
            )
            cargo(work, "update", "--workspace")
        else:
            cargo(work, "update", "-p", "birch", "-p", "alder")
        _commit(work, "deps: upstream change")
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        run_git(("reset", "-q", "--hard", local_tip), cwd=work)
        run_git(("fetch", "-q", "upstream"), cwd=work)
        sandbox.recorded["cargo-state"] = state
        sandbox.recorded["expected-packages"] = json.dumps(sorted(EXPECTED[state]))

    def check(self, sandbox: Sandbox) -> GroundTruth:
        work = sandbox.work
        upstream_tip = git_out("rev-parse", "refs/heads/main", cwd=sandbox.upstream)
        if not tip_contained(work, upstream_tip):
            return GroundTruth(
                ok=False, detail=f"upstream tip {upstream_tip[:12]} is not contained"
            )
        markers = run_git(("grep", "-n", "-I", "-E", _MARKER_PATTERN), cwd=work, check=False)
        if markers.stdout.strip():
            first = markers.stdout.splitlines()[0]
            return GroundTruth(ok=False, detail=f"conflict markers remain: {first}")
        lock = work / LOCK
        if not lock.is_file():
            return GroundTruth(ok=False, detail=f"{LOCK} is missing after the sync")
        try:
            resolved = packages_of(lock.read_text(encoding="utf-8"))
        except ValueError as error:
            return GroundTruth(ok=False, detail=f"{LOCK} does not parse: {error}")
        expected = {tuple(p) for p in json.loads(sandbox.recorded["expected-packages"])}
        if resolved != expected:
            missing, extra = sorted(expected - resolved), sorted(resolved - expected)
            return GroundTruth(
                ok=False,
                detail=f"{LOCK} resolves the wrong set: missing {missing}, unexpected {extra}",
            )
        accepted = cargo(work, "metadata", "--locked", "--format-version", "1", check=False)
        if accepted.returncode != 0:
            reason = (accepted.stderr.strip().splitlines() or ["(no message)"])[-1]
            return GroundTruth(
                ok=False, detail=f"cargo refuses {LOCK} for the merged manifest: {reason}"
            )
        return GroundTruth(
            ok=True,
            detail=(
                "upstream is contained, no marker remains, and the lock resolves the right "
                "set, which cargo accepts for the merged manifest"
            ),
        )

    def task_text(self, seed: int) -> str:
        return INTENT.task_text(seed)

    def state_for_seed(self, seed: int) -> str:
        return state_for_seed(seed)

    def variant_for_seed(self, seed: int) -> str:
        return STATE_VARIANT[state_for_seed(seed)]

    def instance_for_seed(self, seed: int) -> str:
        """One instance per state: the crates and versions are fixed, so there is no axis yet."""
        return f"cargo_lock_conflict/{self.variant_for_seed(seed)}/{state_for_seed(seed)}"


SPEC = CargoLockConflictFault()
