"""Read the hidden-share inputs and put every capture on the settlement it shows.

Three sources meet here, and none of them is stored under the activity date it describes.

* OCC's series search (`occ_census`, `occ_open_interest/date=<capture>`) returns the
  latest settlement OCC has processed when it is asked, which during or soon after a
  session is the previous one. Two captures can therefore hold one settlement.
* A Cboe chain (`cboe_chain/date=<capture>`) carries a quote timestamp. Its quotes belong
  to the session under way or just closed at that time, and its open interest is the
  latest settlement before that calendar day in New York (OCC's figure, disseminated
  before the open). Timestamps are stored in UTC.
* The FLEX report is stored under its own activity date already.

A series-search capture is dated by its listed side, which the FLEX report does not
touch: it takes the settlement whose Cboe chain shows the same listed open interest,
series for series, for most of its symbols. The FLEX side is then free to be checked
against the FLEX report on that date.
"""

from __future__ import annotations

import glob
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from hidden_options.measure.hidden_share import (
    LISTED_INDEX_ROOTS,
    listed_index,
    listed_product,
)

NEW_YORK = "America/New_York"
# Minutes after midnight at which the regular session opens, 09:30 in New York.
SESSION_OPEN_MINUTES = 9 * 60 + 30
# Weekdays appended after the last FLEX report so later captures still find their day.
CALENDAR_TAIL_DAYS = 10
# A capture is searched for among settlements at most this many days before its folder.
CAPTURE_LOOKBACK_DAYS = 7

CHAIN_READ_COLUMNS = (
    "symbol",
    "quote_timestamp",
    "contract",
    "expiry",
    "right",
    "strike",
    "bid",
    "ask",
    "theo",
    "open_interest",
)
CHAIN_OI_COLUMNS = (
    "date",
    "symbol",
    "root",
    "contract",
    "expiry",
    "right",
    "strike",
    "open_interest",
)
PRICED_COLUMNS = (
    "date",
    "symbol",
    "root",
    "expiry",
    "right",
    "strike",
    "open_interest",
    "bid",
    "ask",
    "theo",
)
REPORT_COLUMNS = (
    "report_date",
    "kind",
    "root",
    "underlying",
    "right",
    "expiry",
    "strike",
    "mark_price",
    "open_interest",
)
OCC_COLUMNS = (
    "date",
    "symbol",
    "product_symbol",
    "expiry",
    "strike",
    "call_open_interest",
    "put_open_interest",
)

