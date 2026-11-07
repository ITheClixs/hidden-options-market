"""Tests for hidden gamma: dollar gamma, the listed surface read at FLEX strikes, the
pair-netting rule and the shares (docs/log/2026-11-07-hidden-gamma-spec.md)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.hidden_gamma import (
    dollar_gamma,
    flex_gamma,
    gamma_shares,
    listed_gamma,
    pair_netted,
    surface_points,
    surface_vol,
)
from hidden_options.measure.pricing import black_scholes_greeks

DAY = pd.Timestamp("2026-09-01")
RATE = 0.04


def bs_gamma(spot, strike, days, sigma):
    greeks = black_scholes_greeks(
        spot, strike, days / 365.0, sigma, rate=RATE, carry=0.0, is_call=True
    )
    return float(np.asarray(greeks.gamma).item())


def chain(rows, spot=100.0, date=DAY, symbol="XYZ"):
    """rows: (days, right, strike, iv[, open_interest])"""
    return pd.DataFrame(
        [
            {
                "date": date,
                "symbol": symbol,
                "root": symbol,
                "expiry": date + pd.Timedelta(days=row[0]),
                "right": row[1],
                "strike": float(row[2]),
                "iv": row[3],
                "open_interest": row[4] if len(row) > 4 else 0.0,
                "underlying_price": spot,
            }
            for row in rows
        ]
    )


def flex(rows, date=DAY, symbol="XYZ", root="1XYZ"):
    """rows: (days, right, strike, open_interest)"""
    return pd.DataFrame(
        [
            {
                "date": date,
                "symbol": symbol,
                "root": root,
                "expiry": date + pd.Timedelta(days=row[0]),
                "right": row[1],
                "strike": float(row[2]),
                "open_interest": row[3],
            }
            for row in rows
        ]
    )


class TestDollarGamma:
    def test_is_the_dollar_delta_change_for_a_one_percent_move(self):
        # gamma 0.02 per share, 10 contracts, spot 100: 0.02 * 10 * 100 * 100**2 * 0.01 = 2000
        assert dollar_gamma(0.02, 10, 100.0) == pytest.approx(2000.0)

    def test_scales_with_the_square_of_spot(self):
        assert dollar_gamma(0.01, 1, 200.0) == pytest.approx(4 * dollar_gamma(0.01, 1, 100.0))

    def test_gamma_matches_a_finite_difference_of_delta(self):
        bump = 1e-3
        up = black_scholes_greeks(100 + bump, 105, 0.25, 0.3, rate=RATE, carry=0, is_call=True)
        down = black_scholes_greeks(100 - bump, 105, 0.25, 0.3, rate=RATE, carry=0, is_call=True)
        numeric = (np.asarray(up.delta).item() - np.asarray(down.delta).item()) / (2 * bump)
        assert bs_gamma(100, 105, 0.25 * 365, 0.3) == pytest.approx(numeric, rel=1e-5)


class TestSurfacePoints:
    def test_keeps_out_of_the_money_quotes_only(self):
        rows = chain(
            [
                (30, "C", 110, 0.25),  # OTM call: kept
                (30, "P", 90, 0.35),  # OTM put: kept
                (30, "C", 90, 9.0),  # ITM call: dropped
                (30, "P", 110, 9.0),  # ITM put: dropped
            ]
        )
        points = surface_points(rows)
        assert sorted(points["strike"]) == [90.0, 110.0]
        assert points["iv"].max() < 1.0

    def test_drops_missing_and_absurd_volatilities(self):
        rows = chain([(30, "C", 110, 0.0), (30, "C", 120, np.nan), (30, "C", 130, 7.0)])
        assert surface_points(rows).empty


class TestSurfaceVol:
    def test_a_flat_surface_reads_flat_everywhere(self):
        points = surface_points(
            chain(
                [(d, "C", k, 0.3) for d in (30, 90) for k in (105, 110, 120)]
                + [(d, "P", k, 0.3) for d in (30, 90) for k in (80, 90, 95)]
            )
        )
        sigma, interior = surface_vol(
            points, 100.0, DAY, flex([(60, "C", 100, 1), (400, "P", 50, 1)])
        )
        assert sigma == pytest.approx([0.3, 0.3])
        assert list(interior) == [True, False]

    def test_linear_in_log_moneyness_within_an_expiry(self):
        points = surface_points(chain([(30, "P", 90, 0.2), (30, "C", 110, 0.4)]))
        sigma, _ = surface_vol(points, 100.0, DAY, flex([(30, "C", 100, 1)]))
        weight = -math.log(0.9) / (math.log(1.1) - math.log(0.9))
        assert sigma[0] == pytest.approx(0.2 + 0.2 * weight)

    def test_flat_beyond_the_outermost_strikes(self):
        points = surface_points(chain([(30, "P", 90, 0.2), (30, "C", 110, 0.4)]))
        sigma, interior = surface_vol(
            points, 100.0, DAY, flex([(30, "C", 200, 1), (30, "P", 10, 1)])
        )
        assert sigma == pytest.approx([0.4, 0.2])
        assert not interior.any()

    def test_linear_in_total_variance_between_expiries(self):
        points = surface_points(
            chain(
                [(30, "P", 90, 0.2), (30, "C", 110, 0.2), (90, "P", 90, 0.3), (90, "C", 110, 0.3)]
            )
        )
        sigma, interior = surface_vol(points, 100.0, DAY, flex([(60, "C", 100, 1)]))
        w30, w90 = 0.2**2 * 30 / 365, 0.3**2 * 90 / 365
        expected = math.sqrt((w30 + (w90 - w30) * 0.5) / (60 / 365))
        assert sigma[0] == pytest.approx(expected)
        assert interior[0]

    def test_flat_in_sigma_before_the_first_and_after_the_last_expiry(self):
        points = surface_points(
            chain(
                [(30, "P", 90, 0.2), (30, "C", 110, 0.2), (90, "P", 90, 0.3), (90, "C", 110, 0.3)]
            )
        )
        sigma, interior = surface_vol(
            points, 100.0, DAY, flex([(5, "C", 100, 1), (500, "C", 100, 1)])
        )
        assert sigma == pytest.approx([0.2, 0.3])
        assert not interior.any()

    def test_no_surface_gives_missing(self):
        sigma, interior = surface_vol(
            surface_points(chain([])), 100.0, DAY, flex([(30, "C", 100, 1)])
        )
        assert np.isnan(sigma[0])
        assert not interior[0]


class TestPairNetted:
    def test_a_conversion_nets_to_nothing(self):
        netted = pair_netted(flex([(30, "C", 100, 10), (30, "P", 100, 10)]))
        assert list(netted["netted_oi"]) == [0, 0]

    def test_the_excess_of_one_right_survives_on_that_right(self):
        netted = pair_netted(flex([(30, "C", 100, 10), (30, "P", 100, 4)]))
        assert dict(zip(netted["right"], netted["netted_oi"], strict=True)) == {"C": 6, "P": 0}

    def test_lines_pair_only_within_root_expiry_and_strike(self):
        netted = pair_netted(flex([(30, "C", 100, 10), (30, "P", 105, 10), (60, "P", 100, 10)]))
        assert list(netted["netted_oi"]) == [10, 10, 10]

    def test_does_not_change_its_input(self):
        rows = flex([(30, "C", 100, 10), (30, "P", 100, 10)])
        before = rows.copy()
        pair_netted(rows)
        pd.testing.assert_frame_equal(rows, before)


class TestListedGamma:
    def test_computes_gamma_from_implied_volatility_not_the_rounded_column(self):
        rows = chain([(30, "C", 105, 0.3, 50), (30, "P", 95, 0.3, 20)])
        rows["gamma"] = 0.0  # what a rounded chain column shows for index options
        found = listed_gamma(rows, rate=RATE)
        expected = dollar_gamma(bs_gamma(100, 105, 30, 0.3), 50, 100.0) + dollar_gamma(
            bs_gamma(100, 95, 30, 0.3), 20, 100.0
        )
        assert found.loc[0, "listed_gross"] == pytest.approx(expected)

    def test_signed_view_counts_calls_up_and_puts_down(self):
        rows = chain([(30, "C", 105, 0.3, 50), (30, "P", 95, 0.3, 20)])
        found = listed_gamma(rows, rate=RATE)
        expected = dollar_gamma(bs_gamma(100, 105, 30, 0.3), 50, 100.0) - dollar_gamma(
            bs_gamma(100, 95, 30, 0.3), 20, 100.0
        )
        assert found.loc[0, "listed_signed"] == pytest.approx(expected)

    def test_listed_pairs_net_the_same_way_as_flex(self):
        # A listed conversion at 100 nets out; the lone call at 105 stays.
        rows = chain([(30, "C", 100, 0.3, 40), (30, "P", 100, 0.3, 40), (30, "C", 105, 0.3, 10)])
        found = listed_gamma(rows, rate=RATE)
        assert found.loc[0, "listed_netted"] == pytest.approx(
            dollar_gamma(bs_gamma(100, 105, 30, 0.3), 10, 100.0)
        )
        assert found.loc[0, "listed_gross"] > found.loc[0, "listed_netted"]

    def test_series_expiring_on_the_date_are_out(self):
        rows = chain([(0, "C", 105, 0.3, 50), (30, "C", 105, 0.3, 50)])
        alone = chain([(30, "C", 105, 0.3, 50)])
        assert listed_gamma(rows, rate=RATE).loc[0, "listed_gross"] == pytest.approx(
            listed_gamma(alone, rate=RATE).loc[0, "listed_gross"]
        )

    def test_one_row_per_symbol_and_date(self):
        rows = pd.concat(
            [chain([(30, "C", 105, 0.3, 5)]), chain([(30, "C", 105, 0.3, 5)], symbol="ABC")]
        )
        found = listed_gamma(rows, rate=RATE)
        assert sorted(found["symbol"]) == ["ABC", "XYZ"]


class TestFlexGamma:
    def surface(self):
        return chain([(d, r, k, 0.3) for d in (30, 90) for r, k in (("P", 90), ("C", 110))])

    def test_gross_and_pair_netted_dollar_gamma(self):
        series = flex([(30, "C", 100, 10), (30, "P", 100, 4)])
        found = flex_gamma(series, self.surface(), rate=RATE)
        one = dollar_gamma(bs_gamma(100, 100, 30, 0.3), 1, 100.0)
        assert found["gross"].sum() == pytest.approx(14 * one)
        assert found["netted"].sum() == pytest.approx(6 * one)

    def test_expired_series_and_series_without_a_surface_are_out(self):
        series = pd.concat(
            [
                flex([(0, "C", 100, 10), (30, "C", 100, 10)]),
                flex([(30, "C", 100, 10)], symbol="NOPE"),
            ]
        )
        found = flex_gamma(series, self.surface(), rate=RATE)
        assert len(found) == 1
        assert found["symbol"].iloc[0] == "XYZ"

    def test_records_where_sigma_came_from(self):
        series = flex([(60, "C", 100, 10), (700, "C", 100, 10)])
        found = flex_gamma(series, self.surface(), rate=RATE)
        assert list(found["interior"]) == [True, False]


class TestGammaShares:
    def test_share_of_the_total_under_each_rule(self):
        listed = pd.DataFrame(
            {
                "date": [DAY],
                "symbol": ["XYZ"],
                "listed_gross": [300.0],
                "listed_netted": [200.0],
                "listed_signed": [100.0],
            }
        )
        flex_rows = pd.DataFrame(
            {
                "date": [DAY, DAY],
                "symbol": ["XYZ", "XYZ"],
                "gross": [80.0, 20.0],
                "netted": [20.0, 5.0],
                "signed": [80.0, -20.0],
                "interior": [True, False],
                "open_interest": [8, 2],
            }
        )
        found = gamma_shares(listed, flex_rows)
        row = found.iloc[0]
        assert row["share_gross"] == pytest.approx(100 / 400)
        assert row["share_netted"] == pytest.approx(25 / 325)
        assert row["share_netted_both"] == pytest.approx(25 / 225)
        assert row["interior_oi_share"] == pytest.approx(0.8)

    def test_an_underlying_with_no_flex_has_zero_share(self):
        listed = pd.DataFrame(
            {
                "date": [DAY],
                "symbol": ["XYZ"],
                "listed_gross": [300.0],
                "listed_netted": [200.0],
                "listed_signed": [100.0],
            }
        )
        empty = pd.DataFrame(
            columns=["date", "symbol", "gross", "netted", "signed", "interior", "open_interest"]
        )
        found = gamma_shares(listed, empty)
        assert found.loc[0, "share_gross"] == 0.0
        assert found.loc[0, "share_netted"] == 0.0
