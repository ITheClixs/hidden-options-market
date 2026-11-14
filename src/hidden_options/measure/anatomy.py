"""What the FLEX market is made of: one report date split into products.

Specification: `docs/log/2026-11-10-anatomy-spec.md`. Every rule works within one root and
one expiry, on open-interest counts and marks alone:

* a *paired strike* carries equal, positive call and put open interest;
* a *box* is two paired strikes with the same count, a loan of the distance between them;
* a *stock-leg call* is an unpaired call struck at no more than 5% of its mark plus its
  strike, the leg through which a defined-outcome fund holds its underlying;
* a *package leg* is any other series with the count of a stock-leg call beside it;
* a *same-strike pair* is a paired strike that is neither, a forward;
* everything else is *other*.

Categories are assigned in that order. Open interest has no sign, so nothing here says
who lends or who is long.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

CATEGORIES = ("box", "stock_leg", "package_leg", "pair", "other")
STOCK_LEG_MAX_SHARE = 0.05
CONTRACT_MULTIPLIER = 100
WIDE_RATIO = 1.25
MIN_RATE_DAYS = 7
DAYS_PER_YEAR = 365.0
MATURITY_EDGES = (30, 91, 365, 730)
MATURITY_LABELS = ("to_1m", "1m_3m", "3m_12m", "1y_2y", "over_2y")
EUROPEAN_DIGITS = ("2", "4")
UNDERLYING_GROUPS = ("SPX", "SPY", "other")

BUCKET = ["root", "expiry"]
LINE = [*BUCKET, "strike"]
SERIES = [*LINE, "right"]
BOX_COLUMNS = (
    "root",
    "expiry",
    "underlying",
    "count",
    "lower",
    "upper",
    "face",
    "value",
    "sharing",
)


@dataclass(frozen=True)
class Anatomy:
    """One date's series with their `category`, its boxes, and the box face under the
    alternative matching of each paired strike with its neighbour. A box's `sharing` is
    how many paired strikes of its root and expiry carry its count: at two, the matching
    is not in question."""

    series: pd.DataFrame
    boxes: pd.DataFrame
    neighbour_face: float


def classify(day: pd.DataFrame) -> Anatomy:
    """Assign every series of one report date with open interest to a category.

    `day` holds `root`, `underlying`, `right`, `expiry`, `strike`, `mark_price` and
    `open_interest`. The returned series carry `category` and, at a paired strike,
    `forward`: the call mark less the put mark.
    """
    held = day.loc[day["open_interest"] > 0].reset_index(drop=True)
    paired = _paired_strikes(held)
    series = held.merge(paired[[*LINE, "count", "slot", "forward"]], on=LINE, how="left")
    in_box = (series["slot"] >= 0).to_numpy()
    is_paired = series["count"].notna().to_numpy()
    reach = series["mark_price"].to_numpy(float) + series["strike"].to_numpy(float)
    stock = (
        (series["right"] == "C").to_numpy()
        & ~is_paired
        & (series["strike"].to_numpy(float) <= STOCK_LEG_MAX_SHARE * reach)
    )
    counts = series.loc[stock, [*BUCKET, "open_interest"]].drop_duplicates().assign(matched=True)
    matched = (
        series[[*BUCKET, "open_interest"]]
        .merge(counts, on=[*BUCKET, "open_interest"], how="left")["matched"]
        .fillna(False)
        .to_numpy(dtype=bool)
    )
    category = np.select(
        [in_box, stock, matched, is_paired], list(CATEGORIES[:4]), default=CATEGORIES[4]
    )
    series = series.drop(columns=["count", "slot"]).assign(category=category)
    return Anatomy(series, _boxes(paired, held), _face(paired, "neighbour_slot"))


def _paired_strikes(held: pd.DataFrame) -> pd.DataFrame:
    """Strikes with equal call and put open interest, with their place in each matching.

    `slot` numbers the boxes of one root, expiry and count from the outside in, and is -1
    for a strike left without a partner; `neighbour_slot` does the same pairing each
    strike with the next one up.
    """
    calls = held[held["right"] == "C"].groupby(LINE)[["open_interest", "mark_price"]].first()
    puts = held[held["right"] == "P"].groupby(LINE)[["open_interest", "mark_price"]].first()
    both = calls.reset_index().merge(puts.reset_index(), on=LINE, suffixes=("_call", "_put"))
    paired = both[both["open_interest_call"] == both["open_interest_put"]].copy()
    paired["count"] = paired["open_interest_call"].astype(np.int64)
    paired["forward"] = paired["mark_price_call"] - paired["mark_price_put"]
    group = paired.groupby([*BUCKET, "count"], sort=False)["strike"]
    rank = group.rank(method="first").astype(np.int64) - 1
    size = group.transform("size").astype(np.int64)
    middle = (size % 2 == 1) & (rank == (size - 1) // 2)
    paired["sharing"] = size
    paired["slot"] = rank.where(rank <= size - 1 - rank, size - 1 - rank).where(~middle, -1)
    paired["neighbour_slot"] = (rank // 2).where(rank < 2 * (size // 2), -1)
    return paired


def _spans(paired: pd.DataFrame, slot: str) -> pd.DataFrame:
    legs = paired[paired[slot] >= 0].sort_values("strike")
    spans = legs.groupby([*BUCKET, "count", slot], sort=False).agg(
        lower=("strike", "first"),
        upper=("strike", "last"),
        lower_forward=("forward", "first"),
        upper_forward=("forward", "last"),
        sharing=("sharing", "first"),
    )
    return spans.reset_index()


def _face(paired: pd.DataFrame, slot: str) -> float:
    spans = _spans(paired, slot)
    return float(((spans["upper"] - spans["lower"]) * spans["count"]).sum() * CONTRACT_MULTIPLIER)


def _boxes(paired: pd.DataFrame, held: pd.DataFrame) -> pd.DataFrame:
    spans = _spans(paired, "slot")
    size = spans["count"] * CONTRACT_MULTIPLIER
    owners = held.drop_duplicates("root").set_index("root")["underlying"]
    boxes = spans.assign(
        underlying=spans["root"].map(owners),
        face=(spans["upper"] - spans["lower"]) * size,
        value=(spans["lower_forward"] - spans["upper_forward"]) * size,
    )
    return boxes[list(BOX_COLUMNS)].reset_index(drop=True)


def split(series: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Series, open interest and mark value in each category."""
    value = series["open_interest"] * series["mark_price"] * CONTRACT_MULTIPLIER
    frame = pd.DataFrame(
        {"category": series["category"], "oi": series["open_interest"], "value": value}
    )
    sums = frame.groupby("category").agg(
        series=("oi", "size"), open_interest=("oi", "sum"), value=("value", "sum")
    )
    sums = sums.reindex(list(CATEGORIES), fill_value=0)
    return {
        str(name): {
            "series": int(row["series"]),
            "open_interest": int(row["open_interest"]),
            "value": float(row["value"]),
        }
        for name, row in sums.iterrows()
    }


