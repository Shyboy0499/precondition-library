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

import tempfile
from pathlib import Path

from pydantic import BaseModel

from .sandbox import Sandbox, git_config, run_git, submodule_path, upstream_ref


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


CONFIG_DIR = "config"
RENAMES_FILE = "config/renames.conf"
"""The app's key-rename table (ADR-0041): one `old = new` per line."""

_CONFIG_FIELDS = frozenset({"config_stale_keys", "config_keys_set_twice", "config_ignored_files"})
"""Fields `as_text` renders only when set. Every state before ADR-0041 has none of them, so
leaving them out when empty keeps each such state's text, and every arm-2 figure taken from it,
byte for byte what it was."""


def config_assignments(text: str) -> list[tuple[str, str]]:
    """The `key = value` lines of a config file, in order; comments and blank lines skipped."""
    pairs = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        pairs.append((key.strip(), value.strip()))
    return pairs


def _config_tree(work: Path) -> tuple[list[str], list[str], list[str]]:
    """Stale keys, keys set under both names, and ignored config files, as the fields hold them."""
    renames_path = work / RENAMES_FILE
    if not renames_path.is_file():
        return [], [], []
    # Observing must not fail on a checkout's own files: an undecodable byte is replaced,
    # and every other key still reads.
    renames = dict(config_assignments(renames_path.read_text(encoding="utf-8", errors="replace")))
    stale: list[str] = []
    twice: list[str] = []
    for path in sorted((work / CONFIG_DIR).glob("*.conf")):
        relative = f"{CONFIG_DIR}/{path.name}"
        if relative == RENAMES_FILE or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        keys = {key for key, _ in config_assignments(text)}
        for old, new in sorted(renames.items()):
            if old in keys:
                stale.append(f"{relative}: {old} -> {new}")
                if new in keys:
                    twice.append(f"{relative}: {old} -> {new}")
    ignored = run_git(
        ("ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", CONFIG_DIR),
        cwd=work,
    ).stdout
    return stale, twice, sorted(name for name in ignored.split("\0") if name)


