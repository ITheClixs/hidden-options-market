"""Tests for the listed-strike positive control (docs/log/2026-11-08-pinning-control-spec.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.pinning import clustered_mean, with_sigma
from hidden_options.measure.pinning_control import (
    control_events,
    control_statistics,
    grid_strike,
    monthly_expiries,
)


def test_monthly_expiry_is_the_third_friday_or_the_session_before():
    days = pd.bdate_range("2025-03-01", "2025-05-31")
    days = days[days != pd.Timestamp("2025-04-18")]  # Good Friday
    found = monthly_expiries(pd.DatetimeIndex(days))
    assert list(found) == [
        pd.Timestamp("2025-03-21"),
        pd.Timestamp("2025-04-17"),
        pd.Timestamp("2025-05-16"),
    ]
    # Data ending before a month's third Friday gives no expiry for that month.
    assert list(monthly_expiries(pd.bdate_range("2025-06-02", "2025-06-18"))) == []


@pytest.mark.parametrize(
    ("close", "strike"),
    [
        (23.7, 22.5),
        (24.0, 25.0),
        (26.0, 25.0),
        (27.5, 25.0),  # a tie goes to the lower strike
        (199.0, 200.0),
        (204.0, 200.0),
        (215.0, 210.0),
        (1234.0, 1230.0),
    ],
)
def test_nearest_coarse_grid_strike(close, strike):
    assert grid_strike(np.array([close]))[0] == pytest.approx(strike)


def test_events_keep_names_above_five_dollars_and_strikes_within_two_sigma():
    closes = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "session": pd.Timestamp("2025-03-21"),
            "close": [101.0, 4.0, 102.4],
            "prev_close": [101.0, 4.0, 102.4],
            "sigma": [0.02, 0.05, 0.005],
        }
    )
    found = control_events(closes, pd.DatetimeIndex([pd.Timestamp("2025-03-21")]))
    # BBB is under $5; CCC's strike, 100, is 4.7 of its sigmas away.
    assert list(found["underlying"]) == ["AAA"]
    assert found["strike"].iloc[0] == pytest.approx(100.0)


def world(pinned: bool, seed: int = 0) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2025-01-02", periods=400)
    monthly = set(monthly_expiries(days))
    rows = []
    for i in range(80):
        path = 60 * np.exp(np.cumsum(rng.normal(0, 0.02, size=len(days))))
        if pinned:
            for pos, day in enumerate(days):
                if day in monthly and rng.random() < 0.5:
                    path[pos] = grid_strike(np.array([path[pos - 1]]))[0]
        rows.append(
            pd.DataFrame(
                {
                    "symbol": f"N{chr(65 + i // 26)}{chr(65 + i % 26)}",
                    "session": days,
                    "close": path,
                }
            )
        )
    return with_sigma(pd.concat(rows, ignore_index=True)), days


def test_a_planted_pin_at_listed_strikes_is_found_and_none_otherwise():
    closes, days = world(pinned=True)
    stats = control_statistics(closes, days, monthly_expiries(days))
    found = clustered_mean(stats["D"], stats["expiry"])
    assert found["mean"] > 0
    assert found["p_value"] < 0.001

    closes, days = world(pinned=False, seed=1)
    stats = control_statistics(closes, days, monthly_expiries(days))
    assert clustered_mean(stats["D"], stats["expiry"])["p_value"] > 0.01
