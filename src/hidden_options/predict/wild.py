"""Wild cluster restricted bootstrap for one coefficient in a two-way fixed-effects panel.

With few clusters, a clustered t-ratio is compared with the wrong reference distribution.
The restricted wild bootstrap (Cameron, Gelbach and Miller 2008) instead imposes the null,
flips the sign of each cluster's restricted residuals with Rademacher weights, and refits.
The statistic is the t-ratio with one-way clustered (CR1) standard errors. The fixed
effects are re-applied to every bootstrap outcome, since date effects are not nested
within the clusters.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

Z_ONE_SIDED = 1.6448536269514722  # 95th percentile of the standard normal
Z_POWER = 0.8416212335729143  # 80th percentile
TOLERANCE = 1e-11
MAX_ITERATIONS = 500


def two_way_demean(values: np.ndarray, entity: np.ndarray, time: np.ndarray) -> np.ndarray:
    """`values` less entity and time effects, by alternating projection on group codes."""
    out = np.asarray(values, dtype=float).copy()
    entity_n = np.bincount(entity)
    time_n = np.bincount(time)
    for _ in range(MAX_ITERATIONS):
        before = out.copy()
        out -= (np.bincount(entity, weights=out) / entity_n)[entity]
        out -= (np.bincount(time, weights=out) / time_n)[time]
        if np.max(np.abs(out - before)) < TOLERANCE:
            break
    return out


def wild_cluster_test(
    frame: pd.DataFrame,
    outcome: str,
    regressor: str,
    controls: Sequence[str],
    *,
    entity: str = "symbol",
    time: str = "date",
    n_draws: int = 9_999,
    seed: int = 0,
) -> dict[str, Any]:
    """One-sided test of a negative coefficient on `regressor`, clustered by `entity`.

    Returns the coefficient, its CR1 standard error and t, the bootstrap p-value (the share
    of bootstrap t-ratios at or below the observed one), the MDE at 80% power for a
    one-sided 5% test, and the counts.
    """
    data = frame[[outcome, regressor, *controls, entity, time]].dropna()
    groups = pd.factorize(data[entity])[0]
    times = pd.factorize(data[time])[0]
    columns = [regressor, *controls]
    x = np.column_stack(
        [two_way_demean(data[c].to_numpy(dtype=float), groups, times) for c in columns]
    )
    y = two_way_demean(data[outcome].to_numpy(dtype=float), groups, times)

    beta, se = _ols_cr1(x, y, groups)
    restricted = x[:, 1:]
    if restricted.shape[1]:
        gamma = np.linalg.lstsq(restricted, y, rcond=None)[0]
        fitted = restricted @ gamma
    else:
        fitted = np.zeros_like(y)
    residual = y - fitted

    rng = np.random.default_rng(seed)
    n_groups = int(np.max(groups)) + 1
    t_obs = beta[0] / se[0]
    at_or_below = 0
    for _ in range(n_draws):
        weights = rng.choice((-1.0, 1.0), size=n_groups)[groups]
        y_star = fitted + two_way_demean(weights * residual, groups, times)
        b_star, se_star = _ols_cr1(x, y_star, groups)
        at_or_below += int(b_star[0] / se_star[0] <= t_obs)
    return {
        "coefficient": float(beta[0]),
        "std_error": float(se[0]),
        "t_stat": float(t_obs),
        "p_value": (at_or_below + 1) / (n_draws + 1),
        "mde80": float((Z_ONE_SIDED + Z_POWER) * se[0]),
        "n_obs": len(data),
        "clusters": n_groups,
        "n_draws": n_draws,
        "seed": seed,
    }


def _ols_cr1(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    xtx_inv = np.linalg.inv(x.T @ x)
    beta = xtx_inv @ (x.T @ y)
    resid = y - x @ beta
    scores = np.zeros((int(np.max(groups)) + 1, x.shape[1]))
    np.add.at(scores, groups, x * resid[:, None])
    n, k = x.shape
    g = scores.shape[0]
    factor = g / (g - 1) * (n - 1) / (n - k)
    covariance = factor * xtx_inv @ (scores.T @ scores) @ xtx_inv
    return beta, np.sqrt(np.diag(covariance))


__all__ = ["two_way_demean", "wild_cluster_test"]
