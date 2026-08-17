#!/usr/bin/env python
"""Stage 1 of the pilot: does a fund programme leave a volume footprint?

Design and thresholds are fixed in `docs/PILOT_SPEC.md`, written before this was run.

Estimand: the coefficient on post x friday in

    log(dollar volume)_it = a_i + d_t + b1 post_it + b2 (post_it x friday_t)
                            + b3 (friday_t x ever_treated_i) + g |return|_it + e_it

Name effects absorb persistent liquidity differences, date effects absorb market-wide
variation including the common Friday pattern, and |return| absorbs the mechanical
link between volume and volatility. b2 is therefore identified from whether treated
names gain *extra* Friday volume once their fund exists.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.collect.bars import fetch_bars  # noqa: E402
from absorb.collect.http import FetchError, build_session, fetch  # noqa: E402
from absorb.config import load_programmes, load_universe  # noqa: E402
from absorb.measure.panel import fit  # noqa: E402

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def fund_launch_dates(session, programmes) -> pd.DataFrame:
    """First trade date per fund, from the provider's chart metadata."""
    rows = []
    for programme in programmes:
        if programme.underlying.startswith("_"):
            continue
        try:
            payload = fetch(
                session,
                CHART.format(symbol=programme.fund),
                params={"interval": "1d", "range": "1d"},
            )
            meta = json.loads(payload.content)["chart"]["result"][0]["meta"]
            first = meta.get("firstTradeDate")
        except (FetchError, KeyError, IndexError, TypeError, ValueError) as exc:
            logging.warning("%s: no launch date (%s)", programme.fund, exc)
            continue
        if first:
            rows.append(
                {
                    "fund": programme.fund,
                    "symbol": programme.underlying,
                    "launch": pd.Timestamp(first, unit="s", tz="UTC").normalize().tz_localize(None),
                }
            )
    return pd.DataFrame(rows)


def daily_bars(session, symbols: list[str], lookback: str = "5y") -> pd.DataFrame:
    frames = []
    for symbol in symbols:
        try:
            snapshot = fetch_bars(session, symbol, interval="1d", lookback=lookback)
        except Exception as exc:  # noqa: BLE001
            logging.warning("%s: no bars (%s)", symbol, exc)
            continue
        frames.append(snapshot.frame)
    if not frames:
        raise RuntimeError("no bars retrieved for any symbol")
    return pd.concat(frames, ignore_index=True)


def fund_scale() -> pd.DataFrame:
    """Net assets per underlying, from the most recent holdings capture.

    A single current figure, not a time series. It is adequate for sorting names into
    dose terciles, but it cannot capture a programme growing over its life, and any
    conclusion that depends on that must wait for the N-PORT series.
    """
    files = sorted(Path("data/raw/fund_holdings").glob("date=*/*.parquet"))
    if not files:
        return pd.DataFrame(columns=["symbol", "net_assets"])

    programmes = {p.fund: p.underlying for p in load_programmes()}
    rows = []
    for path in files:
        frame = pd.read_parquet(path)
        if frame.empty:
            continue
        fund = str(frame["fund"].iloc[0])
        underlying = programmes.get(fund)
        assets = frame["net_assets"].dropna()
        if underlying and not underlying.startswith("_") and len(assets):
            rows.append({"symbol": underlying, "net_assets": float(assets.iloc[0])})

    if not rows:
        return pd.DataFrame(columns=["symbol", "net_assets"])
    # Several programmes can share an underlying; the flow is their sum.
    return pd.DataFrame(rows).groupby("symbol", as_index=False)["net_assets"].sum()


def build_panel(bars: pd.DataFrame, launches: pd.DataFrame, scale: pd.DataFrame) -> pd.DataFrame:
    panel = bars.copy()
    panel["date"] = pd.to_datetime(panel["timestamp"]).dt.tz_localize(None).dt.normalize()
    panel = panel.sort_values(["symbol", "date"])

    panel["dollar_volume"] = panel["close"] * panel["volume"]
    panel = panel[panel["dollar_volume"] > 0]
    panel["log_dv"] = np.log(panel["dollar_volume"])
    panel["ret"] = panel.groupby("symbol")["close"].pct_change()
    panel["abs_ret"] = panel["ret"].abs()

    first_launch = launches.groupby("symbol", as_index=False)["launch"].min()
    panel = panel.merge(first_launch, on="symbol", how="left")
    panel["ever_treated"] = panel["launch"].notna().astype(float)
    panel["post"] = ((panel["launch"].notna()) & (panel["date"] > panel["launch"])).astype(float)
    panel["friday"] = (panel["date"].dt.weekday == 4).astype(float)

    panel["post_friday"] = panel["post"] * panel["friday"]
    panel["friday_treated"] = panel["friday"] * panel["ever_treated"]

    adv = panel.groupby("symbol", as_index=False)["dollar_volume"].median()
    adv = adv.rename(columns={"dollar_volume": "adv"})
    panel = panel.merge(adv, on="symbol", how="left").merge(scale, on="symbol", how="left")
    panel["dose"] = panel["net_assets"] / panel["adv"]

    return panel.dropna(subset=["log_dv", "abs_ret"])


REGRESSORS = ["post", "post_friday", "friday_treated", "abs_ret"]


def report(panel: pd.DataFrame, label: str) -> None:
    try:
        result = fit(panel, "log_dv", REGRESSORS)
    except ValueError as exc:
        print(f"{label:34s} SKIPPED ({exc})")
        return
    est = result["post_friday"]
    print(f"{label:34s} {est.describe()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback", default="5y")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    session = build_session()
    programmes = [p for p in load_programmes() if not p.underlying.startswith("_")]
    universe = load_universe()

    launches = fund_launch_dates(session, programmes)
    treated = sorted(set(launches["symbol"]))
    controls = [s for s in universe.control_single_name if s not in treated]
    print(f"treated underlyings: {len(treated)} | controls: {len(controls)}")

    bars = daily_bars(session, treated + controls, args.lookback)
    panel = build_panel(bars, launches, fund_scale())
    print(
        f"panel: {len(panel):,} obs | {panel.symbol.nunique()} names | "
        f"{panel.date.nunique():,} dates | "
        f"{panel.date.min().date()} to {panel.date.max().date()}"
    )

    print("\n--- PRIMARY ---")
    report(panel, "all treated")

    print("\n--- BY DOSE TERCILE (net assets / ADV) ---")
    dosed = panel[panel["dose"].notna()]
    if len(dosed):
        edges = dosed.groupby("symbol")["dose"].first().quantile([1 / 3, 2 / 3]).to_numpy()
        for i, name in enumerate(["low", "mid", "high"]):
            lo = -np.inf if i == 0 else edges[i - 1]
            hi = np.inf if i == 2 else edges[i]
            names = dosed.groupby("symbol")["dose"].first()
            keep = set(names[(names > lo) & (names <= hi)].index) | set(controls)
            report(panel[panel.symbol.isin(keep)], f"dose {name}")

    print("\n--- FALSIFICATION ---")
    shifted = panel.copy()
    shifted["post_friday"] = shifted["post"] * (shifted["date"].dt.weekday == 3).astype(float)
    report(shifted, "placebo: Thursday not Friday")

    pre = panel[(panel["post"] == 0)].copy()
    pre["post"] = (
        pre["launch"].notna() & (pre["date"] > pre["launch"] - pd.Timedelta(days=180))
    ).astype(float)
    pre["post_friday"] = pre["post"] * pre["friday"]
    report(pre, "pre-trend: 6m before launch")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
