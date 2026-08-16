"""Collector for issuer-published daily ETF holdings.

Holdings files are overwritten in place each day, so an uncollected day is gone
permanently. This collector is therefore the most time-critical component in the
project.

Two things matter for the study and both are recovered here:

* the exact option leg (root, expiry, right, strike, signed contract count), and
* the fund's scale (net assets, shares outstanding), which sizes the flow.

Position tickers arrive space-padded in an OSI-like form, e.g. ``MSTR  260814C00106000``
and ``2MSTR 260918P00100010``. The leading-digit roots ("2MSTR") denote non-standard
deliverable series, which is how the synthetic-long put leg is written.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import requests

from absorb.collect.cboe import ChainParseError, parse_contract
from absorb.collect.http import fetch

HOLDINGS_COLUMNS = (
    "fund",
    "as_of",
    "position_ticker",
    "security_name",
    "contracts",
    "price",
    "market_value",
    "weight",
    "net_assets",
    "shares_outstanding",
    "is_option",
    "option_root",
    "expiry",
    "right",
    "strike",
)

_REQUIRED_SOURCE_COLUMNS = ("Date", "StockTicker", "Shares", "MarketValue")


class HoldingsParseError(ValueError):
    """Raised when an issuer holdings file does not match the expected layout."""


@dataclass(frozen=True)
class HoldingsSnapshot:
    """One fund's holdings on one day, plus provenance."""

    fund: str
    as_of: date | None
    frame: pd.DataFrame
    payload_sha256: str

    @property
    def n_positions(self) -> int:
        return len(self.frame)

    @property
    def n_option_legs(self) -> int:
        return int(self.frame["is_option"].sum())


def normalise_position_ticker(raw: str) -> str:
    """Collapse the issuer's space padding into a compact OSI identifier."""
    return "".join(str(raw).split())


def split_option_ticker(raw: str) -> tuple[str, date, str, float] | None:
    """Return (root, expiry, right, strike) if the ticker is an option, else None.

    A non-option row (Treasury bill, cash, money-market fund) is not an error, so
    this returns None rather than raising; malformed *option-looking* tickers still
    raise via parse_contract.
    """
    compact = normalise_position_ticker(raw)
    if len(compact) < 15 or not compact[-15:-9].isdigit():
        return None

    try:
        expiry, right, strike = parse_contract(compact)
    except ChainParseError:
        return None
    return compact[:-15], expiry, right, strike


def _parse_money(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).replace(",", "").replace("$", "").strip()
    if not text or text in {"-", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_holdings(fund: str, payload: bytes) -> HoldingsSnapshot:
    """Parse an issuer holdings CSV into a normalised frame."""
    digest = hashlib.sha256(payload).hexdigest()

    try:
        source = pd.read_csv(io.BytesIO(payload))
    except Exception as exc:  # noqa: BLE001 - pandas raises many unrelated types here
        raise HoldingsParseError(f"{fund}: holdings payload is not readable CSV: {exc}") from exc

    missing = [c for c in _REQUIRED_SOURCE_COLUMNS if c not in source.columns]
    if missing:
        raise HoldingsParseError(
            f"{fund}: holdings file is missing required columns {missing}; "
            f"got {list(source.columns)}"
        )
    if source.empty:
        raise HoldingsParseError(f"{fund}: holdings file has a header but no rows")

    as_of = pd.to_datetime(source["Date"].iloc[0], errors="coerce")
    as_of_date = None if pd.isna(as_of) else as_of.date()

    records = []
    for row in source.to_dict("records"):
        ticker = row.get("StockTicker", "")
        option = split_option_ticker(ticker)
        records.append(
            {
                "fund": fund,
                "as_of": as_of_date,
                "position_ticker": normalise_position_ticker(ticker),
                "security_name": row.get("SecurityName"),
                "contracts": _parse_money(row.get("Shares")),
                "price": _parse_money(row.get("Price")),
                "market_value": _parse_money(row.get("MarketValue")),
                "weight": row.get("Weightings"),
                "net_assets": _parse_money(row.get("NetAssets")),
                "shares_outstanding": _parse_money(row.get("SharesOutstanding")),
                "is_option": option is not None,
                "option_root": option[0] if option else None,
                "expiry": option[1] if option else None,
                "right": option[2] if option else None,
                "strike": option[3] if option else None,
            }
        )

    frame = pd.DataFrame.from_records(records, columns=list(HOLDINGS_COLUMNS))
    return HoldingsSnapshot(fund=fund, as_of=as_of_date, frame=frame, payload_sha256=digest)


def fetch_holdings(session: requests.Session, fund: str, url_template: str) -> HoldingsSnapshot:
    """Retrieve and parse one fund's holdings file."""
    result = fetch(session, url_template.format(ticker=fund.upper()))
    return parse_holdings(fund.upper(), result.content)


def snapshot_partition(snapshot: HoldingsSnapshot, as_of: datetime) -> str:
    """Relative storage path, partitioned by capture date (not file date, which can lead)."""
    return f"fund_holdings/date={as_of:%Y-%m-%d}/{snapshot.fund}.parquet"


__all__ = [
    "HOLDINGS_COLUMNS",
    "HoldingsParseError",
    "HoldingsSnapshot",
    "fetch_holdings",
    "normalise_position_ticker",
    "parse_holdings",
    "snapshot_partition",
    "split_option_ticker",
]
