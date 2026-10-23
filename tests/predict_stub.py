"""Synthetic inventory and bars for the predictive tests.

`synthetic_daily` has the shape `daily_inventory` returns, including `available_at`, and
`synthetic_bars` has the shape of the bars file, stamped at the 13:30 UTC open the way the
provider stamps them. The bars start well before the first activity date, so the trailing
controls exist from the start, and end a few sessions after the last.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hidden_options.collect.bars import BAR_COLUMNS
from hidden_options.measure.flex_panel import DAILY_COLUMNS


def available_at(calendar: pd.DatetimeIndex) -> pd.Series:
    """The next activity date, and for the last one the next weekday."""
    following = list(calendar[1:]) + [calendar[-1] + pd.offsets.BDay(1)]
    return pd.Series(following, index=calendar)


def synthetic_daily(
    names: int = 6,
    dates: int = 80,
    start: str = "2025-01-02",
    *,
    skip: dict[str, list[str]] | None = None,
    calendar: pd.DatetimeIndex | None = None,
    seed: int = 7,
) -> pd.DataFrame:
    """Daily inventory for `names` underlyings on a shared calendar of activity dates.

    `skip` removes a name from the listed dates while others still report on them.
    """
    rng = np.random.default_rng(seed)
    days = calendar if calendar is not None else pd.bdate_range(start, periods=dates)
    next_date = available_at(days)
    frames = []
    for i in range(names):
        name = f"N{i:02d}"
        oi = np.exp(8 + np.cumsum(rng.normal(0, 0.05, len(days))))
        near = oi * rng.uniform(0.2, 0.8, len(days))
        puts = oi * rng.uniform(0.1, 0.6, len(days))
        frame = pd.DataFrame(
            {
                "report_date": days,
                "available_at": next_date.to_numpy(),
                "underlying": name,
                "series": 10,
                "open_interest": oi.round(),
                "mark_value": oi * 150.0,
                "call_open_interest": (oi - puts).round(),
                "put_open_interest": puts.round(),
                "mean_days_to_expiry": 45.0,
                "near_dated_open_interest": near.round(),
            }
        )
        missing = pd.DatetimeIndex((skip or {}).get(name, []))
        frames.append(frame[~frame["report_date"].isin(missing)])
    daily = pd.concat(frames, ignore_index=True)
    return daily[list(DAILY_COLUMNS)]


def synthetic_bars(
    daily: pd.DataFrame, *, lead: int = 40, tail: int = 15, seed: int = 11
) -> pd.DataFrame:
    """Daily bars for every name in `daily`, from `lead` sessions before its first date."""
    rng = np.random.default_rng(seed)
    first, last = daily["report_date"].min(), daily["report_date"].max()
    sessions = pd.bdate_range(first - pd.offsets.BDay(lead), last + pd.offsets.BDay(tail))
    frames = []
    for name in sorted(daily["underlying"].unique()):
        overnight = rng.normal(0, 0.01, len(sessions))
        intraday = rng.normal(0, 0.015, len(sessions))
        opens = 50 * np.exp(np.cumsum(overnight + np.r_[0.0, intraday[:-1]]))
        closes = opens * np.exp(intraday)
        frames.append(
            pd.DataFrame(
                {
                    "symbol": name,
                    "timestamp": (sessions + pd.Timedelta(hours=13, minutes=30)).tz_localize("UTC"),
                    "open": opens,
                    "high": np.maximum(opens, closes) * 1.01,
                    "low": np.minimum(opens, closes) * 0.99,
                    "close": closes,
                    "volume": rng.integers(10_000, 100_000, len(sessions)).astype(float),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)[list(BAR_COLUMNS)]


def session_table(bars: pd.DataFrame) -> pd.DataFrame:
    """Per symbol and New York session: open, close and the close-to-close return.

    Written independently of the module under test, so the timing tests check it against
    arithmetic rather than against itself.
    """
    frame = bars.copy()
    frame["session"] = (
        frame["timestamp"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    )
    frame = frame.sort_values(["symbol", "session"])
    frame["ret"] = frame.groupby("symbol")["close"].pct_change()
    return frame.set_index(["symbol", "session"])


def noise_panel(
    names: int = 60, dates: int = 80, *, beta: float = 0.0, seed: int = 3
) -> pd.DataFrame:
    """A plain regression panel: outcome `y`, predictor `x`, two controls, entity and date.

    The outcome carries entity and date effects so the fixed effects have work to do, and
    `x` is correlated with the controls so partialling them out matters.
    """
    rng = np.random.default_rng(seed)
    symbol = np.repeat([f"S{i:03d}" for i in range(names)], dates)
    date = np.tile(pd.bdate_range("2025-01-02", periods=dates), names)
    c1 = rng.normal(size=names * dates)
    c2 = rng.normal(size=names * dates)
    x = 0.5 * c1 + rng.normal(size=names * dates)
    entity_effect = np.repeat(rng.normal(size=names), dates)
    date_effect = np.tile(rng.normal(size=dates), names)
    y = beta * x + 0.3 * c1 - 0.2 * c2 + entity_effect + date_effect + rng.normal(size=x.size)
    return pd.DataFrame({"symbol": symbol, "date": date, "y": y, "x": x, "c1": c1, "c2": c2})


def synthetic_flex_panel(
    names: int = 8, dates: int = 90, start: str = "2025-01-02", *, seed: int = 5
) -> pd.DataFrame:
    """A series-level FLEX panel: per equity name and date a near call and a far put,
    plus one index underlying (SPX) that has no equity bars."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=dates)
    next_date = available_at(days)
    rows = []
    for i in range(names + 1):
        name, kind = (f"N{i:02d}", "equity") if i < names else ("SPX", "index")
        calls = np.exp(7 + np.cumsum(rng.normal(0, 0.05, dates)))
        puts = np.exp(7 + np.cumsum(rng.normal(0, 0.05, dates)))
        for day, call_oi, put_oi in zip(days, calls, puts, strict=True):
            for right, expiry, oi in (
                ("C", day + pd.Timedelta(days=30), call_oi),
                ("P", day + pd.Timedelta(days=200), put_oi),
            ):
                rows.append(
                    {
                        "report_date": day,
                        "available_at": next_date[day],
                        "kind": kind,
                        "class_name": name,
                        "root": "1" + name,
                        "underlying": name,
                        "right": right,
                        "expiry": expiry,
                        "strike": 100.0,
                        "mark_price": 2.0,
                        "open_interest": float(round(oi)),
                    }
                )
    return pd.DataFrame(rows)
