"""Collector for Cboe's free delayed full option chain.

Cboe publishes, per underlying, a JSON document containing every listed series with
two-sided quotes *and quote sizes*, greeks, implied volatility, volume and open
interest. Quote sizes are the reason this source matters: they are what makes an
honest transaction-cost model possible without paid data.

Parsing is separated from fetching so the wire format can be tested offline.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import requests

from absorb.collect.http import FetchError, fetch
from absorb.config import CBOE_CHAIN_URL

# OSI-style contract identifier, e.g. MSTR260814C00030000
_CONTRACT_RE = re.compile(r"^(?P<root>[A-Z0-9^./_-]{1,6}?)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<right>[CP])(?P<strike>\d{8})$")

_OPTION_FIELDS = (
    "bid",
    "bid_size",
    "ask",
    "ask_size",
    "iv",
    "open_interest",
    "volume",
    "delta",
    "gamma",
    "vega",
    "theta",
    "rho",
    "theo",
    "last_trade_price",
    "prev_day_close",
)

CHAIN_COLUMNS = (
    "symbol",
    "quote_timestamp",
    "underlying_price",
    "contract",
    "expiry",
    "right",
    "strike",
    *_OPTION_FIELDS,
    "last_trade_time",
)


class ChainParseError(ValueError):
    """Raised when a Cboe payload does not match the expected shape."""


@dataclass(frozen=True)
class ChainSnapshot:
    """One symbol's chain at one point in time, plus provenance."""

    symbol: str
    quote_timestamp: str
    frame: pd.DataFrame
    payload_sha256: str

    @property
    def n_contracts(self) -> int:
        return len(self.frame)


def parse_contract(contract: str) -> tuple[date, str, float]:
    """Split an OSI contract identifier into (expiry, right, strike).

    Raises ChainParseError rather than returning None, so a vendor format change
    surfaces loudly instead of silently dropping rows.
    """
    match = _CONTRACT_RE.match(contract.strip())
    if match is None:
        raise ChainParseError(f"Unrecognised contract identifier: {contract!r}")

    parts = match.groupdict()
    try:
        expiry = date(2000 + int(parts["yy"]), int(parts["mm"]), int(parts["dd"]))
    except ValueError as exc:
        raise ChainParseError(f"Contract {contract!r} encodes an invalid date: {exc}") from exc

    return expiry, parts["right"], int(parts["strike"]) / 1000.0


def parse_chain(symbol: str, payload: bytes) -> ChainSnapshot:
    """Convert a raw Cboe chain payload into a normalised frame."""
    digest = hashlib.sha256(payload).hexdigest()

    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ChainParseError(f"{symbol}: payload is not valid JSON: {exc}") from exc

    data = document.get("data")
    if not isinstance(data, dict):
        raise ChainParseError(f"{symbol}: payload has no 'data' object")

    options = data.get("options")
    if not isinstance(options, list) or not options:
        raise ChainParseError(f"{symbol}: payload contains no option records")

    quote_timestamp = str(document.get("timestamp", ""))
    underlying_price = data.get("current_price")

    records = []
    for entry in options:
        contract = entry.get("option")
        if not contract:
            raise ChainParseError(f"{symbol}: option record without an 'option' field")
        expiry, right, strike = parse_contract(contract)
        record = {
            "symbol": symbol,
            "quote_timestamp": quote_timestamp,
            "underlying_price": underlying_price,
            "contract": contract,
            "expiry": expiry,
            "right": right,
            "strike": strike,
            "last_trade_time": entry.get("last_trade_time"),
        }
        record.update({field: entry.get(field) for field in _OPTION_FIELDS})
        records.append(record)

    frame = pd.DataFrame.from_records(records, columns=list(CHAIN_COLUMNS))
    return ChainSnapshot(
        symbol=symbol,
        quote_timestamp=quote_timestamp,
        frame=frame,
        payload_sha256=digest,
    )


def fetch_chain(session: requests.Session, symbol: str) -> ChainSnapshot:
    """Retrieve and parse one symbol's chain.

    Propagates FetchError for network problems and ChainParseError for format
    problems; the caller decides whether one bad symbol should abort the run.
    """
    url = CBOE_CHAIN_URL.format(symbol=symbol)
    result = fetch(session, url)
    return parse_chain(symbol, result.content)


def snapshot_partition(snapshot: ChainSnapshot, as_of: datetime) -> str:
    """Relative storage path for a snapshot, partitioned by capture date."""
    safe_symbol = snapshot.symbol.lstrip("_") or snapshot.symbol
    prefix = "index" if snapshot.symbol.startswith("_") else "equity"
    return f"cboe_chain/date={as_of:%Y-%m-%d}/{prefix}_{safe_symbol}.parquet"


__all__ = [
    "CHAIN_COLUMNS",
    "ChainParseError",
    "ChainSnapshot",
    "FetchError",
    "fetch_chain",
    "parse_chain",
    "parse_contract",
    "snapshot_partition",
]
