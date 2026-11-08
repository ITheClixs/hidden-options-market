"""Tests for the pinning test (docs/log/2026-11-08-pinning-spec.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.pinning import (
    CAP,
    PSEUDO_OFFSETS,
    closeness,
    clustered_mean,
    event_statistics,
    flex_only,
    listed_nonfriday,
    pin_strikes,
    sign_flip_p,
    size_terciles,
    with_sigma,
)

DAYS = pd.bdate_range("2026-01-05", periods=120)
HOLIDAYS = frozenset({pd.Timestamp("2026-04-03")})  # a Friday


class TestListedNonFriday:
    def test_a_holiday_shifted_thursday_does_not_count(self):
        listed = pd.DataFrame(
            {
                "symbol": ["AAA", "BBB", "BBB"],
                "expiry": pd.to_datetime(["2026-04-02", "2026-04-02", "2026-04-08"]),
            }
        )
        assert listed_nonfriday(listed, HOLIDAYS) == {"BBB"}


class TestFlexOnly:
    def test_monday_to_thursday_only_and_not_before_a_friday_holiday(self):
        days = pd.DatetimeIndex(["2026-03-30", "2026-04-02", "2026-04-06", "2026-04-10"])
        found = flex_only(days, HOLIDAYS)
        # Monday kept; Thursday before Good Friday dropped; Monday kept; Friday dropped.
        assert list(found) == [True, False, True, False]


def closes_frame(symbol, values, days=DAYS):
    return pd.DataFrame({"symbol": symbol, "session": days[: len(values)], "close": values})


class TestSigma:
    def test_uses_only_returns_before_the_date(self):
        values = 100 * np.exp(np.cumsum(np.r_[0, np.full(70, 0.01)]))
        values[65] *= 1.5  # a jump on session 65
        frame = with_sigma(closes_frame("AAA", values))
        assert frame.set_index("session").loc[DAYS[65], "sigma"] == pytest.approx(0.0, abs=1e-12)
        assert frame.set_index("session").loc[DAYS[66], "sigma"] > 0.01


class TestPinStrikes:
    def book(self, rows):
        """rows: (underlying, expiry, strike, right, open_interest)"""
        return pd.DataFrame(
            rows, columns=["underlying", "expiry", "strike", "right", "open_interest"]
        )

    def test_largest_book_strike_within_two_sigma_and_large_enough(self):
        expiry = DAYS[80]
        book = self.book(
            [
                ("AAA", expiry, 100.0, "C", 400),
                ("AAA", expiry, 100.0, "P", 300),  # 700 at 100
                ("AAA", expiry, 150.0, "C", 5000),  # bigger but too far from spot
                ("AAA", expiry, 101.0, "C", 600),
            ]
        )
        prev = pd.DataFrame(
            {"underlying": ["AAA"], "expiry": [expiry], "prev_close": [100.5], "sigma": [0.02]}
        )
        found = pin_strikes(book, prev)
        assert len(found) == 1
        row = found.iloc[0]
        assert row["strike"] == 100.0
        assert row["open_interest"] == 700
        assert row["call_share"] == pytest.approx(400 / 700)

    def test_too_small_a_book_is_no_event(self):
        expiry = DAYS[80]
        book = self.book([("AAA", expiry, 100.0, "C", 99)])
        prev = pd.DataFrame(
            {"underlying": ["AAA"], "expiry": [expiry], "prev_close": [100.0], "sigma": [0.02]}
        )
        assert pin_strikes(book, prev).empty


class TestCloseness:
    def test_positive_when_nearer_the_strike_than_its_mirror(self):
        # Strike 102 above a previous close of 100: mirror at 100**2 / 102.
        at_strike = closeness(102.0, 100.0, 102.0, 0.02)
        at_mirror = closeness(100.0**2 / 102.0, 100.0, 102.0, 0.02)
        assert at_strike > 0
        assert at_mirror == pytest.approx(-at_strike)

    def test_capped(self):
        far = closeness(200.0, 100.0, 102.0, 0.02)
        assert abs(far) <= CAP


def planted_events(n_events=600, n_dates=90, pin_share=0.0, seed=0):
    rng = np.random.default_rng(seed)
    rows, closes = [], []
    dates = DAYS[20 : 20 + n_dates]
    for e in range(n_events):
        symbol = f"S{e}"
        expiry_pos = 20 + e % n_dates
        sigma = 0.02
        path = 100 * np.exp(np.cumsum(rng.normal(0, sigma, size=len(DAYS))))
        strike = path[expiry_pos - 1] * np.exp(rng.uniform(-1.5, 1.5) * sigma)
        if rng.random() < pin_share:
            path[expiry_pos] = strike
        closes.append(closes_frame(symbol, path))
        rows.append(
            {
                "underlying": symbol,
                "expiry": DAYS[expiry_pos],
                "strike": strike,
                "sigma": sigma,
                "open_interest": 1000,
                "call_share": 0.5,
                "size": float(e % 3),
            }
        )
    del dates
    return pd.DataFrame(rows), pd.concat(closes, ignore_index=True)


class TestEventStatistics:
    def test_planted_pinning_is_found(self):
        events, closes = planted_events(pin_share=0.3)
        stats = event_statistics(events, closes, DAYS)
        found = clustered_mean(stats["D"], stats["expiry"])
        assert found["mean"] > 0
        assert found["p_value"] < 0.001

    def test_no_pinning_is_not_found(self):
        events, closes = planted_events(pin_share=0.0, seed=4)
        stats = event_statistics(events, closes, DAYS)
        assert clustered_mean(stats["D"], stats["expiry"])["p_value"] > 0.01

    def test_pseudo_dates_are_the_five_sessions_after_expiry(self):
        assert PSEUDO_OFFSETS == (-1, -2, -3, -4, -5)

    def test_an_event_missing_a_pseudo_close_is_dropped(self):
        events, closes = planted_events(n_events=3, n_dates=3)
        first = events.iloc[0]
        gap = DAYS.get_loc(first["expiry"]) + 3
        closes = closes[
            ~((closes["symbol"] == first["underlying"]) & (closes["session"] == DAYS[gap]))
        ]
        stats = event_statistics(events, closes, DAYS)
        assert first["underlying"] not in set(stats["underlying"])


class TestInference:
    def test_clustered_mean_and_degrees_of_freedom(self):
        values = pd.Series([1.0, 3.0, 2.0, 4.0])
        clusters = pd.Series(["a", "a", "b", "b"])
        found = clustered_mean(values, clusters)
        # Cluster means 2 and 3: mean 2.5, se = sd(2,3)/sqrt(2) = 0.5.
        assert found["mean"] == pytest.approx(2.5)
        assert found["std_error"] == pytest.approx(0.5)
        assert found["clusters"] == 2

    def test_sign_flip_p_is_large_for_symmetric_noise_and_small_for_a_shift(self):
        rng = np.random.default_rng(0)
        clusters = pd.Series(np.repeat(np.arange(200), 5))
        noise = pd.Series(rng.normal(size=1000))
        assert sign_flip_p(noise, clusters, n_draws=2000, seed=1) > 0.05
        assert sign_flip_p(noise + 0.5, clusters, n_draws=2000, seed=1) < 0.001


class TestSizeTerciles:
    def test_top_minus_bottom(self):
        frame = pd.DataFrame(
            {
                "D": [0.0, 0.0, 1.0, 1.0, 2.0, 2.0],
                "size": [1, 2, 3, 4, 5, 6],
                "expiry": list("aabbcc"),
            }
        )
        found = size_terciles(frame)
        assert found["difference"] == pytest.approx(2.0)
