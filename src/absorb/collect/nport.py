"""Collector for fund net assets from SEC Form N-PORT.

Why this exists
---------------
Programme size is the dose variable in the pilot, and the first pass measured it with
a single current figure applied across five years of history. That is close to a
random re-labelling: MSTY reported $1.28bn of net assets in January 2026 and $726m in
August 2026, a 43% fall in seven months, and most of these funds grew by orders of
magnitude from launch.

N-PORT gives an authoritative net-asset figure per fund per report date, free, back to
each fund's inception. It is quarterly-public with roughly a two-month lag, so it is a
step function rather than a daily series — but a correct step function beats a
constant.

Filings are located by SEC *series* identifier rather than by CIK, because a single
trust files for many funds and the CIK-level index does not say which fund a filing
belongs to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests

from absorb.collect.http import fetch

FILING_INDEX_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/primary_doc.xml"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers_mf.json"

_ACCESSION_RE = re.compile(r"<accession-n[um]*ber>(.*?)</accession-n[um]*ber>")

REPORT_COLUMNS = ("fund", "series_id", "report_date", "net_assets", "total_assets", "series_name")


class NportParseError(ValueError):
    """Raised when an N-PORT document does not contain the expected fields."""


@dataclass(frozen=True)
class NportReport:
    """One fund's reported scale at one report date."""

    fund: str
    series_id: str
    series_name: str
    report_date: date
    net_assets: float
    total_assets: float


def _tag(document: str, name: str) -> str | None:
    match = re.search(rf"<{name}>(.*?)</{name}>", document, re.DOTALL)
    return match.group(1).strip() if match else None


def parse_report(fund: str, series_id: str, document: str) -> NportReport:
    """Extract scale fields from an N-PORT primary document."""
    report_date = _tag(document, "repPdDate")
    net_assets = _tag(document, "netAssets")
    total_assets = _tag(document, "totAssets")

    if report_date is None or net_assets is None:
        raise NportParseError(
            f"{fund}: N-PORT document lacks repPdDate or netAssets; layout may have changed"
        )

    try:
        parsed_date = date.fromisoformat(report_date)
        parsed_net = float(net_assets)
        parsed_total = float(total_assets) if total_assets else float("nan")
    except ValueError as exc:
        raise NportParseError(f"{fund}: unparseable N-PORT fields: {exc}") from exc

    return NportReport(
        fund=fund,
        series_id=series_id,
        series_name=_tag(document, "seriesName") or "",
        report_date=parsed_date,
        net_assets=parsed_net,
        total_assets=parsed_total,
    )


def list_accessions(
    session: requests.Session, series_id: str, *, limit: int = 40
) -> tuple[str, ...]:
    """Accession numbers of a series' N-PORT filings, newest first."""
    result = fetch(
        session,
        FILING_INDEX_URL,
        params={
            "action": "getcompany",
            "CIK": series_id,
            "type": "NPORT-P",
            "dateb": "",
            "owner": "include",
            "count": str(limit),
            "output": "atom",
        },
    )
    return tuple(_ACCESSION_RE.findall(result.text))


def fetch_report(
    session: requests.Session, cik: int | str, accession: str, *, fund: str, series_id: str
) -> NportReport:
    """Retrieve and parse one N-PORT filing."""
    result = fetch(
        session,
        DOCUMENT_URL.format(cik=str(cik).lstrip("0"), accession=accession.replace("-", "")),
    )
    return parse_report(fund, series_id, result.text)


def to_frame(reports: list[NportReport]) -> pd.DataFrame:
    """Normalise reports into a frame, newest last, one row per fund report date."""
    if not reports:
        return pd.DataFrame(columns=list(REPORT_COLUMNS))
    frame = pd.DataFrame([r.__dict__ for r in reports])[list(REPORT_COLUMNS)]
    return frame.sort_values(["fund", "report_date"]).reset_index(drop=True)


def as_of_series(reports: pd.DataFrame, dates: pd.Series, fund: str) -> pd.Series:
    """Step-function net assets for one fund evaluated on arbitrary dates.

    Uses the most recent report at or before each date, so no value is ever carried
    backwards into a period before it was reported. Dates before a fund's first report
    return NaN rather than being back-filled, because the fund's early scale is
    genuinely unknown rather than equal to its first observation.
    """
    history = reports[reports["fund"] == fund].sort_values("report_date")
    if history.empty:
        return pd.Series(float("nan"), index=dates.index)

    # merge_asof requires identical datetime resolutions on both keys; report dates
    # arrive as date objects and the panel carries nanosecond timestamps.
    lookup = pd.DataFrame(
        {
            "report_date": pd.to_datetime(history["report_date"]).astype("datetime64[ns]"),
            "net_assets": history["net_assets"].to_numpy(),
        }
    ).sort_values("report_date")

    target = pd.DataFrame(
        {"date": pd.to_datetime(dates).astype("datetime64[ns]").to_numpy()}, index=dates.index
    )
    merged = pd.merge_asof(
        target.sort_values("date"),
        lookup,
        left_on="date",
        right_on="report_date",
        direction="backward",
    )
    merged.index = target.sort_values("date").index
    return merged["net_assets"].reindex(dates.index)


__all__ = [
    "REPORT_COLUMNS",
    "NportParseError",
    "NportReport",
    "as_of_series",
    "fetch_report",
    "list_accessions",
    "parse_report",
    "to_frame",
]