class _ThreeWay:
    """One file's three versions -- merge base, local, upstream -- read without writing.

    Each is read with `git show <commit>:<path>`; a side that does not have the file
    reads as empty. The merge is tried with `git merge-file -p` on copies in a temporary
    directory outside the repository, so observing never writes to it.
    """

    def __init__(self, work: Path, path: str, base: str, upstream: str) -> None:
        def blob(commit: str) -> str:
            shown = run_git(("show", f"{commit}:{path}"), cwd=work, check=False)
            return shown.stdout if shown.returncode == 0 else ""

        self.base, self.local, self.upstream = blob(base), blob("HEAD"), blob(upstream)
        self._work = work

    def conflicts(self) -> bool:
        with tempfile.TemporaryDirectory() as scratch:
            names = []
            for name, text in (("local", self.local), ("base", self.base), ("up", self.upstream)):
                target = Path(scratch) / name
                target.write_text(text, encoding="utf-8")
                names.append(str(target))
            merged = run_git(("merge-file", "-p", "-q", *names), cwd=self._work, check=False)
        return merged.returncode != 0

    def dropped_by(self, side: str) -> list[str]:
        """Base lines `side` removed that the other side still has.

        A line both sides changed -- a version bump, say -- is in neither side's text,
        so it is not counted as dropped by either: only a real removal is.
        """
        base = set(self.base.splitlines())
        dropper, keeper = (
            (self.upstream, self.local) if side == "upstream" else (self.local, self.upstream)
        )
        return sorted((base - set(dropper.splitlines())) & set(keeper.splitlines()))


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

    # Discriminators for the branch-renamed intent (#190, ADR-0028).
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

    # Discriminators for the lock-conflict intent (#191, ADR-0029).
    merge_conflicted_files: list[str] = []
    """Files both sides changed whose three-way merge conflicts: `git merge-file -p` on the
    merge base's, HEAD's and upstream's versions, tried outside the repository."""
    upstream_dropped_lines: list[str] = []
    """In those files, lines of the merge base upstream removed and the local side kept."""
    local_dropped_lines: list[str] = []
    """In those files, lines of the merge base the local side removed and upstream kept."""

    # Discriminators for the renamed-config-key intent (#266, ADR-0041). Read from files, not
    # from git history: the app keeps its key renames in `config/renames.conf`, one `old = new`
    # per line, and its settings in the other `config/*.conf` files, one `key = value` per line.
    config_stale_keys: list[str] = []
    """Each renamed key a config file still sets, as `<path>: <old> -> <new>`, over every
    `config/*.conf` but the renames table, tracked or not."""
    config_keys_set_twice: list[str] = []
    """Of those, each whose file sets the new name too, in the same form."""
    config_ignored_files: list[str] = []
    """Config files git ignores:
    `git ls-files --others --ignored --exclude-standard -z -- config`."""

    @property
    def conflicting_files(self) -> set[str]:
        """Files both sides touched.

        The discriminator that decides merge versus rebase: if the two sides
        changed the same file, replaying local commits on top of upstream would
        discard a resolution someone already made.
        """
        return set(self.local_touched_files) & set(self.upstream_touched_files)

    @property
    def follows_a_renamed_branch(self) -> bool:
        """Whether the current branch follows a branch upstream no longer calls its default.

        Both names must be known: a clone that records no upstream default -- every
        state no rename touched -- is not in this situation, whatever it tracks. Every
        intent whose resolutions leave the branch wiring alone must refuse such a state:
        syncing against the new name while still following the old one passes no
        checker (#190).
        """
        return bool(
            self.tracked_branch
            and self.upstream_default_branch
            and self.tracked_branch != self.upstream_default_branch
        )

    @property
    def sync_would_conflict(self) -> bool:
        """Whether both sides committed and a three-way merge conflicts in some file.

        Every intent whose resolutions sync commits by merging or rebasing must refuse
        such a state: a plain merge stops on the conflict, and a marker left in a file
        passes no checker (#191).
        """
        return (
            bool(self.merge_conflicted_files)
            and self.upstream_ahead > 0
            and self.upstream_behind > 0
        )

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

        def paths(*args: str) -> list[str]:
            # NUL-separated, so each path is git's raw name. Without `-z` git escapes a
            # non-ASCII name as a quoted octal string, which then names no file: the
            # three-way read below shows nothing for it, and a conflict there goes unseen
            # (ADR-0039). Every shipped path is plain ASCII, so no shipped fingerprint moves.
            return [path for path in run_git((*args, "-z"), cwd=work).stdout.split("\0") if path]

        upstream = upstream_ref(env)
        branch = out("rev-parse", "--abbrev-ref", "HEAD")
        upstream_ahead = int(out("rev-list", "--count", f"HEAD..{upstream}"))
        upstream_behind = int(out("rev-list", "--count", f"{upstream}..HEAD"))
        # One entry per path, never split on whitespace: a path may contain a space, and
        # splitting one into two entries makes `dirty_files` and `upstream_touched_files`
        # disagree about the same file -- the `same_file` state then reads as `disjoint`, and
        # `build_sandbox` refuses the build as mislabelled. Found by the held-out path axis
        # (#263), whose pool varies paths precisely so this cannot stay invisible; every
        # shipped state's paths are space-free, so no shipped fingerprint moves.
        local_touched = paths("diff", "--name-only", f"{upstream}...HEAD")
        upstream_touched = paths("diff", "--name-only", f"HEAD...{upstream}")

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
        merge_ref = git_config(work, f"branch.{branch}.merge") or ""

        untracked = paths("ls-files", "--others", "--exclude-standard")
        upstream_paths = set(paths("ls-tree", "-r", "--name-only", upstream))

        conflicted: list[_ThreeWay] = []
        conflicted_names: list[str] = []
        both_changed = sorted(set(local_touched) & set(upstream_touched))
        merge_base = run_git(("merge-base", "HEAD", upstream), cwd=work, check=False)
        if both_changed and merge_base.returncode == 0:
            for path in both_changed:
                three = _ThreeWay(work, path, merge_base.stdout.strip(), upstream)
                if three.conflicts():
                    conflicted.append(three)
                    conflicted_names.append(path)

        config_stale, config_twice, config_ignored = _config_tree(work)

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
            dirty_files=sorted(paths("diff", "--name-only", "HEAD")),
            untracked_upstream_collisions=sorted(p for p in untracked if p in upstream_paths),
            tracked_branch=merge_ref.removeprefix("refs/heads/"),
            upstream_default_branch=default_ref.removeprefix(f"{remote}/"),
            local_branches=sorted(
                out("for-each-ref", "--format=%(refname:short)", "refs/heads/").splitlines()
            ),
            merge_conflicted_files=conflicted_names,
            upstream_dropped_lines=sorted(
                {line for three in conflicted for line in three.dropped_by("upstream")}
            ),
            local_dropped_lines=sorted(
                {line for three in conflicted for line in three.dropped_by("local")}
            ),
            config_stale_keys=config_stale,
            config_keys_set_twice=config_twice,
            config_ignored_files=config_ignored,
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

        The config fields (`_CONFIG_FIELDS`) are rendered only when set, so a state with no
        config tree reads exactly as it did before they existed (ADR-0041).
        """
        return "\n".join(
            f"{name}: {_render(getattr(self, name))}"
            for name in type(self).model_fields
            if name not in _CONFIG_FIELDS or getattr(self, name)
        )


class TaskSignature(BaseModel):
    """A request plus the state it arrived in."""

    intent: str
    """The user-facing request, e.g. 'sync this fork with upstream'."""
    fingerprint: StateFingerprint
    target: str
    """Environment identity, e.g. the sandbox path. Never a real repo in phase 1."""
