"""Collector for intraday underlying bars.

Why this exists
---------------
The roll-window test needs intraday returns on the underlying. Free intraday history
is shallow — 5-minute bars reach back 60 days and 1-minute bars 7 days — so two years
of it cannot be downloaded, only accumulated. The power arithmetic in
`docs/POWER_AND_DATA_LIMITS.md` shows the achievable minimum detectable effect falls
from roughly 27 bp on the free 60-day window to roughly 9 bp after a year of
accumulation, which is the difference between a test that can see the hypothesised
effect and one that cannot.

Each run fetches an overlapping window rather than only the current day. Re-fetching
days already held is cheap and means a missed run repairs itself on the next one,
which matters because these bars cannot be recovered once they age out.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
import requests

from absorb.collect.http import fetch

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

BAR_COLUMNS = (
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)

# Depth available per interval. Requesting more than the provider retains silently
# returns less, so these are the honest maxima rather than aspirations.
INTERVAL_MAX_RANGE = {
    "1m": "7d",
    "2m": "60d",
    "5m": "60d",
    "15m": "60d",
    "1h": "730d",
    "1d": "10y",
}


class BarParseError(ValueError):
    """Raised when a chart payload does not match the expected shape."""


@dataclass(frozen=True)
class BarSnapshot:
    """One symbol's bars over one fetched window, plus provenance."""

    symbol: str
    interval: str
    frame: pd.DataFrame
    payload_sha256: str

    @property
    def n_bars(self) -> int:
        return len(self.frame)

    @property
    def first_timestamp(self) -> pd.Timestamp | None:
        return self.frame["timestamp"].min() if len(self.frame) else None

    @property
    def last_timestamp(self) -> pd.Timestamp | None:
        return self.frame["timestamp"].max() if len(self.frame) else None


def parse_chart(symbol: str, interval: str, payload: bytes) -> BarSnapshot:
    """Convert a chart payload into a normalised bar frame."""
    digest = hashlib.sha256(payload).hexdigest()

    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BarParseError(f"{symbol}: payload is not valid JSON: {exc}") from exc

    chart = document.get("chart")
    if not isinstance(chart, dict):
        raise BarParseError(f"{symbol}: payload has no 'chart' object")
    if chart.get("error"):
        raise BarParseError(f"{symbol}: provider returned error {chart['error']}")

    results = chart.get("result")
    if not results:
        raise BarParseError(f"{symbol}: payload contains no result")

    result = results[0]
    timestamps = result.get("timestamp")
    if not timestamps:
        # A symbol that exists but has no bars in the window (a fresh listing, or a
        # halt) is not a parse failure, but it must not be written as valid data.
        raise BarParseError(f"{symbol}: no bars returned for interval {interval}")

    try:
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise BarParseError(f"{symbol}: payload has no quote series: {exc}") from exc

    frame = pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": pd.to_datetime(timestamps, unit="s", utc=True),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        },
        columns=list(BAR_COLUMNS),
    )

    # Providers pad the grid with empty bars outside trading; those carry no
    # information and would distort any return computed across them.
    frame = frame.dropna(subset=["close"]).reset_index(drop=True)
    if frame.empty:
        raise BarParseError(f"{symbol}: all bars were empty for interval {interval}")

    return BarSnapshot(symbol=symbol, interval=interval, frame=frame, payload_sha256=digest)


def fetch_bars(
    session: requests.Session, symbol: str, *, interval: str = "5m", lookback: str | None = None
) -> BarSnapshot:
    """Retrieve and parse one symbol's bars.

    `lookback` defaults to the deepest window the provider retains for the interval,
    since re-fetching held days is cheap and repairs gaps left by a missed run.
    """
    if interval not in INTERVAL_MAX_RANGE:
        raise ValueError(
            f"Unsupported interval {interval!r}; use one of {sorted(INTERVAL_MAX_RANGE)}"
        )

    window = lookback or INTERVAL_MAX_RANGE[interval]
    result = fetch(
        session,
        CHART_URL.format(symbol=symbol),
        params={"interval": interval, "range": window, "includePrePost": "false"},
    )
    return parse_chart(symbol, interval, result.content)


def snapshot_partition(snapshot: BarSnapshot, as_of: datetime | None = None) -> str:
    """Relative storage path, partitioned by interval and capture date.

    Windows overlap by design, so each capture is stored whole and de-duplicated at
    read time rather than merged in place. That keeps every capture independently
    verifiable against its payload hash.
    """
    stamp = as_of or datetime.now(UTC)
    safe = snapshot.symbol.lstrip("^").replace("=", "_")
    return f"underlying_bars/interval={snapshot.interval}/date={stamp:%Y-%m-%d}/{safe}.parquet"


__all__ = [
    "BAR_COLUMNS",
    "CHART_URL",
    "INTERVAL_MAX_RANGE",
    "BarParseError",
    "BarSnapshot",
    "fetch_bars",
    "parse_chart",
    "snapshot_partition",
]
