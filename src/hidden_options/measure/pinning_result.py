"""Result `pinning`: do stocks close nearer large FLEX strikes on FLEX-only expiries?

Specification and its amendment: `docs/log/2026-11-08-pinning-spec.md`. The trading
calendar is the one SPY's daily bars give. Names with listed non-Friday expiries are read
from OCC's census and the stored Cboe chains. The expiring book is read from the report
of the session before expiry.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from hidden_options.config import BARS_PATH, PANEL_END, RAW_DIR
from hidden_options.measure.hidden_share import is_adjusted_product, is_flex_product
from hidden_options.measure.hidden_share_data import load_reports
from hidden_options.measure.pinning import (
    BANDS,
    clustered_mean,
    event_statistics,
    flex_only,
    listed_nonfriday,
    pin_strikes,
    sign_flip_p,
    size_terciles,
    with_sigma,
)
from hidden_options.measure.pinning_macros import pinning_macros
from hidden_options.predict.inference import holm
from hidden_options.predict.panel import _sessions
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "pinning"
CALENDAR_SYMBOL = "SPY"
ADV_SESSIONS = 20
N_FLIPS = 10_000
SEED = 20261108
# NYSE Friday holidays after the last bar, for classifying listed expiries in the census
# and chains that fall beyond it (Christmas 2026, Good Friday, Juneteenth and Christmas
# observed in 2027).
LATER_FRIDAY_HOLIDAYS = ("2026-12-25", "2027-03-26", "2027-06-18", "2027-12-24")


@dataclass(frozen=True)
class PinningInputs:
    """Daily closes and volumes, the FLEX report rows near expiry, and listed expiries."""

    bars: pd.DataFrame
    reports: pd.DataFrame
    listed: pd.DataFrame


def pinning_result(inputs: PinningInputs) -> Result:
    """The tests of record, the descriptive rows and the sample, as specified."""
    days, holidays = _calendar(inputs.bars)
    closes = with_sigma(_closes(inputs.bars))
    excluded = listed_nonfriday(inputs.listed, holidays)
    book = _expiring_book(inputs.reports, days)
    adv = _adv_shares(inputs.bars)

    only = book["expiry"].map(dict(zip(days, flex_only(days, holidays), strict=True))).astype(bool)
    eligible = ~book["underlying"].isin(excluded)
    main = _events(book[only & eligible], closes, adv, days)
    friday = _events(book[book["expiry"].dt.day_of_week == 4], closes, adv, days)

    h1 = clustered_mean(main["D"], main["expiry"])
    h2 = size_terciles(main.dropna(subset=["size"]))
    adjusted = holm({"h1": h1["p_value"], "h2": h2["p_value"]})
    values: dict[str, Any] = {
        "h1": {
            **h1,
            "holm_p": adjusted["h1"],
            "sign_flip_p": sign_flip_p(main["D"], main["expiry"], n_draws=N_FLIPS, seed=SEED),
        },
        "h2": {**h2, "holm_p": adjusted["h2"]},
        "descriptive": {
            **{
                f"band_{band}": clustered_mean(main[f"D_b{band}"], main["expiry"]) for band in BANDS
            },
            "expiry_only": clustered_mean(main["s_expiry"], main["expiry"]),
            "pseudo_only": clustered_mean(main["s_pseudo"], main["expiry"]),
            "friday": clustered_mean(friday["D"], friday["expiry"]),
            "calls": clustered_mean(*_split(main, main["call_share"] >= 0.5)),
            "puts": clustered_mean(*_split(main, main["call_share"] < 0.5)),
        },
        "sample": {
            "events": len(main),
            "expiry_dates": int(main["expiry"].nunique()),
            "underlyings": int(main["underlying"].nunique()),
            "median_contracts": float(main["open_interest"].median()),
            "median_size": float(main["size"].median()),
            "near_expiry": float(main["n0.25_expiry"].mean()),
            "near_after": float(main["n0.25_pseudo"].mean()),
            "excluded_names": sorted(excluded),
            "friday_events": len(friday),
        },
        "settings": {"n_flips": N_FLIPS, "seed": SEED, "bands": list(BANDS)},
    }
    run_inputs = {
        "source": "data/raw/occ_flex",
        "bars": "data/flex_underlying_bars.parquet",
        "panel_end": f"{PANEL_END:%Y-%m-%d}",
        "first_expiry": f"{main['expiry'].min():%Y-%m-%d}",
        "last_expiry": f"{main['expiry'].max():%Y-%m-%d}",
    }
    return Result(NAME, values, pinning_macros(values), run_inputs, now_iso())


@ANALYSES.register(NAME)
def pinning_analysis() -> Result:
    """The pinning test on every report and bar on disk up to PANEL_END."""
    return pinning_result(load_inputs())


def load_inputs(raw: Path | None = None, bars_path: Path | None = None) -> PinningInputs:
    raw = RAW_DIR if raw is None else raw
    bars = pd.read_parquet(BARS_PATH if bars_path is None else bars_path)
    reports = load_reports(raw, pd.Timestamp("2024-01-01"), pd.Timestamp(PANEL_END))
    reports = reports[(reports["kind"] == "equity") & (reports["expiry"] > reports["report_date"])]
    reports = reports[reports["expiry"] <= reports["report_date"] + pd.Timedelta(days=7)]
    return PinningInputs(bars=bars, reports=reports.reset_index(drop=True), listed=_listed(raw))


def _calendar(bars: pd.DataFrame) -> tuple[pd.DatetimeIndex, set[pd.Timestamp]]:
    sessions = _sessions(bars.loc[bars["symbol"] == CALENDAR_SYMBOL, "timestamp"])
    days = pd.DatetimeIndex(sorted(sessions.unique()))
    holidays = set(pd.bdate_range(days.min(), days.max()).difference(days))
    return days, holidays | {pd.Timestamp(d) for d in LATER_FRIDAY_HOLIDAYS}


def _closes(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars[["symbol", "timestamp", "close"]].assign(session=_sessions(bars["timestamp"]))
    return frame[["symbol", "session", "close"]].drop_duplicates(["symbol", "session"])


def _adv_shares(bars: pd.DataFrame) -> pd.DataFrame:
    """Mean share volume of the ADV_SESSIONS sessions ending the session before each date."""
    frame = bars[["symbol", "timestamp", "volume"]].assign(session=_sessions(bars["timestamp"]))
    frame = frame.sort_values(["symbol", "session"])
    frame["adv"] = frame.groupby("symbol")["volume"].transform(
        lambda v: v.rolling(ADV_SESSIONS, min_periods=ADV_SESSIONS).mean().shift(1)
    )
    return frame.rename(columns={"symbol": "underlying", "session": "expiry"})[
        ["underlying", "expiry", "adv"]
    ]


def _expiring_book(reports: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Series expiring on a trading day, as the report of the session before it shows them."""
    previous = pd.Series(days[:-1], index=days[1:])
    frame = reports[~reports["root"].astype(str).map(is_adjusted_product).astype(bool)]
    frame = frame[frame["expiry"].isin(days)]
    frame = frame[frame["report_date"] == frame["expiry"].map(previous)]
    return frame[["underlying", "expiry", "strike", "right", "open_interest"]].reset_index(
        drop=True
    )


