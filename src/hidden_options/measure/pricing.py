"""Option prices and greeks over arrays: Black-Scholes and a Cox-Ross-Rubinstein tree.

Both models take a constant `rate` and a continuous `carry` yield paid by the underlying
(a dividend yield; zero means none), so the forward is spot times exp((rate - carry) T).
Time is in years. Every function works row by row over equal-length arrays, which is what
lets the mark inversion run over a whole report at once.

European options are priced in closed form. American options are priced on a 200-step
CRR tree, except where early exercise can never pay: a put when the rate is not positive,
a call when the carry yield is not positive (Merton 1973). There the American option is
worth its European twin exactly, and the closed form is used. `early_exercise_matters`
says which rows need the tree.

Vega is quoted per vol point, the change in price for a 0.01 rise in volatility, as the
listed chains quote it. `black_scholes_vega` gives the derivative itself, per unit of
volatility, for the root finder.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import numpy.typing as npt
from scipy.special import ndtr

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

TREE_STEPS = 200
# Rows priced on the tree at once; a 200-step tree holds 201 nodes a row.
TREE_CHUNK = 20_000
VOL_POINT = 0.01
# The tree's up-probability leaves (0, 1) when sigma sqrt(dt) < |rate - carry| dt. Twice
# that bound keeps it near 0.75 at worst.
_TREE_SIGMA_MARGIN = 2.0
_SIGMA_FLOOR = 1e-4
_INV_SQRT_2PI = 1.0 / np.sqrt(2.0 * np.pi)


class Greeks(NamedTuple):
    """Per-contract sensitivities: delta, gamma per unit of spot, vega per vol point."""

    delta: FloatArray
    gamma: FloatArray
    vega: FloatArray


def black_scholes(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    sigma: npt.ArrayLike,
    *,
    rate: float,
    carry: float,
    is_call: npt.ArrayLike,
) -> FloatArray:
    """European option prices with a continuous carry yield."""
    s, k, t, v = _floats(spot, strike, years, sigma)
    sign = _sign(is_call, s.shape)
    d1, d2 = _d1_d2(s, k, t, v, rate, carry)
    discounted_spot = s * np.exp(-carry * t)
    discounted_strike = k * np.exp(-rate * t)
    return np.asarray(
        sign * (discounted_spot * ndtr(sign * d1) - discounted_strike * ndtr(sign * d2)),
        dtype=np.float64,
    )


def black_scholes_vega(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    sigma: npt.ArrayLike,
    *,
    rate: float,
    carry: float,
) -> FloatArray:
    """dPrice/dSigma per unit of volatility, the same for a call and a put."""
    s, k, t, v = _floats(spot, strike, years, sigma)
    d1, _ = _d1_d2(s, k, t, v, rate, carry)
    return np.asarray(s * np.exp(-carry * t) * _pdf(d1) * np.sqrt(t), dtype=np.float64)


def black_scholes_greeks(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    sigma: npt.ArrayLike,
    *,
    rate: float,
    carry: float,
    is_call: npt.ArrayLike,
) -> Greeks:
    """Closed-form delta, gamma and vega (per vol point) of European options."""
    s, k, t, v = _floats(spot, strike, years, sigma)
    sign = _sign(is_call, s.shape)
    d1, _ = _d1_d2(s, k, t, v, rate, carry)
    yield_discount = np.exp(-carry * t)
    delta = sign * yield_discount * ndtr(sign * d1)
    gamma = yield_discount * _pdf(d1) / (s * v * np.sqrt(t))
    vega = s * yield_discount * _pdf(d1) * np.sqrt(t) * VOL_POINT
    return Greeks(*(np.asarray(g, dtype=np.float64) for g in (delta, gamma, vega)))


def binomial(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    sigma: npt.ArrayLike,
    *,
    rate: float,
    carry: float,
    is_call: npt.ArrayLike,
    steps: int = TREE_STEPS,
) -> FloatArray:
    """American option prices on a Cox-Ross-Rubinstein tree of `steps` steps."""
    return _tree_in_chunks(spot, strike, years, sigma, rate, carry, is_call, steps)[0]


def binomial_greeks(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    sigma: npt.ArrayLike,
    *,
    rate: float,
    carry: float,
    is_call: npt.ArrayLike,
    steps: int = TREE_STEPS,
) -> Greeks:
    """Delta and gamma read off the tree's first two steps; vega by a vol-point bump.

    Vega is the tree price at sigma + 0.01 less the price at sigma, the change for one
    vol point, which keeps a deep in-the-money put that is exercised at once at zero.
    """
    s, k, t, v = _floats(spot, strike, years, sigma)
    price, delta, gamma = _tree_in_chunks(s, k, t, v, rate, carry, is_call, steps)
    bumped = _tree_in_chunks(s, k, t, v + VOL_POINT, rate, carry, is_call, steps)[0]
    return Greeks(delta, gamma, bumped - price)


def lowest_tree_sigma(
    years: npt.ArrayLike, *, rate: float, carry: float, steps: int = TREE_STEPS
) -> FloatArray:
    """The lowest volatility at which the tree's probabilities stay inside (0, 1).

    Below about |rate - carry| sqrt(T / steps) an up-move no longer outgrows the forward
    and the tree has no meaning; the floor is twice that, and never below 1e-4.
    """
    t = np.asarray(years, dtype=np.float64)
    bound = _TREE_SIGMA_MARGIN * abs(rate - carry) * np.sqrt(np.maximum(t, 0.0) / steps)
    return np.asarray(np.maximum(bound, _SIGMA_FLOOR), dtype=np.float64)


def early_exercise_matters(is_call: npt.ArrayLike, *, rate: float, carry: float) -> BoolArray:
    """True where an American option can be worth more than its European twin.

    A put can be when the rate is positive, a call when the carry yield is positive.
    Elsewhere exercise before expiry never pays, and the two are worth the same.
    """
    calls = np.asarray(is_call, dtype=bool)
    return np.asarray(np.where(calls, carry > 0, rate > 0), dtype=bool)


def _tree_in_chunks(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    sigma: npt.ArrayLike,
    rate: float,
    carry: float,
    is_call: npt.ArrayLike,
    steps: int,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Price, delta and gamma on the tree, TREE_CHUNK rows at a time to bound memory."""
    s, k, t, v = _floats(spot, strike, years, sigma)
    calls = np.broadcast_to(np.asarray(is_call, dtype=bool), s.shape)
    out = np.full((3, s.size), np.nan)
    for start in range(0, s.size, TREE_CHUNK):
        part = slice(start, start + TREE_CHUNK)
        out[:, part] = _tree(s[part], k[part], t[part], v[part], rate, carry, calls[part], steps)
    return out[0], out[1], out[2]


