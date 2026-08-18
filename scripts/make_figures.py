#!/usr/bin/env python
"""Build the paper's figures from the FLEX panel."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.measure.flex_panel import daily_inventory, load_panel  # noqa: E402

OUT = Path("paper/figures")
GREY, DARK, MID = "#b0b0b0", "#2b2b2b", "#707070"

plt.rcParams.update(
    {
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 200,
        "savefig.bbox": "tight",
    }
)


def fig_growth(daily: pd.DataFrame) -> None:
    """The market roughly doubled over the panel."""
    agg = daily.groupby("report_date").agg(oi=("open_interest", "sum"), value=("mark_value", "sum"))
    fig, ax = plt.subplots(figsize=(6.0, 3.0))
    ax.plot(agg.index, agg["oi"] / 1e6, color=DARK, lw=1.5, label="Open interest (m contracts)")
    ax.set_ylabel("Open interest, m contracts")
    ax.set_ylim(0, agg["oi"].max() / 1e6 * 1.12)

    right = ax.twinx()
    right.plot(
        agg.index, agg["value"] / 1e9, color=MID, lw=1.2, ls="--", label="Mark value (\\$bn)"
    )
    right.set_ylabel("Mark value, \\$bn")
    right.set_ylim(0, agg["value"].max() / 1e9 * 1.12)
    right.spines["top"].set_visible(False)

    lines = ax.get_lines() + right.get_lines()
    ax.legend(lines, [line.get_label() for line in lines], frameon=False, loc="lower right")
    fig.savefig(OUT / "growth.pdf")
    plt.close(fig)


def fig_concentration(panel: pd.DataFrame) -> None:
    """Where the inventory sits, on the final date."""
    last = panel[panel["report_date"] == panel["report_date"].max()]
    by_symbol = last.groupby("underlying")["open_interest"].sum().sort_values(ascending=False)
    share = by_symbol.cumsum() / by_symbol.sum()

    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    ax.plot(np.arange(1, len(share) + 1), share.to_numpy() * 100, color=DARK, lw=1.4)
    for n in (10, 25, 100):
        if n <= len(share):
            ax.plot([n, n], [0, share.iloc[n - 1] * 100], color=GREY, lw=0.7, ls=":")
            ax.text(
                n,
                share.iloc[n - 1] * 100 + 2.5,
                f"top {n}: {share.iloc[n - 1] * 100:.0f}\\%",
                fontsize=7.5,
                ha="center",
                color=DARK,
            )
    ax.set_xscale("log")
    ax.set_xlabel("Underlyings, ranked by open interest (log scale)")
    ax.set_ylabel("Cumulative share (\\%)")
    ax.set_ylim(0, 105)
    fig.savefig(OUT / "concentration.pdf")
    plt.close(fig)


def fig_maturity(panel: pd.DataFrame) -> None:
    """More than half of the inventory is short-dated."""
    last = panel[panel["report_date"] == panel["report_date"].max()].copy()
    last["dte"] = (last["expiry"] - last["report_date"]).dt.days
    buckets = [(0, 30), (30, 60), (60, 90), (90, 180), (180, 365), (365, 100000)]
    labels = ["$\\leq$30d", "30--60d", "60--90d", "90--180d", "180--365d", "$>$1y"]
    weights = [
        last.loc[last["dte"].between(lo, hi, inclusive="left"), "open_interest"].sum() / 1e6
        for lo, hi in buckets
    ]
    colors = [DARK if i < 2 else GREY for i in range(len(labels))]

    fig, ax = plt.subplots(figsize=(4.6, 2.8))
    ax.bar(labels, weights, color=colors, width=0.62)
    for i, w in enumerate(weights):
        ax.text(i, w + 0.6, f"{w:.1f}", ha="center", fontsize=8)
    ax.set_ylabel("Open interest, m contracts")
    ax.set_ylim(0, max(weights) * 1.2)
    fig.savefig(OUT / "maturity.pdf")
    plt.close(fig)


def fig_placebo() -> None:
    """The predictive test against its own placebo."""
    names = [
        "Inventory\ninnovation",
        "Inventory\nchange",
        "Near-dated\nshare",
        "Placebo:\nfuture inventory",
    ]
    betas = [-0.00030, -0.00016, 0.00081, -0.00032]
    errs = [0.00062 / 2.8, 0.00115 / 2.8, 0.00390 / 2.8, 0.00065 / 2.8]
    colors = [DARK, DARK, DARK, MID]

    fig, ax = plt.subplots(figsize=(5.2, 2.8))
    x = np.arange(len(names))
    ax.errorbar(
        x,
        betas,
        yerr=[1.96 * e for e in errs],
        fmt="o",
        color="none",
        ecolor=GREY,
        elinewidth=1.2,
        capsize=3,
    )
    for xi, b, c in zip(x, betas, colors, strict=True):
        ax.plot(xi, b, "o", color=c, markersize=6)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=7.5)
    ax.set_ylabel("Coefficient on next-day $|r|$")
    ax.annotate(
        "identical to the\ngenuine predictor",
        xy=(3, -0.00032),
        xytext=(2.05, -0.0011),
        fontsize=7.5,
        color=DARK,
        arrowprops={"arrowstyle": "->", "color": MID, "lw": 0.8},
    )
    fig.savefig(OUT / "placebo.pdf")
    plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in ("composition.pdf", "naive_vs_grouped.pdf", "expiry_signature.pdf"):
        (OUT / stale).unlink(missing_ok=True)

    panel = load_panel(Path("data/raw"))
    daily = daily_inventory(panel)

    fig_growth(daily)
    fig_concentration(panel)
    fig_maturity(panel)
    fig_placebo()

    for path in sorted(OUT.glob("*.pdf")):
        print(f"  {path}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
