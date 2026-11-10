"""Parsers for two issuer holdings sources that the daily fund collector does not cover.

* Innovator publishes one CSV holding every fund's positions, in the layout the fund
  collector already reads, with the fund in an `Account` column.
* The BOXX fund page carries its holdings as an HTML table: ticker, name, CUSIP, quantity,
  price, market value and weight.

Both give signed quantities and OSI-style option tickers whose root keeps the FLEX prefix
(`4SPY  261231C00006830`). Only option lines are kept. The files are overwritten in place,
so a day not captured is gone.
"""

from __future__ import annotations

import html
import io
import re

import pandas as pd

from hidden_options.collect.holdings import split_option_ticker

INNOVATOR_URL = "https://www.innovatoretfs.com/etf/xt_holdings.csv"
BOXX_URL = "https://funds.alphaarchitect.com/boxx/"
HOLDING_COLUMNS = (
    "fund",
    "as_of",
    "position_ticker",
    "option_root",
    "expiry",
    "right",
    "strike",
    "contracts",
    "price",
    "net_assets",
)
FAMILY_SOURCE_COLUMNS = ("Date", "Account", "StockTicker", "Shares", "Price", "NetAssets")

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG = re.compile(r"<[^>]+>")
_TICKER = re.compile(r"\d?[A-Z]+\s+\d{6}[CP]\d{8}")


class SnapshotParseError(ValueError):
    """Raised when an issuer snapshot is not in the expected layout."""


def parse_family_file(payload: bytes) -> pd.DataFrame:
    """The option lines of an all-funds holdings CSV, in HOLDING_COLUMNS."""
    source = pd.read_csv(io.BytesIO(payload), encoding="utf-8-sig")
    missing = [name for name in FAMILY_SOURCE_COLUMNS if name not in source.columns]
    if missing:
        raise SnapshotParseError(f"The holdings file lacks the columns {missing}")
    records = []
    for row in source.to_dict("records"):
        option = split_option_ticker(str(row["StockTicker"]))
        if option is None:
            continue
        root, expiry, right, strike = option
        records.append(
            {
                "fund": str(row["Account"]),
                "as_of": pd.to_datetime(row["Date"], format="%m/%d/%Y"),
                "position_ticker": "".join(str(row["StockTicker"]).split()),
                "option_root": root,
                "expiry": pd.Timestamp(expiry),
                "right": right,
                "strike": float(strike),
                "contracts": float(row["Shares"]),
                "price": float(row["Price"]),
                "net_assets": float(row["NetAssets"]),
            }
        )
    if not records:
        raise SnapshotParseError("The holdings file has no option line")
    return pd.DataFrame.from_records(records, columns=list(HOLDING_COLUMNS))


def parse_box_fund_page(payload: bytes, fund: str, as_of: pd.Timestamp | None) -> pd.DataFrame:
    """The option rows of a fund page's holdings table, in HOLDING_COLUMNS.

    A row is a table row whose first cell is an option ticker; its fourth and fifth cells
    are the quantity and the price. The page states no machine-readable date for the
    table, so the caller supplies `as_of`.
    """
    text = payload.decode("utf-8", errors="replace")
    records = []
    for row in _ROW.findall(text):
        cells = [html.unescape(_TAG.sub("", cell)).strip() for cell in _CELL.findall(row)]
        if len(cells) < 5 or not _TICKER.fullmatch(cells[0]):
            continue
        option = split_option_ticker(cells[0])
        if option is None:
            continue
        root, expiry, right, strike = option
        records.append(
            {
                "fund": fund,
                "as_of": as_of,
                "position_ticker": "".join(cells[0].split()),
                "option_root": root,
                "expiry": pd.Timestamp(expiry),
                "right": right,
                "strike": float(strike),
                "contracts": _number(cells[3]),
                "price": _number(cells[4]),
                "net_assets": float("nan"),
            }
        )
    if not records:
        raise SnapshotParseError("The page has no option row in a holdings table")
    return pd.DataFrame.from_records(records, columns=list(HOLDING_COLUMNS))


def _number(text: str) -> float:
    return float(text.replace(",", ""))


__all__ = [
    "BOXX_URL",
    "HOLDING_COLUMNS",
    "INNOVATOR_URL",
    "SnapshotParseError",
    "parse_box_fund_page",
    "parse_family_file",
]
