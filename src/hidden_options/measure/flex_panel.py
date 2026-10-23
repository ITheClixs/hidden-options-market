"""Assemble the OCC FLEX reports into a panel and derive daily state variables.

The reports give, for every cleared FLEX series on every activity date, the open
interest and a mark price. Two things follow that the single-date census could not do.

**Inventory becomes a stock with a history.** Open interest on a series is the amount
outstanding, so its change between dates is the net creation or extinguishment of
hidden inventory in that series. Aggregated per underlying this is a daily flow.

**Positions can be valued rather than scaled.** The report's mark price gives the
dollar value of the open interest directly, which replaces the contracts-times-spot
proxy used before.

A caution carried from earlier work: open interest is unsigned and aggregated across
holders. Nothing here identifies who is long. These are gross inventory measures, and
they are named accordingly.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DAILY_COLUMNS = (
    "report_date",
    "underlying",
    "series",
    "open_interest",
    "mark_value",
    "call_open_interest",
    "put_open_interest",
    "mean_days_to_expiry",
    "near_dated_open_interest",
)

NEAR_DATED_DAYS = 60


@dataclass(frozen=True)
class PanelSummary:
    """Coverage of an assembled panel."""

    dates: int
    underlyings: int
    rows: int
    first_date: pd.Timestamp
    last_date: pd.Timestamp

    def describe(self) -> str:
        return (
            f"{self.dates} activity dates, {self.underlyings:,} underlyings, "
            f"{self.rows:,} series-days, {self.first_date.date()} to {self.last_date.date()}"
        )


def load_panel(root: Path, kinds: tuple[str, ...] = ("equity", "index")) -> pd.DataFrame:
    """Read every stored FLEX report into one frame.

    Files are already partitioned by activity date, so no capture-date deduplication is
    needed here; each date appears once by construction.
    """
    frames = []
    for kind in kinds:
        for path in sorted(glob.glob(str(root / f"occ_flex/date=*/{kind}.parquet"))):
            frames.append(pd.read_parquet(path))
    if not frames:
        raise FileNotFoundError(f"no FLEX reports found under {root}/occ_flex")

    panel = pd.concat(frames, ignore_index=True)
    panel["report_date"] = pd.to_datetime(panel["report_date"])
    panel["expiry"] = pd.to_datetime(panel["expiry"])
    return panel.sort_values(["report_date", "underlying", "expiry", "strike"]).reset_index(
        drop=True
    )


def summarise_panel(panel: pd.DataFrame) -> PanelSummary:
    return PanelSummary(
        dates=panel["report_date"].nunique(),
        underlyings=panel["underlying"].nunique(),
        rows=len(panel),
        first_date=panel["report_date"].min(),
        last_date=panel["report_date"].max(),
    )


def daily_inventory(panel: pd.DataFrame) -> pd.DataFrame:
    """Collapse the series panel to one row per underlying per activity date.

    ``mark_value`` is open interest valued at the report's own mark price and is the
    dollar size of hidden inventory. ``near_dated_open_interest`` isolates contracts
    expiring within sixty days, where any hedging response is most concentrated.
    """
    # reset_index matters: concatenated reports carry duplicate index labels, and any
    # aggregation that indexes back into the parent frame misaligns silently.
    frame = panel.reset_index(drop=True).copy()
    frame["days_to_expiry"] = (frame["expiry"] - frame["report_date"]).dt.days
    frame["mark_value"] = frame["open_interest"] * 100 * frame["mark_price"]
    frame["call_oi"] = frame["open_interest"].where(frame["right"] == "C", 0)
    frame["put_oi"] = frame["open_interest"].where(frame["right"] == "P", 0)

    daily = (
        frame.groupby(["report_date", "underlying"], sort=False)
        .agg(
            series=("strike", "size"),
            open_interest=("open_interest", "sum"),
            mark_value=("mark_value", "sum"),
            call_open_interest=("call_oi", "sum"),
            put_open_interest=("put_oi", "sum"),
            mean_days_to_expiry=("days_to_expiry", "mean"),
        )
        .reset_index()
    )
    near = (
        frame[frame["days_to_expiry"].between(0, NEAR_DATED_DAYS)]
        .groupby(["report_date", "underlying"])["open_interest"]
        .sum()
        .rename("near_dated_open_interest")
    )
    daily = daily.merge(near, on=["report_date", "underlying"], how="left")
    daily["near_dated_open_interest"] = daily["near_dated_open_interest"].fillna(0.0)
    return daily[list(DAILY_COLUMNS)]


def inventory_changes(daily: pd.DataFrame, min_history: int = 20) -> pd.DataFrame:
    """Day-over-day changes in hidden inventory, per underlying.

    ``d_log_oi`` is the change in log open interest, which is comparable across
    underlyings of very different size. Underlyings observed on fewer than
    ``min_history`` dates are dropped: a change series needs a base to be meaningful.
    """
    frame = daily.sort_values(["underlying", "report_date"]).copy()
    counts = frame.groupby("underlying")["report_date"].transform("size")
    frame = frame[counts >= min_history]

    grouped = frame.groupby("underlying", sort=False)
    frame["d_open_interest"] = grouped["open_interest"].diff()
    frame["d_mark_value"] = grouped["mark_value"].diff()
    frame["d_log_oi"] = grouped["open_interest"].transform(lambda s: np.log(s.clip(lower=1)).diff())
    frame["d_near_dated"] = grouped["near_dated_open_interest"].diff()
    return frame.dropna(subset=["d_log_oi"]).reset_index(drop=True)


__all__ = [
    "DAILY_COLUMNS",
    "NEAR_DATED_DAYS",
    "PanelSummary",
    "daily_inventory",
    "inventory_changes",
    "load_panel",
    "summarise_panel",
]
