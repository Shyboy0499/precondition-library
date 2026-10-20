"""Fault: the app renamed config keys, and a config file still sets an old name.

The first family whose state is not git history (issue #266, ADR-0041). The repository is
still a git working tree, because the runtime's snapshots and guard assume one, but nothing
the request is about lives in commits: the fault, its discriminators and its fix are the
contents of the app's config files.

## The app

A small synthetic app keeps its settings under `config/`, one `key = value` per line:

* `config/renames.conf` -- the app's own migration table, `old = new` per line. It names
  every key the app has renamed, and the app warns while a config file still sets an old name;
* `config/settings.conf` -- the project's settings, tracked;
* `config/local.conf` -- a per-machine override, git-ignored, present only where a user made one.

Like `lockfile_conflict`'s lock-shaped file, this is a **synthetic config convention, not any
real tool's format**, and nothing here should be described as more than that.

## Three live states

Each seed selects one, chosen so that different fixed resolutions are right in different
states, by this checker:

* ``stale_key`` -- `settings.conf` sets an old name and not the new one: rename it, keeping
  its value (`rename`);
* ``both_keys`` -- `settings.conf` sets both names. The app reads the new one, so the old line
  is dead: delete it, keeping the new value (`drop_old`). Renaming instead leaves the key set
  twice, and keeps whichever value a reader happens to take;
* ``local_override`` -- `settings.conf` is already migrated; the old name is in the ignored
  `local.conf`. Rename it there and leave the file ignored and uncommitted (`migrate_local`).
  Editing `settings.conf` fixes nothing, and committing `local.conf` publishes a machine's
  private settings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ...sandbox import Sandbox, record_base, run_git
from ...signatures import CONFIG_DIR, RENAMES_FILE, StateFingerprint, config_assignments
from ..intent import IntentSpec, ResolutionVariant, draw_index, sample_index
from ..spec import FaultSpec, GroundTruth

SETTINGS_FILE = f"{CONFIG_DIR}/settings.conf"
LOCAL_FILE = f"{CONFIG_DIR}/local.conf"
_GITIGNORE = ".gitignore"

RENAMES: tuple[tuple[str, str], ...] = (
    ("timeout_s", "request_timeout_s"),
    ("retries", "max_retries"),
    ("log", "log_level"),
    ("cache_dir", "cache_path"),
)
"""The app's whole rename table, written to `config/renames.conf` in every state. A seed's
stale key is one of these pairs; the others are listed and set nowhere under the old name."""

INJECTED_STATES = ("stale_key", "both_keys", "local_override")
_STATE_SALT = "config_renamed:state"
"""Appending a state would change which state an existing seed injects; add deliberately."""

STATE_VARIANT = {
    "stale_key": "rename",
    "both_keys": "drop_old",
    "local_override": "migrate_local",
}
"""Which resolution each injected state is labelled with; what `INTENT`'s rules decide."""


# --- Tier 1 instance axes (ADR-0005) ---------------------------------------------
#
#   key      which pair of `RENAMES` the stale setting uses. Every program can read the
#            table, so a program that hard-codes the key it learned on is what this axis
#            exposes; no key moves a state across a rule, so no draw relabels.
#   content  the values every setting holds. A value never decides anything.
#
# Not drawn: file paths (Tier 2), the number of stale keys (Tier 3).


@dataclass(frozen=True)
class _Flavour:
    """One drawn `content` value: the value of each key, by its new name."""

    values: Mapping[str, str]
    old_value: str
    """On `both_keys`, the stale value the old name still carries; the new name keeps its own."""


_FLAVOURS: tuple[_Flavour, ...] = (
    _Flavour(
        {
            "request_timeout_s": "30",
            "max_retries": "3",
            "log_level": "info",
            "cache_path": "/var/cache/app",
        },
        "10",
    ),
    _Flavour(
        {
            "request_timeout_s": "45",
            "max_retries": "5",
            "log_level": "warn",
            "cache_path": "/tmp/app-cache",
        },
        "15",
    ),
    _Flavour(
        {
            "request_timeout_s": "60",
            "max_retries": "2",
            "log_level": "debug",
            "cache_path": ".cache",
        },
        "5",
    ),
    _Flavour(
        {
            "request_timeout_s": "20",
            "max_retries": "4",
            "log_level": "error",
            "cache_path": "/srv/cache",
        },
        "90",
    ),
)

AXES: Mapping[str, tuple[str, ...]] = {
    "key": tuple(old for old, _ in RENAMES),
    "content": tuple(str(index) for index in range(len(_FLAVOURS))),
}
"""The Tier 1 axes this fault draws, with the values each may take."""

