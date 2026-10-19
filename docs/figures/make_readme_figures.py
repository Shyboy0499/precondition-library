"""Draw the README's two figures from the committed results, in light and dark.

Every number is read from `results/`; nothing is typed in. Run from the repository root:

    python docs/figures/make_readme_figures.py

It writes `docs/figures/{primary,heldout}-{light,dark}.svg`. The SVGs carry no date and use
a fixed hash salt, so a rerun on the same results and matplotlib version is byte-identical.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from precondition_library.tasks.faults.dirty_tree import paths_for_seed  # noqa: E402
from precondition_library.tasks.faults.lockfile_conflict import lock_path_for_seed  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNS = ("run-11", "run-12", "run-13")

# Neutral chrome plus one accent, in light and dark steps. The accent and the de-emphasis gray
# stay apart under every colour-vision-deficiency simulation, and both clear 3:1 on the surface.
THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "accent": "#2a78d6",
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#f0efec",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "accent": "#3987e5",
    },
}


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """The 95% Wilson interval for `k` of `n`, the interval every result file reports."""
    p = k / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denominator = 1 + z * z / n
    return (centre - half) / denominator, (centre + half) / denominator


@dataclass(frozen=True)
class Rate:
    k: int
    n: int

    @property
    def value(self) -> float:
        return self.k / self.n


_ARM3 = re.compile(
    r"arm 3 \(pre-registered coverage point\): coverage \d+/\d+, mismatch (\d+)/(\d+)"
)
_ARM2 = re.compile(r"at matched coverage arm 2 \(threshold [^)]*\) has mismatch (\d+)/(\d+)")


def _primary(path: Path) -> tuple[Rate, Rate]:
    text = path.read_text(encoding="utf-8")
    arm3, arm2 = _ARM3.search(text), _ARM2.search(text)
    if arm3 is None or arm2 is None:
        raise ValueError(f"{path}: no arm 3 point or matched arm 2 point")
    return Rate(int(arm3[1]), int(arm3[2])), Rate(int(arm2[1]), int(arm2[2]))


def primary_rows() -> list[tuple[str, list[Rate]]]:
    """Mis-fire rate at matched coverage, per replicate, for arm 3 and each text scorer."""
    base = ROOT / "results/replicates-2026-10-05"
    sources = {
        "text: lexical": "primary/primary.txt",
        "text: embedding": "rescore-embedding/primary/primary.txt",
        "text: reranker": "rescore-cross-encoder/primary/primary.txt",
    }
    arm3 = [_primary(base / run / sources["text: lexical"])[0] for run in RUNS]
    rows = [("precondition checks (arm 3)", arm3)]
    for name, rel in sources.items():
        rows.append((name, [_primary(base / run / rel)[1] for run in RUNS]))
    return rows


def _summed(paths: list[Path]) -> Rate:
    fires = wrong = 0
    for path in paths:
        summary = json.loads(path.read_text(encoding="utf-8"))
        fires += summary["arm3_fires"]
        wrong += summary["arm3_wrong"]
    return Rate(wrong, fires)


def heldout_rows() -> list[tuple[str, Rate, str]]:
    """Arm 3's mis-fire rate per held-out source, summed over the three libraries."""
    results = ROOT / "results"
    dirty = [
        results / "heldout-2026-10-16/dirty_tree/run-11/summary.json",
        results / "heldout-2026-10-10/run-12/summary.json",
        results / "heldout-2026-10-16/dirty_tree/run-13/summary.json",
    ]
    diverged = [results / f"heldout-2026-10-16/diverged/{run}/summary.json" for run in RUNS]
    lock = [results / f"heldout-2026-10-18/lockfile_conflict/{run}/summary.json" for run in RUNS]
    names = [results / f"heldout-2026-10-19/branch_renamed/{run}/summary.json" for run in RUNS]
    submodules = [
        results / f"heldout-2026-10-19/submodule_moved/{run}/summary.json" for run in RUNS
    ]
    arm3 = primary_rows()[0][1]
    in_distribution = Rate(sum(rate.k for rate in arm3), sum(rate.n for rate in arm3))

    def dirty_paths(seed: int) -> list[str]:
        paths = paths_for_seed(seed)
        return [paths.upstream_file, paths.tracked_file, paths.untracked_path]

    return [
        ("in distribution (the five git faults)", in_distribution, ""),
        ("held out: dirty_tree, new paths", _summed(dirty), _awkward_share(dirty, dirty_paths)),
        ("held out: diverged, new shape", _summed(diverged), ""),
        ("held out: branch_renamed, new names", _summed(names), ""),
        ("held out: submodule_moved, new paths", _summed(submodules), ""),
        (
            "held out: lockfile_conflict, new paths",
            _summed(lock),
            _awkward_share(lock, lambda seed: [lock_path_for_seed(seed)]),
        ),
    ]


