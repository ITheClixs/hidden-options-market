#!/usr/bin/env python
"""Intraday test: does programme size shift the underlying's time-of-day volume shape?

Why the design differs from Stage 1
-----------------------------------
Only 60 days of 5-minute history is freely available, and every programme in the
sample launched before that window opens. There is no pre/post variation inside it, so
the difference-in-differences that identified Stage 1 collapses.

Identification instead comes from the interaction of dose with time of day. Name fixed
effects absorb each name's overall liquidity, and date x bin fixed effects absorb the
market-wide intraday shape on every session. What remains is whether names with larger
programmes carry a *different* volume profile across the session:

    log(dollar volume)_ibt = a_i + d_bt + sum_b beta_b (log_dose_i x bin_b)
                             + g |return|_ibt + e_ibt

If dealers hedge a scheduled programme, beta_b should be positive in the bins where
they transact — most plausibly the close — and flat elsewhere. A flat profile across
every bin is evidence against a concentrated hedging footprint.

One bin is dropped as the reference, so coefficients read as deviations from it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.collect.bars import fetch_bars  # noqa: E402
from absorb.collect.http import build_session  # noqa: E402
from absorb.collect.nport import as_of_series  # noqa: E402
from absorb.config import RAW_DIR, load_programmes, load_universe  # noqa: E402
from absorb.measure.panel import fit  # noqa: E402

BIN_MINUTES = 30
REFERENCE_BIN = "12:00"  # mid-session, the quietest and least mechanical period


def intraday_bars(session, symbols: list[str]) -> pd.DataFrame:
    frames = []
    for symbol in symbols:
        try:
            snapshot = fetch_bars(session, symbol, interval="5m", lookback="60d")
        except Exception as exc:  # noqa: BLE001
            logging.warning("%s: %s", symbol, exc)
            continue
        frames.append(snapshot.frame)
    if not frames:
        raise RuntimeError("no intraday bars retrieved")
    return pd.concat(frames, ignore_index=True)


def build_intraday_panel(bars: pd.DataFrame, dose_by_symbol: dict[str, float]) -> pd.DataFrame:
    frame = bars.copy()
    stamp = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("America/New_York")
    frame["date"] = stamp.dt.date
    frame["minutes"] = stamp.dt.hour * 60 + stamp.dt.minute

    # Regular session only: extended-hours bars have a different liquidity regime.
    frame = frame[(frame["minutes"] >= 9 * 60 + 30) & (frame["minutes"] < 16 * 60)]

    binned = (frame["minutes"] // BIN_MINUTES) * BIN_MINUTES
    frame["bin"] = [f"{m // 60:02d}:{m % 60:02d}" for m in binned]

    grouped = (
        frame.assign(dv=frame["close"] * frame["volume"])
        .groupby(["symbol", "date", "bin"], as_index=False)
        .agg(dv=("dv", "sum"), open=("open", "first"), close=("close", "last"))
    )
    grouped = grouped[grouped["dv"] > 0]
    grouped["log_dv"] = np.log(grouped["dv"])
    grouped["abs_ret"] = (grouped["close"] / grouped["open"] - 1).abs()

    grouped["date_bin"] = grouped["date"].astype(str) + "|" + grouped["bin"]
    grouped["log_dose"] = grouped["symbol"].map(dose_by_symbol)
    grouped["log_dose"] = grouped["log_dose"].fillna(grouped["log_dose"].min())
    return grouped.dropna(subset=["log_dv", "abs_ret"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    reports = pd.read_parquet(args.root / "nport" / "net_assets.parquet")

    from run_stage1 import daily_bars, fund_launch_dates  # noqa: PLC0415

    session = build_session()
    programmes = [p for p in load_programmes() if not p.underlying.startswith("_")]
    universe = load_universe()
    launches = (
        fund_launch_dates(session, programmes)
        .sort_values("launch")
        .drop_duplicates("symbol", keep="first")
    )
    treated = sorted(set(launches["symbol"]))
    controls = [s for s in universe.control_single_name if s not in treated]

    # Dose from the most recent report, over median daily dollar volume.
    daily = daily_bars(session, treated + controls, "1y")
    daily["dv"] = daily["close"] * daily["volume"]
    adv = daily.groupby("symbol")["dv"].median()

    dose = {}
    for symbol in treated:
        fund = launches.loc[launches.symbol == symbol, "fund"].iloc[0]
        recent = as_of_series(reports, pd.Series([pd.Timestamp.today()]), fund)
        if pd.notna(recent.iloc[0]) and symbol in adv:
            dose[symbol] = float(np.log(recent.iloc[0] / adv[symbol]))
    print(f"treated with dose: {len(dose)} | controls: {len(controls)}")

    bars = intraday_bars(session, treated + controls)
    panel = build_intraday_panel(bars, dose)
    print(
        f"panel {len(panel):,} obs | {panel.symbol.nunique()} names | "
        f"{panel.date.nunique()} sessions | {panel.bin.nunique()} bins"
    )

    bins = sorted(panel["bin"].unique())
    regressors = []
    for label in bins:
        if label == REFERENCE_BIN:
            continue
        column = f"dose_{label.replace(':', '')}"
        panel[column] = panel["log_dose"] * (panel["bin"] == label).astype(float)
        regressors.append(column)
    regressors.append("abs_ret")

    result = fit(panel, "log_dv", regressors, entity="symbol", time="date_bin")

    print(f"\n--- DOSE x TIME-OF-DAY (reference bin {REFERENCE_BIN}) ---")
    print(f"{'bin':>7s} {'beta':>9s} {'t':>7s} {'MDE80':>8s}")
    for label in bins:
        if label == REFERENCE_BIN:
            print(f"{label:>7s} {'--':>9s} {'ref':>7s} {'':>8s}")
            continue
        est = result[f"dose_{label.replace(':', '')}"]
        flag = "  <<<" if abs(est.t_stat) > 2.5 else ""
        print(f"{label:>7s} {est.coefficient:+9.4f} {est.t_stat:+7.2f} {est.mde80:8.4f}{flag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
