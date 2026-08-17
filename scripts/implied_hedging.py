#!/usr/bin/env python
"""Size the hedging flow that option-income programmes actually imply.

This is the calculation that should have preceded the empirical tests.

These funds hold a synthetic long (long call plus short put at effectively the same
strike) and write calls against it. The synthetic long is a forward by put-call
parity, so it carries essentially **zero gamma**: the dealer on the other side hedges
it once at inception and does not rebalance it. All the rebalancing flow comes from the
short-call overlay, and because the funds write call *spreads* rather than naked calls,
even that is partly offset.

The consequence is that notional is a badly misleading measure of these programmes'
hedging footprint. A fund can hold several times its underlying's daily turnover in
notional while implying a daily rehedge of a fraction of a percent of it.

Greeks are taken from the exchange chain where the series is listed, and computed under
Black-Scholes where the leg is FLEX and therefore absent from the chain. The FLEX legs
are exactly the synthetic puts, so omitting them would leave the long synthetic calls
uncancelled and overstate gamma by orders of magnitude.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.config import RAW_DIR, load_programmes  # noqa: E402

RISK_FREE = 0.04


def bs_greeks(spot: float, strike: float, years: float, vol: float, right: str):
    """Black-Scholes delta and gamma, used only for FLEX legs absent from the chain."""
    if years <= 0 or vol <= 0 or strike <= 0:
        return (1.0 if right == "C" else -1.0), 0.0
    d1 = (np.log(spot / strike) + (RISK_FREE + vol * vol / 2) * years) / (vol * np.sqrt(years))
    delta = norm.cdf(d1) if right == "C" else norm.cdf(d1) - 1.0
    gamma = norm.pdf(d1) / (spot * vol * np.sqrt(years))
    return delta, gamma


def load(root: Path):
    holdings = pd.concat(
        [pd.read_parquet(f) for f in glob.glob(str(root / "fund_holdings/date=*/*.parquet"))],
        ignore_index=True,
    ).drop_duplicates(subset=["fund", "position_ticker", "contracts"])

    chains = pd.concat(
        [pd.read_parquet(f) for f in glob.glob(str(root / "cboe_chain/date=*/equity_*.parquet"))],
        ignore_index=True,
    ).drop_duplicates(subset=["symbol", "contract"])

    bars = pd.concat(
        [
            pd.read_parquet(f)
            for f in glob.glob(str(root / "underlying_bars/interval=1d/date=*/*.parquet"))
        ],
        ignore_index=True,
    )
    adv = bars.assign(dv=bars["close"] * bars["volume"]).groupby("symbol")["dv"].median()
    return holdings, chains, adv


def programme_exposure(holdings, chains, adv, fund: str, underlying: str, as_of: pd.Timestamp):
    legs = holdings[(holdings["fund"] == fund) & holdings["is_option"].fillna(False)]
    chain = chains[chains["symbol"] == underlying]
    if legs.empty or chain.empty:
        return None

    spot = float(chain["underlying_price"].iloc[0])
    fallback_vol = float(chain["iv"].replace(0, np.nan).median())

    dollar_delta = 0.0
    dollar_gamma_1pct = 0.0
    n_flex = 0

    for leg in legs.itertuples():
        years = max((pd.Timestamp(leg.expiry) - as_of).days, 0) / 365.0
        hit = chain[
            (chain["expiry"] == leg.expiry)
            & (chain["right"] == leg.right)
            & (np.isclose(chain["strike"], leg.strike, atol=0.005))
        ]
        if len(hit) and pd.notna(hit["delta"].iloc[0]) and hit["iv"].iloc[0] > 0:
            delta, gamma = float(hit["delta"].iloc[0]), float(hit["gamma"].iloc[0])
        else:
            delta, gamma = bs_greeks(spot, leg.strike, years, fallback_vol, leg.right)
            n_flex += 1

        dollar_delta += leg.contracts * 100 * delta * spot
        dollar_gamma_1pct += leg.contracts * 100 * gamma * spot * (spot * 0.01)

    turnover = float(adv.get(underlying, np.nan))
    return {
        "fund": fund,
        "underlying": underlying,
        "dollar_delta_m": dollar_delta / 1e6,
        "gamma_per_1pct_m": dollar_gamma_1pct / 1e6,
        "adv_m": turnover / 1e6,
        "hedge_pct_adv": abs(dollar_gamma_1pct) / turnover * 100 if turnover else np.nan,
        "flex_legs": n_flex,
        "legs": len(legs),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    holdings, chains, adv = load(args.root)
    as_of = pd.Timestamp.today().normalize()

    rows = []
    for programme in load_programmes():
        if programme.underlying.startswith("_"):
            continue
        result = programme_exposure(
            holdings, chains, adv, programme.fund, programme.underlying, as_of
        )
        if result:
            rows.append(result)

    frame = pd.DataFrame(rows).sort_values("hedge_pct_adv", ascending=False)
    pd.set_option("display.width", 160)
    print(frame.round(2).to_string(index=False))

    print(
        "\nA 1% move in the underlying implies a rehedge of "
        f"{frame.hedge_pct_adv.min():.2f}% to {frame.hedge_pct_adv.max():.2f}% of daily volume "
        f"(median {frame.hedge_pct_adv.median():.2f}%)."
    )
    print(
        "Notional is not the relevant scale: the synthetic long is a forward and carries "
        "no gamma, so only the short-call overlay generates rebalancing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
