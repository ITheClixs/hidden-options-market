"""Confidence intervals for proportions."""

from __future__ import annotations

import math

from scipy.stats import norm

CONFIDENCE = 0.95


def wilson(successes: float, trials: int, confidence: float = CONFIDENCE) -> tuple[float, float]:
    """The Wilson score interval for `successes` out of `trials`.

    `successes` may be fractional, when a proportion is an average over trials rather than a
    count; the interval then treats it as that share of `trials`.
    """
    if trials <= 0:
        raise ValueError(f"A Wilson interval needs at least one trial, got {trials}")
    z = float(norm.ppf(0.5 + confidence / 2))
    p = successes / trials
    centre = (p + z * z / (2 * trials)) / (1 + z * z / trials)
    half = (
        z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / (1 + z * z / trials)
    )
    return max(0.0, centre - half), min(1.0, centre + half)


__all__ = ["CONFIDENCE", "wilson"]
