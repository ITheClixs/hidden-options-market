"""Result `listed_boxes`: traded FLEX box rates against listed SPX box rates, same dates.

Specification: `docs/log/2026-11-17-listed-boxes-spec.md`. The FLEX trades are the
headline sample of the box-rate result; the listed rates come from SPX quotes of each
trade date by put-call parity (`measure.listed_boxes`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.collect.treasury import SNAPSHOT as CURVE_SNAPSHOT
from hidden_options.config import PANEL_END, RAW_DIR
from hidden_options.measure.anatomy import UNDERLYING_GROUPS
from hidden_options.measure.anatomy_macros import dollars
from hidden_options.measure.box_rates import block_bootstrap, spread_summary
from hidden_options.measure.box_rates_macros import basis_points
from hidden_options.measure.box_rates_result import collect_trades, headline_trades, trade_days
from hidden_options.measure.hidden_share_data import load_chains, priced_chains, trading_calendar
from hidden_options.measure.listed_boxes import listed_curve, rate_at
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "listed_boxes"
SEED = 20261117
DRAWS = 2000


def listed_boxes_result(headline: pd.DataFrame, quotes: pd.DataFrame) -> Result:
    """The figures the specification lists.

    `headline` holds the headline FLEX box trades (with `rate`, `benchmark`, `settle_days`,
    `face`, `trade_date`, `underlying`); `quotes` SPX's listed rows by session `date`.
    """
    curves = {
        pd.Timestamp(str(day)): listed_curve(rows, pd.Timestamp(str(day)))
        for day, rows in quotes.groupby("date")
    }
    curves = {day: curve for day, curve in curves.items() if not curve.empty}
    sessions = sorted(curves)
    window = (
        headline[(headline["trade_date"] >= sessions[0]) & (headline["trade_date"] <= sessions[-1])]
        if sessions
        else headline.iloc[0:0]
    )
    listed = np.array(
        [
            rate_at(curves[day], days) if day in curves else np.nan
            for day, days in zip(window["trade_date"], window["settle_days"], strict=True)
        ],
        dtype=float,
    )
    matched = window.assign(listed=listed)
    matched = matched[np.isfinite(matched["listed"])].reset_index(drop=True)
    diff = matched.assign(spread=matched["rate"] - matched["listed"])
    over = matched.assign(spread=matched["listed"] - matched["benchmark"])
    group = np.where(diff["underlying"].isin(UNDERLYING_GROUPS[:2]), diff["underlying"], "other")
    used = pd.concat(curves.values(), ignore_index=True) if curves else pd.DataFrame()
    values: dict[str, Any] = {
        "sessions": len(sessions),
        "first_session": f"{sessions[0]:%Y-%m-%d}" if sessions else None,
        "last_session": f"{sessions[-1]:%Y-%m-%d}" if sessions else None,
        "window_trades": len(window),
        "window_face": float(window["face"].sum()),
        "unmatched": int(len(window) - len(matched)),
        "difference": {
            **spread_summary(diff),
            **block_bootstrap(diff, diff["trade_date"].astype(str), draws=DRAWS, seed=SEED),
        },
        "by_underlying": {name: spread_summary(diff[group == name]) for name in UNDERLYING_GROUPS},
        "listed_over_treasury": spread_summary(over),
        "fit": {
            "median_strikes": float(used["strikes"].median()) if len(used) else None,
            "median_r2": float(used["r2"].median()) if len(used) else None,
            "expiries": len(used),
        },
    }
    run_inputs = {"first_session": values["first_session"], "last_session": values["last_session"]}
    return Result(NAME, values, listed_boxes_macros(values), run_inputs, now_iso())


def listed_boxes_macros(values: Mapping[str, Any]) -> dict[str, str]:
    diff, over, fit = values["difference"], values["listed_over_treasury"], values["fit"]
    macros = {
        "LBoxSessions": formats.count(values["sessions"]),
        "LBoxMatched": formats.count(diff["trades"]),
        "LBoxUnmatched": formats.count(values["unmatched"]),
        "LBoxFace": dollars(diff["face"]),
        "LBoxWindowFace": dollars(values["window_face"]),
        "LBoxWindowTrades": formats.count(values["window_trades"]),
        "LBoxDiffMedian": basis_points(diff["median"]),
        "LBoxDiffLow": basis_points(diff["q25"]),
        "LBoxDiffHigh": basis_points(diff["q75"]),
        "LBoxDiffMean": basis_points(diff["mean"]),
        "LBoxDiffCILow": basis_points(diff["median_low"]),
        "LBoxDiffCIHigh": basis_points(diff["median_high"]),
        "LBoxListedOverTsyMedian": basis_points(over["median"]),
        "LBoxListedOverTsyMean": basis_points(over["mean"]),
        "LBoxStrikes": formats.count(fit["median_strikes"] or 0),
        "LBoxRSquared": formats.decimal(fit["median_r2"] or 0.0, 4),
    }
    if values["first_session"]:
        macros["LBoxFirst"] = formats.long_date(pd.Timestamp(values["first_session"]))
        macros["LBoxLast"] = formats.long_date(pd.Timestamp(values["last_session"]))
    for name, stem in (("SPX", "SPX"), ("SPY", "SPY"), ("other", "Else")):
        row = values["by_underlying"][name]
        macros[f"LBoxDiff{stem}"] = basis_points(row["median"])
        macros[f"LBoxDiff{stem}Trades"] = formats.count(row["trades"])
    return macros


@ANALYSES.register(NAME)
def listed_boxes_analysis() -> Result:
    """The comparison on every SPX chain session on disk up to PANEL_END."""
    end = pd.Timestamp(PANEL_END)
    trades, *_ = collect_trades(trade_days(RAW_DIR, end))
    headline = headline_trades(trades, pd.read_parquet(RAW_DIR / CURVE_SNAPSHOT))
    chains = load_chains([RAW_DIR], trading_calendar(RAW_DIR), pattern="index_SPX.parquet")
    quotes = priced_chains(chains)
    quotes = quotes[(quotes["symbol"] == "SPX") & (quotes["date"] <= end)]
    return listed_boxes_result(headline, quotes)


__all__ = ["NAME", "listed_boxes_analysis", "listed_boxes_macros", "listed_boxes_result"]
