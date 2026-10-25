"""Why a strike rule cannot find FLEX (M3).

Listed strikes sit on a grid: whole dollars, halves, and on some products quarters. A
FLEX strike is whatever the counterparties chose, so a strike off that grid looks like a
FLEX tell, and before OCC's FLEX report was in hand this project used exactly that rule.
OCC's series search makes it possible to score: it lists every series OCC clears on an
underlying, and a FLEX product carries a leading digit (`hidden_share.is_flex_product`),
so whether each series is FLEX is known exactly.

What is scored is one series per line of the search: a product, an expiry and a strike,
with the call and the put open interest at it together, as the search reports them. A
listed and a FLEX series at the same strike and expiry are two lines and count twice.
Lines with nothing open on either side hold no position to find and are left out, and
so are adjusted-deliverable classes (`hidden_share.is_adjusted_product`), which are
underlyings of their own here as in the hidden-share measure.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Literal

import numpy as np
import pandas as pd

from hidden_options.measure.flex import strike_cents
from hidden_options.measure.hidden_share import is_adjusted_product, is_flex_product

GridPosition = Literal["dollar", "half", "quarter", "off_grid"]
GRID_POSITIONS: tuple[GridPosition, ...] = ("dollar", "half", "quarter", "off_grid")
_ON_GRID: MappingProxyType[int, GridPosition] = MappingProxyType(
    {0: "dollar", 50: "half", 25: "quarter", 75: "quarter"}
)
GROUPS = ("flex", "listed")
MEASURES = ("series", "open_interest")
SERIES_COLUMNS = (
    "symbol",
    "product_symbol",
    "expiry",
    "strike",
    "call_open_interest",
    "put_open_interest",
    "open_interest",
    "flex",
    "grid",
)


def grid_position(strike: float) -> GridPosition:
    """Where a strike sits on the listing grid, from its cents: 00, 50, 25 or 75, or off it."""
    return _ON_GRID.get(strike_cents(strike), "off_grid")


@dataclass(frozen=True)
class Confusion:
    """The strike rule against the truth, in series or in open interest.

    `tp` FLEX the rule flags, `fp` listed series it flags, `fn` FLEX it passes, `tn`
    listed series it passes. A metric whose denominator is zero is undefined (NaN).
    """

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def precision(self) -> float:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float:
        """The harmonic mean of precision and recall, as 2tp / (2tp + fp + fn)."""
        return _ratio(2 * self.tp, 2 * self.tp + self.fp + self.fn)

    def as_dict(self) -> dict[str, float]:
        """The four counts and the three metrics, for a result's values."""
        return {
            **asdict(self),
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


def scored_series(census: pd.DataFrame) -> pd.DataFrame:
    """The census lines the rule is scored on, with their truth and grid position.

    Keeps one row per line of the search with open interest on either side, outside the
    adjusted-deliverable classes, and adds `open_interest` (call and put together),
    `flex` (the truth) and `grid` (`grid_position` of the strike). `census` is not changed.
    """
    products = census["product_symbol"].astype(str)
    open_interest = census["call_open_interest"] + census["put_open_interest"]
    keep = ~products.map(is_adjusted_product).astype(bool) & (open_interest > 0)
    series = census.loc[keep].assign(
        open_interest=open_interest[keep],
        flex=products[keep].map(is_flex_product).astype(bool),
        grid=census.loc[keep, "strike"].map(grid_position),
    )
    return series[list(SERIES_COLUMNS)].reset_index(drop=True)


def score_strike_rule(series: pd.DataFrame, *, weight: str | None = None) -> Confusion:
    """Score "an off-grid strike is FLEX" on every row of `series`, as given.

    The truth is the product symbol (`is_flex_product`), the prediction `grid_position`
    of the strike. Rows count once each, or by their `weight` column (open interest,
    say). Which rows to score is the caller's choice; `scored_series` makes the usual one.
    """
    truth = series["product_symbol"].astype(str).map(is_flex_product).astype(bool).to_numpy()
    flagged = (series["strike"].map(grid_position) == "off_grid").to_numpy()
    weights = np.ones(len(series), dtype=np.int64)
    if weight is not None:
        weights = series[weight].to_numpy(dtype=np.int64)

    def total(mask: np.ndarray) -> int:
        return int(weights[mask].sum())

    return Confusion(
        tp=total(truth & flagged),
        fp=total(~truth & flagged),
        fn=total(truth & ~flagged),
        tn=total(~truth & ~flagged),
    )


def grid_shares(series: pd.DataFrame) -> pd.DataFrame:
    """Share of FLEX and of listed series, and of their open interest, at each grid position.

    `series` is `scored_series` output. The frame is indexed by GRID_POSITIONS with columns
    `<group>_<measure>` for group in GROUPS and measure in MEASURES; each column sums to one,
    and a position a group never takes is zero.
    """
    flex = series["flex"].to_numpy(dtype=bool)
    positions = list(GRID_POSITIONS)
    columns: dict[str, pd.Series] = {}
    for group, members in (("flex", flex), ("listed", ~flex)):
        part = series.loc[members]
        for measure in MEASURES:
            counts = pd.Series(1, index=part.index)
            weights = part["open_interest"] if measure == "open_interest" else counts
            sums = weights.groupby(part["grid"]).sum().reindex(positions, fill_value=0)
            columns[f"{group}_{measure}"] = (sums / sums.sum()).astype(float)
    return pd.DataFrame(columns, index=pd.Index(positions))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else math.nan


__all__ = [
    "GRID_POSITIONS",
    "GROUPS",
    "MEASURES",
    "SERIES_COLUMNS",
    "Confusion",
    "GridPosition",
    "grid_position",
    "grid_shares",
    "score_strike_rule",
    "scored_series",
]
