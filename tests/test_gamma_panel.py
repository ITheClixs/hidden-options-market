"""Tests for the gamma-based predictive panel (docs/log/2026-11-08-gamma-predictive-spec.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.predict.gamma_panel import (
    COVERAGE_MIN,
    LEAD,
    aggregate_gamma,
    gamma_predictors,
    range_outcome,
    standardise,
)

DAY = pd.Timestamp("2026-09-01")


def priced(rows):
    """rows: (underlying, root, right, strike, oi, netted_oi, in_domain, gamma, spot)"""
    return pd.DataFrame(
        [
            {
                "date": DAY,
                "underlying": r[0],
                "root": r[1],
                "right": r[2],
                "expiry": pd.Timestamp("2026-10-16"),
                "strike": r[3],
                "open_interest": r[4],
                "netted_oi": r[5],
                "in_domain": r[6],
                "gamma": r[7],
                "spot": r[8],
            }
            for r in rows
        ]
    )


def dg(gamma, oi, spot):
    return gamma * oi * 100 * spot**2 * 0.01


class TestAggregateGamma:
    def test_sums_dollar_gamma_per_underlying_on_validated_rows(self):
        rows = priced(
            [
                ("AAA", "1AAA", "C", 100, 10, 6, True, 0.02, 100.0),
                ("AAA", "1AAA", "P", 100, 4, 0, True, 0.02, 100.0),
                ("AAA", "1AAA", "C", 150, 30, 30, False, np.nan, 100.0),
            ]
        )
        found = aggregate_gamma(rows).set_index("underlying").loc["AAA"]
        assert found["g_gross"] == pytest.approx(dg(0.02, 14, 100))
        assert found["g_net"] == pytest.approx(dg(0.02, 6, 100))
        assert found["g_signed"] == pytest.approx(dg(0.02, 10, 100) - dg(0.02, 4, 100))
        assert found["coverage"] == pytest.approx(14 / 44)
        assert found["flex_oi"] == 44

    def test_an_underlying_with_nothing_validated_has_zero_gamma_and_zero_coverage(self):
        rows = priced([("BBB", "1BBB", "C", 100, 10, 10, False, np.nan, 50.0)])
        found = aggregate_gamma(rows).set_index("underlying").loc["BBB"]
        assert found["g_net"] == 0.0
        assert found["coverage"] == 0.0


def bars(symbol, closes, volumes, start="2026-08-03", highs=None, lows=None):
    days = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": [
                d.tz_localize("America/New_York") + pd.Timedelta(hours=9.5) for d in days
            ],
            "open": closes,
            "high": highs if highs is not None else [c * 1.01 for c in closes],
            "low": lows if lows is not None else [c * 0.99 for c in closes],
            "close": closes,
            "volume": volumes,
        }
    )


class TestGammaPredictors:
    def daily(self, days, g_net, coverage=1.0):
        return pd.DataFrame(
            {
                "date": days,
                "underlying": "AAA",
                "g_net": g_net,
                "g_gross": [2 * g for g in g_net],
                "g_signed": [-g for g in g_net],
                "coverage": coverage,
                "flex_oi": 100,
            }
        )

    def test_scaled_by_twenty_session_dollar_volume_ending_on_the_date(self):
        b = bars("AAA", [10.0] * 25, [1000.0] * 25)
        days = pd.bdate_range("2026-08-03", periods=25)
        found = gamma_predictors(self.daily(days, [500.0] * 25), b)
        row = found.set_index("date").loc[days[21]]
        assert row["x_net_raw"] == pytest.approx(500.0 / (10.0 * 1000.0))
        assert row["x_gross_raw"] == pytest.approx(1000.0 / 10000.0)
        assert row["x_signed_raw"] == pytest.approx(-500.0 / 10000.0)
        # Fewer than twenty sessions of volume: no ADV, no predictor.
        assert np.isnan(found.set_index("date").loc[days[5], "x_net_raw"])

    def test_low_coverage_is_missing_not_zero(self):
        b = bars("AAA", [10.0] * 25, [1000.0] * 25)
        days = pd.bdate_range("2026-08-03", periods=25)
        found = gamma_predictors(self.daily(days, [500.0] * 25, coverage=COVERAGE_MIN - 0.01), b)
        assert found["x_net_raw"].isna().all()

    def test_lead_is_the_predictor_two_report_dates_later(self):
        b = bars("AAA", [10.0] * 30, [1000.0] * 30)
        days = pd.bdate_range("2026-08-03", periods=30)
        found = gamma_predictors(self.daily(days, [float(i) for i in range(30)]), b).set_index(
            "date"
        )
        assert found.loc[days[22], "x_net_lead_raw"] == pytest.approx(
            found.loc[days[22 + LEAD], "x_net_raw"]
        )


class TestStandardise:
    def test_winsorised_then_scaled_to_unit_deviation(self):
        values = pd.Series(np.r_[np.arange(998, dtype=float), 1e6, -1e6])
        found = standardise(values)
        assert found.std(ddof=1) == pytest.approx(1.0)
        # The two outliers are pulled in to the 1st and 99th percentiles of the rest.
        assert found.max() == pytest.approx(found.iloc[:998].max())
        assert found.iloc[998] == pytest.approx(found.max())
        assert found.iloc[999] == pytest.approx(found.min())

    def test_missing_stays_missing(self):
        found = standardise(pd.Series([1.0, 2.0, np.nan, 4.0]))
        assert np.isnan(found.iloc[2])


class TestRangeOutcome:
    def test_log_high_over_low_of_each_session(self):
        b = bars("AAA", [10.0, 11.0], [1.0, 1.0], highs=[11.0, 12.0], lows=[9.0, 10.0])
        found = range_outcome(b).set_index("session")
        assert found["log_range"].iloc[0] == pytest.approx(np.log(11 / 9))
        assert found["log_range"].iloc[1] == pytest.approx(np.log(12 / 10))