AXES_BY_RESOLUTION: Mapping[str, tuple[str, ...]] = {
    "rename": ("key", "content"),
    "drop_old": ("key", "content"),
    "migrate_local": ("key", "content"),
}
"""Which axes may vary for each resolution: both, for all three."""

_LOCAL_NOTE = ("local_note", "set on this machine only")
"""A setting `local.conf` always carries besides the stale key, so the file is not just the key."""


def state_for_seed(seed: int) -> str:
    """Which live state this seed injects. Deterministic."""
    return INJECTED_STATES[sample_index(seed, _STATE_SALT, len(INJECTED_STATES))]


@dataclass(frozen=True)
class Draw:
    """Everything one seed's instance draw decides, for `inject` and identity."""

    state: str
    resolution: str
    key: int
    content: int

    @property
    def old(self) -> str:
        return RENAMES[self.key][0]

    @property
    def new(self) -> str:
        return RENAMES[self.key][1]

    @property
    def identity(self) -> str:
        return f"config_renamed/{self.resolution}/key={self.old}/content={self.content}"

    @property
    def axes(self) -> Mapping[str, str]:
        drawn = {"key": self.old, "content": str(self.content)}
        return {axis: drawn[axis] for axis in AXES_BY_RESOLUTION[self.resolution]}


def draw_for_seed(seed: int) -> Draw:
    """The Tier 1 draw for `seed`: state, the stale key and the content flavour.

    Each axis uses `draw_index` under its own salt, independent of the state selection, so
    which resolution a seed needs stays a function of the seed alone (ADR-0005).
    """
    state = state_for_seed(seed)
    return Draw(
        state=state,
        resolution=STATE_VARIANT[state],
        key=draw_index(seed, "config_renamed", "key", len(RENAMES)),
        content=draw_index(seed, "config_renamed", "content", len(_FLAVOURS)),
    )


def _lines(pairs: list[tuple[str, str]]) -> str:
    return "".join(f"{key} = {value}\n" for key, value in pairs)


def _renames_text() -> str:
    return "# keys the app has renamed: old = new\n" + _lines(list(RENAMES))


@dataclass(frozen=True)
class _Layout:
    """The text each config file holds in one state, and what a correct fix leaves."""

    settings: str
    local: str | None
    target: str
    """The file the stale key is in, and so the file a fix must edit."""
    expected_value: str
    """The value the new name must carry once the file is fixed."""
    other_lines: tuple[tuple[str, str], ...]
    """Every other setting in the target file, which a fix must leave exactly as it was."""


def layout_for_seed(seed: int) -> _Layout:
    """The config tree `inject` writes at `seed`, and what its checker expects of a fix."""
    draw = draw_for_seed(seed)
    flavour = _FLAVOURS[draw.content]
    migrated = [(new, flavour.values[new]) for _, new in RENAMES]
    if draw.state == "stale_key":
        settings = [(draw.old if key == draw.new else key, value) for key, value in migrated]
        others = tuple(pair for pair in migrated if pair[0] != draw.new)
        return _Layout(_lines(settings), None, SETTINGS_FILE, flavour.values[draw.new], others)
    if draw.state == "both_keys":
        settings = [*migrated, (draw.old, flavour.old_value)]
        others = tuple(pair for pair in migrated if pair[0] != draw.new)
        return _Layout(_lines(settings), None, SETTINGS_FILE, flavour.values[draw.new], others)
    return _Layout(
        _lines(migrated),
        _lines([(draw.old, flavour.old_value), _LOCAL_NOTE]),
        LOCAL_FILE,
        flavour.old_value,
        (_LOCAL_NOTE,),
    )


# --- the intent (#266), registered in `tasks.registry` (ADR-0041) ---------------
#
# Its acceptable sets are pinned against `check` by replay
# (`tests/test_config_renamed_intent.py`).


def has_stale_config(state: StateFingerprint) -> bool:
    """The family's situation: some config file still sets a renamed key."""
    return bool(state.config_stale_keys)


def _in_an_ignored_file(state: StateFingerprint, entry: str) -> bool:
    """Whether a `config_stale_keys` entry (`<file>: <old> -> <new>`) is in an ignored file.

    Matched by prefix rather than split on `: `, so a file name holding `: ` is not misread.
    """
    return any(entry.startswith(f"{name}: ") for name in state.config_ignored_files)


# Each rule holds only when one resolution fixes *every* stale entry: a checkout that mixes
# them -- one file renamed, another setting both names -- has no fixed resolution, and is
# left unlabelled rather than given one that fixes part of it.


