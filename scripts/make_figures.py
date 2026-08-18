#!/usr/bin/env python
"""Build the paper's figures from the census artefacts."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

OUT = Path("paper/figures")
GREY, DARK = "#9a9a9a", "#2b2b2b"

plt.rcParams.update(
    {
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 200,
        "savefig.bbox": "tight",
    }
)


def fig_composition(structures: pd.DataFrame) -> None:
    """Exposure by structure type, against the naive per-leg total."""
    grouped = structures.groupby("structure")["exposure"].sum().div(1e9).sort_values(ascending=True)
    grouped = grouped[grouped > 1.0]

    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    ax.barh(
        [s.replace("_", " ") for s in grouped.index],
        grouped.to_numpy(),
        color=DARK,
        height=0.65,
    )
    for i, v in enumerate(grouped.to_numpy()):
        ax.text(v + 1, i, f"{v:.0f}", va="center", fontsize=8, color=DARK)
    ax.set_xlabel("Exposure, \\$bn (contracts $\\times$ spot, counted once per structure)")
    ax.set_xlim(0, grouped.max() * 1.18)
    fig.savefig(OUT / "composition.pdf")
    plt.close(fig)


def fig_naive_vs_grouped(structures: pd.DataFrame, census: pd.DataFrame) -> None:
    """The size of the counting error, and where it comes from."""
    naive = census["notional"].sum() / 1e9
    grouped = structures["exposure"].sum() / 1e9

    fig, ax = plt.subplots(figsize=(3.4, 3.0))
    bars = ax.bar(
        ["Legs summed\n(naive)", "Structures\n(corrected)"],
        [naive, grouped],
        color=[GREY, DARK],
        width=0.55,
    )
    for bar, value in zip(bars, [naive, grouped], strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 12,
            f"\\${value:.0f}bn",
            ha="center",
            fontsize=9,
        )
    ax.set_ylabel("US\\$bn")
    ax.set_ylim(0, naive * 1.18)
    ax.annotate(
        f"{naive / grouped:.1f}$\\times$",
        xy=(0.5, (naive + grouped) / 2),
        ha="center",
        fontsize=11,
        color=DARK,
    )
    fig.savefig(OUT / "naive_vs_grouped.pdf")
    plt.close(fig)


def fig_concentration(structures: pd.DataFrame) -> None:
    """How concentrated exposure is across underlyings."""
    by_symbol = structures.groupby("symbol")["exposure"].sum().sort_values(ascending=False)
    share = by_symbol.cumsum() / by_symbol.sum()

    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    ax.plot(np.arange(1, len(share) + 1), share.to_numpy() * 100, color=DARK, lw=1.4)
    for n in (10, 25, 50):
        if n <= len(share):
            ax.plot([n, n], [0, share.iloc[n - 1] * 100], color=GREY, lw=0.7, ls=":")
            ax.text(
                n,
                share.iloc[n - 1] * 100 + 2.5,
                f"top {n}: {share.iloc[n - 1] * 100:.0f}%",
                fontsize=7.5,
                ha="center",
                color=DARK,
            )
    ax.set_xlabel("Underlyings, ranked by exposure")
    ax.set_ylabel("Cumulative share of exposure (\\%)")
    ax.set_xlim(0, len(share))
    ax.set_ylim(0, 105)
    fig.savefig(OUT / "concentration.pdf")
    plt.close(fig)


def fig_expiry_signature(census: pd.DataFrame) -> None:
    """Month-end expiry share by category: the outcome-period cycle, unprompted."""
    frame = census.copy()
    frame["month_end"] = pd.to_datetime(frame["expiry"]).dt.is_month_end
    share = frame.groupby("category")["month_end"].mean().sort_values() * 100
    share = share[share.index != "unclassified"]

    fig, ax = plt.subplots(figsize=(4.6, 2.6))
    colors = [DARK if s == "index_linked" else GREY for s in share.index]
    ax.barh([s.replace("_", " ") for s in share.index], share.to_numpy(), color=colors, height=0.6)
    for i, v in enumerate(share.to_numpy()):
        ax.text(v + 0.5, i, f"{v:.1f}\\%", va="center", fontsize=8)
    ax.set_xlabel("Series expiring on a month end (\\%)")
    ax.set_xlim(0, max(share.max() * 1.25, 5))
    fig.savefig(OUT / "expiry_signature.pdf")
    plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    census = pd.read_parquet("data/flex_census.parquet")
    structures = pd.read_parquet("data/flex_structures.parquet")

    fig_composition(structures)
    fig_naive_vs_grouped(structures, census)
    fig_concentration(structures)
    fig_expiry_signature(census)

    for path in sorted(OUT.glob("*.pdf")):
        print(f"  {path}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
