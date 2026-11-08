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

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from hidden_options.collect.splits import read_bars
from hidden_options.config import BARS_PATH, PANEL_END, RAW_DIR
from hidden_options.measure.hidden_share import is_adjusted_product, is_flex_product
from hidden_options.measure.hidden_share_data import load_reports
from hidden_options.measure.pinning import (
    BANDS,
    PSEUDO_OFFSETS,
    clustered_mean,
    event_statistics,
    flex_only,
    listed_nonfriday,
    matched_placebo,
    pin_strikes,
    power_at,
    sign_flip_p,
    simulate_worlds,
    size_terciles,
    with_sigma,
)
from hidden_options.measure.pinning_control import control_statistics, monthly_expiries
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
SIZE_WORLDS = 1000
POWER_WORLDS = 400
PULLED = (0.05, 0.10, 0.15)
# NYSE Friday holidays after the last bar, for classifying listed expiries in the census
# and chains that fall beyond it (Christmas 2026, Good Friday, Juneteenth and Christmas
# observed in 2027).
LATER_FRIDAY_HOLIDAYS = ("2026-12-25", "2027-03-26", "2027-06-18", "2027-12-24")


@dataclass(frozen=True)
class PinningInputs:
    """Daily closes and volumes on each session's basis (with `split_factor` where splits
    were applied), the FLEX report rows near expiry, and listed expiries."""

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
    straddling = _straddles_split(main, closes, days)
    main = main[~straddling].reset_index(drop=True)
    friday = _events(book[book["expiry"].dt.day_of_week == 4], closes, adv, days)
    friday = friday[~_straddles_split(friday, closes, days)].reset_index(drop=True)

    h1 = clustered_mean(main["D"], main["expiry"])
    h2 = size_terciles(main.dropna(subset=["size"]))
    adjusted = holm({"h1": h1["p_value"], "h2": h2["p_value"]})
    values: dict[str, Any] = {
        "h1": {
            **h1,
            "holm_p": adjusted["h1"],
            "mde80_holm": _holm_mde(h1),
            "sign_flip_p": sign_flip_p(main["D"], main["expiry"], n_draws=N_FLIPS, seed=SEED),
        },
        "h2": {**h2, "holm_p": adjusted["h2"]},
        "h1_net": _net(main, closes, days),
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
            "split_dropped": int(straddling.sum()),
            "in_listed_sources": int(
                main.loc[
                    main["underlying"].isin(set(inputs.listed["symbol"])), "underlying"
                ].nunique()
            ),
        },
        "simulation": _simulation(main, h1),
        "control": _control(closes, days),
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
    bars = read_bars(BARS_PATH if bars_path is None else bars_path, with_factor=True)
    reports = load_reports(raw, pd.Timestamp("2024-01-01"), pd.Timestamp(PANEL_END))
    reports = reports[(reports["kind"] == "equity") & (reports["expiry"] > reports["report_date"])]
    reports = reports[reports["expiry"] <= reports["report_date"] + pd.Timedelta(days=7)]
    return PinningInputs(bars=bars, reports=reports.reset_index(drop=True), listed=_listed(raw))


def _calendar(bars: pd.DataFrame) -> tuple[pd.DatetimeIndex, set[pd.Timestamp]]:
    sessions = _sessions(bars.loc[bars["symbol"] == CALENDAR_SYMBOL, "timestamp"])
    days = pd.DatetimeIndex(sorted(sessions.unique()))
    holidays = set(pd.bdate_range(days.min(), days.max()).difference(days))
    return days, holidays | {pd.Timestamp(d) for d in LATER_FRIDAY_HOLIDAYS}


def _with_factor(bars: pd.DataFrame) -> pd.DataFrame:
    return bars if "split_factor" in bars else bars.assign(split_factor=1.0)


def _closes(bars: pd.DataFrame) -> pd.DataFrame:
    bars = _with_factor(bars)
    frame = bars[["symbol", "timestamp", "close", "split_factor"]].assign(
        session=_sessions(bars["timestamp"])
    )
    return frame[["symbol", "session", "close", "split_factor"]].drop_duplicates(
        ["symbol", "session"]
    )


def _adv_shares(bars: pd.DataFrame) -> pd.DataFrame:
    """Mean share volume of the ADV_SESSIONS sessions ending the session before each date,
    in shares of that session's basis, the basis its open interest is on."""
    bars = _with_factor(bars)
    frame = bars[["symbol", "timestamp", "volume", "split_factor"]].assign(
        session=_sessions(bars["timestamp"])
    )
    frame = frame.sort_values(["symbol", "session"])
    adjusted = frame["volume"] * frame["split_factor"]
    mean = adjusted.groupby(frame["symbol"]).transform(
        lambda v: v.rolling(ADV_SESSIONS, min_periods=ADV_SESSIONS).mean().shift(1)
    )
    frame["adv"] = mean / frame.groupby("symbol")["split_factor"].shift(1)
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


