"""F9 and F10: what the hidden book holds in convexity, and what the pinning test can see.

F9 places each market the gamma comparison follows by FLEX's share of its option gamma,
counted gross (x) and pair-netted (y). A point on the diagonal holds outright options; a
point on the floor holds forwards. Index products are in the accent, the single names in
ink (programme names) and muted (controls).

F10 is the registered pinning statistic on the placebo dates of the empirical null, each
offset's mean with its 95% interval, beside the estimate on the expiry itself (offset 0)
in the accent. The real expiry should look like any placebo date if nothing pins.

Everything drawn is read from the `hidden_gamma` and `pinning` results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter

from hidden_options.config import PROJECT_ROOT
from hidden_options.figures.style import PALETTE, apply_style, new_figure, save
from hidden_options.publish.registry import FIGURES
from hidden_options.publish.results import RESULTS_DIR, read_results

GAMMA_RESULT = "hidden_gamma"
PINNING_RESULT = "pinning"
GAMMA_STEM = "gamma_share"
PINNING_STEM = "pinning_null"
LABELLED = ("SPY", "NDX", "RUT", "EFA", "MSFT", "LCID")
Z95 = 1.96

_GROUP_COLOUR = {"index": "accent", "programme": "ink", "control": "muted"}
_KEY = (
    ("index", "index products"),
    ("programme", "option-income underlyings"),
    ("control", "controls"),
)


def gamma_points(
    underlyings: Mapping[str, Mapping[str, Any]], index: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One point per market: single names from `underlyings`, index products from `index`."""
    names = [
        {"name": name, "group": row["group"], **_shares(row)}
        for name, row in underlyings.items()
        if name not in index
    ]
    products = [{"name": name, "group": "index", **_shares(row)} for name, row in index.items()]
    return names + products


def _shares(row: Mapping[str, Any]) -> dict[str, float]:
    return {"gross": float(row["share_gross"]), "netted": float(row["share_netted"])}


def fig_gamma_share(
    points: Sequence[Mapping[str, Any]], *, labelled: Sequence[str] = LABELLED
) -> Figure:
    """Gross against netted FLEX share of option gamma, one point per market."""
    fig = new_figure(0.62, aspect=0.82)
    ax = fig.subplots()
    top = max(0.05, *(max(p["gross"], p["netted"]) for p in points)) * 1.08
    ax.plot([0, top], [0, top], color=PALETTE["faint"], linewidth=0.8, zorder=0)
    for group in ("control", "programme", "index"):
        chosen = [p for p in points if p["group"] == group]
        if chosen:
            ax.scatter(
                [p["gross"] for p in chosen],
                [p["netted"] for p in chosen],
                s=12 if group == "index" else 8,
                color=PALETTE[_GROUP_COLOUR[group]],
                linewidths=0,
                zorder=2,
            )
    for p in points:
        if p["name"] in labelled:
            ax.annotate(
                p["name"],
                xy=(p["gross"], p["netted"]),
                xytext=(4, 2),
                textcoords="offset points",
                color=PALETTE[_GROUP_COLOUR[p["group"]]],
            )
    ax.annotate(
        "netting removes nothing",
        xy=(0.62 * top, 0.62 * top),
        xytext=(-4, 4),
        textcoords="offset points",
        ha="right",
        color=PALETTE["muted"],
    )
    for row, (group, text) in enumerate(_KEY):
        ax.text(
            0.03,
            0.97 - 0.06 * row,
            text,
            transform=ax.transAxes,
            va="top",
            color=PALETTE[_GROUP_COLOUR[group]],
        )
    ax.set_xlim(0.0, top)
    ax.set_ylim(0.0, top)
    ax.set_aspect("equal")
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("FLEX share of gamma, gross")
    ax.set_ylabel("FLEX share of gamma, pair-netted")
    return fig


def fig_pinning_null(null: Mapping[str, Any], h1: Mapping[str, Any]) -> Figure:
    """Each placebo offset's mean with its 95% interval, and the expiry itself at zero."""
    fig = new_figure(0.8, aspect=0.45)
    ax = fig.subplots()
    ax.axhline(0.0, color=PALETTE["faint"], linewidth=0.8, zorder=0)
    for row in null["offsets"]:
        _interval(ax, float(row["offset"]), row, PALETTE["muted"])
    _interval(ax, 0.0, h1, PALETTE["accent"])
    ax.annotate(
        "expiry",
        xy=(0.0, float(h1["mean"]) - Z95 * float(h1["std_error"])),
        xytext=(0, -4),
        textcoords="offset points",
        ha="center",
        va="top",
        color=PALETTE["accent"],
    )
    ax.set_xlabel("Sessions from the FLEX expiry (placebo dates, no expiry)")
    ax.set_ylabel(r"Closeness to strike, $\sigma$")
    return fig


def _interval(ax: Any, x: float, row: Mapping[str, Any], colour: str) -> None:
    mean, half = float(row["mean"]), Z95 * float(row["std_error"])
    ax.plot([x, x], [mean - half, mean + half], color=colour, linewidth=1.0)
    ax.plot([x], [mean], "o", color=colour, markersize=3.0)


def _values(results: Path, name: str) -> Mapping[str, Any]:
    found = read_results(results)
    if name not in found:
        raise FileNotFoundError(
            f"No {name!r} result in {results}; run `hidden-options results --only {name}` first"
        )
    return found[name].values


@FIGURES.register(GAMMA_STEM)
def build_gamma_share(results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT) -> None:
    """F9, for the paper and the README."""
    values = _values(results, GAMMA_RESULT)
    apply_style()
    fig = fig_gamma_share(gamma_points(values["underlyings"], values["index"]))
    save(fig, GAMMA_STEM, paper=True, readme=True, root=root)


@FIGURES.register(PINNING_STEM)
def build_pinning_null(results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT) -> None:
    """F10, for the paper."""
    values = _values(results, PINNING_RESULT)
    apply_style()
    fig = fig_pinning_null(values["empirical_null"], values["h1"])
    save(fig, PINNING_STEM, paper=True, root=root)


__all__ = [
    "build_gamma_share",
    "build_pinning_null",
    "fig_gamma_share",
    "fig_pinning_null",
    "gamma_points",
]
