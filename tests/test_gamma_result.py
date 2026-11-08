"""Tests for the `gamma_predictive` result's pieces: Holm, the verdict, and recovery of a
planted effect by the estimating row."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.predict.gamma_macros import gamma_predictive_macros
from hidden_options.predict.gamma_result import (
    BOUNDED_SHARE,
    PRIMARY,
    SECONDARY,
    _holm,
    _row,
    _verdict,
)
from hidden_options.predict.panel import CONTROLS
from hidden_options.predict.regressions import PredictiveRow


def row(coefficient=0.0, p=0.5, mde=1e-4):
    return PredictiveRow(
        predictor=PRIMARY,
        outcome="abs_ret_next",
        coefficient=coefficient,
        t_stat=0.0,
        mde80=mde,
        n_obs=100,
        placebo=False,
        std_error=mde / 2.8,
        p_value=p,
        ci_low=-1.0,
        ci_high=1.0,
        n_underlyings=10,
        n_dates=10,
    )


class TestHolm:
    def test_step_down_adjustment(self):
        found = _holm({"h1": 0.01, "h2": 0.04})
        assert found == {"h1": pytest.approx(0.02), "h2": pytest.approx(0.04)}

    def test_monotone_and_capped_at_one(self):
        found = _holm({"h1": 0.6, "h2": 0.3})
        assert found["h2"] == pytest.approx(0.6)
        assert found["h1"] == pytest.approx(0.6)


class TestVerdict:
    def test_finding_when_holm_rejects(self):
        assert _verdict(row(-1e-4, p=0.01), 0.02, 0.02)["kind"] == "finding"

    def test_bounded_null_when_the_mde_is_small(self):
        mean_abs = 0.02
        found = _verdict(row(mde=0.5 * BOUNDED_SHARE * mean_abs), 0.5, mean_abs)
        assert found["kind"] == "bounded_null"

    def test_inconclusive_otherwise(self):
        mean_abs = 0.02
        assert (
            _verdict(row(mde=2 * BOUNDED_SHARE * mean_abs), 0.5, mean_abs)["kind"] == "inconclusive"
        )


def planted(beta: float, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    symbols, dates = 40, 120
    frame = pd.DataFrame(
        {
            "symbol": np.repeat([f"S{i}" for i in range(symbols)], dates),
            "date": np.tile(pd.bdate_range("2025-01-01", periods=dates), symbols),
        }
    )
    n = len(frame)
    for control in CONTROLS:
        frame[control] = rng.normal(size=n)
    frame[PRIMARY] = rng.normal(size=n)
    noise = rng.normal(scale=0.01, size=n)
    frame["abs_ret_next"] = 0.02 + beta * frame[PRIMARY] + 0.001 * frame["rv5"] + noise
    return frame


class TestPlantedEffect:
    def test_a_planted_effect_is_recovered(self):
        found = _row(planted(-0.002), PRIMARY, "abs_ret_next", [PRIMARY])
        assert found.coefficient == pytest.approx(-0.002, abs=4 * found.std_error)
        assert found.p_value < 0.001

    def test_no_effect_is_not_found(self):
        found = _row(planted(0.0), PRIMARY, "abs_ret_next", [PRIMARY])
        assert found.p_value > 0.01


def test_macros_cover_every_secondary_row():
    est = {**row().__dict__}
    values = {
        "h1": {**est, "holm_p": 0.5, "permutation_p": 0.5},
        "h2": {**est, "holm_p": 0.5},
        "secondary": [{**est, "predictor": x, "outcome": y} for x, y in SECONDARY],
        "verdict": {"kind": "bounded_null", "mde_share": 0.01, "sign": -1.0},
        "sample": {
            "underlying_days": 100,
            "underlyings": 10,
            "dates": 10,
            "excluded_low_coverage": 1,
            "median_coverage": 0.9,
            "x_net_raw_median": 1e-4,
            "x_net_raw_p90": 1e-3,
            "x_net_sd": 5e-4,
            "mean_abs_ret": 0.02,
        },
    }
    macros = gamma_predictive_macros(values)
    assert macros["GPredVerdict"] == "a bounded null"
    for stem in ("Gross", "Signed", "OpenClose", "Range", "Lead"):
        assert f"GPred{stem}T" in macros


def test_table_lists_the_tests_of_record_first():
    from hidden_options.predict.gamma_table import gamma_predictive_table
    from hidden_options.publish.results import Result

    est = {**row().__dict__}
    values = {
        "h1": {**est, "holm_p": 0.5, "permutation_p": 0.5},
        "h2": {**est, "predictor": "x_net_top", "holm_p": 0.5},
        "secondary": [{**est, "predictor": x, "outcome": y} for x, y in SECONDARY],
        "verdict": {"kind": "bounded_null", "mde_share": 0.01, "sign": -1.0},
        "sample": {
            "underlying_days": 100,
            "underlyings": 10,
            "dates": 10,
            "excluded_low_coverage": 1,
            "median_coverage": 0.9,
            "x_net_raw_median": 1e-4,
            "x_net_raw_p90": 1e-3,
            "x_net_sd": 5e-4,
            "mean_abs_ret": 0.02,
        },
    }
    result = Result("gamma_predictive", values, gamma_predictive_macros(values), {}, "now")
    text = gamma_predictive_table({"gamma_predictive": result})
    assert text.index("H1: Netted gamma") < text.index("Gross gamma")
    assert "\\label{tab:gamma-pred}" in text
