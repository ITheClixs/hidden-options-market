"""A synthetic FLEX market for the market-level tests.

`synthetic_market` has the two features the market measures exist for: a growth break at a
known date and the monthly expiry sawtooth of the real report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PANEL_COLUMNS = (
    "report_date",
    "kind",
    "class_name",
    "root",
    "underlying",
    "right",
    "expiry",
    "strike",
    "mark_price",
    "open_interest",
)


def make_panel(rows) -> pd.DataFrame:
    """rows: (report_date, underlying, right, expiry, strike, mark, oi)"""
    return pd.DataFrame(
        [
            {
                "report_date": pd.Timestamp(d),
                "kind": "equity",
                "class_name": u,
                "root": "1" + u,
                "underlying": u,
                "right": r,
                "expiry": pd.Timestamp(e),
                "strike": k,
                "mark_price": m,
                "open_interest": oi,
            }
            for d, u, r, e, k, m, oi in rows
        ],
        columns=list(PANEL_COLUMNS),
    )


def third_fridays(start: str, end: str) -> pd.DatetimeIndex:
    months = pd.date_range(pd.Timestamp(start).to_period("M").start_time, end, freq="MS")
    return pd.DatetimeIndex([m + pd.offsets.WeekOfMonth(week=2, weekday=4) for m in months])


def synthetic_market(
    start: str = "2025-01-02",
    end: str = "2025-12-31",
    break_at: str = "2025-05-01",
    growth: float = 0.8,
    underlyings: int = 12,
) -> pd.DataFrame:
    """A market flat until `break_at`, then growing at `growth` log points a year.

    Every underlying holds a call and a put in each monthly expiry up to a year out. A
    series grows as it nears expiry and is gone the activity date after it, so the front
    cohort is about an eighth of the book and the total has the real report's sawtooth.
    """
    calendar = pd.DataFrame({"report_date": pd.bdate_range(start, end)})
    horizon = pd.Timestamp(end) + pd.Timedelta(days=400)
    cohorts = pd.DataFrame({"expiry": third_fridays(start, str(horizon.date()))})
    grid = calendar.merge(cohorts, how="cross")
    days = (grid["expiry"] - grid["report_date"]).dt.days
    grid = grid[(days >= 0) & (days <= 365)].reset_index(drop=True)
    days = (grid["expiry"] - grid["report_date"]).dt.days

    years = (grid["report_date"] - pd.Timestamp(break_at)).dt.days.clip(lower=0) / 365.25
    grid["base"] = 1000 * np.exp(growth * years) * (1 + (365 - days) / 180)

    names = pd.DataFrame({"underlying": [f"U{u:02d}" for u in range(underlyings)]})
    names["size"] = np.arange(1, underlyings + 1)
    rights = pd.DataFrame({"right": ["C", "P"]})
    panel = grid.merge(names, how="cross").merge(rights, how="cross")
    panel["open_interest"] = (panel["base"] * panel["size"]).round().astype("int64")
    panel["kind"] = "equity"
    panel["class_name"] = panel["underlying"]
    panel["root"] = "1" + panel["underlying"]
    panel["strike"] = 100.0
    panel["mark_price"] = 2.0
    return panel[list(PANEL_COLUMNS)]
