"""The predictive panel: hidden inventory at T against what the underlying does next.

OCC reports open interest for activity date T overnight, so an observer first has it on
``available_at``, the next activity date. Every predictor here is built from reports up
to and including T. Every outcome is realised on ``available_at`` or later, and the join
that attaches outcomes refuses anything else, so the publication lag is enforced rather
than assumed.

Predictors enter as changes or as innovations relative to the underlying's own trailing
level, because the level of inventory is dominated by persistent differences between
underlyings that the fixed effects remove. Changes come from `inventory_changes`, which
withholds a change that spans an activity date the underlying did not report.

Outcomes are standard daily proxies for realised volatility: the absolute and squared
close-to-close return realised on ``available_at``, the absolute open-to-close return of
that session (which excludes the overnight move before the report could be read), and
the mean absolute return over the sessions starting there. Controls are known by the
close of T: trailing mean absolute return over five and twenty-two sessions, the same
day's absolute return, and log dollar volume.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pandas.api.typing import SeriesGroupBy

from hidden_options.measure.flex_panel import inventory_changes

CONTROLS = ("rv5", "rv22", "abs_ret", "log_dv")
VOLATILITY_WINDOWS = {"rv5": 5, "rv22": 22}
HORIZONS = (3, 5, 10)

# The innovation compares the log level with the mean of the underlying's previous twenty
# reported levels, and needs at least five of them.
INNOVATION_WINDOW = 20
INNOVATION_MIN = 5

# The placebo is the innovation two activity dates later: dated after the outcome, which
# is realised on the next activity date, so it cannot carry information about it.
PLACEBO_LEAD = 2

OUTCOMES = (
    "abs_ret_next",
    "sq_ret_next",
    "oc_abs_next",
    *(f"abs_ret_next_{days}d" for days in HORIZONS),
)
PREDICTORS = ("oi_innov", "d_log_oi", "d_near_share", "put_share", "oi_innov_placebo")

# A row enters the panel only with these: the main outcome, the controls, and the
# predictors every table row shares, so the rows are estimated on one sample.
_REQUIRED = ("abs_ret_next", *CONTROLS, "oi_innov", "d_log_oi")

_MARKET_TZ = ZoneInfo("America/New_York")


def _sessions(timestamps: pd.Series) -> pd.Series:
    """The New York date of each bar timestamp."""
    stamps = pd.to_datetime(timestamps, utc=True)
    sessions: pd.Series = stamps.dt.tz_convert(_MARKET_TZ).dt.tz_localize(None).dt.normalize()
    return sessions


def bars_through(bars: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    """The bars of sessions on or before `end`, in a fresh index.

    An outcome is realised on ``available_at`` or later, so a panel whose last report is
    read on `end` meets no bar after it.
    """
    return bars[_sessions(bars["timestamp"]) <= end].reset_index(drop=True)


def session_frame(bars: pd.DataFrame) -> pd.DataFrame:
    """Per symbol and session: returns, the trailing controls and the forward outcomes.

    ``session`` is the bar's New York date. Values on a session are realised by its
    close: ``abs_ret`` is that session's absolute close-to-close return, ``rv5`` and
    ``rv22`` average the sessions before it, and ``abs_ret_{h}d`` averages ``h``
    sessions starting with it (missing unless all ``h`` exist).
    """
    frame = bars[["symbol", "timestamp", "open", "close", "volume"]].copy()
    frame["session"] = _sessions(frame["timestamp"])
    if frame.duplicated(["symbol", "session"]).any():
        raise ValueError("bars hold more than one bar for a symbol and session")
    frame = frame.sort_values(["symbol", "session"]).reset_index(drop=True)

    grouped = frame.groupby("symbol", sort=False)
    ret = frame["close"] / grouped["close"].shift(1) - 1
    frame["abs_ret"] = ret.abs()
    frame["sq_ret"] = ret**2
    frame["oc_abs"] = (frame["close"] / frame["open"] - 1).abs()
    dollar_volume = frame["close"] * frame["volume"]
    frame["log_dv"] = np.log(dollar_volume.where(dollar_volume > 0))

    by_symbol = frame.groupby("symbol", sort=False)["abs_ret"]
    for name, window in VOLATILITY_WINDOWS.items():
        frame[name] = _mean_of_shifts(by_symbol, range(1, window + 1))
    for days in HORIZONS:
        frame[f"abs_ret_{days}d"] = _mean_of_shifts(by_symbol, range(0, -days, -1))
    return frame.drop(columns=["timestamp", "open", "close", "volume"])


def _mean_of_shifts(grouped: SeriesGroupBy, shifts: range) -> pd.Series:
    """Mean of a series over the given row offsets within each group; NaN if any is."""
    total = pd.concat([grouped.shift(k) for k in shifts], axis=1).sum(axis=1, min_count=len(shifts))
    mean: pd.Series = total / len(shifts)
    return mean


def join_outcomes(
    frame: pd.DataFrame, sessions: pd.DataFrame, *, at: str = "available_at"
) -> pd.DataFrame:
    """Attach the outcomes realised on each row's ``at`` date.

    ``at`` must be strictly after the activity date ``date`` on every row: a report is
    published after its session closes, so an outcome on the activity date itself, or
    before it, is look-ahead. Joining on ``date`` is refused outright.
    """
    if at == "date":
        raise ValueError(
            "outcomes must be joined on a date after the activity date; "
            "the report for a date is published after that session closes"
        )
    early = frame[frame[at] <= frame["date"]]
    if not early.empty:
        first = early.iloc[0]
        raise ValueError(
            f"{len(early)} rows are usable no later than their activity date "
            f"(first: {first['symbol']} on {first['date']:%Y-%m-%d}, {at} "
            f"{first[at]:%Y-%m-%d}); outcomes must come after the activity date"
        )
    outcomes = sessions[["symbol", "session", "abs_ret", "sq_ret", "oc_abs"]].rename(
        columns={
            "session": at,
            "abs_ret": "abs_ret_next",
            "sq_ret": "sq_ret_next",
            "oc_abs": "oc_abs_next",
        }
    )
    for days in HORIZONS:
        outcomes[f"abs_ret_next_{days}d"] = sessions[f"abs_ret_{days}d"]
    return frame.merge(outcomes, on=["symbol", at], how="inner")


def inventory_predictors(daily: pd.DataFrame, min_history: int) -> pd.DataFrame:
    """Predictors per underlying and activity date, from reports up to that date.

    Pass the full daily inventory: the calendar that decides whether a change spans a
    missing date, and where the placebo's date falls, is every date in ``daily``.
    """
    calendar = pd.DatetimeIndex(daily["report_date"].unique()).sort_values()
    frame = daily.sort_values(["underlying", "report_date"]).reset_index(drop=True)
    log_oi = np.log(frame["open_interest"].clip(lower=1))
    trailing = log_oi.groupby(frame["underlying"], sort=False).transform(
        lambda s: s.rolling(INNOVATION_WINDOW, min_periods=INNOVATION_MIN).mean().shift(1)
    )
    frame["oi_innov"] = log_oi - trailing
    frame["put_share"] = frame["put_open_interest"] / frame["open_interest"].clip(lower=1)

    changes = inventory_changes(frame, min_history=min_history)
    # get_indexer takes any array-like at runtime; the stubs ask for an Index.
    position = calendar.get_indexer(changes["report_date"])  # type: ignore[arg-type]
    later = frame[["underlying", "report_date", "oi_innov"]].assign(
        position=calendar.get_indexer(frame["report_date"]) - PLACEBO_LEAD  # type: ignore[arg-type]
    )
    changes = changes.assign(position=position).merge(
        later.drop(columns="report_date").rename(columns={"oi_innov": "oi_innov_placebo"}),
        on=["underlying", "position"],
        how="left",
    )
    columns = ["underlying", "report_date", "available_at", *PREDICTORS]
    return changes[columns].rename(columns={"underlying": "symbol", "report_date": "date"})


def build_predictive_panel(
    daily: pd.DataFrame, bars: pd.DataFrame, *, min_history: int = 40
) -> pd.DataFrame:
    """One row per underlying and activity date T: predictors at T, controls at T, and
    outcomes realised from ``available_at(T)``.

    Underlyings with fewer than ``min_history`` activity dates, or fewer than that many
    complete rows once joined to the bars, are dropped. An underlying with no bars (an
    index, or a symbol the bar provider does not carry) drops out at the join.
    """
    sessions = session_frame(bars)
    frame = inventory_predictors(daily, min_history)
    controls = sessions[["symbol", "session", *CONTROLS]].rename(columns={"session": "date"})
    frame = frame.merge(controls, on=["symbol", "date"], how="inner")
    frame = join_outcomes(frame, sessions)
    frame = frame.dropna(subset=list(_REQUIRED))
    counts = frame.groupby("symbol")["date"].transform("size")
    frame = frame[counts >= min_history]
    ordered = ["symbol", "date", "available_at", *PREDICTORS, *CONTROLS, *OUTCOMES]
    return frame[ordered].sort_values(["symbol", "date"]).reset_index(drop=True)


__all__ = [
    "CONTROLS",
    "HORIZONS",
    "INNOVATION_MIN",
    "INNOVATION_WINDOW",
    "OUTCOMES",
    "PLACEBO_LEAD",
    "PREDICTORS",
    "bars_through",
    "build_predictive_panel",
    "inventory_predictors",
    "join_outcomes",
    "session_frame",
]
