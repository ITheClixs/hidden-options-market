"""Tests for the calibrated alternative to the gamma null."""

from __future__ import annotations

import math

import pytest

from hidden_options.predict.calibration import calibration, impact_effect


def test_square_root_law():
    # x = 1% of daily volume per 1% move, a 2% move, constant 1, sigma 2% x sqrt(pi/2).
    effect = impact_effect(0.01, 0.02, 1.0)
    assert effect == pytest.approx(0.02 * math.sqrt(math.pi / 2) * math.sqrt(0.02))
    assert impact_effect(0.04, 0.02, 1.0) == pytest.approx(2 * effect)


def test_calibration_against_the_mde():
    sample = {"mean_abs_ret": 0.02, "x_net_sd": 0.0094, "x_net_within_sd": 0.0052}
    found = calibration(sample, mde=0.0002)
    assert set(found["effects"]) == {"pooled", "within"}
    assert found["effects"]["within"]["0.5"] < found["effects"]["pooled"]["1.0"]
    assert found["smallest_over_mde"] == pytest.approx(found["effects"]["within"]["0.5"] / 0.0002)


def test_result_reads_the_predictive_result():
    from hidden_options.predict.calibration_result import calibration_result
    from hidden_options.publish.results import Result

    source = Result(
        "gamma_predictive",
        {
            "sample": {"mean_abs_ret": 0.02, "x_net_sd": 0.0094, "x_net_within_sd": 0.0052},
            "h1": {"mde80": 0.0002},
        },
        {},
        {},
        "2026-11-15T00:00:00+00:00",
    )
    found = calibration_result(source)
    assert found.macros["GCalWithinLow"] == f"{found.values['effects']['within']['0.5'] * 1e4:.0f}"
    assert float(found.macros["GCalRatio"]) > 1
