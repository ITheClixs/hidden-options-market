"""Tests for the gamma test's timing rows (docs/log/2026-11-08-gamma-timing-spec.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.predict.gamma_timing import (
    carried_gamma,
    oi_weighted_iv,
    timing_predictors,
)

T0, T1, T2 = pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02"), pd.Timestamp("2026-09-03")
EXPIRY = pd.Timestamp("2026-10-16")


def rows(day, specs):
    """specs: (underlying, strike, right, oi, netted_oi, in_domain, gamma, spot, iv)"""
    return pd.DataFrame(
        [
            {
                "date": day,
                "underlying": s[0],
                "root": f"1{s[0]}",
                "expiry": EXPIRY,
                "strike": s[1],
                "right": s[2],
                "open_interest": s[3],
                "netted_oi": s[4],
                "in_domain": s[5],
                "gamma": s[6],
                "spot": s[7],
                "iv": s[8],
            }
            for s in specs
        ]
    )


def dg(gamma, oi, spot):
    return gamma * oi * 100 * spot**2 * 0.01


class TestCarriedGamma:
    def test_prices_todays_open_interest_with_yesterdays_gamma_and_spot(self):
        before = rows(T0, [("AAA", 100.0, "C", 5, 5, True, 0.03, 98.0, 0.3)])
        today = rows(T1, [("AAA", 100.0, "C", 8, 6, True, 0.05, 104.0, 0.2)])
        found = carried_gamma(before, today, T1).set_index("underlying").loc["AAA"]
        assert found["date"] == T1
        assert found["g_net"] == pytest.approx(dg(0.03, 6, 98.0))
        assert found["coverage"] == pytest.approx(1.0)

    def test_a_series_new_today_or_unpriced_before_is_unpriced(self):
        before = rows(
            T0,
            [
                ("AAA", 100.0, "C", 5, 5, True, 0.03, 98.0, 0.3),
                ("AAA", 110.0, "C", 5, 5, False, np.nan, 98.0, np.nan),
            ],
        )
        today = rows(
            T1,
            [
                ("AAA", 100.0, "C", 10, 10, True, 0.05, 104.0, 0.2),
                ("AAA", 110.0, "C", 10, 10, True, 0.05, 104.0, 0.2),
                ("AAA", 120.0, "C", 20, 20, True, 0.05, 104.0, 0.2),
            ],
        )
        found = carried_gamma(before, today, T1).set_index("underlying").loc["AAA"]
        assert found["g_net"] == pytest.approx(dg(0.03, 10, 98.0))
        assert found["coverage"] == pytest.approx(10 / 40)

    def test_output_can_be_dated_by_the_pricing_date(self):
        before = rows(T0, [("AAA", 100.0, "C", 5, 5, True, 0.03, 98.0, 0.3)])
        later = rows(T2, [("AAA", 100.0, "C", 9, 9, True, 0.05, 104.0, 0.2)])
        found = carried_gamma(before, later, T0)
        assert list(found["date"]) == [T0]
        assert found["g_net"].iloc[0] == pytest.approx(dg(0.03, 9, 98.0))


def test_open_interest_weighted_iv_over_priced_series():
    today = rows(
        T1,
        [
            ("AAA", 100.0, "C", 30, 30, True, 0.05, 100.0, 0.2),
            ("AAA", 110.0, "C", 10, 10, True, 0.05, 100.0, 0.6),
            ("AAA", 120.0, "C", 50, 50, False, np.nan, 100.0, 2.0),
        ],
    )
    found = oi_weighted_iv(today).set_index("underlying").loc["AAA"]
    assert found["iv_oi"] == pytest.approx((30 * 0.2 + 10 * 0.6) / 40)


def bars(symbol, closes, volume=1000.0, start="2026-08-03"):
    days = pd.bdate_range(start, periods=len(closes))
    stamps = [d.tz_localize("America/New_York") + pd.Timedelta(hours=9.5) for d in days]
    return pd.DataFrame({"symbol": symbol, "timestamp": stamps, "close": closes, "volume": volume})


class TestTimingPredictors:
    def daily(self, day, **values):
        base = {
            "date": day,
            "underlying": "AAA",
            "g_net_pre": 2.0e6,
            "coverage_pre": 1.0,
            "g_net_lead_fixed": 3.0e6,
            "coverage_lead_fixed": 1.0,
            "iv_oi": 0.25,
        }
        return pd.DataFrame([{**base, **values}])

    def test_pre_is_scaled_by_volume_ending_the_session_before(self):
        closes = np.r_[np.full(21, 100.0), 200.0]  # the 22nd session doubles dollar volume
        frame = bars("AAA", closes)
        day = pd.bdate_range("2026-08-03", periods=22)[-1]
        found = timing_predictors(
            self.daily(day), frame, pd.DataFrame(columns=["symbol", "session", "ratio"])
        )
        row = found.set_index("date").loc[day]
        assert row["x_pre_raw"] == pytest.approx(2.0e6 / (100.0 * 1000.0))
        adv_today = (19 * 100.0 + 200.0) * 1000.0 / 20
        assert row["x_lead_fixed_raw"] == pytest.approx(3.0e6 / adv_today)
        assert row["log_iv"] == pytest.approx(np.log(0.25))

    def test_low_coverage_is_missing(self):
        frame = bars("AAA", np.full(22, 100.0))
        day = pd.bdate_range("2026-08-03", periods=22)[-1]
        daily = self.daily(day, coverage_pre=0.4, coverage_lead_fixed=0.3)
        found = timing_predictors(
            daily, frame, pd.DataFrame(columns=["symbol", "session", "ratio"])
        )
        assert found["x_pre_raw"].isna().all()
        assert found["x_lead_fixed_raw"].isna().all()

    def test_a_split_between_pricing_and_holding_dates_drops_the_row(self):
        frame = bars("AAA", np.full(30, 100.0))
        days = pd.bdate_range("2026-08-03", periods=30)
        day = days[25]
        splits = pd.DataFrame(
            {"symbol": ["AAA", "AAA"], "session": [day, days[28]], "ratio": [2.0, 3.0]}
        )
        found = timing_predictors(self.daily(day), frame, splits).set_index("date").loc[day]
        # A split on T separates T-1's pricing from T's open interest.
        assert np.isnan(found["x_pre_raw"])
        # The split on T is not between T and T+2; the next one, three sessions on, is not either.
        assert not np.isnan(found["x_lead_fixed_raw"])
        later = (
            timing_predictors(self.daily(days[27]), frame, splits).set_index("date").loc[days[27]]
        )
        assert np.isnan(later["x_lead_fixed_raw"])
        assert not np.isnan(later["x_pre_raw"])


def test_timing_daily_dates_each_row_as_specified():
    from hidden_options.predict.gamma_timing import timing_daily

    day = {
        T0: rows(T0, [("AAA", 100.0, "C", 5, 5, True, 0.01, 90.0, 0.3)]),
        T1: rows(T1, [("AAA", 100.0, "C", 6, 6, True, 0.02, 95.0, 0.4)]),
        T2: rows(T2, [("AAA", 100.0, "C", 7, 7, True, 0.03, 99.0, 0.5)]),
    }
    found = timing_daily([T0, T1, T2], day.__getitem__).set_index("date")
    # R1 at T1: T1's open interest at T0's pricing.
    assert found.loc[T1, "g_net_pre"] == pytest.approx(dg(0.01, 6, 90.0))
    assert np.isnan(found.loc[T0, "g_net_pre"])
    # R4 at T0: T2's open interest at T0's pricing; none for the last two dates.
    assert found.loc[T0, "g_net_lead_fixed"] == pytest.approx(dg(0.01, 7, 90.0))
    assert np.isnan(found.loc[T1, "g_net_lead_fixed"])
    assert found.loc[T2, "iv_oi"] == pytest.approx(0.5)