def _needs_rename(s: StateFingerprint) -> bool:
    """Every stale key is in a file git does not ignore, set under its old name only."""
    return (
        has_stale_config(s)
        and not s.config_keys_set_twice
        and not any(_in_an_ignored_file(s, entry) for entry in s.config_stale_keys)
    )


def _needs_drop_old(s: StateFingerprint) -> bool:
    """Every stale key is in a file git does not ignore, set under both names."""
    return (
        has_stale_config(s)
        and set(s.config_stale_keys) == set(s.config_keys_set_twice)
        and not any(_in_an_ignored_file(s, entry) for entry in s.config_stale_keys)
    )


def _needs_migrate_local(s: StateFingerprint) -> bool:
    """Every stale key is in an ignored file, set under its old name only."""
    return (
        has_stale_config(s)
        and not s.config_keys_set_twice
        and all(_in_an_ignored_file(s, entry) for entry in s.config_stale_keys)
    )


VARIANTS = [
    ResolutionVariant(
        id="rename",
        decided_by=_needs_rename,
        accepted_by=_needs_rename,
        rationale=(
            "The project's settings set an old key name and not the new one, so the key is "
            "renamed where it stands and keeps its value."
        ),
    ),
    ResolutionVariant(
        id="drop_old",
        decided_by=_needs_drop_old,
        accepted_by=_needs_drop_old,
        rationale=(
            "The settings set both names and the app reads the new one, so the old line is "
            "dead: it is deleted and the new value stays."
        ),
    ),
    ResolutionVariant(
        id="migrate_local",
        decided_by=_needs_migrate_local,
        accepted_by=_needs_migrate_local,
        rationale=(
            "The project's settings are already current; the old name is in this machine's "
            "ignored override, so it is renamed there and the file stays private."
        ),
    ),
]

INTENT = IntentSpec(
    name="update_renamed_config_keys",
    fault="config_renamed",
    phrasings=[
        "The app keeps warning that my config uses old setting names. Make the warning go away "
        "without changing what the settings do.",
        "Bring my configuration up to date with the setting names the app uses now.",
        "Startup logs a deprecation warning about a config key. Fix the config.",
        "Some setting in my config has been renamed upstream. Sort the config out.",
        "Clean up the outdated config keys the app complains about, and keep my values.",
        "The app says a configuration key is deprecated. Update the config so it stops.",
        "Migrate my settings to the current key names.",
        "Fix the stale config entry the app is warning about, without losing any setting.",
    ],
    naming_markers=["rename", "renamed"],
    variants=VARIANTS,
    variant_phrasings={
        "rename": ["the old name is in the project's settings, and the new one is not there yet"],
        "drop_old": ["the settings already have the new name as well as the old one"],
        "migrate_local": ["the old name is only in my machine's own override file"],
    },
)


