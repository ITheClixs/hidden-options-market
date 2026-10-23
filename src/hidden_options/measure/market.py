"""The FLEX market as one book: its size, its make-up, when its growth turned, its cohorts.

Summed over every series, the report gives the size of the hidden market on each activity
date. That total has a monthly sawtooth. Open interest builds through each cycle and falls
when the standard monthly expiry, the third Friday, clears, and the fall is spread over
two reports: an expiring series is still listed on its expiry date with part of its open
interest, and gone on the next activity date. A level read off a single date therefore
depends on where in the cycle the date falls, so growth here is measured by a fit to the
whole series or by averages over complete expiry cycles, never by two chosen days.

Open interest is gross and aggregated across holders, as everywhere in this package.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from hidden_options.measure.flex_panel import NEAR_DATED_DAYS

CONTRACT_MULTIPLIER = 100
DAYS_PER_YEAR = 365.25

MARKET_DAILY_COLUMNS = ("report_date", "open_interest", "mark_value", "series", "underlyings")
COMPOSITION_KEYS = ("series", "underlyings", "top10_share", "within60d_share", "call_share")
CYCLE_COLUMNS = ("start", "end", "dates", "open_interest")
DROP_COLUMNS = ("report_date", "previous_date", "change", "pct_change", "on_expiry", "expiry")

TOP_UNDERLYINGS = 10
# A break needs this many activity dates on each side, about two months, so a fit cannot
# hang its break on the first or last few expiry cycles.
BREAK_MIN_SIDE = 40
TOP_DROPS = 10
# A holiday moves an expiry back a day; a third Friday further than this from the last
# activity date before it means the panel has a gap there, not a holiday.
_MAX_EXPIRY_SHIFT_DAYS = 3


@dataclass(frozen=True)
class GrowthFit:
    """A one-break piecewise-linear fit to a log level.

    Growth rates are in log points per year: 0.59 means the level grows by a factor of
    e^0.59, about 1.8, a year. The fit is continuous at the break, so `intercept` (the log
    level at `origin`) and the two rates give the fitted line everywhere.
    """

    break_date: pd.Timestamp
    origin: pd.Timestamp
    intercept: float
    pre_growth: float
    post_growth: float
    sse: float


def market_daily(panel: pd.DataFrame) -> pd.DataFrame:
    """One row per activity date: open interest, mark value, series and underlyings.

    `series` counts every line of the report, including the few with no open interest
    left, because each is a series OCC still clears. `mark_value` is open interest valued
    at the report's own mark price.
    """
    frame = panel[["report_date", "underlying", "open_interest", "mark_price"]]
    mark_value = frame["open_interest"] * CONTRACT_MULTIPLIER * frame["mark_price"]
    daily = (
        frame.assign(mark_value=mark_value)
        .groupby("report_date", sort=True)
        .agg(
            open_interest=("open_interest", "sum"),
            mark_value=("mark_value", "sum"),
            series=("open_interest", "size"),
            underlyings=("underlying", "nunique"),
        )
        .reset_index()
    )
    return daily[list(MARKET_DAILY_COLUMNS)]


def composition_by_date(panel: pd.DataFrame) -> pd.DataFrame:
    """`COMPOSITION_KEYS` for every activity date, indexed by date.

    `top10_share` is the open interest of the ten largest underlyings on that date over
    the total; `within60d_share` counts series expiring within sixty days, inclusive, as
    the panel's near-dated measure does; `call_share` is calls over the total.
    """
    frame = panel[["report_date", "underlying", "right", "expiry", "open_interest"]]
    oi = frame["open_interest"]
    days = (frame["expiry"] - frame["report_date"]).dt.days
    frame = frame.assign(
        near=oi.where(days.between(0, NEAR_DATED_DAYS), 0),
        calls=oi.where(frame["right"] == "C", 0),
    )
    totals = frame.groupby("report_date", sort=True).agg(
        series=("open_interest", "size"),
        underlyings=("underlying", "nunique"),
        open_interest=("open_interest", "sum"),
        near=("near", "sum"),
        calls=("calls", "sum"),
    )

    by_underlying = frame.groupby(["report_date", "underlying"])["open_interest"].sum()
    ranked = by_underlying.sort_values(ascending=False)
    rank = ranked.groupby(level="report_date").cumcount()
    top = ranked[rank < TOP_UNDERLYINGS].groupby(level="report_date").sum()

    total = totals["open_interest"]
    shares = pd.DataFrame(
        {
            "series": totals["series"],
            "underlyings": totals["underlyings"],
            "top10_share": top.reindex(totals.index) / total,
            "within60d_share": totals["near"] / total,
            "call_share": totals["calls"] / total,
        }
    )
    return shares[list(COMPOSITION_KEYS)]


def composition(panel: pd.DataFrame, on: pd.Timestamp) -> dict[str, float]:
    """The market's make-up on one activity date; see `composition_by_date`."""
    day = panel[panel["report_date"] == on]
    if day.empty:
        raise ValueError(f"No FLEX series on {on:%Y-%m-%d}")
    row = composition_by_date(day).iloc[0]
    return {key: float(row[key]) for key in COMPOSITION_KEYS}


