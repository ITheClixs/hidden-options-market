#!/usr/bin/env python
"""Build the README figures from the FLEX panel, on the paper's window.

The paper's numbers are computed on 269 activity dates, 2025-07-23 to 2026-08-17.
Later backfills extend the local store further back, so the window is pinned here
rather than taken from whatever happens to be on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.measure.flex_panel import daily_inventory, load_panel  # noqa: E402

OUT = Path("docs/figures")
WINDOW = (pd.Timestamp("2025-07-23"), pd.Timestamp("2026-08-17"))
GREY, DARK, MID = "#b0b0b0", "#2b2b2b", "#707070"

# Coefficient on next-day |r| and MDE80, as reported in docs/PREDICTIVE_RESULT.md.
PREDICTORS = (
    ("Inventory\ninnovation", -0.00030, 0.00062),
    ("Inventory\nchange", -0.00016, 0.00115),
    ("Near-dated\nshare change", 0.00081, 0.00390),
    ("Placebo:\nfuture inventory", -0.00032, 0.00065),
)

plt.rcParams.update(
    {
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
    }
)


def fig_growth(agg: pd.DataFrame) -> None:
    """Open interest and mark value across the paper's window."""
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
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

    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    lines = ax.get_lines() + right.get_lines()
    ax.legend(lines, [line.get_label() for line in lines], frameon=False, loc="lower right")
    fig.savefig(OUT / "growth.png")
    plt.close(fig)


def fig_placebo() -> None:
    """The predictive test against its own placebo, with 95% intervals."""
    names = [name for name, _, _ in PREDICTORS]
    betas = [beta for _, beta, _ in PREDICTORS]
    halfwidths = [1.96 * mde / 2.8 for _, _, mde in PREDICTORS]
    colors = [DARK, DARK, DARK, MID]

    fig, ax = plt.subplots(figsize=(6.0, 2.8))
    x = np.arange(len(names))
    ax.errorbar(x, betas, yerr=halfwidths, fmt="none", ecolor=GREY, elinewidth=1.2, capsize=3)
    for xi, beta, color in zip(x, betas, colors, strict=True):
        ax.plot(xi, beta, "o", color=color, markersize=6)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=8)
    ax.set_ylabel("Coefficient on next-day $|r|$")
    ax.annotate(
        "inventory dated after the\noutcome: same estimate",
        xy=(3, -0.00032),
        xytext=(2.12, -0.0016),
        fontsize=8,
        color=DARK,
        arrowprops={"arrowstyle": "->", "color": MID, "lw": 0.8},
    )
    fig.savefig(OUT / "placebo.png")
    plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = load_panel(Path("data/raw"))
    panel = panel[panel["report_date"].between(*WINDOW)]
    agg = (
        daily_inventory(panel)
        .groupby("report_date")
        .agg(oi=("open_interest", "sum"), value=("mark_value", "sum"))
    )

    fig_growth(agg)
    fig_placebo()

    first, last = agg.iloc[0], agg.iloc[-1]
    print(f"  {len(agg)} activity dates, {panel['underlying'].nunique():,} underlyings")
    print(f"  open interest {first['oi'] / 1e6:.1f}m -> {last['oi'] / 1e6:.1f}m")
    print(f"  mark value    ${first['value'] / 1e9:.0f}bn -> ${last['value'] / 1e9:.0f}bn")
    for path in sorted(OUT.glob("*.png")):
        print(f"  {path}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
