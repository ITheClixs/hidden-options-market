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
import re
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

CHANGE_COLUMNS = ("d_open_interest", "d_mark_value", "d_log_oi", "d_near_dated")

# Exercise-style markers in a class heading, as OCC spells them. The heading field is cut
# at thirty characters, so a marker is often clipped ("(AMER/F", "(EUR"), and a continued
# heading ends in "(CONT)".
_STYLE_MARKERS = (("AMER/FLEX", "american"), ("EURO/FLEX", "european"))
# Shorter stubs ("(A", "(AM", "(E") also fit "(AM SETTLED)", "(ADR)" and the like.
_MIN_CLIPPED_MARKER = 3
_CONTINUATION = re.compile(r"\s*\(CONT\)\s*$", re.IGNORECASE)
# A parenthetical that is either closed or runs to the end of the (clipped) heading.
_PARENTHETICAL = re.compile(r"\(([^()]*)(\)|$)")


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


def parse_exercise_style(class_name: object) -> str | None:
    """Read ``"american"`` or ``"european"`` from a class heading, else ``None``.

    Equity headings carry ``(AMER/FLEX)`` or ``(EURO/FLEX)`` when OCC marks them, and
    many are unmarked. A closed parenthetical must spell the marker out; one that runs
    into the thirty-character cut-off may be a clipped marker of at least three letters.
    Anything shorter is left unknown rather than guessed, and so is a heading that
    carries both markers.
    """
    if not isinstance(class_name, str):
        return None
    heading = _CONTINUATION.sub("", class_name)
    found = set()
    for text, closer in _PARENTHETICAL.findall(heading):
        token = re.sub(r"[\s/]+", "/", text.strip().upper())
        for marker, style in _STYLE_MARKERS:
            clipped = not closer and len(token) >= _MIN_CLIPPED_MARKER
            if token == marker or (clipped and marker.startswith(token)):
                found.add(style)
    return found.pop() if len(found) == 1 else None


def _exercise_styles(panel: pd.DataFrame) -> np.ndarray:
    """Exercise style per row: the heading's own marker, else European for indices.

    Index options are European-style as a rule and their headings seldom use the equity
    markers, so an unmarked index heading is read as European. An unmarked equity heading
    stays ``None``: American and European FLEX equity options both exist.
    """
    codes, headings = pd.factorize(panel["class_name"])
    table = np.array([parse_exercise_style(h) for h in headings] + [None], dtype=object)
    styles = table[codes]  # a missing heading has code -1 and takes the trailing None
    index_default = (panel["kind"] == "index").to_numpy() & pd.isna(styles)
    return np.where(index_default, "european", styles)


def _available_at(report_dates: pd.Series) -> pd.DatetimeIndex:
    """When each activity date's report can first be acted on.

    OCC publishes the report for activity date T overnight, so an observer has it before
    the next session: the next date in the panel's own calendar. The calendar is the
    panel's, not each underlying's, because a date is absent for everyone or no one. The
    last date has no successor yet and takes the next weekday.
    """
    calendar = pd.DatetimeIndex(report_dates.unique()).sort_values()
    following = calendar[1:].append(pd.DatetimeIndex([calendar[-1] + pd.offsets.BDay(1)]))
    return following.take(calendar.get_indexer(report_dates))


def load_panel(root: Path, kinds: tuple[str, ...] = ("equity", "index")) -> pd.DataFrame:
    """Read every stored FLEX report into one frame.

    Files are already partitioned by activity date, so no capture-date deduplication is
    needed here; each date appears once by construction.

    Two point-in-time fields are added. ``available_at`` is when the report for a row's
    activity date can be acted on; a predictor built from that date may only meet outcomes
    realised on or after it. ``exercise_style`` is ``"american"``, ``"european"`` or
    ``None`` where the class heading does not say.
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
    panel = panel.sort_values(["report_date", "underlying", "expiry", "strike"]).reset_index(
        drop=True
    )
    panel["available_at"] = _available_at(panel["report_date"])
    # Object dtype keeps the unknowns as None; a bare array would be coerced to NaN.
    panel["exercise_style"] = pd.Series(_exercise_styles(panel), index=panel.index, dtype=object)
    return panel


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

    A change is only one day of flow if the previous row is the immediately preceding
    activity date. When an underlying skips a date that other underlyings reported, the
    row after the skip spans several days, so its changes are set to NaN; the row stays
    so the gap is visible. A date no underlying reported (a market holiday) is not a skip.
    The calendar is every date in ``daily``, so pass the full daily panel, not a subset.
    """
    calendar = pd.DatetimeIndex(daily["report_date"].unique()).sort_values()
    frame = daily.sort_values(["underlying", "report_date"]).reset_index(drop=True)
    counts = frame.groupby("underlying")["report_date"].transform("size")
    frame = frame[counts >= min_history].copy()

    grouped = frame.groupby("underlying", sort=False)
    frame["d_open_interest"] = grouped["open_interest"].diff()
    frame["d_mark_value"] = grouped["mark_value"].diff()
    frame["d_log_oi"] = grouped["open_interest"].transform(lambda s: np.log(s.clip(lower=1)).diff())
    frame["d_near_dated"] = grouped["near_dated_open_interest"].diff()

    position = pd.Series(calendar.get_indexer(frame["report_date"]), index=frame.index)
    previous = position.groupby(frame["underlying"], sort=False).shift(1)
    skipped = previous.notna() & (position - previous != 1)

    frame = frame.dropna(subset=["d_log_oi"])
    frame.loc[skipped[frame.index], list(CHANGE_COLUMNS)] = np.nan
    return frame.reset_index(drop=True)


__all__ = [
    "CHANGE_COLUMNS",
    "DAILY_COLUMNS",
    "NEAR_DATED_DAYS",
    "PanelSummary",
    "daily_inventory",
    "inventory_changes",
    "load_panel",
    "parse_exercise_style",
    "summarise_panel",
]
