"""Collector for the OCC FLEX Open Interest report.

This is the authoritative source. OCC publishes a dedicated daily FLEX report --- one
for equity classes, one for index classes --- carrying symbol, right, expiry, strike,
mark price and open interest for every cleared FLEX series. History runs back roughly
twenty months.

An earlier stage of this project identified FLEX indirectly, by observing that listed
strikes fall on a standard grid and treating off-grid strikes as FLEX. That heuristic
is superseded here and is retained only as a diagnostic to be scored against this
report. Two properties of the authoritative data show why the heuristic could never
have been sufficient:

* FLEX roots carry a leading-digit prefix (``1AAL``, ``2DJX``, ``4SPY``), which
  identifies them directly and exactly;
* FLEX series are frequently struck **on** the standard grid --- ``1AAON C 08/21/2026
  99.000`` is FLEX at a round strike --- so any strike-based rule has irreducible
  false negatives.

The report is fixed-layout text with per-class headers and totals, so parsing is
positional and validated against the class totals the report itself carries.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests

from absorb.collect.http import fetch

REPORT_URL = "https://marketdata.theocc.com/flex-reports"

# optionType selects the report: E for equity classes, I for index classes.
REPORT_KINDS = {"equity": "E", "index": "I"}

FLEX_COLUMNS = (
    "report_date",
    "kind",
    "class_name",
    "root",
    "underlying",
    "right",
    "expiry",
    "strike",
    "mark_price",
    "open_interest",
)

# " 1AAL     C   09 02 2026  00021 960      0.0081     52850"
_ROW = re.compile(
    r"^\s+(?P<root>[0-9A-Z]{1,7})\s+(?P<right>[CP])\s+"
    r"(?P<mm>\d{2})\s+(?P<dd>\d{2})\s+(?P<yy>\d{4})\s+"
    r"(?P<whole>\d+)\s+(?P<frac>\d{3})\s+"
    r"(?P<mark>[-\d.]+)\s+(?P<oi>\d+)\s*$"
)
_CLASS_TOTAL = re.compile(r"\*\*\*\s+CLASS TOTALS\s+\*\*\*\s+(\d+)")
_LEADING_DIGITS = re.compile(r"^\d+")

# Lines that are report furniture rather than the name of an option class.
_FURNITURE = (
    "OPTIONS CLEARING",
    "REPORT",
    "MARK PRICES",
    "SYMBOL",
    "EXPIRATION",
    "AND DATA",
    "OPTIONS ARE",
)


def _is_class_heading(stripped: str) -> bool:
    return bool(
        stripped
        and not stripped.startswith("*")
        and "  " not in stripped[:3]
        and not any(token in stripped.upper() for token in _FURNITURE)
    )


class FlexReportError(ValueError):
    """Raised when the report does not match the expected layout."""


@dataclass(frozen=True)
class FlexReport:
    """One day's FLEX open interest for one report kind."""

    report_date: date
    kind: str
    frame: pd.DataFrame
    payload_sha256: str
    class_totals_checked: int
    class_totals_matched: int

    @property
    def n_series(self) -> int:
        return len(self.frame)

    @property
    def open_interest(self) -> int:
        return int(self.frame["open_interest"].sum())


def strip_flex_prefix(root: str) -> str:
    """``1AAL`` -> ``AAL``. FLEX roots are the listed root with a numeric prefix."""
    return _LEADING_DIGITS.sub("", root)


def parse_report(payload: bytes, kind: str, report_date: date) -> FlexReport:
    """Parse the fixed-layout report, validating against its own class totals."""
    digest = hashlib.sha256(payload).hexdigest()
    text = payload.decode("utf-8", errors="replace")

    if "FLEX OPEN INTEREST REPORT" not in text.upper():
        raise FlexReportError(f"{kind} {report_date}: payload is not a FLEX open interest report")

    records: list[dict] = []
    class_name = ""
    running = 0
    checked = matched = 0

    for line in text.splitlines():
        total = _CLASS_TOTAL.search(line)
        if total:
            checked += 1
            if running == int(total.group(1)):
                matched += 1
            running = 0
            continue

        row = _ROW.match(line)
        if row is None:
            stripped = line.strip()
            # A non-matching, non-empty line without report furniture names the class.
            if _is_class_heading(stripped):
                class_name = stripped
            continue

        parts = row.groupdict()
        open_interest = int(parts["oi"])
        running += open_interest
        records.append(
            {
                "report_date": report_date,
                "kind": kind,
                "class_name": class_name,
                "root": parts["root"],
                "underlying": strip_flex_prefix(parts["root"]),
                "right": parts["right"],
                "expiry": date(int(parts["yy"]), int(parts["mm"]), int(parts["dd"])),
                "strike": int(parts["whole"]) + int(parts["frac"]) / 1000.0,
                "mark_price": float(parts["mark"]),
                "open_interest": open_interest,
            }
        )

    if not records:
        raise FlexReportError(f"{kind} {report_date}: no series rows parsed")

    return FlexReport(
        report_date=report_date,
        kind=kind,
        frame=pd.DataFrame.from_records(records, columns=list(FLEX_COLUMNS)),
        payload_sha256=digest,
        class_totals_checked=checked,
        class_totals_matched=matched,
    )


def fetch_report(session: requests.Session, report_date: date, kind: str = "equity") -> FlexReport:
    """Retrieve and parse one day's report.

    Dates before the retention window return a short 'File requested does not exist'
    body rather than an HTTP error, so that case is detected on content.
    """
    if kind not in REPORT_KINDS:
        raise ValueError(f"kind must be one of {sorted(REPORT_KINDS)}")

    result = fetch(
        session,
        REPORT_URL,
        params={
            "instrumentType": "E",
            "reportType": "OI",
            "optionType": REPORT_KINDS[kind],
            "reportDate": report_date.strftime("%Y%m%d"),
        },
    )
    if len(result.content) < 2000:
        raise FlexReportError(
            f"{kind} {report_date}: no report available ({result.text.strip()[:60]})"
        )
    return parse_report(result.content, kind, report_date)


def snapshot_path(report: FlexReport) -> str:
    """Storage path, partitioned by the report's own activity date rather than by
    capture time, which is what the settlement-lag problem requires."""
    return f"occ_flex/date={report.report_date:%Y-%m-%d}/{report.kind}.parquet"


__all__ = [
    "FLEX_COLUMNS",
    "REPORT_KINDS",
    "REPORT_URL",
    "FlexReport",
    "FlexReportError",
    "fetch_report",
    "parse_report",
    "snapshot_path",
    "strip_flex_prefix",
]