def _events(
    book: pd.DataFrame, closes: pd.DataFrame, adv: pd.DataFrame, days: pd.DatetimeIndex
) -> pd.DataFrame:
    prev = closes.rename(columns={"symbol": "underlying", "session": "expiry"})[
        ["underlying", "expiry", "prev_close", "sigma"]
    ].dropna()
    events = pin_strikes(book, prev).merge(adv, on=["underlying", "expiry"], how="left")
    events["size"] = events["open_interest"] * 100 / events["adv"]
    return event_statistics(events, closes, days)


def _split(stats: pd.DataFrame, mask: pd.Series) -> tuple[pd.Series, pd.Series]:
    return stats.loc[mask, "D"], stats.loc[mask, "expiry"]


def _listed(raw: Path) -> pd.DataFrame:
    """(symbol, expiry) of every listed series in the census and the stored chains."""
    frames: list[pd.DataFrame] = []
    for path in glob.glob(str(raw / "occ_census/*.parquet")):
        census = pd.read_parquet(path, columns=["symbol", "product_symbol", "expiry"])
        frames.append(census[~census["product_symbol"].map(is_flex_product)][["symbol", "expiry"]])
    for path in glob.glob(str(raw / "cboe_chain/date=*/equity_*.parquet")):
        chain = pd.read_parquet(path, columns=["symbol", "expiry"])
        frames.append(chain.assign(symbol=chain["symbol"].astype(str).str.lstrip("_")))
    listed = pd.concat(frames, ignore_index=True)
    listed["expiry"] = pd.to_datetime(listed["expiry"])
    return listed.drop_duplicates().reset_index(drop=True)


__all__ = ["NAME", "PinningInputs", "load_inputs", "pinning_analysis", "pinning_result"]
