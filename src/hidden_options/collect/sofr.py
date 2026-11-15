"""Collector for the Secured Overnight Financing Rate, from the New York Fed.

The New York Fed publishes SOFR each business day with a free JSON interface. It is a
second benchmark beside the Treasury curve for box-spread rates (`measure.box_rates`),
because funding desks quote against it.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from hidden_options.collect.http import build_session, fetch
from hidden_options.collect.storage import write_frame

URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"
SNAPSHOT = "sofr/sofr.parquet"


class SofrParseError(ValueError):
    """Raised when the New York Fed's payload is not in the expected layout."""


def parse_sofr(payload: bytes) -> pd.DataFrame:
    """The payload as `date` and `rate` (percent), sorted by date."""
    try:
        rows = json.loads(payload)["refRates"]
    except (KeyError, ValueError) as exc:
        raise SofrParseError("The SOFR payload has no refRates") from exc
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime([row["effectiveDate"] for row in rows]),
            "rate": [float(row["percentRate"]) for row in rows],
        }
    )
    return frame.drop_duplicates("date").sort_values("date").reset_index(drop=True)


def collect_sofr(
    start: date, end: date, root: Path, *, session: requests.Session | None = None
) -> pd.DataFrame:
    """Fetch SOFR from `start` to `end` and write it under `root`."""
    http = session or build_session()
    params = {"startDate": f"{start:%Y-%m-%d}", "endDate": f"{end:%Y-%m-%d}"}
    frame = parse_sofr(fetch(http, URL, params=params).content)
    write_frame(frame, root / SNAPSHOT)
    return frame


__all__ = ["SNAPSHOT", "SofrParseError", "collect_sofr", "parse_sofr"]
