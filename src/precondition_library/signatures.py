"""How a task is described, and how its environment's state is fingerprinted.

Two competing dispatch mechanisms consume these:

  arm 2 (similarity)    compares the intent and the fingerprint rendered as
                        text (`StateFingerprint.as_text()`), scoring surface
                        overlap only -- it cannot evaluate the fingerprint
  arm 3 (preconditions) runs `StateFingerprint` probes and lets each stored
                        Program decide applicability for itself

Arm 2 is given the state as text, not denied it: issue #4 requires both arms to
receive the same full representation so the comparison measures the dispatch
mechanism rather than a difference in what each arm was shown. The fingerprint is
what stops arm 3 from being a rerun of arm 2: it describes the *environment*, not
the request, and arm 3 can act on it. Two tasks phrased identically against
structurally different repos must not resolve to the same program.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .sandbox import Sandbox, run_git, submodule_path, upstream_ref


def _render(value: object) -> str:
    """One fingerprint field as text, spelled the same way every time.

    Only the values the fingerprint already stores are rendered: booleans as
    `true`/`false`, lists comma-separated in their stored order, and empty
    values as `(none)` so a line is never blank. `str()` is the fallback rather
    than a format string because a field added to the model must render without
    this helper knowing about it.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "(none)"
    if value == "":
        return "(none)"
    return str(value)


_NOT_YET_RENDERED = frozenset({"tracked_branch", "upstream_default_branch", "local_branches"})
"""Fields `as_text` leaves out until the branch-renamed intent is registered (#190).

`as_text` is arm 2's whole view of state, so a field added to it changes every arm-2
score in every measured family. These exist for the branch-renamed intent, which is
not yet measured; rendering them is part of the change that registers it (as
ADR-0027 did for the dirty-tree fields), so until then every measured arm-2 text is
byte-identical."""


