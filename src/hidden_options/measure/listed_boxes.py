"""Box rates implied by listed SPX quotes, by put-call parity.

Specification: `docs/log/2026-11-17-listed-boxes-spec.md`. For European options the call
less the put at one strike is S·e^(−qT) − K·e^(−rT), so across strikes of one expiry the
call mid less the put mid is a line in the strike whose slope is −e^(−rT). The rate that
slope implies is the rate of a box spread between any two of those strikes: the method
of van Binsbergen, Diamond and Grotteria (2022). Days are counted from settlement to
settlement, as for FLEX boxes (`box_rates.settlement_days`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hidden_options.measure.box_rates import RATE_RANGE, settlement_days

MONEYNESS_BAND = 0.20
MIN_STRIKES = 10
DAYS_PER_YEAR = 365.0
CURVE_COLUMNS = ("expiry", "settle_days", "rate", "strikes", "r2")


def listed_curve(quotes: pd.DataFrame, session: pd.Timestamp) -> pd.DataFrame:
    """One session's box rate for each listed expiry, in CURVE_COLUMNS, by settle days.

    `quotes` holds the session's listed rows: `expiry`, `right`, `strike`, `bid`, `ask`
    and `underlying_price`.
    """
    prices = quotes["underlying_price"].dropna()
    if prices.empty:  # a settlement with no quotes from its own session
        return pd.DataFrame(columns=list(CURVE_COLUMNS))
    spot = float(prices.iloc[0])
    usable = quotes[(quotes["bid"] > 0) & (quotes["ask"] >= quotes["bid"])]
    usable = usable[(usable["strike"] / spot - 1).abs() <= MONEYNESS_BAND]
    mids = usable.assign(mid=(usable["bid"] + usable["ask"]) / 2)
    wide = mids.pivot_table(
        index=["expiry", "strike"], columns="right", values="mid", aggfunc="mean"
    )
    if not {"C", "P"} <= set(wide.columns):
        return pd.DataFrame(columns=list(CURVE_COLUMNS))
    wide = wide.dropna(subset=["C", "P"]).reset_index()
    rows = []
    for key, group in wide.groupby("expiry"):
        if len(group) < MIN_STRIKES:
            continue
        expiry = pd.Timestamp(str(key))
        days = int(settlement_days(pd.Series([session]), pd.Series([expiry]))[0])
        if days <= 0:
            continue
        strike = group["strike"].to_numpy(float)
        parity = (group["C"] - group["P"]).to_numpy(float)
        slope, intercept = np.polyfit(strike, parity, 1)
        if slope >= 0:
            continue
        fitted = intercept + slope * strike
        total = float(((parity - parity.mean()) ** 2).sum())
        r2 = 1 - float(((parity - fitted) ** 2).sum()) / total if total else 0.0
        rate = -np.log(-slope) / (days / DAYS_PER_YEAR)
        low, high = RATE_RANGE
        if not low <= rate <= high:
            continue
        rows.append(
            {
                "expiry": expiry,
                "settle_days": days,
                "rate": float(rate),
                "strikes": len(group),
                "r2": r2,
            }
        )
    frame = pd.DataFrame(rows, columns=list(CURVE_COLUMNS))
    return frame.sort_values("settle_days").reset_index(drop=True)


def rate_at(curve: pd.DataFrame, days: float) -> float:
    """The curve's rate at `days`, linear between expiries and flat beyond them."""
    if curve.empty:
        return float("nan")
    return float(
        np.interp(days, curve["settle_days"].to_numpy(float), curve["rate"].to_numpy(float))
    )


__all__ = ["CURVE_COLUMNS", "MIN_STRIKES", "MONEYNESS_BAND", "listed_curve", "rate_at"]