def cumulative_share(panel: pd.DataFrame, on: pd.Timestamp) -> pd.Series:
    """Share of open interest held by the largest k underlyings on `on`, indexed by k."""
    day = panel[panel["report_date"] == on]
    if day.empty:
        raise ValueError(f"No FLEX series on {on:%Y-%m-%d}")
    by_underlying = day.groupby("underlying")["open_interest"].sum()
    ranked = by_underlying.sort_values(ascending=False, kind="stable")
    shares = ranked.cumsum() / ranked.sum()
    rank = pd.RangeIndex(1, len(shares) + 1, name="rank")
    return pd.Series(shares.to_numpy(), index=rank, name="cumulative_share")


def largest_underlyings(panel: pd.DataFrame, on: pd.Timestamp, n: int) -> list[str]:
    """The `n` underlyings with the most open interest on `on`, largest first."""
    day = panel[panel["report_date"] == on]
    by_underlying = day.groupby("underlying")["open_interest"].sum()
    return list(by_underlying.sort_values(ascending=False, kind="stable").index[:n])


def fit_growth(
    daily: pd.DataFrame, column: str = "open_interest", *, min_side: int = BREAK_MIN_SIDE
) -> GrowthFit:
    """Fit log `column` with one break, chosen by least squares over the interior dates.

    Every activity date with at least `min_side` dates before it and after it is tried as
    the break. Time is calendar time, so a holiday does not compress the slope.
    """
    frame = daily.sort_values("report_date")
    dates = pd.DatetimeIndex(frame["report_date"])
    needed = 2 * min_side + 1
    if len(dates) < needed:
        raise ValueError(
            f"A one-break fit with {min_side} dates each side needs at least {needed} "
            f"dates, got {len(dates)}"
        )
    level = frame[column].to_numpy(dtype=float)
    if not (level > 0).all():
        raise ValueError(f"Column {column!r} must be positive to fit its log level")

    log_level = np.log(level)
    years = _years_since(dates, dates[0])
    candidates = range(min_side, len(dates) - min_side)
    fits = [_hinge_fit(years, log_level, years[candidate]) for candidate in candidates]
    # min keeps the earliest of equally good breaks.
    best = min(range(len(fits)), key=lambda position: fits[position][0])
    sse, coef = fits[best]
    candidate = candidates[best]
    return GrowthFit(
        break_date=dates[candidate],
        origin=dates[0],
        intercept=float(coef[0]),
        pre_growth=float(coef[1]),
        post_growth=float(coef[1] + coef[2]),
        sse=sse,
    )


def growth_break(
    daily: pd.DataFrame, column: str = "open_interest", *, min_side: int = BREAK_MIN_SIDE
) -> pd.Timestamp:
    """The date at which a one-break fit to log `column` changes slope."""
    return fit_growth(daily, column, min_side=min_side).break_date


def expiry_cohorts(panel: pd.DataFrame, freq: str = "MS") -> pd.DataFrame:
    """Open interest by expiry period (rows) and activity date (columns).

    Each column sums to the market's open interest on that date. Only expiry periods that
    hold open interest on some date appear as rows.
    """
    grouped = panel.groupby([pd.Grouper(key="expiry", freq=freq), "report_date"])[
        "open_interest"
    ].sum()
    cohorts = grouped.unstack("report_date", fill_value=0).sort_index()
    cohorts.index.name = "expiry"
    cohorts.columns.name = "report_date"
    return cohorts