def _config(work: Path, key: str) -> str:
    """A git config value, or "" when the key is unset (`git config --get` exits 1)."""
    result = run_git(("config", "--get", key), cwd=work, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _has_locked_branch(work: Path, branch: str) -> bool:
    """Whether git holds a lock file for the branch ref.

    A `<ref>.lock` file is git's marker that a ref update is in progress, so that
    is what the probe reads, via git's own `--git-path` rather than a hard-coded
    layout. Nothing in this repository creates such a lock, so on the current
    sandboxes the probe is always false; it is here because the fingerprint
    declares the field.
    """
    lock = Path(
        run_git(("rev-parse", "--git-path", f"refs/heads/{branch}.lock"), cwd=work).stdout.strip()
    )
    if not lock.is_absolute():
        lock = work / lock
    return lock.exists()


class StateFingerprint(BaseModel):
    """Observable git-level facts about an environment, gathered without an LLM.

    Every field must be obtainable from git alone, because arm 3 decides by
    running probes over exactly these values. A field that cannot be probed does
    not belong here: it would make a resolution undecidable and quietly turn the
    experiment into a comparison of two equally blind dispatchers.
    """

    dirty_worktree: bool
    branch: str
    upstream_ahead: int
    """Commits upstream has that HEAD lacks: `git rev-list --count HEAD..upstream/main`."""
    upstream_behind: int
    """Commits HEAD has that upstream lacks: `git rev-list --count upstream/main..HEAD`."""
    has_locked_branch: bool
    has_submodule_reference: bool
    remotes: list[str] = []

    # Discriminators for the ambiguous intents (see the intent model added in the next task).
    local_touched_files: list[str] = []
    """Files the local-only commits change: `git diff --name-only upstream/main...HEAD`."""
    upstream_touched_files: list[str] = []
    """Files upstream's new commits change: `git diff --name-only HEAD...upstream/main`."""
    submodule_initialised: bool = False
    """Whether the submodule directory has been initialised in this clone:
    `git submodule status` prefixes an uninitialised entry with `-`."""
    submodule_pin_matches_upstream: bool = True
    """Whether the recorded submodule commit equals the one upstream pins:
    `git diff --name-only upstream/main HEAD -- <submodule_path>` is empty when it does."""
    upstream_still_references_submodule: bool = True
    """Whether upstream's tree still contains the submodule path at all:
    `git ls-tree upstream/main -- <submodule_path>` is non-empty when it does."""

    # Discriminators for the dirty-tree intent (#189, ADR-0027).
    dirty_files: list[str] = []
    """Tracked files with uncommitted changes, staged or not: `git diff --name-only HEAD`."""
    untracked_upstream_collisions: list[str] = []
    """Untracked files at a path upstream's tree holds: `git ls-files --others
    --exclude-standard`, kept where `git ls-tree -r --name-only upstream/main` lists the
    path. A sync cannot bring upstream's file in without displacing such a file."""

    # Discriminators for the branch-renamed intent (#190). Observed now, rendered by
    # `as_text` only once that intent is registered: see `_NOT_YET_RENDERED`.
    tracked_branch: str = ""
    """The upstream branch the current branch is configured to follow: `git config
    branch.<branch>.merge`, without `refs/heads/`. Empty when it follows none."""
    upstream_default_branch: str = ""
    """The branch upstream calls its default: `git symbolic-ref --short
    refs/remotes/<remote>/HEAD`, without the remote, where `<remote>` is upstream's
    remote. A plain fetch never updates it, but the trusted pre-fetch does (`git
    remote set-head --auto`, #205), and so does an injector that models a fetched
    clone; empty when the clone records none."""
    local_branches: list[str] = []
    """Every local branch: `git for-each-ref --format=%(refname:short) refs/heads/`."""

    @property
    def conflicting_files(self) -> set[str]:
        """Files both sides touched.

        The discriminator that decides merge versus rebase: if the two sides
        changed the same file, replaying local commits on top of upstream would
        discard a resolution someone already made.
        """
        return set(self.local_touched_files) & set(self.upstream_touched_files)

    @property
    def has_local_only_commits(self) -> bool:
        """Whether the local branch is ahead of upstream at all.

        Derived from `upstream_behind` rather than carried as its own field: the
        two are the same measurement, and having two names for one quantity is how
        a fingerprint ends up asserting two contradictory things at once. A count
        rather than a flag because the zero case is the *benign* state -- nothing
        to resolve, so every program must refuse to fire, and a dispatcher that
        always fires can only be caught by states that require refusal.
        """
        return self.upstream_behind > 0

    @classmethod
    def observe(cls, env: Sandbox) -> StateFingerprint:
        """Read the environment into a fingerprint; never mutate it.

        The fields whose docstrings name a command use exactly that command; the
        rest (dirty state, branch, ref lock, submodule reference, remotes) are
        read with the direct git equivalent. The count and touch probes read
        remote-tracking refs, which the fault injector leaves current rather than
        `observe` refreshing them -- fetching here would write to the repo.

        "Upstream" below is `sandbox.upstream_ref(env)`: `upstream/main` in a harness
        sandbox, the derived `<remote>/<branch>` on a checkout (#181), so the field
        docstrings' `upstream/main` is the harness spelling of that ref. A checkout with
        no derivable upstream raises `sandbox.NoUpstreamError` rather than observe
        against a ref that is not its upstream.
        """
        work = env.work

        def out(*args: str) -> str:
            return run_git(args, cwd=work).stdout.strip()

        upstream = upstream_ref(env)
        branch = out("rev-parse", "--abbrev-ref", "HEAD")
        upstream_ahead = int(out("rev-list", "--count", f"HEAD..{upstream}"))
        upstream_behind = int(out("rev-list", "--count", f"{upstream}..HEAD"))
        local_touched = out("diff", "--name-only", f"{upstream}...HEAD").split()
        upstream_touched = out("diff", "--name-only", f"HEAD...{upstream}").split()

        path = submodule_path(env)
        if path is None:
            submodule_initialised = False
            pin_matches = True
            upstream_references = True
        else:
            status = out("submodule", "status", "--", path)
            submodule_initialised = bool(status) and not status.startswith("-")
            pin_matches = (
                run_git(
                    ("diff", "--name-only", upstream, "HEAD", "--", path),
                    cwd=work,
                    check=False,
                ).stdout.strip()
                == ""
            )
            upstream_references = bool(out("ls-tree", upstream, "--", path))

        remote = upstream.split("/", 1)[0]
        default_ref = run_git(
            ("symbolic-ref", "-q", "--short", f"refs/remotes/{remote}/HEAD"), cwd=work, check=False
        ).stdout.strip()
        merge_ref = _config(work, f"branch.{branch}.merge")

        untracked = out("ls-files", "--others", "--exclude-standard").splitlines()
        upstream_paths = set(out("ls-tree", "-r", "--name-only", upstream).splitlines())

        return cls(
            dirty_worktree=bool(out("status", "--porcelain")),
            branch=branch,
            upstream_ahead=upstream_ahead,
            upstream_behind=upstream_behind,
            has_locked_branch=_has_locked_branch(work, branch),
            has_submodule_reference=any(
                line.startswith("160000 ") for line in out("ls-tree", "-r", "HEAD").splitlines()
            ),
            remotes=out("remote").split(),
            local_touched_files=local_touched,
            upstream_touched_files=upstream_touched,
            submodule_initialised=submodule_initialised,
            submodule_pin_matches_upstream=pin_matches,
            upstream_still_references_submodule=upstream_references,
            dirty_files=sorted(out("diff", "--name-only", "HEAD").splitlines()),
            untracked_upstream_collisions=sorted(p for p in untracked if p in upstream_paths),
            tracked_branch=merge_ref.removeprefix("refs/heads/"),
            upstream_default_branch=default_ref.removeprefix(f"{remote}/"),
            local_branches=sorted(
                out("for-each-ref", "--format=%(refname:short)", "refs/heads/").splitlines()
            ),
        )

    def as_text(self) -> str:
        """The fingerprint as stable, readable text -- arm 2's whole view of state.

        This is part of arm 2's definition, not a formatting convenience: the arm
        sees the environment only as these words. Field order is the declaration
        order above, every time, so two renders of one state are byte-identical
        and a lexical score cannot depend on iteration order; field names are
        included because they are the words that carry the meaning ("dirty",
        "upstream", "submodule").

        Nothing outside the fingerprint is read. No probe is run and no git
        command is issued, and no derived probe result is added: arm 2's real
        blindness is that it cannot *evaluate* this text, so handing it a probe's
        verdict would give it arm 3's mechanism and reduce the ablation to one
        signal compared with itself.
        """
        return "\n".join(
            f"{name}: {_render(getattr(self, name))}"
            for name in type(self).model_fields
            if name not in _NOT_YET_RENDERED
        )


class TaskSignature(BaseModel):
    """A request plus the state it arrived in."""

    intent: str
    """The user-facing request, e.g. 'sync this fork with upstream'."""
    fingerprint: StateFingerprint
    target: str
    """Environment identity, e.g. the sandbox path. Never a real repo in phase 1."""
