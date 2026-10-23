"""Quantify the option gamma that listed chains cannot see.

The question
------------
Dealer-gamma measures in public use are built from listed option chains. FLEX series
are not in those chains. If FLEX open interest were attributed the same way listed
open interest is, how different would the measured gamma be?

This is deliberately a statement about *measurement*, not about true dealer
positioning. Attributing a sign to open interest requires knowing who holds each side,
which listed data does not reveal --- that is the standing problem in this literature
and we do not solve it. What we can say is that a standard calculation omits inputs,
and by how much.

Two corrections matter and both reduce the estimate
---------------------------------------------------
**Matched legs cancel.** A series carrying equal call and put open interest is a
conversion, reversal or box. Long call plus short put at one strike is a forward, so
the pair contributes no gamma. Summing both legs at full weight, as a naive count
would, overstates the contribution. We therefore attribute gamma only to the
*unmatched residual* at each strike.

**Local volatility, not a single median.** Gamma is sharply peaked in moneyness, so
pricing a far-out-of-the-money FLEX strike at the chain's median implied volatility
misstates it badly. We interpolate implied volatility from the nearest listed strikes
in the same expiry where available.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

RISK_FREE = 0.04

RESULT_COLUMNS = (
    "symbol",
    "listed_gamma",
    "flex_gamma_gross",
    "flex_gamma_residual",
    "flex_series",
    "flex_open_interest",
    "share_gross",
    "share_residual",
)


@dataclass(frozen=True)
class GammaGapConfig:
    """Settings for the gamma-gap calculation."""

    min_days: int = 1
    max_days: int = 400
    fallback_vol: float = 0.50


def bs_gamma(spot: float, strike: float, years: float, vol: float) -> float:
    """Black-Scholes gamma. Identical for a call and a put at the same strike."""
    if years <= 0 or vol <= 0 or strike <= 0 or spot <= 0:
        return 0.0
    d1 = (np.log(spot / strike) + (RISK_FREE + vol * vol / 2) * years) / (vol * np.sqrt(years))
    return float(norm.pdf(d1) / (spot * vol * np.sqrt(years)))


def local_vol(chain: pd.DataFrame, expiry, strike: float, fallback: float) -> float:
    """Implied volatility near a strike, taken from the nearest listed strikes.

    Falls back to the expiry's median, then the chain's median, then a constant.
    A single chain-wide median is not adequate: gamma is peaked in moneyness and a
    far out-of-the-money FLEX strike priced at an at-the-money volatility is wrong by
    a large factor.
    """
    same_expiry = chain[(chain["expiry"] == expiry) & (chain["iv"] > 0)]
    if len(same_expiry):
        nearest = same_expiry.iloc[(same_expiry["strike"] - strike).abs().argsort()[:4]]
        value = float(nearest["iv"].median())
        if np.isfinite(value) and value > 0:
            return value

    any_iv = chain[chain["iv"] > 0]["iv"]
    if len(any_iv):
        value = float(any_iv.median())
        if np.isfinite(value) and value > 0:
            return value
    return fallback


def gamma_gap(
    chain: pd.DataFrame,
    open_interest: pd.DataFrame,
    as_of: pd.Timestamp,
    config: GammaGapConfig | None = None,
) -> dict | None:
    """Compare listed-chain gamma with the gamma of FLEX series absent from it.

    ``flex_gamma_gross`` counts all open interest in absent series.
    ``flex_gamma_residual`` counts only the unmatched excess of one right over the
    other, which is the economically meaningful figure because matched legs cancel.
    """
    cfg = config or GammaGapConfig()
    if chain.empty or open_interest.empty:
        return None

    spot = float(chain["underlying_price"].iloc[0])
    if not np.isfinite(spot) or spot <= 0:
        return None

    priced = chain.dropna(subset=["gamma", "open_interest"])
    listed_gamma = float(
        (priced["gamma"] * priced["open_interest"] * 100 * spot * (spot * 0.01)).sum()
    )
    if listed_gamma <= 0:
        return None

    listed_keys = set(zip(chain["expiry"], chain["strike"].round(2), strict=True))

    gross = residual = 0.0
    n_series = 0
    n_oi = 0

    for row in open_interest.itertuples():
        if (row.expiry, round(row.strike, 2)) in listed_keys:
            continue
        days = (pd.Timestamp(row.expiry) - as_of).days
        if days < cfg.min_days or days > cfg.max_days:
            continue

        vol = local_vol(chain, row.expiry, row.strike, cfg.fallback_vol)
        gamma = bs_gamma(spot, row.strike, days / 365.0, vol)
        scale = gamma * 100 * spot * (spot * 0.01)

        call, put = float(row.call_open_interest), float(row.put_open_interest)
        gross += scale * (call + put)
        residual += scale * abs(call - put)
        n_series += 1
        n_oi += int(call + put)

    if n_series == 0:
        return None

    return {
        "symbol": chain["symbol"].iloc[0],
        "listed_gamma": listed_gamma,
        "flex_gamma_gross": gross,
        "flex_gamma_residual": residual,
        "flex_series": n_series,
        "flex_open_interest": n_oi,
        "share_gross": gross / listed_gamma,
        "share_residual": residual / listed_gamma,
    }


__all__ = ["RESULT_COLUMNS", "GammaGapConfig", "bs_gamma", "gamma_gap", "local_vol"]
