"""Figures for the market section: growth (F1), remaining maturity (F2), concentration.

The drawing functions take data and return a figure; the registered builders load the
panel, read the `market` result for every number a figure prints, and save. A builder
refuses to draw against a result computed from a different panel, since the figure and
the text beside it would then disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator, NullFormatter

from hidden_options.config import PROJECT_ROOT, RAW_DIR
from hidden_options.figures.style import PALETTE, apply_style, new_figure, save, seq_cmap
from hidden_options.measure.flex_panel import load_panel
from hidden_options.measure.market import (
    cumulative_share,
    expiry_cohorts,
    market_daily,
    maturity_profile,
)
from hidden_options.publish.registry import FIGURES
from hidden_options.publish.results import RESULTS_DIR, read_results

RESULT = "market"


def fig_growth(daily: pd.DataFrame, break_date: pd.Timestamp, expiries: pd.DatetimeIndex) -> Figure:
    """F1: open interest on one axis, mark value in a small panel below, sharing dates.

    Faint vertical lines are the standard monthly expiries, so each tooth of the sawtooth
    can be read against the expiry that cut it. The accent marks the growth break.
    """
    dates = pd.DatetimeIndex(daily["report_date"])
    fig = new_figure(1.0, aspect=0.5)
    top, bottom = fig.subplots(2, 1, sharex=True, height_ratios=(2.6, 1.0))

    for ax in (top, bottom):
        for expiry in expiries:
            ax.axvline(expiry, color=PALETTE["faint"], linewidth=0.5, zorder=0)

    open_interest = daily["open_interest"].to_numpy(dtype=float) / 1e6
    mark_value = daily["mark_value"].to_numpy(dtype=float) / 1e9
    top.plot(dates, open_interest, color=PALETTE["ink"], linewidth=0.9)
    bottom.plot(dates, mark_value, color=PALETTE["ink"], linewidth=0.9)

    top.set_ylim(0, float(np.max(open_interest)) * 1.1)
    bottom.set_ylim(0, float(np.max(mark_value)) * 1.2)
    bottom.yaxis.set_major_locator(MaxNLocator(3))
    top.set_title("Open interest, million contracts")
    bottom.set_title("Mark value, \\$bn")

    # The break is the one thing to notice; its label sits in the empty band below the
    # flat stretch, clear of the series.
    top.axvline(break_date, color=PALETTE["accent"], linewidth=1.0, zorder=1)
    top.annotate(
        f"growth break, {break_date:%B %Y}",
        xy=(break_date, float(np.max(open_interest)) * 0.12),
        xytext=(4, 0),
        textcoords="offset points",
        ha="left",
        va="center",
        color=PALETTE["ink"],
    )
    bottom.set_xlim(dates[0], dates[-1])
    return fig


def fig_maturity(profile: pd.DataFrame) -> Figure:
    """F2: each activity date's open interest by calendar months to its expiry month.

    Rows count months ahead, 0 being the activity date's own month. The top row gathers
    every expiry beyond the horizon, so the long-dated tail is shown rather than cut off.
    Colour is the share of the date's open interest on a linear scale, so a row looks as
    heavy as it is and a thinly held far month stays pale.
    """
    report_dates = pd.DatetimeIndex(profile.columns)
    rows = len(profile)
    horizon = rows - 1
    shares = profile.to_numpy(dtype=float) * 100

    fig = new_figure(1.0, aspect=0.5)
    ax = fig.subplots()
    mesh = ax.pcolormesh(
        _edges(_date_numbers(report_dates)),
        np.arange(rows + 1) - 0.5,
        shares,
        cmap=seq_cmap(),
        norm=Normalize(vmin=0.0, vmax=float(shares.max())),
        shading="flat",
        rasterized=True,
    )
    ax.xaxis_date()
    # A rule in the page colour sets the gathered row apart from the single months.
    ax.axhline(horizon - 0.5, color=PALETTE["surface"], linewidth=1.5)
    ticks = [*range(0, horizon, 6), horizon]
    ax.set_yticks(ticks, [*(str(tick) for tick in ticks[:-1]), f"{horizon}+"])
    ax.set_ylim(-0.5, horizon + 0.5)
    ax.set_xlabel("Activity date")
    ax.set_ylabel("Months to expiry month")
    bar = fig.colorbar(mesh, ax=ax, pad=0.02, fraction=0.04)
    bar.set_label("Share of the date's open interest, %")
    bar.outline.set_visible(False)
    return fig


def fig_concentration(cumulative: pd.Series, marks: Mapping[int, float]) -> Figure:
    """Cumulative share of open interest held by the largest k underlyings, log k."""
    fig = new_figure(0.62, aspect=0.66)
    ax = fig.subplots()
    ax.plot(cumulative.index, cumulative.to_numpy() * 100, color=PALETTE["ink"], linewidth=1.0)
    for k, share in marks.items():
        ax.plot([k], [share * 100], marker="o", markersize=3, color=PALETTE["ink"], ls="none")
        ax.annotate(
            f"top {k}: {share * 100:.0f}%",
            xy=(k, share * 100),
            xytext=(-5, 4),
            textcoords="offset points",
            ha="right",
            va="bottom",
            color=PALETTE["ink"],
        )
    ax.set_xscale("log")
    _plain_log_ticks(ax.xaxis)
    ax.set_xlim(1, len(cumulative))
    ax.set_ylim(0, 100)
    ax.set_xlabel("Underlyings, ranked by open interest")
    ax.set_ylabel("Cumulative share of open interest, %")
    return fig


@lru_cache(maxsize=1)
def cached_panel(raw: Path) -> pd.DataFrame:
    """The panel, loaded once per process for however many figures are built."""
    return load_panel(raw)


@FIGURES.register("growth")
def build_growth(
    raw: Path = RAW_DIR, results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT
) -> None:
    """F1, for the paper and as the README's figure."""
    values = _market_values(results)
    daily = _checked_daily(cached_panel(raw), values)
    apply_style()
    fig = fig_growth(
        daily, pd.Timestamp(values["growth"]["break_date"]), pd.DatetimeIndex(values["expiries"])
    )
    save(fig, "growth", paper=True, readme=True, root=root)


