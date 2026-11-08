"""The pinning test's positive control: listed strikes at standard monthly expirations.

Specification: `docs/log/2026-11-08-pinning-control-spec.md`. The statistic and inference
are the registered test's (`measure.pinning`); only the events differ. The pin strike is
the strike nearest the previous close on a coarse listed grid, which every optionable name
lists at its monthly expiration, since the finer grids contain it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hidden_options.measure.pinning import WINDOW_SIGMAS, event_statistics

MIN_PRICE = 5.0
# Strike intervals: $2.50 below $25, $5 from $25 to $200, $10 above.
LOW, HIGH = 25.0, 200.0
INTERVALS = (2.5, 5.0, 10.0)
THIRD_FRIDAY_WEEK = 2  # zero-based: the third Friday falls in days 15 to 21


def monthly_expiries(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The standard monthly expiration of every month `days` covers: its third Friday, or
    the last session before it when that Friday is not a session."""
    sessions = pd.DatetimeIndex(sorted(days))
    months = pd.period_range(sessions.min(), sessions.max(), freq="M")
    out = []
    for month in months:
        fridays = pd.date_range(month.start_time, month.end_time, freq="W-FRI")
        third = fridays[THIRD_FRIDAY_WEEK]
        before = sessions[sessions <= third]
        if third <= sessions.max() and len(before) and before[-1] >= third - pd.Timedelta(days=4):
            out.append(before[-1])
    return pd.DatetimeIndex(out)


def grid_strike(prev_close: np.ndarray) -> np.ndarray:
    """The coarse-grid strike nearest each previous close; a tie goes to the lower one."""
    p = np.asarray(prev_close, dtype=float)
    interval = np.select([p < LOW, p <= HIGH], INTERVALS[:2], INTERVALS[2])
    return np.asarray(np.ceil(p / interval - 0.5) * interval, dtype=float)


def control_events(closes: pd.DataFrame, expiries: pd.DatetimeIndex) -> pd.DataFrame:
    """One event per symbol and expiry: `with_sigma` closes on the expiry date give the
    previous close and sigma; the pin strike is its nearest grid strike, kept within
    WINDOW_SIGMAS and for previous closes of at least MIN_PRICE."""
    frame = closes[closes["session"].isin(expiries)].dropna(subset=["prev_close", "sigma"])
    frame = frame[frame["prev_close"] >= MIN_PRICE]
    strike = grid_strike(frame["prev_close"].to_numpy(dtype=float))
    near = np.abs(np.log(strike / frame["prev_close"].to_numpy(dtype=float))) <= (
        WINDOW_SIGMAS * frame["sigma"].to_numpy(dtype=float)
    )
    events = pd.DataFrame(
        {
            "underlying": frame["symbol"].to_numpy(),
            "expiry": frame["session"].to_numpy(),
            "strike": strike,
            "prev_close": frame["prev_close"].to_numpy(dtype=float),
            "sigma": frame["sigma"].to_numpy(dtype=float),
        }
    )
    return pd.DataFrame(events[near].reset_index(drop=True))


def control_statistics(
    closes: pd.DataFrame, days: pd.DatetimeIndex, expiries: pd.DatetimeIndex
) -> pd.DataFrame:
    """`event_statistics` on the control events of `expiries`."""
    return event_statistics(control_events(closes, expiries), closes, days)


__all__ = [
    "INTERVALS",
    "MIN_PRICE",
    "control_events",
    "control_statistics",
    "grid_strike",
    "monthly_expiries",
]
