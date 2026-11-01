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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd

CONTRACT_MULTIPLIER = 100
LEG_COLUMNS = ("underlying", "expiry", "right", "strike", "contracts")
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

    These values were frozen before the detector was first scored against fund holdings
    (`holdings_truth`). A change after that needs both scores reported.
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


def structure_type(
    rights: Sequence[str],
    strikes: Sequence[float] | np.ndarray,
    sizes: Sequence[float] | np.ndarray,
) -> str:
    """The label of a set of legs: `synthetic`, `collar_buffer`, `3_leg` and so on."""
    calls = sum(1 for right in rights if right == "C")
    return _label(calls, len(rights) - calls, np.asarray(strikes, dtype=float), np.asarray(sizes))


def group_legs(
    legs: pd.DataFrame, spots: Mapping[str, float], config: GroupingConfig | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group one date's legs into structures.

    Returns the legs with a `structure_id` (-1 for a leg in no structure) and a
    `structure` label, and a table of the structures in STRUCTURE_COLUMNS plus
    `structure_id`. Legs group within an underlying and expiry, on contract count alone,
    so an underlying without a spot is still grouped: only its `exposure` is missing.
    ``contracts`` in the table is the median leg, and ``exposure`` that size times spot.
    """
    cfg = config or GroupingConfig()
    ids = np.full(len(legs), -1, dtype=np.int64)
    labels = np.full(len(legs), None, dtype=object)
    records: list[dict[str, Any]] = []
    sizes = legs["contracts"].to_numpy(dtype=float)
    rights = legs["right"].to_numpy(dtype=object)
    strikes = legs["strike"].to_numpy(dtype=float)
    eligible = np.flatnonzero(sizes >= cfg.min_contracts)
    keys = legs.iloc[eligible]
    for found in keys.groupby(["underlying", "expiry"], sort=True).indices.values():
        rows = eligible[found]
        if len(rows) < cfg.min_legs:
            continue
        first = legs.iloc[rows[0]]
        clusters = _cluster_by_count(sizes[rows], cfg.count_tolerance)
        for cluster in np.unique(clusters):
            members = rows[clusters == cluster]
            if len(members) < cfg.min_legs:
                continue
            record = _structure(
                first["underlying"],
                first["expiry"],
                rights[members],
                strikes[members],
                sizes[members],
                spots,
            )
            record["structure_id"] = len(records)
            ids[members] = len(records)
            labels[members] = record["structure"]
            records.append(record)
    grouped = legs.assign(structure_id=ids, structure=labels)
    table = pd.DataFrame(records, columns=[*STRUCTURE_COLUMNS, "structure_id"])
    return grouped, table


def _structure(
    underlying: Any,
    expiry: Any,
    rights: np.ndarray,
    strikes: np.ndarray,
    sizes: np.ndarray,
    spots: Mapping[str, float],
) -> dict[str, Any]:
    call_legs = int((rights == "C").sum())
    representative = float(np.median(sizes))
    spot = spots.get(cast(str, underlying), float("nan"))
    return {
        "symbol": underlying,
        "expiry": expiry,
        "structure": structure_type(list(rights), strikes, sizes),
        "n_legs": len(rights),
        "contracts": representative,
        "exposure": representative * CONTRACT_MULTIPLIER * spot,
        "call_legs": call_legs,
        "put_legs": len(rights) - call_legs,
        "min_strike": float(strikes.min()),
        "max_strike": float(strikes.max()),
    }


def group_structures(
    census: pd.DataFrame, spot_by_symbol: dict[str, float], config: GroupingConfig | None = None
) -> pd.DataFrame:
    """Group a census's legs into structures and value each once, on the underlying.

    A symbol without a usable spot is left out. The rest is `group_legs`, largest first.
    """
    priced = census[census["symbol"].map(lambda name: _usable(spot_by_symbol.get(name)))]
    if priced.empty:
        return pd.DataFrame(columns=list(STRUCTURE_COLUMNS))
    calls = priced.assign(right="C", contracts=priced["call_open_interest"])
    puts = priced.assign(right="P", contracts=priced["put_open_interest"])
    both = pd.concat([calls, puts], ignore_index=True).rename(columns={"symbol": "underlying"})
    held = both.loc[both["contracts"] > 0, list(LEG_COLUMNS)].reset_index(drop=True)
    _, table = group_legs(held, spot_by_symbol, config)
    if table.empty:
        return pd.DataFrame(columns=list(STRUCTURE_COLUMNS))
    frame = table[list(STRUCTURE_COLUMNS)]
    return frame.sort_values("exposure", ascending=False).reset_index(drop=True)


def _usable(spot: float | None) -> bool:
    return bool(spot) and bool(np.isfinite(cast(float, spot)))


__all__ = [
    "LEG_COLUMNS",
    "STRUCTURE_COLUMNS",
    "GroupingConfig",
    "group_legs",
    "group_structures",
    "structure_type",
]