@FIGURES.register("maturity")
def build_maturity(
    raw: Path = RAW_DIR, results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT
) -> None:
    """F2, at the horizon the result's tail shares were computed with."""
    values = _market_values(results)
    panel = cached_panel(raw)
    _checked_daily(panel, values)
    profile = maturity_profile(expiry_cohorts(panel), int(values["maturity"]["horizon_months"]))
    apply_style()
    save(fig_maturity(profile), "maturity", root=root)


@FIGURES.register("concentration")
def build_concentration(
    raw: Path = RAW_DIR, results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT
) -> None:
    """Concentration on the last date, with the shares the text quotes."""
    values = _market_values(results)
    panel = cached_panel(raw)
    _checked_daily(panel, values)
    on = pd.Timestamp(values["concentration"]["date"])
    marks = {int(k): float(v) for k, v in values["concentration"]["top_shares"].items()}
    apply_style()
    save(fig_concentration(cumulative_share(panel, on), marks), "concentration", root=root)


def _market_values(results: Path) -> Mapping[str, Any]:
    found = read_results(results)
    if RESULT not in found:
        raise FileNotFoundError(
            f"No {RESULT!r} result in {results}; run `hidden-options results --only market` first"
        )
    return found[RESULT].values


def _checked_daily(panel: pd.DataFrame, values: Mapping[str, Any]) -> pd.DataFrame:
    """The market's daily totals, after checking the result was computed on this panel."""
    daily = market_daily(panel)
    first, last = (f"{daily['report_date'].iloc[i]:%Y-%m-%d}" for i in (0, -1))
    expected = (values["panel"]["first_date"], values["panel"]["last_date"])
    if (first, last) != expected or len(daily) != values["panel"]["dates"]:
        raise ValueError(
            f"The panel on disk ({first} to {last}, {len(daily)} dates) is not the one "
            f"results/{RESULT}.json was computed on ({expected[0]} to {expected[1]}); "
            "run `hidden-options results --only market` again"
        )
    return daily


def _date_numbers(dates: pd.DatetimeIndex) -> np.ndarray:
    """Dates as matplotlib's day numbers, which a mesh needs for its cell edges."""
    return np.asarray(mdates.date2num(dates.to_pydatetime()), dtype=float)  # type: ignore[no-untyped-call]


def _plain_log_ticks(axis: Any) -> None:
    """Label a log axis 0.01, 1, 1,000 rather than as powers of ten, minor ticks bare."""
    axis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,g}"))
    axis.set_minor_formatter(NullFormatter())


def _edges(centres: np.ndarray) -> np.ndarray:
    """Cell edges halfway between centres, the outer ones half a step out."""
    middles = (centres[1:] + centres[:-1]) / 2
    first = centres[0] - (middles[0] - centres[0]) if len(centres) > 1 else centres[0] - 0.5
    last = centres[-1] + (centres[-1] - middles[-1]) if len(centres) > 1 else centres[-1] + 0.5
    return np.concatenate([[first], middles, [last]])
