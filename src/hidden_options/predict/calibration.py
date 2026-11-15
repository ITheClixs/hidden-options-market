"""What the gamma test's null rules out: a calibrated alternative.

Added after the test's result was seen (`docs/log/2026-11-08-gamma-predictive-spec.md`,
addition of 2026-11-15), so it is a reading of the result, not a test.

Suppose the netted FLEX book of an underlying were one-sided and hedged in the stock.
For a move of |r| percent, the dealer then trades x·|r| of a day's dollar volume, where
x is the test's predictor before standardising: the hedge for a 1% move as a fraction of
dollar volume. Under the square-root law of price impact, a trade of a fraction q of
daily volume moves the price by Y·σ·√q, with σ the daily volatility and Y a constant
that empirical work puts between about 0.5 and 1. A dealer short gamma trades with the
move and adds that much to |r|; one long gamma trades against it and takes it away.
The effect of one standard deviation of x on next-day |r|, against no book, is then
Y·σ·√(x·|r|). Set against the test's minimum detectable effect, that says whether such a
book could have hidden from the test.
"""

from __future__ import annotations

import math
from typing import Any

IMPACT_CONSTANTS = (0.5, 1.0)


def impact_effect(x: float, mean_abs_ret: float, constant: float) -> float:
    """The change in |r| (a return) from hedging a one-sided book of size `x` per 1% move,
    on a move of the mean size, under the square-root law with constant `constant`.

    `mean_abs_ret` is a return (0.0198 for 1.98%); the daily volatility is taken as
    mean |r| x sqrt(pi/2), which holds for a normal return.
    """
    sigma = mean_abs_ret * math.sqrt(math.pi / 2)
    move_in_percent = mean_abs_ret * 100
    return constant * sigma * math.sqrt(x * move_in_percent)


def calibration(sample: dict[str, Any], mde: float) -> dict[str, Any]:
    """The predicted effect per standard deviation of x, pooled and within names, for each
    impact constant, and its ratio to the minimum detectable effect `mde`."""
    mean_abs = float(sample["mean_abs_ret"])
    out: dict[str, Any] = {"mde": mde, "mean_abs_ret": mean_abs, "effects": {}}
    for label, x in (("pooled", sample["x_net_sd"]), ("within", sample["x_net_within_sd"])):
        effects = {f"{c:.1f}": impact_effect(float(x), mean_abs, c) for c in IMPACT_CONSTANTS}
        out["effects"][label] = effects
    smallest = min(min(row.values()) for row in out["effects"].values())
    out["smallest_over_mde"] = smallest / mde if mde else None
    return out


__all__ = ["IMPACT_CONSTANTS", "calibration", "impact_effect"]
