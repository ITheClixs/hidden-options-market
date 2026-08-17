"""Tests for the fixed-effects estimator.

This is the component most likely to be wrong in a way that still produces
plausible-looking numbers, so it is checked against constructed data where the true
coefficient is known.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from absorb.measure.panel import absorb_two_way, fit


def _panel(beta: float = 0.30, n_names: int = 25, n_dates: int = 200, seed: int = 0):
    """Build a panel with known entity effects, date effects and treatment effect."""
    rng = np.random.default_rng(seed)
    names = [f"N{i:02d}" for i in range(n_names)]
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")

    name_fe = dict(zip(names, rng.normal(0, 2.0, n_names), strict=True))
    date_fe = dict(zip(dates, rng.normal(0, 1.0, n_dates), strict=True))
    treated = set(names[: n_names // 2])

    rows = []
    for nm in names:
        for d in dates:
            treat = 1.0 if (nm in treated and d > dates[n_dates // 2]) else 0.0
            rows.append(
                {
                    "symbol": nm,
                    "date": d,
                    "treat": treat,
                    "y": name_fe[nm] + date_fe[d] + beta * treat + rng.normal(0, 0.5),
                }
            )
    return pd.DataFrame(rows)


class TestAbsorbTwoWay:
    def test_removes_entity_and_time_means(self):
        frame = _panel()
        out = absorb_two_way(frame, ["y"], entity="symbol", time="date")
        joined = frame[["symbol", "date"]].join(out)
        assert joined.groupby("symbol")["y"].mean().abs().max() < 1e-8
        assert joined.groupby("date")["y"].mean().abs().max() < 1e-8

    def test_handles_unbalanced_panels(self):
        """One pass of alternating demeaning is not enough when groups differ in size."""
        frame = _panel().drop(index=range(0, 400, 3))
        out = absorb_two_way(frame, ["y"], entity="symbol", time="date")
        joined = frame[["symbol", "date"]].reset_index(drop=True).join(out.reset_index(drop=True))
        assert joined.groupby("symbol")["y"].mean().abs().max() < 1e-6


def realistic_panel(
    beta: float = 0.0,
    n_names: int = 40,
    n_dates: int = 300,
    rho: float = 0.5,
    factor_sd: float = 0.6,
    seed: int = 0,
):
    """Panel whose errors carry within-name persistence and a common daily factor.

    Clustering exists to handle exactly this dependence, so calibration must be
    judged here rather than under iid noise.
    """
    rng = np.random.default_rng(seed)
    names = [f"N{i:02d}" for i in range(n_names)]
    dates = pd.date_range("2023-01-02", periods=n_dates, freq="B")
    common = rng.normal(0, factor_sd, n_dates)
    loadings = rng.uniform(0.5, 1.5, n_names)
    treated = set(names[: n_names // 2])
    cut = dates[n_dates // 2]

    rows = []
    for k, nm in enumerate(names):
        err = 0.0
        for j, d in enumerate(dates):
            err = rho * err + rng.normal(0, 0.5)
            treat = 1.0 if (nm in treated and d > cut) else 0.0
            rows.append(
                {
                    "symbol": nm,
                    "date": d,
                    "treat": treat,
                    "y": beta * treat + loadings[k] * common[j] + err,
                }
            )
    return pd.DataFrame(rows)


class TestFit:
    def test_recovers_a_known_coefficient(self):
        """Tolerance is set from the sampling sd (~0.04 at this panel size), not from
        wishful precision: a single draw is not expected to land on the truth."""
        est = fit(_panel(beta=0.30), "y", ["treat"])["treat"]
        assert est.coefficient == pytest.approx(0.30, abs=3 * est.std_error)

    def test_is_unbiased_across_replications(self):
        betas = [
            fit(_panel(beta=0.30, seed=s), "y", ["treat"])["treat"].coefficient for s in range(20)
        ]
        assert np.mean(betas) == pytest.approx(0.30, abs=0.03)

    def test_recovers_a_zero_coefficient(self):
        est = fit(_panel(beta=0.0), "y", ["treat"])["treat"]
        assert abs(est.coefficient) < 3 * est.std_error

    def test_t_stat_detects_a_real_effect(self):
        assert fit(_panel(beta=0.30), "y", ["treat"])["treat"].t_stat > 3.0

    def test_t_stat_is_small_under_the_null(self):
        assert abs(fit(_panel(beta=0.0), "y", ["treat"])["treat"].t_stat) < 2.5

    def test_reports_cluster_counts(self):
        est = fit(_panel(), "y", ["treat"])["treat"]
        assert est.n_names == 25
        assert est.n_dates == 200

    def test_mde_is_reported_for_bounding_nulls(self):
        """MDE uses t critical values, not the normal 2.80, because few entity
        clusters make the normal approximation too generous."""
        est = fit(_panel(beta=0.0), "y", ["treat"])["treat"]
        assert est.mde80 > 2.80 * est.std_error
        assert est.mde80 == pytest.approx(
            (est.t_crit + float(stats.t.ppf(0.80, est.df))) * est.std_error
        )

    def test_t_critical_value_exceeds_the_normal_approximation(self):
        est = fit(_panel(beta=0.0), "y", ["treat"])["treat"]
        assert est.t_crit > 1.96
        assert est.df == 24

    def test_two_way_clustering_is_wider_than_naive_ols(self):
        """The whole point of clustering: naive OLS understates the error here."""
        frame = _panel(beta=0.30)
        est = fit(frame, "y", ["treat"])["treat"]
        absorbed = absorb_two_way(frame, ["y", "treat"], entity="symbol", time="date")
        x = absorbed[["treat"]].to_numpy()
        y = absorbed["y"].to_numpy()
        b = np.linalg.lstsq(x, y, rcond=None)[0]
        resid = y - x @ b
        naive_se = float(np.sqrt((resid @ resid) / (len(y) - 1) / (x.T @ x)[0, 0]))
        assert est.std_error > naive_se

    def test_rejects_missing_columns(self):
        with pytest.raises(ValueError, match="missing columns"):
            fit(_panel(), "y", ["absent"])

    def test_rejects_collinear_regressors(self):
        frame = _panel()
        frame["copy"] = frame["treat"]
        with pytest.raises(ValueError, match="collinear"):
            fit(frame, "y", ["treat", "copy"])

    def test_rejects_empty_panel(self):
        frame = _panel().head(0)
        with pytest.raises(ValueError, match="no complete observations"):
            fit(frame, "y", ["treat"])

    def test_absorbed_regressor_is_reported_as_collinear(self):
        """A time-invariant regressor is wiped out by entity effects; that must fail
        loudly rather than return a meaningless coefficient."""
        frame = _panel()
        frame["const_by_name"] = frame["symbol"].str[-1].astype(int).astype(float)
        with pytest.raises(ValueError, match="collinear"):
            fit(frame, "y", ["const_by_name"])


class TestInferenceCalibration:
    """Guards against the failure mode that matters: a standard error that is too
    small, which manufactures significance. Checked under dependence rather than iid
    noise, because clustering is pointless under the latter."""

    def test_standard_error_is_calibrated_under_dependence(self):
        betas, errors = [], []
        for seed in range(40):
            est = fit(realistic_panel(beta=0.0, seed=seed), "y", ["treat"])["treat"]
            betas.append(est.coefficient)
            errors.append(est.std_error)
        ratio = np.mean(errors) / np.std(betas, ddof=1)
        # Must not understate. Conservative is acceptable; anti-conservative is not.
        assert ratio > 0.85, f"clustered SE understates sampling variation (ratio {ratio:.3f})"

    def test_does_not_over_reject_under_the_null(self):
        rejections = 0
        reps = 40
        for seed in range(reps):
            est = fit(realistic_panel(beta=0.0, seed=seed), "y", ["treat"])["treat"]
            if abs(est.t_stat) > est.t_crit:
                rejections += 1
        assert rejections / reps <= 0.15, f"rejection rate {rejections / reps:.3f} too high"


class TestAgreesWithReferenceImplementation:
    """The estimator is hand-rolled, so it is pinned against a mature library."""

    def test_matches_linearmodels_panelols(self):
        pytest.importorskip("linearmodels")
        from linearmodels.panel import PanelOLS

        frame = _panel(beta=0.30, n_names=30, n_dates=250, seed=7)
        mine = fit(frame, "y", ["treat"])["treat"]

        indexed = frame.set_index(["symbol", "date"])
        reference = PanelOLS(
            indexed["y"], indexed[["treat"]], entity_effects=True, time_effects=True
        ).fit(cov_type="clustered", cluster_entity=True, cluster_time=True)

        assert mine.coefficient == pytest.approx(float(reference.params["treat"]), rel=1e-6)
        assert mine.std_error == pytest.approx(float(reference.std_errors["treat"]), rel=1e-3)
