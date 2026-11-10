"""Collector for Cboe's daily FLEX execution reports.

Cboe publishes every FLEX execution on its options exchange as one spreadsheet per trading
day: time, price, size, root, expiry, right, strike and a flag for legs of a multi-leg
order. The files start around April 2025. A date with no file (a holiday, or one before
the archive begins) answers 403, which is recorded as absent, not as a failure.

The spreadsheet is read with the standard library: an `.xlsx` is a zip of XML, and these
sheets hold one flat table. Dates and times arrive as Excel serial numbers, in the
exchange's local time. Every execution appears twice, once from each side; this collector
stores the rows as published and leaves the halving to whoever counts them.

Rows without a root are the stock legs of orders tied to stock. They are kept, with a
missing `root` and `right`.
"""

from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pandas as pd
import requests

from hidden_options.collect.http import build_session
from hidden_options.collect.storage import write_frame
from hidden_options.config import REQUEST_SPACING_SECONDS, REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

URL = (
    "https://cdn.cboe.com/resources/us/options/market-statistics/flex-trade-reports/cone/"
    "cone_options_rpt_flex_executions_late_{day:%Y%m%d}.xlsx"
)
SOURCE_COLUMNS = (
    "transact_time",
    "price",
    "size",
    "osi_root",
    "expire_date",
    "call_put_flag",
    "strike_price",
    "spread",
)
EXECUTION_COLUMNS = (
    "trade_date",
    "time",
    "price",
    "size",
    "root",
    "expiry",
    "right",
    "strike",
    "spread",
)
ABSENT_STATUS = (403, 404)
MAX_ATTEMPTS = 3
MAX_SHEET_BYTES = 200 * 1024 * 1024
EXCEL_EPOCH = pd.Timestamp("1899-12-30")

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_SHEET = re.compile(r"xl/worksheets/sheet\d+\.xml")
_COLUMN = re.compile(r"[A-Z]+")


class TradeReportError(ValueError):
    """Raised when a file is not a FLEX execution report in the expected layout."""


class EmptyTradeReport(TradeReportError):
    """Raised when a report has its header and no executions under it."""


def report_url(day: date) -> str:
    return URL.format(day=day)


def snapshot_path(day: date) -> str:
    return f"cboe_flex_trades/date={day:%Y-%m-%d}/executions.parquet"


def parse_executions(payload: bytes) -> pd.DataFrame:
    """One day's report as a frame in EXECUTION_COLUMNS, rows as published."""
    table = _sheet_rows(payload)
    if not table:
        raise TradeReportError("The report has no rows")
    names = {name: letter for letter, name in table[0].items()}
    missing = [name for name in SOURCE_COLUMNS if name not in names]
    if missing:
        raise TradeReportError(f"The report lacks the columns {missing}")
    body = table[1:]
    if not body:
        raise EmptyTradeReport("The report has no executions")

    def column(name: str) -> list[Any]:
        return [row.get(names[name]) for row in body]

    moment = EXCEL_EPOCH + pd.to_timedelta(pd.to_numeric(column("transact_time")), unit="D")
    expiry = EXCEL_EPOCH + pd.to_timedelta(pd.to_numeric(column("expire_date")), unit="D")
    frame = pd.DataFrame(
        {
            "trade_date": pd.DatetimeIndex(moment).normalize(),
            "time": pd.DatetimeIndex(moment).round("ms"),
            "price": pd.to_numeric(column("price")),
            "size": pd.to_numeric(column("size")).astype("int64"),
            "root": pd.Series(column("osi_root"), dtype=object),
            "expiry": pd.DatetimeIndex(expiry).normalize(),
            "right": pd.Series(column("call_put_flag"), dtype=object),
            "strike": pd.to_numeric(column("strike_price")),
            "spread": [value == "Y" for value in column("spread")],
        }
    )
    return frame[list(EXECUTION_COLUMNS)]


def _sheet_rows(payload: bytes) -> list[dict[str, str | None]]:
    """The first sheet's rows, each a map from column letter to the cell's text."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise TradeReportError("The payload is not a workbook") from exc
    names = archive.namelist()
    sheets = sorted(name for name in names if _SHEET.fullmatch(name))
    if not sheets:
        raise TradeReportError("The workbook has no sheet")
    if archive.getinfo(sheets[0]).file_size > MAX_SHEET_BYTES:
        raise TradeReportError("The sheet is larger than any execution report should be")
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for item in ElementTree.fromstring(archive.read("xl/sharedStrings.xml")).iter(f"{_NS}si"):
            shared.append("".join(text.text or "" for text in item.iter(f"{_NS}t")))
    rows: list[dict[str, str | None]] = []
    for row in ElementTree.fromstring(archive.read(sheets[0])).iter(f"{_NS}row"):
        rows.append({_letters(cell): _text(cell, shared) for cell in row.iter(f"{_NS}c")})
    return rows


def _letters(cell: ElementTree.Element) -> str:
    found = _COLUMN.match(cell.get("r", ""))
    if found is None:
        raise TradeReportError("A cell has no reference")
    return found.group(0)


def _text(cell: ElementTree.Element, shared: list[str]) -> str | None:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{_NS}t"))
    value = cell.find(f"{_NS}v")
    if value is None or value.text is None:
        return None
    return shared[int(value.text)] if kind == "s" else value.text


def backfill(
    start: date, end: date, root: Path, *, session: requests.Session | None = None
) -> dict[str, int]:
    """Fetch every weekday's report in ``[start, end]`` that is not already on disk.

    Returns how many files were written, were absent at the source, were published
    empty, were already held, or failed. A failure is logged and the walk goes on.
    """
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    http = session or build_session()
    summary = {"written": 0, "absent": 0, "empty": 0, "held": 0, "failed": 0}
    day = start
    while day <= end:
        if day.weekday() < 5:
            summary[_collect(http, day, root)] += 1
        day += timedelta(days=1)
    return summary


def _collect(session: requests.Session, day: date, root: Path) -> str:
    destination = root / snapshot_path(day)
    if destination.exists():
        return "held"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = session.get(report_url(day), timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            logger.warning("%s attempt %d: %s", day, attempt + 1, exc)
            time.sleep(REQUEST_SPACING_SECONDS * (attempt + 1))
            continue
        time.sleep(REQUEST_SPACING_SECONDS)
        if response.status_code in ABSENT_STATUS:
            return "absent"
        if response.ok:
            try:
                write_frame(parse_executions(response.content), destination)
            except EmptyTradeReport:
                logger.info("%s: published with no executions", day)
                return "empty"
            except TradeReportError as exc:
                logger.warning("%s: %s", day, exc)
                return "failed"
            return "written"
        logger.warning("%s attempt %d: HTTP %d", day, attempt + 1, response.status_code)
    return "failed"


__all__ = [
    "EXECUTION_COLUMNS",
    "EmptyTradeReport",
    "TradeReportError",
    "backfill",
    "parse_executions",
    "report_url",
    "snapshot_path",
]
