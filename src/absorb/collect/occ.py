"""Collector for OCC series-level open interest.

OCC's series search is the authoritative record of open interest per contract series
and is free and unauthenticated. It is the independent cross-check on positions
inferred from fund holdings: if a fund reports writing N contracts of a series, that
series' open interest should move by a corresponding amount.

The endpoint returns a tab-delimited text report, not JSON, so parsing is defensive.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import requests

from absorb.collect.http import fetch
from absorb.config import OCC_SERIES_URL

_HEADER_TOKEN = "ProductSymbol"
_EXPECTED_FIELDS = 10

OPEN_INTEREST_COLUMNS = (
    "symbol",
    "product_symbol",
    "expiry",
    "strike",
    "call_open_interest",
    "put_open_interest",
    "position_limit",
)


class OccParseError(ValueError):
    """Raised when an OCC report does not match the expected layout."""


@dataclass(frozen=True)
class OpenInterestSnapshot:
    """One underlying's series-level open interest, plus provenance."""

    symbol: str
    frame: pd.DataFrame
    payload_sha256: str

    @property
    def n_series(self) -> int:
        return len(self.frame)


def _tokenise(line: str) -> list[str]:
    return [token.strip() for token in line.split("\t") if token.strip()]


def parse_open_interest(symbol: str, payload: bytes) -> OpenInterestSnapshot:
    """Parse the OCC series-search report into a normalised frame.

    Lines that do not carry the expected field count are skipped, but if *no* data
    line parses the function raises, so a silent layout change cannot masquerade as
    a symbol with no open interest.
    """
    digest = hashlib.sha256(payload).hexdigest()
    text = payload.decode("utf-8", errors="replace")

    lines = text.splitlines()
    header_index = next((i for i, line in enumerate(lines) if _HEADER_TOKEN in line), None)
    if header_index is None:
        raise OccParseError(f"{symbol}: no '{_HEADER_TOKEN}' header found in OCC report")

    records = []
    skipped = 0
    for line in lines[header_index + 1 :]:
        tokens = _tokenise(line)
        if len(tokens) != _EXPECTED_FIELDS:
            skipped += 1
            continue
        product, year, month, day, whole, frac, _right, call_oi, put_oi, limit = tokens
        try:
            expiry = date(int(year), int(month), int(day))
            strike = int(whole) + int(frac) / 1000.0
            record = {
                "symbol": symbol,
                "product_symbol": product,
                "expiry": expiry,
                "strike": strike,
                "call_open_interest": int(call_oi),
                "put_open_interest": int(put_oi),
                "position_limit": int(limit),
            }
        except ValueError:
            skipped += 1
            continue
        records.append(record)

    if not records:
        raise OccParseError(
            f"{symbol}: OCC report had a header but no parseable data rows "
            f"({skipped} lines skipped); the layout may have changed"
        )

    frame = pd.DataFrame.from_records(records, columns=list(OPEN_INTEREST_COLUMNS))
    return OpenInterestSnapshot(symbol=symbol, frame=frame, payload_sha256=digest)


def fetch_open_interest(session: requests.Session, symbol: str) -> OpenInterestSnapshot:
    """Retrieve and parse one underlying's series-level open interest."""
    result = fetch(session, OCC_SERIES_URL, params={"symbolType": "U", "symbol": symbol})
    return parse_open_interest(symbol, result.content)


def snapshot_partition(snapshot: OpenInterestSnapshot, as_of: datetime) -> str:
    """Relative storage path for a snapshot, partitioned by capture date."""
    return f"occ_open_interest/date={as_of:%Y-%m-%d}/{snapshot.symbol}.parquet"


__all__ = [
    "OPEN_INTEREST_COLUMNS",
    "OccParseError",
    "OpenInterestSnapshot",
    "fetch_open_interest",
    "parse_open_interest",
    "snapshot_partition",
]
