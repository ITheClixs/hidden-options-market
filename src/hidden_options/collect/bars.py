"""Collector for intraday underlying bars.

Why this exists
---------------
The roll-window test needs intraday returns on the underlying. Free intraday history
is shallow — 5-minute bars reach back 60 days and 1-minute bars 7 days — so two years
of it cannot be downloaded, only accumulated. The power arithmetic in
`docs/log/2026-08-17-power-and-data-limits.md` shows the achievable minimum detectable
effect falls from roughly 27 bp on the free 60-day window to roughly 9 bp after a year
of accumulation, which is the difference between a test that can see the hypothesised
effect and one that cannot.

Each run fetches an overlapping window rather than only the current day. Re-fetching
days already held is cheap and means a missed run repairs itself on the next one,
which matters because these bars cannot be recovered once they age out.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from hidden_options.collect.http import build_session, fetch
from hidden_options.collect.storage import write_frame

logger = logging.getLogger(__name__)

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


# An underlying needs this many distinct FLEX activity dates before its daily bars are
# worth holding: the panel regressions drop anything with a shorter history anyway.
MIN_ACTIVITY_DATES = 40

# The longest trailing control averages the twenty-two sessions before an activity date.
# The bars reach this many sessions before the panel's first date, which covers it with
# room for the holidays and missing bars inside the window.
HISTORY_SESSIONS = 40

# Daily bars are stamped at the open, so the session a bar belongs to is its New York date.
_MARKET_TZ = ZoneInfo("America/New_York")
_SESSION_CLOSE = time(16, 0)

_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

# A full refresh is over a thousand paced requests; say how far along it is.
_PROGRESS_EVERY = 100


@dataclass(frozen=True)
class BarsRefresh:
    """What one refresh of the daily bars did, symbol by symbol.

    ``failed`` maps each symbol the provider refused to the reason; ``dropped`` are the
    symbols the file held that are no longer in the qualifying set. ``late_starts`` are
    refreshed symbols whose bars begin after ``history_start``, the session the panel's
    first activity date needs: a later listing, or history the provider cut short.
    """

    path: Path
    requested: tuple[str, ...]
    refreshed: tuple[str, ...]
    failed: Mapping[str, str]
    dropped: tuple[str, ...]
    history_start: pd.Timestamp
    late_starts: tuple[str, ...]
    rows: int

    def describe(self) -> str:
        return (
            f"refreshed {len(self.refreshed)} of {len(self.requested)} underlyings "
            f"({self.rows:,} rows) into {self.path}; {len(self.failed)} failed, "
            f"{len(self.dropped)} dropped as outside the qualifying set, "
            f"{len(self.late_starts)} starting after {self.history_start:%Y-%m-%d}"
        )


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


def flex_underlyings(panel: pd.DataFrame, min_dates: int = MIN_ACTIVITY_DATES) -> list[str]:
    """Underlyings of the equity FLEX report seen on at least ``min_dates`` activity dates.

    Index underlyings (SPX, NDX, RUT, ...) are left out: the daily bars come from the
    equity quote feed, which has no series for them under these symbols.
    """
    needed = {"kind", "underlying", "report_date"}
    missing = needed - set(panel.columns)
    if missing:
        raise ValueError(f"panel lacks column(s) {sorted(missing)}")

    equity = panel[panel["kind"] == "equity"]
    dates = equity.groupby("underlying")["report_date"].nunique()
    return sorted(dates[dates >= min_dates].index)


def history_start(panel: pd.DataFrame, sessions: int = HISTORY_SESSIONS) -> pd.Timestamp:
    """The first session the bars must hold: ``sessions`` weekdays before the first date.

    Weekdays stand in for sessions; the holidays among them only make the reach longer.
    """
    if panel.empty:
        raise ValueError("the panel is empty; there is no first activity date to reach back from")
    first = pd.Timestamp(panel["report_date"].min())
    start: pd.Timestamp = first - pd.offsets.BDay(sessions)
    return start


def lookback_since(start: pd.Timestamp, now: datetime | None = None) -> str:
    """A provider range that reaches back to ``start`` from today's New York date.

    Yahoo reads an ``Nd`` range on daily bars as N sessions. Counting calendar days gives
    the larger number, so the range reaches ``start`` under either reading.
    """
    today = (now or datetime.now(UTC)).astimezone(_MARKET_TZ).date()
    return f"{max((today - start.date()).days, 1)}d"


def settled_daily_bars(frame: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Drop a daily bar whose session has not closed.

    The provider returns today's bar while the market is open, with the last trade as
    its close. Stored, it would be read next time as a finished day, and as a next-day
    outcome it looks like an unusually quiet one.
    """
    clock = (now or datetime.now(UTC)).astimezone(_MARKET_TZ)
    if clock.time() >= _SESSION_CLOSE:
        return frame
    sessions = frame["timestamp"].dt.tz_convert(_MARKET_TZ).dt.date
    settled: pd.DataFrame = frame[sessions < clock.date()]
    return settled.reset_index(drop=True)


