"""Collector for the US Treasury's daily par yield curve.

The Treasury publishes one CSV per calendar year: a row per business day and a column per
constant maturity, in percent. It is the benchmark beside which box-spread rates are set
(`measure.box_rates`). Maturities the Treasury did not publish on a date are missing.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

from hidden_options.collect.http import build_session, fetch
from hidden_options.collect.storage import write_frame

URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
)
PARAMS = {"type": "daily_treasury_yield_curve", "_format": "csv"}
SNAPSHOT = "treasury/par_yields.parquet"


class TreasuryCurveError(ValueError):
    """Raised when a yield-curve file is not in the expected layout."""


def parse_curve(payload: bytes) -> pd.DataFrame:
    """One year's file as a frame: `date` and one column of yields per maturity."""
    frame = pd.read_csv(io.BytesIO(payload))
    if "Date" not in frame.columns or len(frame.columns) < 2:
        raise TreasuryCurveError("The yield-curve file has no Date column or no maturities")
    frame = frame.rename(columns={"Date": "date"})
    frame["date"] = pd.to_datetime(frame["date"], format="%m/%d/%Y")
    maturities = [column for column in frame.columns if column != "date"]
    frame[maturities] = frame[maturities].apply(pd.to_numeric, errors="coerce")
    return frame.sort_values("date").reset_index(drop=True)


def collect_curve(
    years: range, root: Path, *, session: requests.Session | None = None
) -> pd.DataFrame:
    """Fetch each year's curve, join them and write the result under `root`."""
    http = session or build_session()
    parts = []
    for year in years:
        params = {**PARAMS, "field_tdr_date_value": str(year)}
        parts.append(parse_curve(fetch(http, URL.format(year=year), params=params).content))
    curve = pd.concat(parts, ignore_index=True).drop_duplicates("date").sort_values("date")
    curve = curve.reset_index(drop=True)
    write_frame(curve, root / SNAPSHOT)
    return curve


__all__ = ["SNAPSHOT", "TreasuryCurveError", "collect_curve", "parse_curve"]