def _tree(
    spot: FloatArray,
    strike: FloatArray,
    years: FloatArray,
    sigma: FloatArray,
    rate: float,
    carry: float,
    is_call: BoolArray,
    steps: int,
) -> FloatArray:
    """Backward induction over every row at once; rows are (price, delta, gamma)."""
    dt = years / steps
    jump = sigma * np.sqrt(dt)
    up = np.exp(jump)
    down = 1.0 / up
    probability = (np.exp((rate - carry) * dt) - down) / (up - down)
    discount = np.exp(-rate * dt)
    p_up = (discount * probability)[:, None]
    p_down = (discount * (1.0 - probability))[:, None]
    sign = np.where(is_call, 1.0, -1.0)[:, None]
    k = strike[:, None]
    nodes = spot[:, None] * np.exp(jump[:, None] * (2 * np.arange(steps + 1) - steps))
    value = np.maximum(sign * (nodes - k), 0.0)
    saved: dict[int, tuple[FloatArray, FloatArray]] = {}
    for step in range(steps - 1, -1, -1):
        value = p_up * value[:, 1:] + p_down * value[:, :-1]
        nodes = nodes[:, :-1] * up[:, None]
        np.maximum(value, sign * (nodes - k), out=value)
        if step in (1, 2):
            saved[step] = (nodes.copy(), value.copy())
    (s1, v1), (s2, v2) = saved[1], saved[2]
    delta = (v1[:, 1] - v1[:, 0]) / (s1[:, 1] - s1[:, 0])
    upper = (v2[:, 2] - v2[:, 1]) / (s2[:, 2] - s2[:, 1])
    lower = (v2[:, 1] - v2[:, 0]) / (s2[:, 1] - s2[:, 0])
    gamma = (upper - lower) / (0.5 * (s2[:, 2] - s2[:, 0]))
    return np.vstack([value[:, 0], delta, gamma])


def _floats(*values: npt.ArrayLike) -> tuple[FloatArray, ...]:
    arrays = np.broadcast_arrays(*(np.asarray(value, dtype=np.float64) for value in values))
    return tuple(np.atleast_1d(np.asarray(array, dtype=np.float64)) for array in arrays)


def _sign(is_call: npt.ArrayLike, shape: tuple[int, ...]) -> FloatArray:
    calls = np.broadcast_to(np.asarray(is_call, dtype=bool), shape)
    return np.where(calls, 1.0, -1.0)


def _d1_d2(
    spot: FloatArray,
    strike: FloatArray,
    years: FloatArray,
    sigma: FloatArray,
    rate: float,
    carry: float,
) -> tuple[FloatArray, FloatArray]:
    root_t = sigma * np.sqrt(years)
    d1 = (np.log(spot / strike) + (rate - carry + 0.5 * sigma**2) * years) / root_t
    return d1, d1 - root_t


def _pdf(x: FloatArray) -> FloatArray:
    return np.asarray(_INV_SQRT_2PI * np.exp(-0.5 * x**2), dtype=np.float64)


__all__ = [
    "TREE_CHUNK",
    "TREE_STEPS",
    "VOL_POINT",
    "BoolArray",
    "FloatArray",
    "Greeks",
    "binomial",
    "binomial_greeks",
    "black_scholes",
    "black_scholes_greeks",
    "black_scholes_vega",
    "early_exercise_matters",
    "lowest_tree_sigma",
]