def _fetch_daily(
    session: requests.Session, symbols: list[str], lookback: str, now: datetime | None
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Daily bars per symbol, plus the reason for each symbol that could not be had.

    One refused symbol must not cost the rest: the provider has no series for some
    tickers the clearing house uses (share classes, recently delisted names).
    """
    fetched: dict[str, pd.DataFrame] = {}
    failed: dict[str, str] = {}
    for done, symbol in enumerate(symbols, start=1):
        try:
            snapshot = fetch_bars(session, symbol, interval="1d", lookback=lookback)
        except Exception as exc:  # noqa: BLE001 - recorded per symbol, never fatal
            failed[symbol] = f"{type(exc).__name__}: {exc}"
        else:
            fetched[symbol] = settled_daily_bars(snapshot.frame, now)
        if done % _PROGRESS_EVERY == 0:
            logger.info("requested %d/%d symbols (%d failed)", done, len(symbols), len(failed))
    return fetched, failed


def _held_bars(out: Path) -> pd.DataFrame:
    """The bars already on disk, or an empty frame if there are none."""
    if not out.exists():
        return pd.DataFrame(columns=list(BAR_COLUMNS))
    held = pd.read_parquet(out)
    if list(held.columns) != list(BAR_COLUMNS):
        raise ValueError(f"{out} has columns {list(held.columns)}, expected {list(BAR_COLUMNS)}")
    return held


def _conform(frame: pd.DataFrame) -> pd.DataFrame:
    """Give every bar frame the dtypes the file has always held."""
    conformed = frame.copy()
    conformed["timestamp"] = pd.to_datetime(conformed["timestamp"], utc=True).dt.as_unit("ms")
    conformed[list(_PRICE_COLUMNS)] = conformed[list(_PRICE_COLUMNS)].astype("float64")
    return conformed


def refresh_flex_underlying_bars(
    panel: pd.DataFrame,
    out: Path,
    lookback: str | None = None,
    *,
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> BarsRefresh:
    """Re-download daily bars for every FLEX underlying and write them to ``out``.

    ``panel`` is the assembled FLEX panel; the underlyings are those of the equity report
    with at least ``MIN_ACTIVITY_DATES`` activity dates. By default the lookback reaches
    ``HISTORY_SESSIONS`` sessions before the panel's first date, the room the trailing
    volatility controls need; a refreshed symbol whose bars start later is named in a
    warning.

    A refreshed symbol's rows are replaced wholesale rather than appended to, because
    the provider restates history after a split and splicing would leave a jump that is
    not a return. A qualifying symbol the provider refuses keeps whatever rows it already
    had; a symbol outside the qualifying set is dropped. The file is replaced atomically,
    and a refresh that could fetch nothing raises rather than reporting success.
    """
    symbols = flex_underlyings(panel)
    if not symbols:
        raise ValueError(
            f"no equity underlying has {MIN_ACTIVITY_DATES} activity dates; nothing to refresh"
        )

    needed = history_start(panel)
    held = _held_bars(out)
    window = lookback or lookback_since(needed, now)
    fetched, failed = _fetch_daily(session or build_session(), symbols, window, now)
    if not fetched:
        raise RuntimeError(f"no symbol could be refreshed ({len(failed)} failed)")

    qualifying = held["symbol"].isin(symbols)
    kept = held[qualifying & ~held["symbol"].isin(fetched)]
    merged = pd.concat([kept, *fetched.values()], ignore_index=True)
    merged = _conform(merged).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    write_frame(merged, out)

    summary = BarsRefresh(
        path=out,
        requested=tuple(symbols),
        refreshed=tuple(sorted(fetched)),
        failed=dict(sorted(failed.items())),
        dropped=tuple(sorted(set(held.loc[~qualifying, "symbol"]))),
        history_start=needed,
        late_starts=_late_starts(fetched, needed),
        rows=len(merged),
    )
    _log_refresh(summary)
    return summary


def _late_starts(fetched: Mapping[str, pd.DataFrame], needed: pd.Timestamp) -> tuple[str, ...]:
    """Symbols whose first fetched session falls after ``needed``."""
    late = []
    for symbol, frame in fetched.items():
        first = frame["timestamp"].min().tz_convert(_MARKET_TZ).date()
        if first > needed.date():
            late.append(symbol)
    return tuple(sorted(late))


def _log_refresh(summary: BarsRefresh) -> None:
    logger.info("%s", summary.describe())
    if summary.failed:
        logger.warning(
            "%d underlyings not refreshed: %s",
            len(summary.failed),
            "; ".join(f"{symbol} ({reason})" for symbol, reason in summary.failed.items()),
        )
    if summary.late_starts:
        logger.warning(
            "%d refreshed underlyings have no bars as early as %s: %s",
            len(summary.late_starts),
            f"{summary.history_start:%Y-%m-%d}",
            ", ".join(summary.late_starts),
        )


__all__ = [
    "BAR_COLUMNS",
    "CHART_URL",
    "HISTORY_SESSIONS",
    "INTERVAL_MAX_RANGE",
    "MIN_ACTIVITY_DATES",
    "BarParseError",
    "BarSnapshot",
    "BarsRefresh",
    "fetch_bars",
    "flex_underlyings",
    "history_start",
    "lookback_since",
    "parse_chart",
    "refresh_flex_underlying_bars",
    "settled_daily_bars",
    "snapshot_partition",
]