def box_lending(found: Anatomy, report_date: pd.Timestamp) -> dict[str, Any]:
    """Face and value of the date's boxes, and how the face divides."""
    boxes = found.boxes
    face = boxes["face"].to_numpy(float)
    total = float(face.sum())
    days = (pd.to_datetime(boxes["expiry"]) - report_date).dt.days.to_numpy()
    bucket = np.searchsorted(MATURITY_EDGES, days, side="left")
    group = np.where(boxes["underlying"].isin(UNDERLYING_GROUPS[:2]), boxes["underlying"], "other")
    european = boxes["root"].astype(str).str[0].isin(EUROPEAN_DIGITS).to_numpy()
    wide = (boxes["upper"] >= WIDE_RATIO * boxes["lower"]).to_numpy()
    return {
        "boxes": len(boxes),
        "face": total,
        "value": float(boxes["value"].sum()),
        "neighbour_face": found.neighbour_face,
        "unambiguous_face": float(face[boxes["sharing"].to_numpy() == 2].sum()),
        "by_maturity": {
            label: float(face[bucket == place].sum()) for place, label in enumerate(MATURITY_LABELS)
        },
        "by_underlying": {name: float(face[group == name].sum()) for name in UNDERLYING_GROUPS},
        "european_share": _share(float(face[european].sum()), total),
        "wide_share": _share(float(face[wide].sum()), total),
        "mark_rate": _mark_rate(boxes, days),
    }


def _mark_rate(boxes: pd.DataFrame, days: np.ndarray) -> float | None:
    """The face-weighted rate that equates value at the marks to face, on boxes with at
    least MIN_RATE_DAYS to run and a positive value."""
    usable = (days >= MIN_RATE_DAYS) & (boxes["value"].to_numpy(float) > 0)
    if not usable.any():
        return None
    face = boxes["face"].to_numpy(float)[usable]
    value = boxes["value"].to_numpy(float)[usable]
    rate = -np.log(value / face) / (days[usable] / DAYS_PER_YEAR)
    return float(np.average(rate, weights=face))