def _control(closes: pd.DataFrame, days: pd.DatetimeIndex) -> dict[str, Any]:
    """The positive control of docs/log/2026-11-08-pinning-control-spec.md."""
    monthly = monthly_expiries(days)
    fridays = days[(days.day_of_week == 4) & ~days.isin(monthly)]

    def statistics(expiries: pd.DatetimeIndex) -> pd.DataFrame:
        stats = control_statistics(closes, days, expiries)
        return stats[~_straddles_split(stats, closes, days)].reset_index(drop=True)

    stats, weekly = statistics(monthly), statistics(pd.DatetimeIndex(fridays))
    # Diagnostic, added after the control was read: ordinary Monday-to-Thursday sessions,
    # where nothing standard expires, show the statistic's baseline at round strikes.
    ordinary = days[(days.day_of_week < 4) & ~days.isin(monthly)]
    ordinary_stats = statistics(pd.DatetimeIndex(ordinary))
    placebo = clustered_mean(ordinary_stats["D"], ordinary_stats["expiry"])
    found = clustered_mean(stats["D"], stats["expiry"])
    return {
        "monthly": {
            **found,
            "sign_flip_p": sign_flip_p(stats["D"], stats["expiry"], n_draws=N_FLIPS, seed=SEED),
            "underlyings": int(stats["underlying"].nunique()),
            "near_expiry": float(stats["n0.25_expiry"].mean()),
            "near_after": float(stats["n0.25_pseudo"].mean()),
        },
        **{f"band_{band}": clustered_mean(stats[f"D_b{band}"], stats["expiry"]) for band in BANDS},
        "weekly": clustered_mean(weekly["D"], weekly["expiry"]),
        "placebo": placebo,
        "monthly_net": _net(stats, closes, days),
        "weekly_net": _net(weekly, closes, days),
    }


def _holm_mde(found: dict[str, Any], tests: int = 2) -> float:
    """The MDE at 80% power at Holm's strictest level across `tests` tests, on t(G - 1)."""
    df = found["clusters"] - 1
    level = 0.05 / tests
    return float((student_t.ppf(1 - level / 2, df) + student_t.ppf(0.80, df)) * found["std_error"])


def _net(stats: pd.DataFrame, closes: pd.DataFrame, days: pd.DatetimeIndex) -> dict[str, Any]:
    """D net of the matched placebo at the same distance (`pinning.matched_placebo`), per
    event, with the registered inference. A diagnostic added after the outcomes were read."""
    net = matched_placebo(stats, closes, days)
    return {
        **clustered_mean(net["D_net"], stats["expiry"]),
        "placebo_mean": float(np.nanmean(net["D_placebo"])),
        "sign_flip_p": sign_flip_p(net["D_net"], stats["expiry"], n_draws=N_FLIPS, seed=SEED),
    }


def _straddles_split(
    stats: pd.DataFrame, closes: pd.DataFrame, days: pd.DatetimeIndex
) -> pd.Series:
    """Events with a split between the session before expiry and the last pseudo-expiry,
    where the pin strike and later closes are on different bases."""
    factor = closes.set_index(["symbol", "session"])["split_factor"]
    position = days.get_indexer(pd.DatetimeIndex(stats["expiry"]))
    first = pd.MultiIndex.from_arrays([stats["underlying"], days[position - 1]])
    last = pd.MultiIndex.from_arrays([stats["underlying"], days[position - min(PSEUDO_OFFSETS)]])
    before = factor.reindex(first).to_numpy()
    after = factor.reindex(last).to_numpy()
    return pd.Series(before != after, index=stats.index)


def _simulation(stats: pd.DataFrame, h1: dict[str, Any]) -> dict[str, Any]:
    """Size of H1 on simulated returns with these events' structure, and its power
    against attraction in a share of events, both on the simulated standard error and on
    the one observed."""
    distances = np.log(
        stats["strike"].to_numpy(dtype=float) / stats["prev_close"].to_numpy(dtype=float)
    )
    sigmas = stats["sigma"].to_numpy(dtype=float)
    clusters = stats["expiry"].to_numpy()

    def run(pulled: float, worlds: int, offset: int) -> dict[str, float]:
        return simulate_worlds(
            distances, sigmas, clusters, pulled=pulled, worlds=worlds, seed=SEED + offset
        )

    def alternative(pulled: float, offset: int) -> dict[str, float]:
        found = run(pulled, POWER_WORLDS, offset)
        observed = power_at(found["mean_effect"], h1["std_error"], clusters=h1["clusters"])
        return {
            "effect": found["mean_effect"],
            "power_simulated": found["rejections"],
            "power_observed": observed,
        }

    return {
        "size_worlds": SIZE_WORLDS,
        "power_worlds": POWER_WORLDS,
        "size": run(0.0, SIZE_WORLDS, 0)["rejections"],
        "power": {f"{q:.2f}": alternative(q, i + 1) for i, q in enumerate(PULLED)},
    }


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