_OSI_TAIL = re.compile(r"\d{6}[CP]\d{8}$")
_OSI_TAIL_LENGTH = 15
_PARTITION = re.compile(r"date=(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class CaptureDate:
    """The settlement a capture shows, and how many symbols vouch for it."""

    date: pd.Timestamp
    support: int
    compared: int


def trading_calendar(raw: Path) -> pd.DatetimeIndex:
    """The FLEX report dates, then CALENDAR_TAIL_DAYS weekdays after the last of them.

    The report dates are OCC's activity dates, so holidays inside the panel are absent.
    The tail lets a capture from after the last report find its own day, which keeps it
    from being taken for the last report's.
    """
    days = sorted({_partition_date(path) for path in glob.glob(str(raw / "occ_flex/date=*"))})
    if not days:
        raise FileNotFoundError(f"No FLEX reports under {raw}/occ_flex")
    reports = pd.DatetimeIndex(days)
    tail = pd.bdate_range(reports[-1] + pd.offsets.BDay(1), periods=CALENDAR_TAIL_DAYS)
    return pd.DatetimeIndex(reports.append(tail))


def chain_dates(timestamps: pd.Series, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """For each UTC quote timestamp, the settlement of its open interest and its session.

    `oi_date` is the last calendar date strictly before the New York calendar day of the
    timestamp. `session` is the last calendar date on or before that day, or strictly
    before it if the timestamp precedes the open.
    """
    local = pd.to_datetime(timestamps, utc=True).dt.tz_convert(NEW_YORK)
    day = pd.DatetimeIndex(local.dt.tz_localize(None).dt.normalize())
    minutes = (local.dt.hour * 60 + local.dt.minute).to_numpy()
    before = calendar.searchsorted(day, side="left") - 1
    on_or_before = calendar.searchsorted(day, side="right") - 1
    session = np.where(minutes < SESSION_OPEN_MINUTES, before, on_or_before)
    if (before < 0).any():
        first = local[before < 0].iloc[0]
        raise ValueError(f"Quote timestamp {first} falls before the trading calendar")
    return pd.DataFrame(
        {"oi_date": calendar[before], "session": calendar[session]}, index=timestamps.index
    )


def load_chains(raw: Path, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Every stored Cboe chain row, with its root, its dates and the symbol without `_`."""
    paths = sorted(glob.glob(str(raw / "cboe_chain/date=*/*.parquet")))
    if not paths:
        raise FileNotFoundError(f"No Cboe chains under {raw}/cboe_chain")
    chains = pd.concat(
        [pd.read_parquet(path, columns=list(CHAIN_READ_COLUMNS)) for path in paths],
        ignore_index=True,
    )
    contracts = chains["contract"].astype(str)
    bad = ~contracts.str.contains(_OSI_TAIL) | (contracts.str.len() <= _OSI_TAIL_LENGTH)
    if bad.any():
        raise ValueError(f"Chain contract {contracts[bad].iloc[0]!r} is not an OSI identifier")

    chains["symbol"] = chains["symbol"].astype(str).str.lstrip("_")
    chains["root"] = contracts.str[:-_OSI_TAIL_LENGTH]
    chains["expiry"] = pd.to_datetime(chains["expiry"])
    chains["quote_timestamp"] = pd.to_datetime(chains["quote_timestamp"], utc=True)
    stamps = pd.Series(chains["quote_timestamp"].unique())
    dates = chain_dates(stamps, calendar).set_index(stamps)
    chains["oi_date"] = dates["oi_date"].reindex(chains["quote_timestamp"]).to_numpy()
    chains["session"] = dates["session"].reindex(chains["quote_timestamp"]).to_numpy()
    return chains


def chain_open_interest(chains: pd.DataFrame) -> pd.DataFrame:
    """Listed open interest per settlement, from the latest chain read for it."""
    latest = chains.groupby(["symbol", "oi_date"])["quote_timestamp"].transform("max")
    frame = chains[chains["quote_timestamp"] == latest]
    frame = frame.drop_duplicates(["symbol", "oi_date", "contract"])
    return frame.rename(columns={"oi_date": "date"})[list(CHAIN_OI_COLUMNS)].reset_index(drop=True)


def priced_chains(chains: pd.DataFrame) -> pd.DataFrame:
    """Each settlement's listed open interest with the quotes of that same session.

    The open interest of settlement D is read from a chain taken after D, and its quotes
    from the latest chain whose session is D. A series with no quote from that session
    keeps missing prices.
    """
    oi = chain_open_interest(chains)
    latest = chains.groupby(["symbol", "session"])["quote_timestamp"].transform("max")
    quotes = chains[chains["quote_timestamp"] == latest]
    quotes = quotes.drop_duplicates(["symbol", "session", "contract"]).rename(
        columns={"session": "date"}
    )[["date", "symbol", "contract", "bid", "ask", "theo"]]
    priced = oi.merge(quotes, on=["date", "symbol", "contract"], how="left")
    return priced[list(PRICED_COLUMNS)]


def load_census(raw: Path) -> pd.DataFrame:
    """The census capture: OCC's series search for every optionable symbol, once."""
    paths = sorted(glob.glob(str(raw / "occ_census/*.parquet")))
    if not paths:
        raise FileNotFoundError(f"No census files under {raw}/occ_census")
    return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)


def load_captures(raw: Path) -> pd.DataFrame:
    """Every daily series-search capture, with the folder date as `capture`."""
    paths = sorted(glob.glob(str(raw / "occ_open_interest/date=*/*.parquet")))
    if not paths:
        raise FileNotFoundError(f"No series-search captures under {raw}/occ_open_interest")
    frames = [
        pd.read_parquet(path).assign(capture=pd.Timestamp(_partition_date(path))) for path in paths
    ]
    return pd.concat(frames, ignore_index=True)


def load_reports(raw: Path, since: pd.Timestamp) -> pd.DataFrame:
    """The FLEX report rows, equity and index, for every activity date from `since`."""
    paths = [
        path
        for path in sorted(glob.glob(str(raw / "occ_flex/date=*/*.parquet")))
        if pd.Timestamp(_partition_date(path)) >= since
    ]
    if not paths:
        raise FileNotFoundError(f"No FLEX reports under {raw}/occ_flex from {since:%Y-%m-%d}")
    reports = pd.concat(
        [pd.read_parquet(path, columns=list(REPORT_COLUMNS)) for path in paths],
        ignore_index=True,
    )
    reports["report_date"] = pd.to_datetime(reports["report_date"])
    reports["expiry"] = pd.to_datetime(reports["expiry"])
    return reports


def date_capture(
    capture: pd.DataFrame,
    chain_oi: pd.DataFrame,
    window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> CaptureDate:
    """The settlement whose chain shows the capture's listed open interest.

    A symbol vouches for a settlement when the chain read for it has the same open
    interest as the capture on every listed series the two share. The settlement most
    symbols vouch for wins, provided it is the only one with that many and more than half
    the symbols compared vouch for it. `window` limits the settlements considered.
    """
    listed = _listed_long(capture)
    chain = chain_oi[chain_oi["root"] == chain_oi["symbol"]]
    if window is not None:
        chain = chain[chain["date"].between(*window)]
    merged = listed.merge(
        chain[["date", "symbol", "expiry", "right", "strike", "open_interest"]],
        on=["symbol", "expiry", "right", "strike"],
    )
    merged["agrees"] = merged["oi"] == merged["open_interest"]
    agrees = merged.groupby(["symbol", "date"])["agrees"].all()
    votes = agrees[agrees].groupby(level="date").size().sort_values(ascending=False)
    compared = int(merged["symbol"].nunique())
    if votes.empty:
        raise ValueError("no chain shows the capture's listed open interest on any settlement")
    if len(votes) > 1 and votes.iloc[1] == votes.iloc[0]:
        tied = ", ".join(f"{day:%Y-%m-%d}" for day in votes.index[votes == votes.iloc[0]])
        raise ValueError(f"the capture is ambiguous between settlements {tied}")
    if 2 * int(votes.iloc[0]) <= compared:
        raise ValueError(f"only {int(votes.iloc[0])} of {compared} symbols agree on a settlement")
    return CaptureDate(pd.Timestamp(votes.index[0]), int(votes.iloc[0]), compared)


def date_captures(
    captures: pd.DataFrame, chain_oi: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Date every capture and keep one capture per settlement.

    Returns the kept rows with their `date`, and a log of every capture: its settlement,
    the symbols that vouched for it out of those compared, and whether it repeats one
    already kept. Two captures of one settlement must be identical, since the search
    shows a settlement as OCC processed it.
    """
    kept: dict[pd.Timestamp, pd.DataFrame] = {}
    log = []
    for key, rows in captures.groupby("capture", sort=True):
        folder = pd.Timestamp(str(key))
        window = (folder - pd.Timedelta(days=CAPTURE_LOOKBACK_DAYS), folder)
        dated = date_capture(rows, chain_oi, window)
        content = _content(rows)
        duplicate = dated.date in kept
        if duplicate and not content.equals(_content(kept[dated.date])):
            raise ValueError(
                f"Captures of the {dated.date:%Y-%m-%d} settlement differ "
                f"(folder {folder:%Y-%m-%d})"
            )
        if not duplicate:
            kept[dated.date] = rows
        log.append(
            {
                "capture": folder,
                "date": dated.date,
                "support": dated.support,
                "compared": dated.compared,
                "duplicate": duplicate,
            }
        )
    frames = [rows.drop(columns="capture").assign(date=day) for day, rows in kept.items()]
    return pd.concat(frames, ignore_index=True), pd.DataFrame(log)


def index_rows(chain_oi: pd.DataFrame, reports: pd.DataFrame) -> pd.DataFrame:
    """Series-search-shaped rows for the index products, from the chains and the report.

    The series-search captures leave the index products out (the collector searches only
    equity and ETF symbols), so for the indices the listed side comes from the Cboe chain,
    whose open interest is the settlement's. A chain read after a
    settlement no longer lists the series that expired on it, so both sides keep only
    series expiring after the date.
    """
    indices = set(LISTED_INDEX_ROOTS.values())
    chain = chain_oi[chain_oi["symbol"].isin(indices)]
    owners = chain["root"].map(listed_index)
    if (owners != chain["symbol"]).any():
        bad = sorted(set(chain.loc[owners != chain["symbol"], "root"]))
        raise ValueError(f"Listed index roots {bad} sit in another index's chain")
    chain = chain[chain["expiry"] > chain["date"]]
    listed = pd.DataFrame(
        {
            "date": chain["date"],
            "symbol": chain["symbol"],
            "product_symbol": chain["root"],
            "expiry": chain["expiry"],
            "strike": chain["strike"],
            "call_open_interest": chain["open_interest"].where(chain["right"] == "C", 0),
            "put_open_interest": chain["open_interest"].where(chain["right"] == "P", 0),
        }
    )

    flex = reports[(reports["kind"] == "index") & (reports["expiry"] > reports["report_date"])]
    owner = {root: listed_product(root, "index") for root in flex["root"].unique()}
    flex_rows = pd.DataFrame(
        {
            "date": flex["report_date"],
            "symbol": flex["root"].map(owner),
            "product_symbol": flex["root"],
            "expiry": flex["expiry"],
            "strike": flex["strike"],
            "call_open_interest": flex["open_interest"].where(flex["right"] == "C", 0),
            "put_open_interest": flex["open_interest"].where(flex["right"] == "P", 0),
        }
    )
    observed = listed[["date", "symbol"]].drop_duplicates()
    flex_rows = flex_rows.merge(observed, on=["date", "symbol"])
    rows = pd.concat([listed, flex_rows], ignore_index=True)
    return rows[list(OCC_COLUMNS)]


def _listed_long(capture: pd.DataFrame) -> pd.DataFrame:
    """A capture's ordinary listed series, one row per right, with `oi`."""
    listed = capture[capture["product_symbol"] == capture["symbol"]]
    base = listed[["symbol", "expiry", "strike"]].assign(expiry=pd.to_datetime(listed["expiry"]))
    calls = base.assign(right="C", oi=listed["call_open_interest"].to_numpy())
    puts = base.assign(right="P", oi=listed["put_open_interest"].to_numpy())
    return pd.concat([calls, puts], ignore_index=True)


def _content(rows: pd.DataFrame) -> pd.DataFrame:
    keys = ["symbol", "product_symbol", "expiry", "strike"]
    frame = rows.drop(columns=["capture"], errors="ignore")
    return frame.sort_values(keys).reset_index(drop=True)


def _partition_date(path: str) -> str:
    match = _PARTITION.search(path)
    if match is None:
        raise ValueError(f"{path} is not in a date=YYYY-MM-DD folder")
    return match.group(1)


__all__ = [
    "CHAIN_OI_COLUMNS",
    "OCC_COLUMNS",
    "PRICED_COLUMNS",
    "REPORT_COLUMNS",
    "CaptureDate",
    "chain_dates",
    "chain_open_interest",
    "date_capture",
    "date_captures",
    "index_rows",
    "load_captures",
    "load_census",
    "load_chains",
    "load_reports",
    "priced_chains",
    "trading_calendar",
]
