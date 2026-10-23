"""Result `market`: the panel, its size and growth, and its expiry cycle (M1, M6).

Everything the paper's Data section and market section print about the FLEX market as a
whole is computed here from every report on disk. Three kinds of number come out.

* The panel and its two end dates: coverage, size, value and make-up.
* Growth, without leaning on two chosen days: a one-break fit to log open interest dates
  the turn, the same fit on the cycle's troughs alone and on its peaks alone says how far
  the date moves with the sawtooth, and averages over complete expiry cycles give the
  level before the turn and the level now.
* The sawtooth itself: whether the largest one-day falls land on monthly expiries, how
  often a day-to-day change touches one at all, and how much of each fall the expiring
  cohort accounts for.
* Maturity: how much of the book is near expiry, and how much is more than one or two
  years out, on the end dates and over every date.

`market_macros` turns these values into the strings the paper and README print.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.config import RAW_DIR
from hidden_options.measure.flex_panel import load_panel
from hidden_options.measure.market import (
    MATURITY_HORIZON_MONTHS,
    TOP_DROPS,
    composition_by_date,
    cumulative_share,
    expiring_decline,
    expiry_cohorts,
    expiry_cycles,
    expiry_window_changes,
    fit_growth,
    largest_drops,
    largest_underlyings,
    market_daily,
    maturity_by_date,
    maturity_profile,
    monthly_expiries,
)
from hidden_options.measure.market_macros import market_macros
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "market"

# The robustness fits run on one date per expiry cycle, so their margin is in cycles.
BREAK_MIN_CYCLES = 4
# The latest cycle is compared with the one this many cycles earlier: a quarter.
QUARTER_CYCLES = 3
CONCENTRATION_MARKS = (10, 25, 100)
TOP_NAMES = 5
_TICKER = re.compile(r"[A-Z0-9./]+")


def market_result(panel: pd.DataFrame) -> Result:
    """The `market` result for an assembled FLEX panel."""
    daily = market_daily(panel)
    calendar = pd.DatetimeIndex(daily["report_date"])
    expiries = monthly_expiries(calendar)
    shares = composition_by_date(panel)
    first, last = calendar[0], calendar[-1]

    growth = _growth(daily, expiries)
    cycles = _cycles(daily, expiries, pd.Timestamp(growth["break_date"]))
    values: dict[str, Any] = {
        "panel": _panel(panel, calendar),
        "start": _snapshot(daily, shares, first),
        "end": _snapshot(daily, shares, last),
        "peak": _peak(daily),
        "shares_over_panel": _share_ranges(shares),
        "growth": growth,
        "cycles": cycles,
        "drops": _drops(panel, daily, expiries),
        "concentration": _concentration(panel, last),
        "maturity": _maturity(panel),
        "expiries": [formats.iso_date(day) for day in expiries],
    }
    inputs = {
        "source": "data/raw/occ_flex",
        "kinds": sorted(panel["kind"].unique()),
        "first_date": formats.iso_date(first),
        "last_date": formats.iso_date(last),
        "dates": len(calendar),
        "rows": len(panel),
    }
    return Result(NAME, values, market_macros(values), inputs, now_iso())


@ANALYSES.register(NAME)
def market() -> Result:
    """M1 and M6 on every FLEX report on disk."""
    return market_result(load_panel(RAW_DIR))


def _panel(panel: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, Any]:
    first, last = calendar[0], calendar[-1]
    missing = pd.bdate_range(first, last).difference(calendar)
    return {
        "dates": len(calendar),
        "underlyings": int(panel["underlying"].nunique()),
        "series_days": len(panel),
        "first_date": formats.iso_date(first),
        "last_date": formats.iso_date(last),
        "months": round((last - first).days / (365.25 / 12)),
        "missing_weekdays": [formats.iso_date(day) for day in missing],
    }


def _snapshot(daily: pd.DataFrame, shares: pd.DataFrame, on: pd.Timestamp) -> dict[str, Any]:
    row = daily[daily["report_date"] == on].iloc[0]
    make_up = shares[shares.index == on].iloc[0]
    return {
        "date": formats.iso_date(on),
        "open_interest": int(row["open_interest"]),
        "mark_value": float(row["mark_value"]),
        "series": int(row["series"]),
        "underlyings": int(row["underlyings"]),
        "top10_share": float(make_up["top10_share"]),
        "within60d_share": float(make_up["within60d_share"]),
        "call_share": float(make_up["call_share"]),
    }


def _peak(daily: pd.DataFrame) -> dict[str, Any]:
    row = daily.iloc[int(np.argmax(daily["open_interest"].to_numpy()))]
    return {
        "date": formats.iso_date(row["report_date"]),
        "open_interest": int(row["open_interest"]),
    }


def _share_ranges(shares: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Mean, low and high of each share over every date: how much a single date can say."""
    return {
        key: {
            "mean": float(shares[key].mean()),
            "min": float(shares[key].min()),
            "max": float(shares[key].max()),
        }
        for key in ("top10_share", "within60d_share", "call_share")
    }


