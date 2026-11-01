"""Cleared series against positions: legs, payoffs and three notionals (M4).

The report gives open interest per series. `structures.group_legs` groups the series of
one underlying and expiry that carry near-equal counts; this module turns the report into
legs for it and values the result three ways, per underlying:

* `strike_notional`: strike x contracts x 100, the naive measure, over every series.
* `mark_value`: OCC's mark x contracts x 100.
* `delta_exposure`: the absolute sum of `delta_dollars` within each detected structure,
  added up over structures and ungrouped legs. Open interest has no sign, so within a
  structure every leg counts as held long; `gross_delta`, which sums the legs' absolute
  deltas and nets nothing, is reported beside it.

A delta exists only where the caller supplies one, which the result limits to the validated
domain of the volatility inversion. A structure with any leg lacking a delta is left out
whole, since it cannot be netted. `strike_notional_priced` is the strike notional of what
is left, so a ratio compares the same series on both sides, and `covered_oi_share` says how
much open interest that is.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

import numpy as np
import pandas as pd

from hidden_options.measure.structures import CONTRACT_MULTIPLIER, GroupingConfig, group_legs

_KEY = ["root", "expiry", "right", "strike"]
# A butterfly's body is twice its wings and its strikes evenly spaced, to within these.
BODY_TOLERANCE = 0.05
SPACING_TOLERANCE = 0.01
MEASURE_COLUMNS = (
    "underlying",
    "open_interest",
    "strike_notional",
    "mark_value",
    "underlying_notional",
    "strike_notional_priced",
    "delta_exposure",
    "gross_delta",
    "structured_oi_share",
    "covered_oi_share",
)
# The payoff above the top strike is checked this far out; only its slope matters.
_BEYOND = 2.0


def legs_from_panel(panel_day: pd.DataFrame) -> pd.DataFrame:
    """One date's report rows as legs: `contracts` is the open interest, zero rows dropped.

    The columns of `structures.LEG_COLUMNS`, with `root` and `report_date` kept beside them.
    """
    held = panel_day[panel_day["open_interest"] > 0]
    legs = pd.DataFrame(
        {
            "report_date": held["report_date"],
            "root": held["root"],
            "underlying": held["underlying"],
            "expiry": held["expiry"],
            "right": held["right"],
            "strike": held["strike"],
            "contracts": held["open_interest"],
        }
    )
    return legs.reset_index(drop=True)


def payoff(structure_legs: pd.DataFrame, prices: np.ndarray) -> np.ndarray:
    """The structure's value at expiry at each underlying price, in dollars.

    `contracts` is signed here, positive for a leg held long. The report does not give the
    sign, so whoever calls this states it.
    """
    strikes = structure_legs["strike"].to_numpy(dtype=float)
    sizes = structure_legs["contracts"].to_numpy(dtype=float) * CONTRACT_MULTIPLIER
    calls = structure_legs["right"].to_numpy(dtype=object) == "C"
    grid = np.asarray(prices, dtype=float)[:, None]
    intrinsic = np.where(calls, np.maximum(grid - strikes, 0.0), np.maximum(strikes - grid, 0.0))
    values: np.ndarray = (intrinsic * sizes).sum(axis=1)
    return values


def max_value(structure_legs: pd.DataFrame) -> float:
    """The most the structure can be worth at expiry, over a grid of its strikes and zero.

    A payoff is piecewise linear with kinks at the strikes, so its maximum is on that grid,
    unless it still rises above the top strike, which gives infinity.
    """
    strikes = structure_legs["strike"].to_numpy(dtype=float)
    top = float(strikes.max())
    grid = np.array([0.0, *sorted(strikes), top * _BEYOND])
    values = payoff(structure_legs, grid)
    if values[-1] > values[-2] + 1e-6:
        return math.inf
    return float(values.max())


def notional_measures(
    panel_day: pd.DataFrame,
    greeks: pd.DataFrame,
    legs_with_ids: pd.DataFrame,
    spots: Mapping[str, float],
) -> pd.DataFrame:
    """The measures of the module docstring, per underlying, in MEASURE_COLUMNS.

    `greeks` holds `delta_dollars` per series, missing where there is no usable delta.
    An underlying with no priced series has a missing `delta_exposure`.
    """
    rows = panel_day.loc[
        panel_day["open_interest"] > 0, [*_KEY, "underlying", "mark_price"]
    ].assign(oi=panel_day["open_interest"].astype(float))
    rows = rows.merge(greeks[[*_KEY, "delta_dollars"]], on=_KEY, how="left", validate="one_to_one")
    rows = rows.merge(legs_with_ids[[*_KEY, "structure_id"]], on=_KEY, how="left")
    rows = rows.assign(structure_id=rows["structure_id"].fillna(-1).astype(np.int64))
    strike_value = rows["strike"].astype(float) * rows["oi"] * CONTRACT_MULTIPLIER
    rows = rows.assign(
        strike_value=strike_value,
        mark_dollars=rows["mark_price"].astype(float) * rows["oi"] * CONTRACT_MULTIPLIER,
        spot_value=rows["oi"] * CONTRACT_MULTIPLIER * rows["underlying"].map(dict(spots)),
        structured_oi=rows["oi"].where(rows["structure_id"] >= 0, 0.0),
        covered=_covered(rows),
    )
    records = [_measure(name, group) for name, group in rows.groupby("underlying", sort=True)]
    return pd.DataFrame(records, columns=list(MEASURE_COLUMNS))


def _covered(rows: pd.DataFrame) -> pd.Series:
    """Priced legs, less every leg of a structure one of whose legs has no delta."""
    priced = rows["delta_dollars"].notna()
    grouped = rows["structure_id"] >= 0
    complete = priced.groupby(rows["structure_id"].where(grouped)).transform("all")
    return (priced & ~grouped) | (grouped & complete.reindex(rows.index, fill_value=False))


def _measure(name: Any, group: pd.DataFrame) -> dict[str, Any]:
    covered = group[group["covered"]]
    total = float(group["oi"].sum())
    net = _net_delta(covered) if len(covered) else float("nan")
    return {
        "underlying": name,
        "open_interest": total,
        "strike_notional": float(group["strike_value"].sum()),
        "mark_value": float(group["mark_dollars"].sum()),
        "underlying_notional": float(group["spot_value"].sum(min_count=1)),
        "strike_notional_priced": float(covered["strike_value"].sum()),
        "delta_exposure": net,
        "gross_delta": float(covered["delta_dollars"].abs().sum())
        if len(covered)
        else float("nan"),
        "structured_oi_share": float(group["structured_oi"].sum()) / total if total else 0.0,
        "covered_oi_share": float(covered["oi"].sum()) / total if total else 0.0,
    }


def _net_delta(covered: pd.DataFrame) -> float:
    grouped = covered["structure_id"] >= 0
    within = covered[grouped].groupby("structure_id")["delta_dollars"].sum().abs().sum()
    return float(within + covered.loc[~grouped, "delta_dollars"].abs().sum())


def per_underlying_ratios(daily: pd.DataFrame) -> pd.DataFrame:
    """Each underlying's median, across its dates, of strike notional over delta exposure
    (`ratio`) and over gross delta (`gross_ratio`). One number an underlying, so that a
    position that persists is not counted once a day."""
    usable = daily[(daily["delta_exposure"] > 0) & (daily["strike_notional_priced"] > 0)]
    ratios = usable.assign(
        ratio=usable["strike_notional_priced"] / usable["delta_exposure"],
        gross_ratio=usable["strike_notional_priced"] / usable["gross_delta"],
    )
    medians = ratios.groupby("underlying", sort=True)[["ratio", "gross_ratio"]].median()
    return medians.reset_index()


def structure_shares(legs_with_ids: pd.DataFrame) -> dict[str, Any]:
    """The share of contracts in a structure, and of those by structure type."""
    sizes = legs_with_ids["contracts"].astype(float)
    grouped = legs_with_ids["structure_id"] >= 0
    held = float(sizes.sum())
    inside = float(sizes[grouped].sum())
    by_type = sizes[grouped].groupby(legs_with_ids.loc[grouped, "structure"]).sum()
    return {
        "contracts": held,
        "structured_contracts": inside,
        "structured": inside / held if held else 0.0,
        "by_type": {str(name): float(value) / inside for name, value in by_type.items()},
    }


def chance_structured_share(
    legs: pd.DataFrame, *, seed: int, config: GroupingConfig | None = None
) -> float:
    """The structured share if each underlying's counts were dealt out at random among its
    series: how much grouping near-equal counts within an expiry finds by chance alone."""
    rng = np.random.default_rng(seed)
    sizes = legs["contracts"].to_numpy(dtype=float)
    groups = legs.groupby("underlying", sort=True).indices
    shuffled = sizes.copy()
    for rows in groups.values():
        shuffled[rows] = rng.permutation(sizes[rows])
    grouped, _ = group_legs(legs.assign(contracts=shuffled), {}, config)
    return float(structure_shares(grouped)["structured"])


def butterfly_triples(rows: pd.DataFrame, min_wing: float = 0.0) -> pd.DataFrame:
    """One date's call lines forming wing, body, wing: `expiry`, `low`, `middle`, `high`,
    `wing` and `body`. Body twice the wings and strikes evenly spaced, to within tolerance."""
    calls = rows[(rows["right"] == "C") & (rows["open_interest"] >= min_wing)]
    found = []
    for expiry, lines in calls.groupby("expiry", sort=True):
        ordered = lines.sort_values("strike")
        strikes = ordered["strike"].to_numpy(dtype=float)
        sizes = ordered["open_interest"].to_numpy(dtype=float)
        for i, j, k in _triples(len(ordered)):
            if _is_butterfly(strikes[[i, j, k]], sizes[[i, j, k]]):
                found.append(
                    {
                        "expiry": expiry,
                        "low": strikes[i],
                        "middle": strikes[j],
                        "high": strikes[k],
                        "wing": float(sizes[i]),
                        "body": float(sizes[j]),
                    }
                )
    return pd.DataFrame(found, columns=["expiry", "low", "middle", "high", "wing", "body"])


def _triples(n: int) -> list[tuple[int, int, int]]:
    return [(i, j, k) for i in range(n) for j in range(i + 1, n) for k in range(j + 1, n)]


def _is_butterfly(strikes: np.ndarray, sizes: np.ndarray) -> bool:
    low, middle, high = strikes
    wing, body, other = sizes
    spaced = abs((middle - low) - (high - middle)) <= SPACING_TOLERANCE * (high - low)
    even = abs(other - wing) <= BODY_TOLERANCE * wing
    double = abs(body - 2 * wing) <= BODY_TOLERANCE * 2 * wing
    return bool(spaced and even and double)


def locate_butterfly(
    panel: pd.DataFrame, underlying: str, *, min_wing: float, expiries: int = 3
) -> dict[str, Any] | None:
    """The butterfly case: the last date on which `underlying` shows one-to-two-to-one call
    lines at `expiries` expiries or more.

    Every line of it, its strike notional and the most it can be worth, with the wings
    long and the body short. None if the panel has no such date.
    """
    rows = panel[panel["underlying"] == underlying]
    for day in sorted(pd.to_datetime(rows["report_date"]).unique(), reverse=True):
        lines = rows[pd.to_datetime(rows["report_date"]) == day]
        triples = butterfly_triples(lines, min_wing)
        if triples["expiry"].nunique() >= expiries:
            return _butterfly_case(pd.Timestamp(day), underlying, triples)
    return None


def _butterfly_case(day: pd.Timestamp, underlying: str, triples: pd.DataFrame) -> dict[str, Any]:
    legs = []
    strike_notional = worth = 0.0
    for row in triples.itertuples():
        signed = pd.DataFrame(
            {
                "right": ["C", "C", "C"],
                "strike": [row.low, row.middle, row.high],
                "contracts": [row.wing, -cast(float, row.body), row.wing],
            }
        )
        strike_notional += float(
            (signed["strike"] * signed["contracts"].abs() * CONTRACT_MULTIPLIER).sum()
        )
        worth += max_value(signed)
        legs.append(signed.assign(expiry=row.expiry))
    return {
        "report_date": day,
        "underlying": underlying,
        "lines": 3 * len(triples),
        "expiries": sorted(triples["expiry"].unique()),
        "legs": pd.concat(legs, ignore_index=True),
        "strike_notional": strike_notional,
        "max_value": worth,
        "overstatement": strike_notional / worth,
    }


def locate_collar(
    panel: pd.DataFrame, underlying: str, *, deep_strike: float, size: float
) -> dict[str, Any] | None:
    """The collar case: the report on which the call of `underlying` struck at `deep_strike`
    has the open interest nearest `size` (latest of any tied), with the three other legs
    of its expiry within five percent of it. None if the panel has no such report."""
    rows = panel[panel["underlying"] == underlying]
    deep = rows[(rows["right"] == "C") & np.isclose(rows["strike"].astype(float), deep_strike)]
    deep = deep[deep["open_interest"] > 0]
    if deep.empty:
        return None
    gaps = (deep["open_interest"].astype(float) - size).abs()
    order = deep.assign(_gap=gaps).sort_values(["_gap", "report_date"], ascending=[True, False])
    for candidate in order.itertuples():
        lines = rows[
            (rows["report_date"] == candidate.report_date) & (rows["expiry"] == candidate.expiry)
        ]
        anchor = float(cast(float, candidate.open_interest))
        near = lines[(lines["open_interest"].astype(float) - anchor).abs() <= 0.05 * anchor]
        if len(near) == 4 and (near["right"] == "C").sum() == 2:
            return {
                "report_date": pd.Timestamp(str(candidate.report_date)),
                "expiry": pd.Timestamp(str(candidate.expiry)),
                "underlying": underlying,
                "legs": near.sort_values(["right", "strike"]).reset_index(drop=True),
            }
    return None


__all__ = [
    "MEASURE_COLUMNS",
    "butterfly_triples",
    "chance_structured_share",
    "legs_from_panel",
    "locate_butterfly",
    "locate_collar",
    "max_value",
    "notional_measures",
    "payoff",
    "per_underlying_ratios",
    "structure_shares",
]
