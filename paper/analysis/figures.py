"""The report's figures, drawn from committed result files and `power.json`; nothing typed in.

    python paper/analysis/figures.py --out paper/figures

Each series has its own marker or line style as well as its colour, so the figures read in
grayscale print and for colour-blind readers.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REPLICATES = ROOT / "results" / "replicates-2026-10-05"
STAGE_B = ROOT / "results" / "real-merges-2026-10-26" / "stage-B"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, MUTED = "#0b0b0b", "#52514e"

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 8,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#e4e3df",
        "grid.linewidth": 0.5,
        "legend.frameon": False,
        "pdf.fonttype": 42,
    }
)


def _curve(path: Path) -> tuple[list[tuple[float, float]], tuple[float, float, float, float]]:
    """Arm 2's operating points (coverage, mismatch), and arm 3's point with its interval."""
    points, arm3 = [], None
    with path.open(encoding="utf-8") as rows:
        for row in csv.DictReader(rows):
            if row["mismatch"] == "":
                continue
            point = (float(row["coverage"]), float(row["mismatch"]))
            if row["dispatcher"].startswith("arm 2 (semantic)"):
                points.append(point)
            elif row["dispatcher"].startswith("arm 3"):
                arm3 = (*point, float(row["wilson_low"]), float(row["wilson_high"]))
    assert arm3 is not None, path
    return sorted(points), arm3


def figure_curves(out: Path) -> None:
    scorers = (
        ("primary", "lexical", BLUE, "-"),
        ("rescore-embedding/primary", "bi-encoder", ORANGE, "--"),
        ("rescore-cross-encoder/primary", "cross-encoder", AQUA, ":"),
    )
    fig, axes = plt.subplots(1, 3, figsize=(6.6, 2.2), sharey=True)
    for axis, run in zip(axes, ("run-11", "run-12", "run-13"), strict=True):
        arm3 = None
        for folder, name, colour, style in scorers:
            points, arm3 = _curve(REPLICATES / run / folder / "figure1.csv")
            axis.plot(*zip(*points, strict=True), style, color=colour, lw=1.2, label=name)
        assert arm3 is not None
        coverage, mismatch, low, high = arm3
        axis.errorbar(
            [coverage],
            [mismatch],
            yerr=[[mismatch - low], [high - mismatch]],
            fmt="D",
            ms=5,
            color=INK,
            mfc="white",
            mew=1.2,
            capsize=2,
            lw=1,
            label="precondition dispatch",
            zorder=5,
        )
        axis.axvline(coverage, color=MUTED, lw=0.6, ls=(0, (1, 2)))
        axis.set_title(f"replicate {int(run[-2:]) - 10}", fontsize=8, color=INK)
        axis.set_xlabel("coverage (fires / 400 pairs)")
        axis.set_xlim(0, 1)
        axis.set_ylim(-0.02, 1.02)
    axes[0].set_ylabel("mismatch (wrong / fires)")
    axes[0].legend(loc="lower right", fontsize=6.5, handlelength=2.2)
    fig.tight_layout()
    fig.savefig(out / "curves.pdf")
    plt.close(fig)


def figure_power(out: Path) -> None:
    grid = json.loads((ROOT / "paper" / "analysis" / "power.json").read_text("utf-8"))["grid"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(6.6, 2.4))
    styles = {
        True: (BLUE, "o", "-", "study 1's build spread"),
        False: (ORANGE, "s", "--", "half that"),
    }
    for calibrated, (colour, marker, style, label) in styles.items():
        rows = [
            g
            for g in grid
            if g["kind"] == "h1" and (abs(g["world"]["s_build"] - 1.0) > 1e-9) == calibrated
        ]
        pairs = sorted(
            (g["realised"]["h1"], g["power"]["h1"]) for g in rows if g["realised"]["h1"] > -0.05
        )
        left.plot(
            *zip(*pairs, strict=True), marker=marker, ms=3.5, color=colour, ls="none", label=label
        )
    left.axhline(0.8, color=MUTED, lw=0.6, ls=(0, (1, 2)))
    left.axhline(0.025, color=MUTED, lw=0.6, ls=(0, (4, 2)))
    left.set_xlabel("true $f$(Control-R) $-$ mean $f$(R's builds)")
    left.set_ylabel("P(H1 supported)")
    left.set_title("H1, the primary test", fontsize=8, color=INK)
    left.legend(loc="lower right", fontsize=6.5)
    left.set_ylim(-0.02, 1.02)

    h3h4 = [g for g in grid if g["kind"] == "h3-h4"]
    for s_clean, colour, marker, style, label in (
        (1.0, BLUE, "o", "-", "clean-case spread 1.0"),
        (None, ORANGE, "s", "--", "study 1's clean-case spread"),
    ):
        rows = [
            g
            for g in h3h4
            if (abs(g["world"]["s_clean_build"] - 1.0) < 1e-9) == (s_clean is not None)
        ]
        by_cost: dict[float, list[float]] = {}
        for g in rows:
            by_cost.setdefault(round(g["realised"]["h4"], 3), []).append(g["power"]["h4"])
        pairs = sorted((cost, sum(v) / len(v)) for cost, v in by_cost.items())
        right.plot(
            *zip(*pairs, strict=True), style, marker=marker, ms=3.5, color=colour, lw=1, label=label
        )
    right.axvline(-0.10, color=MUTED, lw=0.6, ls=(0, (4, 2)))
    right.axhline(0.8, color=MUTED, lw=0.6, ls=(0, (1, 2)))
    right.set_xlabel("true right(R) $-$ right(0) on clean cases")
    right.set_ylabel("P(H4 holds)")
    right.set_title("H4, the non-inferiority guard (margin 0.10)", fontsize=8, color=INK)
    right.legend(loc="upper left", fontsize=6.5)
    right.set_ylim(-0.02, 1.02)
    right.set_xticks([-0.15, -0.10, -0.05, 0.0])
    fig.tight_layout()
    fig.savefig(out / "power.pdf")
    plt.close(fig)


def _wilson(k: int, n: int) -> tuple[float, float, float]:
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, centre - half, centre + half


def figure_refusal(out: Path) -> None:
    """Fire rate on stage B's inexpressible conflicts, per library, as the run's report gives
    it: arm 2 at its matched operating point, the control as registered."""
    report = json.loads((STAGE_B / "report.json").read_text("utf-8"))
    replicates = report["figures"]["replicates"]
    n = 160
    series = (
        ("precondition dispatch", BLUE, "o", "arm 3"),
        ("lexical similarity, matched", ORANGE, "s", "arm 2"),
        ("state reader, intent-scoped", AQUA, "^", "control"),
    )
    fig, axis = plt.subplots(figsize=(3.3, 2.3))
    for offset, (name, colour, marker, key) in zip((-0.2, 0.0, 0.2), series, strict=True):
        for r, replicate in enumerate(replicates):
            p, low, high = _wilson(replicate["fires_on_inexpressible"][key], n)
            axis.errorbar(
                [r + offset],
                [p],
                yerr=[[p - low], [high - p]],
                fmt=marker,
                ms=4,
                color=colour,
                capsize=1.5,
                lw=0.9,
                label=name if r == 0 else None,
            )
    axis.set_xticks(range(3), ["library 1", "library 2", "library 3"])
    axis.set_ylabel(f"fire rate, inexpressible (n = {n})")
    axis.set_ylim(-0.02, 1.05)
    axis.legend(loc="center left", fontsize=6.5, bbox_to_anchor=(0.0, 0.6))
    fig.tight_layout()
    fig.savefig(out / "refusal.pdf")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    figure_curves(args.out)
    figure_power(args.out)
    figure_refusal(args.out)


if __name__ == "__main__":
    main()
