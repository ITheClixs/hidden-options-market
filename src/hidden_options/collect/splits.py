"""Split events, and undoing the provider's split adjustment of daily bars.

The provider restates a symbol's whole history after a split, so stored daily bars are
split-adjusted as of the day they were fetched. OCC's strikes are not, so any comparison
of an equity's price with a strike before a split is off by the split's ratio: NFLX's
bars put it near 93 on 1 April 2025, where its FLEX strikes sit between 855 and 1,120.

`unadjust` puts prices and volumes back on the basis of each session, the basis strikes
are quoted on. A split's ratio is new shares per old share, 10 for a 10:1 split. Prices
before its ex-date are multiplied by it and volumes divided, so dollar volume and every
return within one side of a split are unchanged. A split dated after a symbol's last
stored bar is not in those bars, and is not applied.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import requests

from hidden_options.collect.bars import CHART_URL
from hidden_options.collect.http import build_session, fetch
from hidden_options.config import SPLITS_PATH

logger = logging.getLogger(__name__)

NEW_YORK = "America/New_York"
SPLIT_COLUMNS = ("symbol", "session", "ratio")
PRICE_COLUMNS = ("open", "high", "low", "close")
# Deep enough to cover every bar held: the bars reach back about three years.
SPLIT_RANGE = "10y"


def parse_splits(symbol: str, payload: bytes) -> pd.DataFrame:
    """The split events in one chart payload, dated by the New York session of the ex-date."""
    result = json.loads(payload)["chart"]["result"][0]
    events = (result.get("events") or {}).get("splits") or {}
    rows = [
        {
            "symbol": symbol,
            "session": pd.Timestamp(event["date"], unit="s", tz="UTC")
            .tz_convert(NEW_YORK)
            .tz_localize(None)
            .normalize(),
            "ratio": float(event["numerator"]) / float(event["denominator"]),
        }
        for event in events.values()
    ]
    frame = pd.DataFrame(rows, columns=list(SPLIT_COLUMNS))
    return frame.sort_values("session").reset_index(drop=True)


def fetch_splits(session: requests.Session, symbol: str) -> pd.DataFrame:
    result = fetch(
        session,
        CHART_URL.format(symbol=symbol),
        params={"interval": "1d", "range": SPLIT_RANGE, "events": "splits"},
    )
    return parse_splits(symbol, result.content)


def refresh_splits(symbols: Iterable[str], out: Path) -> pd.DataFrame:
    """Fetch the split events of `symbols` and write them to `out` as parquet."""
    session = build_session()
    frames, failed = [], []
    for symbol in sorted(set(symbols)):
        try:
            frames.append(fetch_splits(session, symbol))
        except (requests.RequestException, KeyError, IndexError, ValueError) as error:
            failed.append(symbol)
            logger.warning("splits for %s not fetched: %s", symbol, error)
    if not frames:
        raise RuntimeError("no split events could be fetched for any symbol")
    splits = pd.concat(frames, ignore_index=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    splits.to_parquet(out, index=False)
    logger.info(
        "splits: %d events for %d symbols, %d failed", len(splits), len(frames), len(failed)
    )
    return splits


def split_factors(bars: pd.DataFrame, splits: pd.DataFrame) -> pd.Series:
    """Per row of `bars`, the product of the ratios of the splits it precedes: the factor
    by which `unadjust` multiplies its prices and divides its volume. Prices divided by it
    are on the provider's adjusted basis, so returns across a split are true returns."""
    factor = pd.Series(1.0, index=bars.index)
    if splits.empty:
        return factor
    session = (
        pd.to_datetime(bars["timestamp"], utc=True)
        .dt.tz_convert(NEW_YORK)
        .dt.tz_localize(None)
        .dt.normalize()
    )
    last_bar = session.groupby(bars["symbol"]).transform("max")
    events = zip(
        splits["symbol"].astype(str),
        pd.to_datetime(splits["session"]),
        splits["ratio"].astype(float),
        strict=True,
    )
    for symbol, ex_date, ratio in events:
        hit = (bars["symbol"] == symbol) & (session < ex_date) & (ex_date <= last_bar)
        factor[hit] *= ratio
    return factor


def unadjust(bars: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """`bars` with prices and volumes on the basis of each session; a new frame."""
    out = bars.copy()
    factor = split_factors(bars, splits)
    for column in PRICE_COLUMNS:
        if column in out:
            out[column] = out[column] * factor
    if "volume" in out:
        out["volume"] = out["volume"] / factor
    return out


def load_splits(path: Path | None = None) -> pd.DataFrame:
    """The stored split events. Missing, they must be fetched first: comparing an adjusted
    price with an unadjusted strike is wrong by the split's ratio, silently."""
    path = SPLITS_PATH if path is None else path
    if not path.exists():
        raise FileNotFoundError(f"No split events at {path}; run `hidden-options refresh-splits`")
    splits = pd.read_parquet(path, columns=list(SPLIT_COLUMNS))
    splits["session"] = pd.to_datetime(splits["session"])
    return splits


def read_bars(
    path: Path, columns: Iterable[str] | None = None, *, with_factor: bool = False
) -> pd.DataFrame:
    """Daily bars put back on each session's basis, for comparison with strikes. With
    `with_factor`, each row also carries its `split_factor`, for returns across splits."""
    frame = pd.read_parquet(path, columns=None if columns is None else list(columns))
    splits = load_splits()
    out = unadjust(frame, splits)
    return out.assign(split_factor=split_factors(frame, splits)) if with_factor else out


__all__ = [
    "PRICE_COLUMNS",
    "SPLIT_COLUMNS",
    "fetch_splits",
    "load_splits",
    "read_bars",
    "parse_splits",
    "refresh_splits",
    "split_factors",
    "unadjust",
]