def pair_notional(series: pd.DataFrame) -> float:
    """Forward notional of the same-strike pairs: count x 100 x (strike + call - put)."""
    calls = series[(series["category"] == "pair") & (series["right"] == "C")]
    forward = calls["strike"] + calls["forward"]
    return float((calls["open_interest"] * forward).sum() * CONTRACT_MULTIPLIER)


def stock_leg_value(series: pd.DataFrame) -> pd.Series:
    """Mark value of the stock-leg calls per underlying, largest first."""
    legs = series[series["category"] == "stock_leg"]
    value = legs["open_interest"] * legs["mark_price"] * CONTRACT_MULTIPLIER
    return value.groupby(legs["underlying"]).sum().sort_values(ascending=False)


def colocated_other_share(series: pd.DataFrame) -> float:
    """The share of open interest in `other` at a root and expiry with a stock-leg call."""
    other = series[series["category"] == "other"]
    homes = series.loc[series["category"] == "stock_leg", BUCKET].drop_duplicates()
    beside = other.merge(homes.assign(beside=True), on=BUCKET, how="left")["beside"].fillna(False)
    inside = other["open_interest"].to_numpy(float)[beside.to_numpy(dtype=bool)].sum()
    return _share(inside, other["open_interest"].sum())


def shuffled(day: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """`day` with open interest dealt at random among the series of each root and expiry.

    A new frame: the counts of every bucket are kept and their lines are not.
    """
    frame = day.reset_index(drop=True)
    receiving = frame.sort_values(BUCKET, kind="stable").index.to_numpy()
    giving = (
        frame.assign(draw=rng.random(len(frame)))
        .sort_values([*BUCKET, "draw"], kind="stable")
        .index.to_numpy()
    )
    dealt = frame["open_interest"].to_numpy().copy()
    dealt[receiving] = frame["open_interest"].to_numpy()[giving]
    return frame.assign(open_interest=dealt)


def shuffled_pairs(day: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """`day` with the counts of its paired strikes dealt at random among the paired strikes
    of the same root, across its expiries. Unpaired lines are left alone.

    A new frame. Every paired strike stays paired and every root keeps its counts, so what
    the deal breaks is only which expiry two equal counts fall in: the boxes it still
    finds are those that equal counts alone would give.
    """
    frame = day.reset_index(drop=True)
    paired = _paired_strikes(frame.loc[frame["open_interest"] > 0])
    if paired.empty:
        return frame
    receiving = paired.sort_values("root", kind="stable").index.to_numpy()
    giving = (
        paired.assign(draw=rng.random(len(paired)))
        .sort_values(["root", "draw"], kind="stable")
        .index.to_numpy()
    )
    dealt = pd.Series(paired.loc[giving, "count"].to_numpy(), index=receiving)
    fresh = paired[LINE].assign(dealt=dealt.reindex(paired.index).to_numpy())
    joined = frame.merge(fresh, on=LINE, how="left")
    counts = joined["dealt"].where(joined["dealt"].notna(), joined["open_interest"])
    return frame.assign(open_interest=counts.astype(frame["open_interest"].dtype).to_numpy())


def new_lines(known: pd.DataFrame, day: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """`known` (root, expiry, strike, first_date) with the lines of `day` not yet in it,
    first seen on `date`. A new frame; lines without open interest are not counted."""
    lines = day.loc[day["open_interest"] > 0, LINE].drop_duplicates()
    if known.empty:
        return lines.assign(first_date=date).reset_index(drop=True)
    joined = lines.merge(known[LINE], on=LINE, how="left", indicator=True)
    fresh = joined.loc[joined["_merge"] == "left_only", LINE].assign(first_date=date)
    return pd.concat([known, fresh], ignore_index=True)


def _share(part: float, whole: float) -> float:
    return float(part / whole) if whole else 0.0


__all__ = [
    "CATEGORIES",
    "MATURITY_LABELS",
    "UNDERLYING_GROUPS",
    "Anatomy",
    "box_lending",
    "classify",
    "colocated_other_share",
    "new_lines",
    "pair_notional",
    "shuffled",
    "shuffled_pairs",
    "split",
    "stock_leg_value",
]
