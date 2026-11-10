"""F11 and F12: what the FLEX market is made of, and what its box lending costs.

F11 stacks the market's mark value by product on every report date: box legs, stock-leg
calls and same-strike pairs in a blue ramp (lending and delta-one exposure), package legs
in the accent and everything else in ink (the options).

F12 has two panels on one date axis. Above, the face of the boxes found in open interest,
under the outside-in matching and under the neighbour matching. Below, each month's median
spread of traded box rates over the Treasury curve.

Everything drawn is read from the `anatomy` and `box_rates` results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from hidden_options.config import PROJECT_ROOT
from hidden_options.figures.style import (
    PALETTE,
    SEQ,
    apply_style,
    label_line_end,
    new_figure,
    save,
)
from hidden_options.publish.registry import FIGURES
from hidden_options.publish.results import RESULTS_DIR, read_results

ANATOMY = "anatomy"
BOX_RATES = "box_rates"
SPLIT_STEM = "product_split"
LENDING_STEM = "box_lending"
BILLION = 1e9
BASIS_POINTS = 1e4
# Bottom to top, with the label and colour of each layer.
LAYERS = (
    ("other", "Other", PALETTE["ink"]),
    ("package_leg", "Package legs", PALETTE["accent"]),
    ("stock_leg", "Stock-leg calls", SEQ[2]),
    ("pair", "Same-strike pairs", SEQ[3]),
    ("box", "Box legs", SEQ[5]),
)


def fig_product_split(daily: Sequence[Mapping[str, Any]]) -> Figure:
    """Mark value by product, stacked, on every report date."""
    fig = new_figure(0.9, aspect=0.5)
    ax = fig.subplots()
    dates = pd.to_datetime([row["date"] for row in daily])
    layers = [
        np.array([row["value"][name] for row in daily], dtype=float) / BILLION
        for name, _, _ in LAYERS
    ]
    ax.stackplot(dates, layers, colors=[colour for _, _, colour in LAYERS], linewidth=0)
    floor = 0.0
    for values, (_, label, _) in zip(layers, LAYERS, strict=True):
        label_line_end(ax, dates[-1], floor + values[-1] / 2, label)
        floor += values[-1]
    ax.set_ylabel("Mark value, \\$bn")
    ax.margins(x=0)
    ax.set_ylim(0.0, None)
    return fig


def fig_box_lending(
    daily: Sequence[Mapping[str, Any]], monthly: Sequence[Mapping[str, Any]]
) -> Figure:
    """Box face in open interest above, the traded spread over Treasuries below."""
    fig = new_figure(0.9, aspect=0.62)
    top, bottom = fig.subplots(2, 1, sharex=True, height_ratios=(1.3, 1.0))
    dates = pd.to_datetime([row["date"] for row in daily])
    face = np.array([row["box_face"] for row in daily], dtype=float) / BILLION
    neighbour = np.array([row["box_neighbour_face"] for row in daily], dtype=float) / BILLION
    top.plot(dates, face, color=PALETTE["ink"])
    top.plot(dates, neighbour, color=PALETTE["muted"])
    label_line_end(top, dates[-1], face[-1], "Outside-in")
    label_line_end(top, dates[-1], neighbour[-1], "Neighbour")
    top.set_ylabel("Box face, \\$bn")
    top.set_ylim(0.0, None)

    months = [row for row in monthly if row["median"] is not None]
    middle = pd.to_datetime([f"{row['month']}-15" for row in months])
    median = np.array([row["median"] for row in months], dtype=float) * BASIS_POINTS
    bottom.axhline(0.0, color=PALETTE["faint"], linewidth=0.8, zorder=0)
    bottom.plot(middle, median, "-o", color=PALETTE["accent"], markersize=3.0)
    bottom.set_ylabel("Spread, bp")
    bottom.margins(x=0)
    return fig


def _values(results: Path, name: str) -> Mapping[str, Any]:
    found = read_results(results)
    if name not in found:
        raise FileNotFoundError(
            f"No {name!r} result in {results}; run `hidden-options results --only {name}` first"
        )
    return found[name].values


@FIGURES.register(SPLIT_STEM)
def build_product_split(results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT) -> None:
    """F11, for the paper and the README."""
    values = _values(results, ANATOMY)
    apply_style()
    save(fig_product_split(values["daily"]), SPLIT_STEM, paper=True, readme=True, root=root)


@FIGURES.register(LENDING_STEM)
def build_box_lending(results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT) -> None:
    """F12, for the paper and the README."""
    daily = _values(results, ANATOMY)["daily"]
    monthly = _values(results, BOX_RATES)["monthly"]
    apply_style()
    save(fig_box_lending(daily, monthly), LENDING_STEM, paper=True, readme=True, root=root)


__all__ = [
    "LAYERS",
    "build_box_lending",
    "build_product_split",
    "fig_box_lending",
    "fig_product_split",
]