def _growth(daily: pd.DataFrame, expiries: pd.DatetimeIndex) -> dict[str, Any]:
    """The break on every date, and on the cycle's troughs and peaks for comparison."""
    fit = fit_growth(daily)
    positions = pd.DatetimeIndex(daily["report_date"]).get_indexer(expiries)
    after = positions[positions + 1 < len(daily)] + 1
    before = positions[positions >= 1] - 1
    troughs = fit_growth(daily.iloc[after], min_side=BREAK_MIN_CYCLES)
    peaks = fit_growth(daily.iloc[before], min_side=BREAK_MIN_CYCLES)
    shift = max(abs((other.break_date - fit.break_date).days) for other in (troughs, peaks))
    value_fit = fit_growth(daily, "mark_value")
    return {
        "break_date": formats.iso_date(fit.break_date),
        "pre_growth_log": fit.pre_growth,
        "post_growth_log": fit.post_growth,
        "pre_growth": math.expm1(fit.pre_growth),
        "post_growth": math.expm1(fit.post_growth),
        "post_growth_quarter": math.expm1(fit.post_growth / 4),
        "intercept": fit.intercept,
        "sse": fit.sse,
        "break_on_troughs": formats.iso_date(troughs.break_date),
        "break_on_peaks": formats.iso_date(peaks.break_date),
        "break_shift_days": shift,
        "break_on_mark_value": formats.iso_date(value_fit.break_date),
    }


def _cycles(
    daily: pd.DataFrame, expiries: pd.DatetimeIndex, break_date: pd.Timestamp
) -> dict[str, Any]:
    """Cycle averages: the flat level before the break and the level now."""
    cycles = expiry_cycles(daily, expiries)
    flat = cycles[cycles["end"] < break_date]
    if flat.empty:
        raise ValueError(f"No complete expiry cycle ends before the break on {break_date:%Y-%m-%d}")
    if len(cycles) <= QUARTER_CYCLES:
        raise ValueError(f"Need more than {QUARTER_CYCLES} complete cycles, got {len(cycles)}")

    latest = cycles.iloc[-1]
    quarter_ago = cycles.iloc[-1 - QUARTER_CYCLES]
    flat_level = float(flat["open_interest"].mean())
    flat_high = float(flat["open_interest"].max())
    # The fitted break is a date; the cycles say when the level actually left its band.
    risen = cycles[(cycles["end"] >= break_date) & (cycles["open_interest"] > flat_high)]
    if risen.empty:
        raise ValueError("No cycle after the break averages above the pre-break band")
    # The cycles are numbered from 0 in order, so the one before is one row up.
    band_end = pd.Timestamp(cycles["end"].iloc[int(risen.index[0]) - 1])
    return {
        "table": [
            {
                "start": formats.iso_date(row["start"]),
                "end": formats.iso_date(row["end"]),
                "dates": int(row["dates"]),
                "open_interest": float(row["open_interest"]),
            }
            for row in cycles.to_dict("records")
        ],
        "flat_cycles": len(flat),
        "flat_low": float(flat["open_interest"].min()),
        "flat_high": flat_high,
        "flat_level": flat_level,
        "flat_band_end": formats.iso_date(band_end),
        "latest_end": formats.iso_date(latest["end"]),
        "latest_level": float(latest["open_interest"]),
        "multiple": float(latest["open_interest"]) / flat_level,
        "quarter_change": float(latest["open_interest"] / quarter_ago["open_interest"] - 1),
    }