def _awkward(path: str) -> bool:
    return " " in path or not path.isascii()


def _awkward_share(summaries: list[Path], paths_of: Callable[[int], list[str]]) -> str:
    """How many of a block's wrong fires were on a state with a spaced or non-ASCII path."""
    seeds = [
        json.loads(line)["seed"]
        for summary in summaries
        for line in (summary.parent / "wrong_fires.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    awkward = sum(1 for seed in seeds if any(_awkward(path) for path in paths_of(seed)))
    if awkward == len(seeds):
        return f"{'the' if awkward == 1 else 'all'} {awkward} on a spaced or non-ASCII path"
    return f"{awkward} of {len(seeds)} on a spaced or non-ASCII path"


def _style(ax, theme: dict[str, str]) -> None:
    ax.set_facecolor(theme["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme["axis"])
    ax.tick_params(colors=theme["muted"], length=0, labelsize=9)
    ax.xaxis.grid(True, color=theme["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlim(-0.02, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])


def draw_primary(mode: str) -> None:
    theme = THEMES[mode]
    rows = primary_rows()
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=100)
    fig.patch.set_facecolor(theme["surface"])
    _style(ax, theme)
    offsets = (-0.18, 0.0, 0.18)
    for i, (name, rates) in enumerate(rows):
        y = len(rows) - 1 - i
        colour = theme["accent"] if i == 0 else theme["muted"]
        for offset, rate in zip(offsets, rates, strict=True):
            low, high = wilson(rate.k, rate.n)
            ax.plot(
                [low, high],
                [y + offset] * 2,
                color=colour,
                linewidth=2,
                solid_capstyle="round",
                clip_on=False,
            )
            ax.plot(
                rate.value,
                y + offset,
                "o",
                markersize=6,
                color=colour,
                markeredgecolor=theme["surface"],
                markeredgewidth=1.5,
                clip_on=False,
            )
        values = [rate.value for rate in rates]
        label = (
            f"{sum(r.k for r in rates)} of {sum(r.n for r in rates)} fires"
            if i == 0
            else f"{min(values):.0%}–{max(values):.0%}"
        )
        x = max(wilson(r.k, r.n)[1] for r in rates) + 0.03
        ax.text(
            x,
            y,
            label,
            va="center",
            ha="left",
            fontsize=9,
            color=theme["ink"] if i == 0 else theme["ink2"],
        )
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([name for name, _ in reversed(rows)], fontsize=9.5, color=theme["ink"])
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel(
        "mis-fire rate at matched coverage (one dot per replicate, 95% Wilson interval)",
        fontsize=8.5,
        color=theme["muted"],
    )
    fig.suptitle(
        "Which program fires: running checks versus matching text",
        x=0.012,
        ha="left",
        fontsize=11,
        color=theme["ink"],
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _save(fig, f"primary-{mode}.svg")


def draw_heldout(mode: str) -> None:
    theme = THEMES[mode]
    rows = heldout_rows()
    fig, ax = plt.subplots(figsize=(7.2, 3.9), dpi=100)
    fig.patch.set_facecolor(theme["surface"])
    _style(ax, theme)
    for i, (name, rate, note) in enumerate(rows):
        y = len(rows) - 1 - i
        width = max(rate.value, 0.004)
        ax.barh(y, width, height=0.5, color=theme["accent"], linewidth=0)
        value = f"{rate.value:.1%}  ({rate.k} of {rate.n} fires)"
        ax.text(
            width + 0.015,
            y + (0.13 if note else 0),
            value,
            va="center",
            ha="left",
            fontsize=9,
            color=theme["ink"],
        )
        if note:
            ax.text(
                width + 0.015,
                y - 0.2,
                note,
                va="center",
                ha="left",
                fontsize=7.5,
                color=theme["muted"],
            )
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([name for name, _, _ in reversed(rows)], fontsize=9.5, color=theme["ink"])
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel(
        "arm 3's mis-fire rate, summed over the three libraries", fontsize=8.5, color=theme["muted"]
    )
    fig.suptitle(
        "Precondition checks on states no build ever saw",
        x=0.012,
        ha="left",
        fontsize=11,
        color=theme["ink"],
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    _save(fig, f"heldout-{mode}.svg")


def _save(fig, name: str) -> None:
    fig.savefig(OUT / name, format="svg", metadata={"Date": None}, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    plt.rcParams["svg.hashsalt"] = "precondition-library"
    plt.rcParams["font.family"] = "DejaVu Sans"
    for mode in THEMES:
        draw_primary(mode)
        draw_heldout(mode)
    for name, rates in primary_rows():
        print(name, [f"{r.k}/{r.n}" for r in rates])
    for name, rate, note in heldout_rows():
        print(name, f"{rate.k}/{rate.n}", note)


if __name__ == "__main__":
    main()