def _read(path: Path) -> str | None:
    """A config file's text, or None where a fix left no readable file there.

    A deleted, replaced-by-a-directory or undecodable file is a failed fix, so the checker
    grades it rather than raising, which would drop the episode as invalid.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


class ConfigRenamedFault(FaultSpec):
    name = "config_renamed"
    description = "The app renamed config keys and a config file still sets an old name"
    # The tracked config tree the injector commits. `local.conf` is never committed: a fix
    # that commits it publishes a machine's private settings, which the checker refuses.
    change_surface = (_GITIGNORE, RENAMES_FILE, SETTINGS_FILE)

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Commit the app's config tree, with the stale key where this seed's state puts it.

        The rename table, the settings and a `.gitignore` naming `config/local.conf` are one
        commit, made locally and pushed, so upstream and the clone agree and there is nothing
        to sync: the fault is in the files, not in the history. On `local_override` the
        ignored `local.conf` is written last and never added. Deterministic in the seed.
        """
        work = sandbox.work
        record_base(sandbox, fault="config_renamed")
        layout = layout_for_seed(seed)
        (work / CONFIG_DIR).mkdir(exist_ok=True)
        (work / RENAMES_FILE).write_text(_renames_text(), encoding="utf-8")
        (work / SETTINGS_FILE).write_text(layout.settings, encoding="utf-8")
        (work / _GITIGNORE).write_text(f"{LOCAL_FILE}\n", encoding="utf-8")
        run_git(("add", _GITIGNORE, RENAMES_FILE, SETTINGS_FILE), cwd=work)
        run_git(("commit", "-q", "-m", "chore: app configuration"), cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)
        run_git(("fetch", "-q", "upstream"), cwd=work)
        if layout.local is not None:
            (work / LOCAL_FILE).write_text(layout.local, encoding="utf-8")

        draw = draw_for_seed(seed)
        sandbox.recorded["config-target"] = layout.target
        sandbox.recorded["config-old"] = draw.old
        sandbox.recorded["config-new"] = draw.new
        sandbox.recorded["config-value"] = layout.expected_value
        sandbox.recorded["config-others"] = _lines(list(layout.other_lines))
        sandbox.recorded["config-settings"] = layout.settings
        sandbox.recorded["config-state"] = draw.state

    def task_text(self, seed: int) -> str:
        return INTENT.task_text(seed)

    def state_for_seed(self, seed: int) -> str:
        return state_for_seed(seed)

    def variant_for_seed(self, seed: int) -> str:
        """The resolution `state_for_seed` makes correct at `seed` (`STATE_VARIANT`)."""
        return STATE_VARIANT[state_for_seed(seed)]

    def instance_for_seed(self, seed: int) -> str:
        return draw_for_seed(seed).identity

    def axes_for_resolution(self, resolution: str) -> Mapping[str, tuple[str, ...]]:
        if resolution not in AXES_BY_RESOLUTION:
            raise KeyError(f"config_renamed declares no resolution {resolution!r}")
        return {name: AXES[name] for name in AXES_BY_RESOLUTION[resolution]}

    def drawn_axes_for_seed(self, seed: int) -> Mapping[str, str]:
        return draw_for_seed(seed).axes

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the config tree, in five clauses, all read from the files.

        First, the rename table and `.gitignore` are as the app shipped them: deleting a row
        of the table silences the warning without fixing anything. Second, no config file
        sets any renamed key's old name. Third, the file the stale key was in sets the new
        name exactly once, to the value it must keep: the old value on `stale_key` and
        `local_override`, the new one on `both_keys`. Fourth, every other setting in that file
        is unchanged. Fifth, on `local_override`, `local.conf` is still there and still not
        tracked, and `settings.conf` is untouched.
        """
        work = sandbox.work
        if _read(work / RENAMES_FILE) != _renames_text():
            return GroundTruth(ok=False, detail=f"{RENAMES_FILE} was changed")
        if _read(work / _GITIGNORE) != f"{LOCAL_FILE}\n":
            return GroundTruth(ok=False, detail=f"{_GITIGNORE} was changed")

        olds = {old for old, _ in RENAMES}
        for path in sorted((work / CONFIG_DIR).glob("*.conf")):
            relative = f"{CONFIG_DIR}/{path.name}"
            if relative == RENAMES_FILE:
                continue
            text = _read(path)
            if text is None:
                return GroundTruth(ok=False, detail=f"{relative} is not a readable config file")
            stale = olds & {key for key, _ in config_assignments(text)}
            if stale:
                return GroundTruth(
                    ok=False, detail=f"{relative} still sets {', '.join(sorted(stale))}"
                )

        target = sandbox.recorded["config-target"]
        new = sandbox.recorded["config-new"]
        target_text = _read(work / target)
        if target_text is None:
            return GroundTruth(ok=False, detail=f"{target} is gone")
        pairs = config_assignments(target_text)
        values = [value for key, value in pairs if key == new]
        if len(values) != 1:
            return GroundTruth(
                ok=False, detail=f"{target} sets {new} {len(values)} times, not once"
            )
        if values[0] != sandbox.recorded["config-value"]:
            return GroundTruth(
                ok=False,
                detail=f"{target} sets {new} = {values[0]}, not the value it must keep",
            )
        others = sorted(pair for pair in pairs if pair[0] != new)
        if others != sorted(config_assignments(sandbox.recorded["config-others"])):
            return GroundTruth(ok=False, detail=f"other settings in {target} were changed")

        if sandbox.recorded["config-state"] == "local_override":
            tracked = run_git(
                ("ls-files", "--error-unmatch", "--", LOCAL_FILE), cwd=work, check=False
            )
            if tracked.returncode == 0:
                return GroundTruth(
                    ok=False, detail=f"{LOCAL_FILE} is tracked: a machine's override was committed"
                )
            if _read(work / SETTINGS_FILE) != sandbox.recorded["config-settings"]:
                return GroundTruth(
                    ok=False, detail=f"{SETTINGS_FILE} was changed; it was already current"
                )

        return GroundTruth(
            ok=True,
            detail=f"no config file sets a renamed key, and {target} sets {new} once, as it must",
        )


SPEC = ConfigRenamedFault()
