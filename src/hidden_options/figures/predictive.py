"""F7: the predictive coefficients, their placebo, and the permutation distribution.

The top panel is the main coefficient re-estimated with the predictor shuffled across
underlyings within each date, with the actual estimate marked in it. The bottom panel is
the estimates with their 95% intervals, on the same axis, so the placebo and the genuine
predictor can be read against the shuffled draws directly. Only the predictors measured
in log points of open interest share that axis; the two share predictors are in other
units and stay in the table. Coefficients are drawn multiplied by 10^4, which for an
absolute-return outcome is basis points.

Everything drawn is read from the `predictive` result; the builder needs no raw data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from hidden_options.config import PROJECT_ROOT
from hidden_options.figures.style import PALETTE, apply_style, new_figure, save
from hidden_options.predict.macros import BASIS_POINTS, p_value
from hidden_options.publish.registry import FIGURES
from hidden_options.publish.results import RESULTS_DIR, read_results

RESULT = "predictive"
STEM = "placebo"

# Rows on the figure's shared axis, top to bottom, with their labels.
FIGURE_LABELS = {
    "innovation": "Inventory innovation",
    "change": "Inventory change",
    "placebo": "Placebo: innovation at $T+2$",
}
_BINS = 30


def figure_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The next-day absolute-return rows whose predictor is in log points, in order."""
    by_key = {row["key"]: row for row in rows if row["outcome"] == "abs_ret_next"}
    return [by_key[key] for key in FIGURE_LABELS if key in by_key]


def fig_null(rows: Sequence[Mapping[str, Any]], permutation: Mapping[str, Any]) -> Figure:
    """Shuffled draws above, estimates with 95% intervals below, one x-axis."""
    fig = new_figure(0.68, aspect=0.72)
    top, bottom = fig.subplots(2, 1, sharex=True, height_ratios=(1.5, 1.0))

    null = np.asarray(permutation["null"], dtype=float) * BASIS_POINTS
    observed = float(permutation["observed"]) * BASIS_POINTS
    top.hist(null, bins=_BINS, color=PALETTE["faint"])
    top.axvline(observed, color=PALETTE["ink"], linewidth=1.0)
    # The label reads leftwards from the line, over the shorter side of the histogram.
    side = "right" if observed <= float(np.median(null)) else "left"
    top.annotate(
        f"estimate, permutation $p$ = {p_value(float(permutation['p_value']))}",
        xy=(observed, 1.0),
        xycoords=("data", "axes fraction"),
        xytext=(-4 if side == "right" else 4, -2),
        textcoords="offset points",
        ha=side,
        va="top",
        color=PALETTE["ink"],
    )
    top.set_yticks([])
    top.spines["left"].set_visible(False)
    top.set_title(f"Shuffled within dates, {int(permutation['n_perm']):,} draws")

    for y, row in enumerate(rows):
        colour = PALETTE["accent"] if row["placebo"] else PALETTE["ink"]
        low, high = (float(row[k]) * BASIS_POINTS for k in ("ci_low", "ci_high"))
        bottom.plot([low, high], [y, y], color=colour, linewidth=1.2)
        bottom.plot([float(row["coefficient"]) * BASIS_POINTS], [y], "o", color=colour)
    bottom.set_yticks(range(len(rows)), [FIGURE_LABELS[row["key"]] for row in rows])
    bottom.set_ylim(len(rows) - 0.5, -0.5)
    bottom.tick_params(axis="y", length=0)
    bottom.set_title("Estimates and 95% intervals")
    bottom.set_xlabel("Coefficient on next-day $|r|$, $\\times10^{4}$ (basis points)")
    bottom.xaxis.set_major_locator(MaxNLocator(7))

    for ax in (top, bottom):
        ax.axvline(0.0, color=PALETTE["faint"], linewidth=0.8, zorder=0)
    return fig


@FIGURES.register(STEM)
def build_placebo(results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT) -> None:
    """F7, for the paper and the README."""
    found = read_results(results)
    if RESULT not in found:
        raise FileNotFoundError(
            f"No {RESULT!r} result in {results}; run `hidden-options results --only {RESULT}` first"
        )
    values = found[RESULT].values
    apply_style()
    fig = fig_null(figure_rows(values["rows"]), values["permutation"])
    save(fig, STEM, paper=True, readme=True, root=root)
