"""Tests for the pinning test's size and power on real returns
(docs/log/2026-11-08-pinning-empirical-null-spec.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.pinning import event_statistics, with_sigma
from hidden_options.measure.pinning_null import empirical_null, placebo_events, planted

DAYS = pd.bdate_range("2025-01-02", periods=300)


def closes_world(seed: int = 0, names: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(names):
        path = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, size=len(DAYS))))
        rows.append(
            pd.DataFrame(
                {
                    "symbol": f"N{chr(65 + i // 26)}{chr(65 + i % 26)}",
                    "session": DAYS,
                    "close": path,
                }
            )
        )
    return with_sigma(pd.concat(rows, ignore_index=True))


def registered_stats(closes: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Events on Tuesdays in the middle of the sample, strikes within a sigma."""
    tuesdays = [d for d in DAYS[100:200] if d.day_of_week == 1]
    frame = closes[closes["session"].isin(tuesdays)].dropna(subset=["sigma"])
    z = rng.uniform(-1, 1, len(frame))
    events = pd.DataFrame(
        {
            "underlying": frame["symbol"].to_numpy(),
            "expiry": frame["session"].to_numpy(),
            "prev_close": frame["prev_close"].to_numpy(),
            "sigma": frame["sigma"].to_numpy(),
            "strike": frame["prev_close"].to_numpy() * np.exp(z * frame["sigma"].to_numpy()),
        }
    )
    return event_statistics(events, closes, DAYS)


def test_placebo_events_keep_the_distance_in_sigmas_and_avoid_expiries():
    closes = closes_world()
    stats = registered_stats(closes, np.random.default_rng(1))
    expiries = {(u, e) for u, e in zip(stats["underlying"], stats["expiry"], strict=True)}
    moved = placebo_events(stats, closes, DAYS, offset=10, flex_expiries=expiries)
    assert len(moved) > 0
    assert set(pd.DatetimeIndex(moved["expiry"]).day_of_week) <= {0, 1, 2, 3}
    assert not any(
        (u, e) in expiries for u, e in zip(moved["underlying"], moved["expiry"], strict=True)
    )
    z_moved = np.log(moved["strike"] / moved["prev_close"]) / moved["sigma"]
    original = stats.set_index(["underlying", "expiry"])
    z_from = np.log(original["strike"] / original["prev_close"]) / original["sigma"]
    assert np.sort(z_moved.to_numpy()) == pytest.approx(
        np.sort(
            z_from.loc[
                list(zip(moved["underlying"], moved["source_expiry"], strict=True))
            ].to_numpy()
        )
    )


def test_planted_pulls_the_chosen_closes_halfway_in_logs():
    closes = closes_world()
    events = pd.DataFrame(
        {
            "underlying": ["NAA"],
            "expiry": [DAYS[150]],
            "strike": [100.0],
            "prev_close": [np.nan],
            "sigma": [np.nan],
        }
    )
    found = planted(closes, events, share=1.0, rng=np.random.default_rng(0))
    row = (found["symbol"] == "NAA") & (found["session"] == DAYS[150])
    before = closes.loc[row, "close"].iloc[0]
    assert found.loc[row, "close"].iloc[0] == pytest.approx(np.sqrt(before * 100.0))
    assert (found.loc[~row, "close"].to_numpy() == closes.loc[~row, "close"].to_numpy()).all()


def test_iid_returns_give_a_centred_null_and_planted_pins_are_found():
    closes = closes_world(seed=2)
    stats = registered_stats(closes, np.random.default_rng(3))
    expiries = {(u, e) for u, e in zip(stats["underlying"], stats["expiry"], strict=True)}
    found = empirical_null(
        stats, closes, DAYS, expiries, offsets=(-31, -21, 21, 31), shares=(0.5,), seed=4
    )
    assert abs(found["centre"]) < 0.03
    assert found["power"]["0.50"] == pytest.approx(1.0)
    assert len(found["offsets"]) == 4