def monthly_expiries(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The standard monthly expiry of each month the activity calendar covers.

    That is the third Friday, or the activity date before it when the Friday is a holiday
    (Good Friday 2025 moved April's expiry to Thursday the 17th). Months whose third
    Friday lies outside the calendar are left out.
    """
    dates = calendar.unique().sort_values()
    months = pd.date_range(dates[0].to_period("M").start_time, dates[-1], freq="MS")
    expiries = []
    for month in months:
        third_friday = month + pd.offsets.WeekOfMonth(week=2, weekday=4)
        before = dates[dates <= third_friday]
        if third_friday > dates[-1] or before.empty:
            continue
        if (third_friday - before[-1]).days <= _MAX_EXPIRY_SHIFT_DAYS:
            expiries.append(before[-1])
    return pd.DatetimeIndex(expiries)


def largest_drops(
    daily: pd.DataFrame, expiries: pd.DatetimeIndex, n: int = TOP_DROPS
) -> pd.DataFrame:
    """The `n` largest one-day falls in open interest, largest first, by relative size.

    A fall is measured from the previous activity date. It lands on an expiry when a
    monthly expiry lies between the two dates, inclusive: the expiry date's own report
    and the one after it are where an expiring cohort leaves the report. `expiry` names
    that expiry (NaT when there is none), so two falls from one expiry can be told apart
    from falls at two.
    """
    frame = daily.sort_values("report_date").reset_index(drop=True)
    table = pd.DataFrame(
        {
            "report_date": frame["report_date"],
            "previous_date": frame["report_date"].shift(1),
            "change": frame["open_interest"].diff(),
            "pct_change": frame["open_interest"].pct_change(),
        }
    ).dropna()
    table = table[table["change"] < 0].nsmallest(n, "pct_change").reset_index(drop=True)
    marks = pd.DatetimeIndex(expiries)
    landed = [
        marks[(marks >= previous) & (marks <= day)]
        for previous, day in zip(table["previous_date"], table["report_date"], strict=True)
    ]
    table["expiry"] = pd.DatetimeIndex([hit[0] if len(hit) else pd.NaT for hit in landed])
    table["on_expiry"] = table["expiry"].notna()
    return table[list(DROP_COLUMNS)]


def expiring_decline(panel: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """How far the open interest of series expiring in [start, end] fell over that span."""
    window = panel["expiry"].between(start, end)
    before = panel.loc[window & (panel["report_date"] == start), "open_interest"].sum()
    after = panel.loc[window & (panel["report_date"] == end), "open_interest"].sum()
    return float(before - after)


def expiry_cycles(daily: pd.DataFrame, expiries: pd.DatetimeIndex) -> pd.DataFrame:
    """Mean open interest over each complete expiry cycle.

    A cycle runs from the activity date after one monthly expiry to the next expiry,
    inclusive. Only cycles with both expiries inside the panel are complete; the partial
    cycles at either end are left out.
    """
    frame = daily.sort_values("report_date")
    rows = []
    for opening, closing in zip(expiries[:-1], expiries[1:], strict=True):
        inside = frame[(frame["report_date"] > opening) & (frame["report_date"] <= closing)]
        rows.append(
            {
                "start": inside["report_date"].iloc[0],
                "end": closing,
                "dates": len(inside),
                "open_interest": float(inside["open_interest"].mean()),
            }
        )
    return pd.DataFrame(rows, columns=list(CYCLE_COLUMNS))


def _hinge_fit(years: np.ndarray, log_level: np.ndarray, kink: float) -> tuple[float, np.ndarray]:
    """Least squares of log level on time and time past `kink`: (SSE, coefficients)."""
    design = np.column_stack([np.ones_like(years), years, np.maximum(0.0, years - kink)])
    coef = np.linalg.lstsq(design, log_level, rcond=None)[0]
    residual = log_level - design @ coef
    return float(residual @ residual), coef


def _years_since(dates: pd.DatetimeIndex, origin: pd.Timestamp) -> np.ndarray:
    return np.asarray((dates - origin).days, dtype=float) / DAYS_PER_YEAR
