"""Tests for the wild cluster restricted bootstrap."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.panel import fit, partial_out_two_way
from hidden_options.predict.wild import two_way_demean, wild_cluster_test


def panel(beta: float, *, names: int = 30, dates: int = 80, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {
            "symbol": np.repeat([f"S{i}" for i in range(names)], dates),
            "date": np.tile(pd.bdate_range("2025-01-01", periods=dates), names),
        }
    )
    frame = frame.sample(frac=0.9, random_state=seed).reset_index(drop=True)  # unbalanced
    n = len(frame)
    name_effect = frame["symbol"].map({f"S{i}": rng.normal() for i in range(names)})
    date_effect = frame["date"].map({d: rng.normal() for d in frame["date"].unique()})
    frame["c"] = rng.normal(size=n)
    frame["x"] = 0.5 * name_effect + rng.normal(size=n)
    # Errors correlated within name, so one-way clustering by name matters.
    shock = frame["symbol"].map({f"S{i}": rng.normal() for i in range(names)})
    frame["y"] = (
        beta * frame["x"]
        + 0.3 * frame["c"]
        + name_effect
        + date_effect
        + 0.5 * shock * frame["x"]
        + rng.normal(size=n)
    )
    return frame


def test_demeaning_matches_alternating_projection():
    frame = panel(0.0)
    expected = partial_out_two_way(frame, ["y"], entity="symbol", time="date")["y"].to_numpy()
    entity = pd.factorize(frame["symbol"])[0]
    time = pd.factorize(frame["date"])[0]
    found = two_way_demean(frame["y"].to_numpy(dtype=float), entity, time)
    assert found == pytest.approx(expected, abs=1e-8)


def test_coefficient_matches_the_fixed_effects_fit():
    frame = panel(-0.4)
    found = wild_cluster_test(frame, "y", "x", ["c"], n_draws=99, seed=1)
    expected = fit(frame, "y", ["x", "c"], entity="symbol", time="date")["x"].coefficient
    assert found["coefficient"] == pytest.approx(expected, rel=1e-8)
    assert found["clusters"] == 30


def test_a_planted_negative_effect_is_found_one_sided():
    found = wild_cluster_test(panel(-0.6), "y", "x", ["c"], n_draws=999, seed=2)
    assert found["coefficient"] < 0
    assert found["p_value"] < 0.01


def test_no_effect_and_the_wrong_sign_are_not_found():
    assert (
        wild_cluster_test(panel(0.0, seed=4), "y", "x", ["c"], n_draws=999, seed=3)["p_value"]
        > 0.05
    )
    assert (
        wild_cluster_test(panel(0.6, seed=5), "y", "x", ["c"], n_draws=999, seed=3)["p_value"] > 0.5
    )


def test_mde_is_the_one_sided_multiple_of_the_standard_error():
    found = wild_cluster_test(panel(0.0), "y", "x", ["c"], n_draws=99, seed=1)
    assert found["mde80"] == pytest.approx((1.6449 + 0.8416) * found["std_error"], rel=1e-3)


def test_size_on_simulated_null_panels():
    """Rejections at 5% over many null panels stay near 5% (binomial range for 120)."""
    p_values = [
        wild_cluster_test(
            panel(0.0, names=15, dates=40, seed=100 + s), "y", "x", ["c"], n_draws=99, seed=s
        )["p_value"]
        for s in range(120)
    ]
    assert 0.0 < np.mean(np.array(p_values) < 0.05) < 0.11
