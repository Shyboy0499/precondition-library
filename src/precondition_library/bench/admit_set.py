"""The build's admit set: one episode per declared resolution, asking for it (ADR-0032).

The primary claim may be worded as a win over text similarity only when arm 2 is a usable
baseline (spec §7 item 11): each intent's library must offer it at least two resolutions
to choose between. Built from `SMOKE_SEEDS` with the fault's own request, it never did.
The fourth and sixth live runs' libraries held one resolution or none for three intents
of five, and no run could measure the floor. The reason is structural:

* **The agent picks a resolution the state accepts, and most states accept several.**
  Every `diverged` state accepts both `merge` and `rebase`; two `dirty_tree` states accept
  all three resolutions. Given a request that names no resolution, the agent took
  `rebase` in all eight `diverged` build episodes of both runs, and `stash` for
  `dirty_tree`.
* **Only some resolutions have a state that forces them.** No `diverged` state accepts a
  single resolution, so no choice of seeds alone yields two.

So each episode here covers one resolution, at a seed whose state is labelled with it --
the state where it is the only acceptable one, where one exists -- and its request is the
fault's own phrasing followed by a directive asking for that resolution in a user's words.
The directives are build-only. Every measured request (`IntentSpec.phrasings` and
`variant_phrasings`, whose tests forbid naming a resolution) is untouched, and the
dispatch arms never read a build request. A build request that names its resolution only
makes the compiled program's text say what it does, which helps arm 2, the baseline.

The table is registered: `tests/test_admit_set.py` pins that it covers every resolution of
every measured intent once, that each seed's state is labelled with its resolution and,
where a state accepts that resolution alone, is such a state, and that no seed falls in the
tune or eval blocks.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..tasks.faults import FAULTS


@dataclass(frozen=True)
class AdmitEpisode:
    """One build episode: the seed whose state calls for `resolution`, and the request."""

    seed: int
    resolution: str
    directive: str
    """How the request asks for the resolution, after the fault's own phrasing."""


ADMIT_SET: dict[str, tuple[AdmitEpisode, ...]] = {
    "diverged": (
        AdmitEpisode(
            1, "discard", "My local commits can go: make my branch match upstream exactly."
        ),
        AdmitEpisode(
            2, "rebase", "Replay my local commits on top of upstream so the history stays linear."
        ),
        AdmitEpisode(0, "merge", "Merge upstream into my branch and keep both histories."),
    ),
    "submodule_moved": (
        AdmitEpisode(0, "remove", "Remove the nested checkout, the way upstream did."),
        AdmitEpisode(4, "init", "Initialise the nested repository and check it out."),
        AdmitEpisode(
            1, "repin", "Check the nested repository out at the commit upstream now pins."
        ),
    ),
    "dirty_tree": (
        AdmitEpisode(
            5, "stash", "Stash my uncommitted work, update the branch, then put my work back."
        ),
        AdmitEpisode(
            0, "commit", "Commit my uncommitted work first, then bring the branch up to date."
        ),
        AdmitEpisode(
            2,
            "aside",
            "Keep my unsaved file beside upstream's version, as `<name>.local`, and update.",
        ),
    ),
    "branch_renamed": (
        AdmitEpisode(0, "rename", "Rename my branch to upstream's new name and track it."),
        AdmitEpisode(
            6,
            "retrack",
            "Keep my branch's name, point its tracking at upstream's new branch and catch up.",
        ),
        AdmitEpisode(1, "merge", "Track upstream's new branch and merge it into my own commits."),
    ),
    "lockfile_conflict": (
        AdmitEpisode(
            5,
            "take_upstream",
            "Start from upstream's dependency file and add back what I added.",
        ),
        AdmitEpisode(
            2,
            "keep_local",
            "Keep my dependency file, with what I removed still removed, and add what "
            "upstream added.",
        ),
    ),
}
"""Each measured fault's build episodes, one per declared resolution (ADR-0032)."""


def admit_request(fault: str, episode: AdmitEpisode) -> str:
    """The build request for `episode`: the fault's own phrasing, then the directive."""
    return f"{FAULTS[fault].task_text(episode.seed)} {episode.directive}"


def admit_seeds(fault: str) -> tuple[int, ...]:
    """The seeds `fault`'s admit episodes build, in table order."""
    return tuple(episode.seed for episode in ADMIT_SET[fault])
