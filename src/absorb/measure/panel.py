"""Panel construction and a two-way fixed-effects estimator with clustered errors.

Kept deliberately small and explicit rather than pulling in an econometrics package:
the estimator is the part of the pilot most likely to be wrong in a way that looks
right, so it should be readable end to end and directly testable against known cases.

Inference uses Cameron–Gelbach–Miller two-way clustering. With a treatment that varies
at the name level and an event that recurs on common dates, errors are correlated both
within a name over time and across names on the same day. Clustering on only one
dimension understates the standard error, in a direction that manufactures
significance.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass(frozen=True)
class Estimate:
    """One coefficient with two-way clustered inference.

    Critical values use a t distribution with degrees of freedom set by the *smaller*
    clustering dimension, following standard practice for few-cluster inference. With
    a few dozen entities the normal approximation is too generous and over-rejects.
    """

    name: str
    coefficient: float
    std_error: float
    n_obs: int
    n_names: int
    n_dates: int

    @property
    def df(self) -> int:
        return max(min(self.n_names, self.n_dates) - 1, 1)

    @property
    def t_stat(self) -> float:
        return self.coefficient / self.std_error if self.std_error > 0 else float("nan")

    @property
    def t_crit(self) -> float:
        return float(stats.t.ppf(0.975, self.df))

    @property
    def p_value(self) -> float:
        return float(2 * stats.t.sf(abs(self.t_stat), self.df))

    @property
    def ci95(self) -> tuple[float, float]:
        half = self.t_crit * self.std_error
        return (self.coefficient - half, self.coefficient + half)

    @property
    def mde80(self) -> float:
        """Minimum effect detectable at 80% power, two-sided 5%.

        Reported alongside every estimate so that a null is expressed as a bound
        rather than as an absence.
        """
        return (self.t_crit + float(stats.t.ppf(0.80, self.df))) * self.std_error

    def describe(self) -> str:
        lo, hi = self.ci95
        return (
            f"{self.name:28s} beta={self.coefficient:+.4f}  se={self.std_error:.4f}  "
            f"t={self.t_stat:+.2f}  p={self.p_value:.4f}  95%CI=[{lo:+.4f},{hi:+.4f}]  "
            f"MDE80={self.mde80:.4f}  N={self.n_obs:,}  df={self.df}"
        )


def _demean(frame: pd.DataFrame, columns: list[str], group: str) -> pd.DataFrame:
    return frame[columns] - frame.groupby(group, observed=True)[columns].transform("mean")


def absorb_two_way(
    frame: pd.DataFrame, columns: list[str], *, entity: str, time: str, iterations: int = 30
) -> pd.DataFrame:
    """Remove entity and time fixed effects by alternating projection.

    Iterating is necessary because the panel is unbalanced: subtracting entity means
    then time means once does not fully purge either when group sizes differ.
    """
    out = frame[columns].astype(float).copy()
    work = frame[[entity, time]].join(out)

    for _ in range(iterations):
        before = work[columns].to_numpy(copy=True)
        work[columns] = _demean(work, columns, entity)
        work[columns] = _demean(work, columns, time)
        if np.nanmax(np.abs(work[columns].to_numpy() - before)) < 1e-10:
            break

    return work[columns]


def fit(
    frame: pd.DataFrame,
    outcome: str,
    regressors: list[str],
    *,
    entity: str = "symbol",
    time: str = "date",
) -> dict[str, Estimate]:
    """Two-way fixed-effects OLS with two-way clustered standard errors.

    Returns one Estimate per regressor. Raises on rank deficiency rather than
    returning a silently meaningless fit.
    """
    needed = [outcome, *regressors, entity, time]
    missing = [c for c in needed if c not in frame.columns]
    if missing:
        raise ValueError(f"panel is missing columns: {missing}")

    data = frame[needed].dropna()
    if data.empty:
        raise ValueError("panel has no complete observations")

    absorbed = absorb_two_way(data, [outcome, *regressors], entity=entity, time=time)
    y = absorbed[outcome].to_numpy()
    x = absorbed[regressors].to_numpy()

    xtx = x.T @ x
    if np.linalg.matrix_rank(xtx) < xtx.shape[0]:
        raise ValueError(
            f"regressors are collinear after absorbing {entity} and {time} effects: {regressors}"
        )

    xtx_inv = np.linalg.inv(xtx)
    beta = xtx_inv @ (x.T @ y)
    resid = y - x @ beta

    n_obs, n_params = x.shape

    def meat(group_key: pd.Series, *, correct: bool = True) -> np.ndarray:
        """Clustered score covariance, with the usual finite-sample correction.

        Without the correction this estimator is biased downward when one clustering
        dimension has few groups, which here means entities: a panel of a few dozen
        names over-rejects noticeably. Verified by simulation before adding.
        """
        total = np.zeros_like(xtx)
        scores = x * resid[:, None]
        keys = group_key.to_numpy()
        for _, idx in pd.Series(range(len(scores))).groupby(keys):
            s = scores[idx.to_numpy()].sum(axis=0)
            total += np.outer(s, s)
        if correct:
            n_groups = len(np.unique(keys))
            if n_groups > 1:
                scale = (n_groups / (n_groups - 1)) * ((n_obs - 1) / max(n_obs - n_params, 1))
                total *= scale
        return total

    # Cameron-Gelbach-Miller: V_entity + V_time - V_intersection.
    both = data[entity].astype(str) + "|" + data[time].astype(str)
    sandwich = xtx_inv @ (meat(data[entity]) + meat(data[time]) - meat(both)) @ xtx_inv

    variances = np.diag(sandwich)
    # A negative variance is possible with CGM in small samples; surface it rather
    # than silently taking the square root of a negative number.
    if np.any(variances < 0):
        raise ValueError(
            "two-way clustered variance is not positive definite; "
            "too few clusters for this estimator"
        )

    return {
        r: Estimate(
            name=r,
            coefficient=float(beta[i]),
            std_error=float(np.sqrt(variances[i])),
            n_obs=len(data),
            n_names=data[entity].nunique(),
            n_dates=data[time].nunique(),
        )
        for i, r in enumerate(regressors)
    }


__all__ = ["Estimate", "absorb_two_way", "fit"]