def _drops(panel: pd.DataFrame, daily: pd.DataFrame, expiries: pd.DatetimeIndex) -> dict[str, Any]:
    """The sawtooth check: do the largest falls land on monthly expiries, and why."""
    drops = largest_drops(daily, expiries, n=TOP_DROPS)
    largest: list[dict[str, Any]] = []
    for row in drops.to_dict("records"):
        expiring = expiring_decline(panel, row["previous_date"], row["report_date"])
        largest.append(
            {
                "date": formats.iso_date(row["report_date"]),
                "previous_date": formats.iso_date(row["previous_date"]),
                "change": int(row["change"]),
                "pct_change": float(row["pct_change"]),
                "on_expiry": bool(row["on_expiry"]),
                "expiry": formats.iso_date(row["expiry"]) if row["on_expiry"] else None,
                "expiring_decline": expiring,
                "expiring_ratio": expiring / -float(row["change"]),
            }
        )
    ratios = [float(drop["expiring_ratio"]) for drop in largest]
    falls = [-float(drop["pct_change"]) for drop in largest]
    touching, changes = expiry_window_changes(daily, expiries)
    return {
        "largest": largest,
        "on_expiry": sum(drop["on_expiry"] for drop in largest),
        "on_expiry_date": sum(drop["date"] == drop["expiry"] for drop in largest),
        "day_after_expiry": sum(drop["previous_date"] == drop["expiry"] for drop in largest),
        "window_changes": touching,
        "changes": changes,
        "window_share": touching / changes,
        "distinct_expiries": len({drop["expiry"] for drop in largest if drop["on_expiry"]}),
        "fall_low": min(falls),
        "fall_high": max(falls),
        "expiring_ratio_low": min(ratios),
        "expiring_ratio_high": max(ratios),
    }


def _concentration(panel: pd.DataFrame, on: pd.Timestamp) -> dict[str, Any]:
    cumulative = cumulative_share(panel, on)
    names = largest_underlyings(panel, on, TOP_NAMES)
    for name in names:
        if not _TICKER.fullmatch(name):
            raise ValueError(f"Underlying {name!r} is not a plain ticker; it cannot be printed")
    return {
        "date": formats.iso_date(on),
        "top_shares": {
            str(k): float(cumulative.iloc[min(k, len(cumulative)) - 1]) for k in CONCENTRATION_MARKS
        },
        "largest": names,
    }


def _maturity(panel: pd.DataFrame) -> dict[str, Any]:
    """Near-dated and long-dated open interest, on the end dates and over every date."""
    by_date = maturity_by_date(panel)
    beyond = maturity_profile(expiry_cohorts(panel)).iloc[-1]
    return {
        "horizon_months": MATURITY_HORIZON_MONTHS,
        "over_one_year": _ends(by_date["over_one_year_share"]),
        "over_two_years": _ends(by_date["over_two_years_share"]),
        "median_days": _ends(by_date["median_days"]),
        "beyond_horizon": _ends(beyond),
    }


def _ends(series: pd.Series) -> dict[str, float]:
    """First and last value of a by-date series, with its mean, low and high."""
    return {
        "start": float(series.iloc[0]),
        "end": float(series.iloc[-1]),
        "mean": float(series.mean()),
        "min": float(series.min()),
        "max": float(series.max()),
    }
