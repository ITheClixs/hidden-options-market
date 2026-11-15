"""SPY's gamma exposure under three readings, with fund legs signed where disclosed.

Specification: `docs/log/2026-11-15-gex-map-spec.md`. Gamma-exposure (GEX) figures in
practitioner use sign listed open interest by convention, dealers long calls and short
puts. This module computes the dealer's net dollar gamma for a 1% move across price
levels three ways:

1. `listed`: listed series under the convention;
2. `convention`: listed and FLEX series under the convention;
3. `signed`: as 2, except that the part of each FLEX series matched to a fund's holding
   takes the dealer's side opposite the fund's.

Each series carries `sigma`, held fixed as the level moves. `signed` is the share of a
series' open interest whose side is disclosed and `dealer_sign` the dealer's side on that
share (+1 long, -1 short).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hidden_options.measure.hidden_gamma import dollar_gamma
from hidden_options.measure.pricing import black_scholes_greeks

LEVELS = tuple(round(-0.15 + 0.005 * step, 3) for step in range(61))
DAYS_PER_YEAR = 365.0


def gex_profiles(
    book: pd.DataFrame, *, spot: float, as_of: pd.Timestamp, rate: float
) -> dict[str, Any]:
    """The three readings at each level of LEVELS, and the size of the signed legs."""
    years = (pd.to_datetime(book["expiry"]) - as_of).dt.days.to_numpy(float) / DAYS_PER_YEAR
    contracts = book["open_interest"].to_numpy(float)
    convention = np.where(book["right"] == "C", 1.0, -1.0)
    signed_share = book["signed"].to_numpy(float)
    dealer = book["dealer_sign"].to_numpy(float)
    listed = (book["source"] == "listed").to_numpy()
    sign_signed = convention * (1 - signed_share) + dealer * signed_share
    out: dict[str, Any] = {"moves": list(LEVELS), "listed": [], "convention": [], "signed": []}
    for move in LEVELS:
        level = np.full(len(book), spot * (1 + move))
        unit = black_scholes_greeks(
            level, book["strike"], years, book["sigma"], rate=rate, carry=0.0, is_call=True
        ).gamma
        dollars = np.nan_to_num(dollar_gamma(unit, contracts, level))
        out["listed"].append(float((dollars * convention)[listed].sum()))
        out["convention"].append(float((dollars * convention).sum()))
        out["signed"].append(float((dollars * sign_signed).sum()))
        if move == 0.0:
            out["matched_gross"] = float((dollars * signed_share).sum())
            out["listed_gross"] = float(dollars[listed].sum())
            out["flex_gross"] = float(dollars[~listed].sum())
    out["matched_share_of_listed"] = _share(out["matched_gross"], out["listed_gross"])
    out["matched_share_of_flex"] = _share(out["matched_gross"], out["flex_gross"])
    return out


def zero_level(moves: list[float], net: list[float]) -> float | None:
    """The move from spot at which `net` changes sign, nearest to spot, by linear
    interpolation; None if it keeps one sign over the range."""
    crossings = []
    for i in range(len(net) - 1):
        a, b = net[i], net[i + 1]
        if (a < 0) != (b < 0):
            crossings.append(moves[i] + (moves[i + 1] - moves[i]) * (-a) / (b - a))
    return min(crossings, key=abs) if crossings else None


def _share(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


__all__ = ["LEVELS", "gex_profiles", "zero_level"]
