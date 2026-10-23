"""Randomization inference for a two-way fixed-effects coefficient.

The clustered t-statistic leans on asymptotics in the number of underlyings and dates.
The permutation test leans on none: it shuffles the predictor across underlyings within
each date, which keeps every date's set of predictor values (and so anything common to a
date) and breaks only the link between an underlying's inventory and its own outcome.
The coefficient is re-estimated on each shuffle, with the same fixed effects and
controls, and the observed coefficient is placed in that distribution.

A thousand re-estimations are cheap because only the shuffled predictor changes. The
outcome and the controls are purged of the fixed effects once, and the predictor is
purged on each draw by an exact two-way within transform rather than by iterating
demeaning to convergence. By Frisch-Waugh-Lovell the coefficient is then a ratio of two
inner products.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import linalg, sparse
from scipy.sparse.csgraph import connected_components

N_PERM = 1000
SEED = 20261023
_BATCH = 100


@dataclass(frozen=True, eq=False)
class PermutationResult:
    """The observed coefficient, the coefficients on shuffled predictors, and the
    two-sided p-value: the share of draws at least as large in absolute value, counting
    the observed estimate itself as one of the draws."""

    observed: float
    null: np.ndarray
    p_value: float
    n_obs: int


class TwoWayProjector:
    """Residuals from a regression on entity and time dummies, for any number of columns.

    With entity counts on the diagonal, the entity effects are eliminated in closed form
    and the time effects solve a dates-by-dates system (the Schur complement), factored
    once. One time effect is fixed at zero, which identifies the rest when the panel is
    connected; a panel that splits into separate blocks of entities and dates is refused.
    """

    def __init__(self, entity: pd.Series | np.ndarray, time: pd.Series | np.ndarray) -> None:
        self.entity_codes, entities = pd.factorize(np.asarray(entity))
        self.time_codes, times = pd.factorize(np.asarray(time))
        n = len(self.entity_codes)
        rows = np.arange(n)
        ones = np.ones(n)
        self._entity: sparse.csr_matrix = sparse.csr_matrix(
            (ones, (rows, self.entity_codes)), shape=(n, len(entities))
        )
        self._time: sparse.csr_matrix = sparse.csr_matrix(
            (ones, (rows, self.time_codes)), shape=(n, len(times))
        )
        self._entity_counts = np.asarray(self._entity.sum(axis=0)).ravel()
        cross = (self._entity.T @ self._time).toarray()

        graph = sparse.bmat([[None, sparse.csr_matrix(cross)], [sparse.csr_matrix(cross.T), None]])
        components, _ = connected_components(graph, directed=False)
        if components > 1:
            raise ValueError(
                f"the panel splits into {components} unconnected blocks of entities and "
                "dates; two-way effects are not identified across them"
            )

        self._cross = cross
        time_counts = np.asarray(self._time.sum(axis=0)).ravel()
        schur = np.diag(time_counts) - cross.T @ (cross / self._entity_counts[:, None])
        self._factor = linalg.cho_factor(schur[1:, 1:]) if len(times) > 1 else None

    def residuals(self, values: np.ndarray) -> np.ndarray:
        """``values`` (n by k) less their fitted entity and time effects."""
        matrix = np.asarray(values, dtype=float)
        column = matrix.ndim == 1
        if column:
            matrix = matrix[:, None]
        entity_sums = self._entity.T @ matrix
        time_sums = self._time.T @ matrix
        rhs = time_sums - self._cross.T @ (entity_sums / self._entity_counts[:, None])
        time_effects = np.zeros_like(time_sums)
        if self._factor is not None:
            time_effects[1:] = linalg.cho_solve(self._factor, rhs[1:])
        entity_effects = (entity_sums - self._cross @ time_effects) / self._entity_counts[:, None]
        out: np.ndarray = matrix - entity_effects[self.entity_codes] - time_effects[self.time_codes]
        return out[:, 0] if column else out


def two_way_residuals(
    entity: pd.Series | np.ndarray, time: pd.Series | np.ndarray, values: np.ndarray
) -> np.ndarray:
    """``values`` purged of entity and time fixed effects, exactly."""
    return TwoWayProjector(entity, time).residuals(values)


class WithinGroupShuffle:
    """Shuffles values among the positions of each group; groups stay where they are.

    The positions are sorted by group once. A draw then sorts on group code plus a
    uniform key in [0, 1), which orders positions by group and at random within it.
    """

    def __init__(self, groups: np.ndarray) -> None:
        codes = np.asarray(groups)
        self._blocks = np.argsort(codes, kind="stable")
        self._sorted = codes[self._blocks].astype(float)

    def __call__(self, values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        keys = self._sorted + rng.random(len(self._sorted))
        shuffled = self._blocks[np.argsort(keys)]
        out = np.empty_like(values)
        out[self._blocks] = values[shuffled]
        return out


def permute_within(values: np.ndarray, groups: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """``values`` shuffled among the positions of each group; groups stay where they are."""
    return WithinGroupShuffle(groups)(values, rng)


def permutation_test(
    panel: pd.DataFrame,
    outcome: str,
    predictor: str,
    controls: Sequence[str],
    *,
    n_perm: int = N_PERM,
    seed: int = SEED,
    entity: str = "symbol",
    time: str = "date",
) -> PermutationResult:
    """Place the fixed-effects coefficient on ``predictor`` among ``n_perm`` coefficients
    estimated with the predictor shuffled across entities within each date.

    The specification is that of `measure.panel.fit`: entity and time fixed effects and
    the given controls, on the rows where every column is present.
    """
    needed = [outcome, predictor, *controls, entity, time]
    missing = [column for column in needed if column not in panel.columns]
    if missing:
        raise ValueError(f"panel is missing columns: {missing}")
    if n_perm < 1:
        raise ValueError(f"n_perm must be at least 1, got {n_perm}")

    data = panel[needed].dropna()
    projector = TwoWayProjector(data[entity], data[time])
    purged = projector.residuals(data[[outcome, *controls]].to_numpy(dtype=float))
    basis = np.linalg.qr(purged[:, 1:])[0] if controls else np.zeros((len(data), 0))
    target = purged[:, 0] - basis @ (basis.T @ purged[:, 0])

    def coefficients(columns: np.ndarray) -> np.ndarray:
        residual = projector.residuals(columns)
        residual -= basis @ (basis.T @ residual)
        betas: np.ndarray = (residual.T @ target) / np.einsum("ij,ij->j", residual, residual)
        return betas

    values = data[predictor].to_numpy(dtype=float)
    observed = float(coefficients(values[:, None])[0])

    rng = np.random.default_rng(seed)
    shuffle = WithinGroupShuffle(projector.time_codes)
    draws = []
    for start in range(0, n_perm, _BATCH):
        size = min(_BATCH, n_perm - start)
        shuffled = [shuffle(values, rng) for _ in range(size)]
        draws.append(coefficients(np.column_stack(shuffled)))
    null = np.concatenate(draws)
    exceed = int(np.sum(np.abs(null) >= abs(observed)))
    return PermutationResult(
        observed=observed,
        null=null,
        p_value=(1 + exceed) / (n_perm + 1),
        n_obs=len(data),
    )


__all__ = [
    "N_PERM",
    "SEED",
    "PermutationResult",
    "TwoWayProjector",
    "WithinGroupShuffle",
    "permutation_test",
    "permute_within",
    "two_way_residuals",
]
