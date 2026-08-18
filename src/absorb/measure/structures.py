"""Recover whole positions from their legs, and value them correctly.

The problem this fixes
----------------------
Classifying cleared series one at a time counts a single position many times and
values it wrongly. Three instances of this were found in succession:

* a fund's written put counted as an outright position rather than half of a forward;
* an MSFT call butterfly counted as three large outright lines, credited with 49 times
  its maximum attainable value;
* a buffer fund counted four times, once per leg, at nearly three times its exposure.

The common cause is treating series independently when they are legs of one trade.

Two rules follow
----------------
**Group before counting.** Legs of one structure carry near-identical contract counts
at a shared expiry, because they were transacted together. Clustering on contract
count within an expiry recovers the structure.

**Value on the underlying, not the strike.** Strike times contracts is not exposure.
It overstates far out-of-the-money legs and catastrophically understates deep
in-the-money ones: a buffer fund's synthetic long call struck at \\$1.87 against a
\\$765 spot carries \\$2.9bn of exposure and is recorded as \\$7m. Underlying-equivalent
exposure --- contracts times spot --- is the scale that survives both.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

STRUCTURE_COLUMNS = (
    "symbol",
    "expiry",
    "structure",
    "n_legs",
    "contracts",
    "exposure",
    "call_legs",
    "put_legs",
    "min_strike",
    "max_strike",
)


@dataclass(frozen=True)
class GroupingConfig:
    """Settings for leg grouping.

    `count_tolerance` is relative: legs of one trade rarely match to the contract
    because of partial exercise and assignment, but they stay within a few percent.
    """

    count_tolerance: float = 0.05
    min_contracts: int = 500
    min_legs: int = 2


def _cluster_by_count(counts: np.ndarray, tolerance: float) -> np.ndarray:
    """Assign legs to clusters of near-equal contract count.

    Legs are sorted and split wherever the relative gap to the previous leg exceeds
    the tolerance, which groups equal-sized legs without needing a cluster count.
    """
    order = np.argsort(-counts)
    labels = np.empty(len(counts), dtype=int)
    current = 0
    labels[order[0]] = 0
    for prev, this in zip(order[:-1], order[1:], strict=True):
        reference = max(counts[prev], 1.0)
        if abs(counts[this] - counts[prev]) / reference > tolerance:
            current += 1
        labels[this] = current
    return labels


def _label(call_legs: int, put_legs: int, strikes: np.ndarray, counts: np.ndarray) -> str:
    n = call_legs + put_legs
    if n == 2 and call_legs == 1 and put_legs == 1:
        # One call and one put at the same strike replicate a forward.
        return "synthetic" if np.ptp(strikes) < 0.05 else "risk_reversal"
    if n == 2:
        return "vertical_spread"
    if n == 3 and len(counts) == 3:
        lo, mid, hi = np.sort(strikes)
        if np.isclose(mid - lo, hi - mid, rtol=0.02):
            return "butterfly"
        return "three_leg"
    if n == 4 and call_legs == 2 and put_legs == 2:
        return "collar_buffer"
    return f"{n}_leg"


def group_structures(
    census: pd.DataFrame, spot_by_symbol: dict[str, float], config: GroupingConfig | None = None
) -> pd.DataFrame:
    """Group legs into structures and value each once, on the underlying.

    ``contracts`` is the representative size of the structure, taken as the median leg
    rather than the sum, because the legs are the same position seen from different
    strikes. ``exposure`` is that size times spot.
    """
    cfg = config or GroupingConfig()
    if census.empty:
        return pd.DataFrame(columns=list(STRUCTURE_COLUMNS))

    records = []
    for (symbol, expiry), group in census.groupby(["symbol", "expiry"], sort=False):
        spot = spot_by_symbol.get(symbol)
        if not spot or not np.isfinite(spot):
            continue

        legs = []
        for row in group.itertuples():
            if row.call_open_interest > 0:
                legs.append((float(row.call_open_interest), float(row.strike), "C"))
            if row.put_open_interest > 0:
                legs.append((float(row.put_open_interest), float(row.strike), "P"))
        legs = [leg for leg in legs if leg[0] >= cfg.min_contracts]
        if len(legs) < cfg.min_legs:
            continue

        counts = np.array([leg[0] for leg in legs])
        labels = _cluster_by_count(counts, cfg.count_tolerance)

        for label in np.unique(labels):
            members = [leg for leg, lab in zip(legs, labels, strict=True) if lab == label]
            if len(members) < cfg.min_legs:
                continue
            sizes = np.array([m[0] for m in members])
            strikes = np.array([m[1] for m in members])
            call_legs = sum(1 for m in members if m[2] == "C")
            put_legs = len(members) - call_legs
            representative = float(np.median(sizes))

            records.append(
                {
                    "symbol": symbol,
                    "expiry": expiry,
                    "structure": _label(call_legs, put_legs, strikes, sizes),
                    "n_legs": len(members),
                    "contracts": representative,
                    "exposure": representative * 100 * spot,
                    "call_legs": call_legs,
                    "put_legs": put_legs,
                    "min_strike": float(strikes.min()),
                    "max_strike": float(strikes.max()),
                }
            )

    if not records:
        return pd.DataFrame(columns=list(STRUCTURE_COLUMNS))
    frame = pd.DataFrame(records)[list(STRUCTURE_COLUMNS)]
    return frame.sort_values("exposure", ascending=False).reset_index(drop=True)


__all__ = ["STRUCTURE_COLUMNS", "GroupingConfig", "group_structures"]
