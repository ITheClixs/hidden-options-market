"""Series against positions: legs from the report, payoffs, and the three notionals."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.positions import (
    butterfly_triples,
    chance_structured_share,
    legs_from_panel,
    locate_butterfly,
    locate_collar,
    max_value,
    notional_measures,
    payoff,
    per_underlying_ratios,
    structure_shares,
)
from hidden_options.measure.structures import group_legs

DAY = pd.Timestamp("2026-08-17")
EXPIRY = pd.Timestamp("2026-09-30")


def _panel(rows, day=DAY):
    """rows: (underlying, right, strike, mark, open interest)"""
    frame = pd.DataFrame(rows, columns=["underlying", "right", "strike", "mark_price", "oi"])
    return frame.rename(columns={"oi": "open_interest"}).assign(
        report_date=day, root="4" + frame["underlying"], expiry=EXPIRY, kind="equity"
    )


def _greeks(panel, delta):
    """`delta`: per-row contract delta. Gross dollars at the row's spot, as in `greeks_frame`."""
    spot = panel["spot"].to_numpy(dtype=float)
    dollars = np.asarray(delta, dtype=float) * panel["open_interest"].to_numpy() * 100 * spot
    return panel.assign(delta_dollars=dollars)


class TestLegsFromPanel:
    def test_contracts_are_the_open_interest(self):
        panel = _panel([("AAA", "C", 50.0, 1.0, 1200)])
        legs = legs_from_panel(panel)
        assert legs["contracts"].iloc[0] == 1200
        for column in ("underlying", "expiry", "right", "strike", "contracts", "root"):
            assert column in legs.columns

    def test_series_with_no_open_interest_are_not_legs(self):
        panel = _panel([("AAA", "C", 50.0, 1.0, 0), ("AAA", "P", 50.0, 1.0, 10)])
        assert list(legs_from_panel(panel)["right"]) == ["P"]


BUTTERFLY = pd.DataFrame(
    {
        "right": ["C", "C", "C"],
        "strike": [510.0, 550.0, 590.0],
        "contracts": [100000.0, -200000.0, 100000.0],
    }
)


class TestPayoff:
    def test_butterfly_max_value_is_wing_times_spacing(self):
        assert max_value(BUTTERFLY) == pytest.approx(100000 * 100 * 40.0)

    def test_payoff_is_zero_outside_the_wings_and_peaks_at_the_body(self):
        values = payoff(BUTTERFLY, np.array([400.0, 510.0, 550.0, 590.0, 700.0]))
        assert values == pytest.approx([0.0, 0.0, 4e8, 0.0, 0.0])

    def test_an_uncapped_position_has_no_maximum(self):
        long_call = pd.DataFrame({"right": ["C"], "strike": [100.0], "contracts": [1.0]})
        assert math.isinf(max_value(long_call))

    def test_a_long_put_peaks_at_a_price_of_zero(self):
        put = pd.DataFrame({"right": ["P"], "strike": [100.0], "contracts": [2.0]})
        assert max_value(put) == pytest.approx(2 * 100 * 100.0)

    def test_the_buffer_collar_is_capped_near_contracts_times_spot(self):
        collar = pd.DataFrame(
            {
                "right": ["C", "C", "P", "P"],
                "strike": [1.87, 765.66, 746.77, 597.42],
                "contracts": [37507.0, -37507.0, 38317.0, -37540.0],
            }
        )
        assert 2.5e9 < max_value(collar) < 3.2e9


class TestNotionalMeasures:
    SPOTS = {"SPY": 765.0}

    def _measures(self, rows, delta, spots=None):
        spots = self.SPOTS if spots is None else spots
        panel = _panel(rows)
        panel = panel.assign(spot=panel["underlying"].map(spots).astype(float))
        legs, _ = group_legs(legs_from_panel(panel), spots)
        return notional_measures(panel, _greeks(panel, delta), legs, spots)

    def test_deep_itm_call_exposure_dwarfs_strike_notional(self):
        out = self._measures([("SPY", "C", 1.87, 763.1, 37507)], [1.0]).set_index("underlying")
        row = out.loc["SPY"]
        assert row["strike_notional"] == pytest.approx(1.87 * 37507 * 100)
        assert row["delta_exposure"] == pytest.approx(37507 * 100 * 765.0)
        assert row["delta_exposure"] / row["strike_notional"] > 300

    def test_strike_notional_and_mark_value_sum_over_the_series(self):
        out = self._measures(
            [("SPY", "C", 700.0, 70.0, 100), ("SPY", "P", 600.0, 1.0, 200)], [0.9, -0.1]
        ).iloc[0]
        assert out["strike_notional"] == pytest.approx((700 * 100 + 600 * 200) * 100)
        assert out["mark_value"] == pytest.approx((70 * 100 + 1 * 200) * 100)

    def test_delta_nets_within_a_structure_and_sums_across_the_rest(self):
        # A structure of 1000 x (0.6 - 0.2) deltas, and a lone leg of 700 x -0.5.
        out = self._measures(
            [
                ("SPY", "C", 700.0, 1.0, 1000),
                ("SPY", "P", 700.0, 1.0, 1000),
                ("SPY", "P", 650.0, 1.0, 700),
            ],
            [0.6, -0.2, -0.5],
        ).iloc[0]
        net = abs(0.6 - 0.2) * 1000 * 100 * 765 + 0.5 * 700 * 100 * 765
        gross = (0.6 + 0.2) * 1000 * 100 * 765 + 0.5 * 700 * 100 * 765
        assert out["delta_exposure"] == pytest.approx(net)
        assert out["gross_delta"] == pytest.approx(gross)

    def test_structured_share_is_of_open_interest(self):
        out = self._measures(
            [
                ("SPY", "C", 700.0, 1.0, 1000),
                ("SPY", "P", 700.0, 1.0, 1000),
                ("SPY", "P", 650.0, 1.0, 2000),
            ],
            [0.5, -0.5, -0.2],
        ).iloc[0]
        assert out["structured_oi_share"] == pytest.approx(0.5)

    def test_a_structure_with_an_unpriced_leg_is_left_out_whole(self):
        out = self._measures(
            [
                ("SPY", "C", 700.0, 1.0, 1000),
                ("SPY", "P", 700.0, 1.0, 1000),
                ("SPY", "P", 650.0, 1.0, 300),
            ],
            [0.6, np.nan, -0.5],
        ).iloc[0]
        assert out["delta_exposure"] == pytest.approx(0.5 * 300 * 100 * 765)
        assert out["strike_notional_priced"] == pytest.approx(650 * 300 * 100)
        assert out["covered_oi_share"] == pytest.approx(300 / 2300)
        assert out["strike_notional"] == pytest.approx((700 * 2000 + 650 * 300) * 100)

    def test_an_underlying_with_no_priced_legs_has_no_exposure(self):
        out = self._measures([("ZZZ", "C", 10.0, 1.0, 1000)], [np.nan], spots={}).iloc[0]
        assert np.isnan(out["delta_exposure"])
        assert out["covered_oi_share"] == 0.0

    def test_one_row_per_underlying(self):
        spots = {"SPY": 765.0, "MSFT": 500.0}
        out = self._measures(
            [("SPY", "C", 700.0, 1.0, 100), ("MSFT", "C", 400.0, 1.0, 100)], [0.5, 0.9], spots
        )
        assert sorted(out["underlying"]) == ["MSFT", "SPY"]


class TestRatios:
    def _daily(self, rows):
        frame = pd.DataFrame(
            rows, columns=["report_date", "underlying", "strike_notional_priced", "delta_exposure"]
        )
        return frame.assign(gross_delta=frame["delta_exposure"])

    def test_each_underlying_gets_its_median_ratio_across_dates(self):
        out = per_underlying_ratios(
            self._daily(
                [
                    (DAY, "AAA", 100.0, 10.0),
                    (DAY + pd.Timedelta(days=1), "AAA", 300.0, 10.0),
                    (DAY, "BBB", 1.0, 10.0),
                ]
            )
        ).set_index("underlying")
        assert out.loc["AAA", "ratio"] == pytest.approx(20.0)
        assert out.loc["BBB", "ratio"] == pytest.approx(0.1)

    def test_an_underlying_with_no_exposure_is_left_out(self):
        out = per_underlying_ratios(self._daily([(DAY, "AAA", 100.0, np.nan), (DAY, "BBB", 1, 2)]))
        assert list(out["underlying"]) == ["BBB"]


class TestStructureShares:
    def test_share_of_structured_open_interest_by_type(self):
        legs = pd.DataFrame(
            {
                "structure_id": [0, 0, 1, 1, -1],
                "structure": ["synthetic", "synthetic", "vertical_spread", "vertical_spread", None],
                "contracts": [300, 300, 200, 200, 1000],
            }
        )
        shares = structure_shares(legs)
        assert shares["structured"] == pytest.approx(1000 / 2000)
        assert shares["by_type"]["synthetic"] == pytest.approx(0.6)
        assert shares["by_type"]["vertical_spread"] == pytest.approx(0.4)


class TestChance:
    def test_shuffling_counts_between_expiries_breaks_pairs(self):
        rng = np.random.default_rng(0)
        expiries = pd.date_range("2026-09-01", periods=40, freq="W")
        sizes = rng.integers(1000, 10**6, size=40)
        rows = [
            {
                "underlying": "AAA",
                "expiry": expiry,
                "right": right,
                "strike": 50.0,
                "contracts": int(size),
            }
            for expiry, size in zip(expiries, sizes, strict=True)
            for right in ("C", "P")
        ]
        legs = pd.DataFrame(rows)
        grouped, _ = group_legs(legs, {"AAA": 50.0})
        assert (grouped["structure_id"] >= 0).all()
        assert chance_structured_share(legs, seed=1) < 0.5

    def test_the_draw_is_reproducible(self):
        legs = pd.DataFrame(
            {
                "underlying": ["AAA"] * 6,
                "expiry": list(pd.date_range("2026-09-01", periods=3, freq="W")) * 2,
                "right": ["C"] * 3 + ["P"] * 3,
                "strike": [50.0] * 6,
                "contracts": [1000, 2000, 3000, 1000, 2000, 3000],
            }
        )
        assert chance_structured_share(legs, seed=3) == chance_structured_share(legs, seed=3)


class TestWorkedCases:
    def test_butterfly_triples_find_one_two_one_at_equal_spacing(self):
        rows = _panel(
            [
                ("MSFT", "C", 510.0, 1.0, 100000),
                ("MSFT", "C", 550.0, 1.0, 200000),
                ("MSFT", "C", 590.0, 1.0, 100000),
                ("MSFT", "C", 700.0, 1.0, 100000),
                ("MSFT", "P", 550.0, 1.0, 100000),
            ]
        )
        triples = butterfly_triples(rows)
        assert len(triples) == 1
        assert list(triples.iloc[0][["low", "middle", "high"]]) == [510.0, 550.0, 590.0]

    def test_an_unevenly_spaced_triple_is_not_a_butterfly(self):
        rows = _panel(
            [
                ("MSFT", "C", 510.0, 1.0, 100000),
                ("MSFT", "C", 550.0, 1.0, 200000),
                ("MSFT", "C", 620.0, 1.0, 100000),
            ]
        )
        assert butterfly_triples(rows).empty

    def _nine_lines(self, day):
        rows = []
        for expiry in ("2026-11-20", "2026-12-17", "2027-01-14"):
            rows.extend(
                {
                    "report_date": day,
                    "underlying": "MSFT",
                    "root": "1MSFT",
                    "right": "C",
                    "expiry": pd.Timestamp(expiry),
                    "strike": strike,
                    "mark_price": 1.0,
                    "open_interest": oi,
                }
                for strike, oi in ((510.0, 100000), (550.0, 200000), (590.0, 100000))
            )
        return pd.DataFrame(rows)

    def test_the_butterfly_is_located_on_the_last_date_all_expiries_show_it(self):
        early, late = self._nine_lines(DAY), self._nine_lines(DAY + pd.Timedelta(days=1))
        later = late[late["expiry"] != pd.Timestamp("2027-01-14")].assign(
            report_date=DAY + pd.Timedelta(days=2)
        )
        case = locate_butterfly(pd.concat([early, late, later]), "MSFT", min_wing=50000)
        assert case["report_date"] == DAY + pd.Timedelta(days=1)
        assert case["lines"] == 9
        assert case["strike_notional"] == pytest.approx(3 * (510 + 2 * 550 + 590) * 100000 * 100)
        assert case["max_value"] == pytest.approx(3 * 40 * 100000 * 100)
        assert case["overstatement"] == pytest.approx(case["strike_notional"] / case["max_value"])

    def test_no_such_butterfly_gives_none(self):
        assert locate_butterfly(self._nine_lines(DAY), "AAPL", min_wing=50000) is None

    def _collar(self, day, size):
        strikes = (("C", 1.87), ("C", 765.66), ("P", 746.77), ("P", 597.42))
        return pd.DataFrame(
            [
                {
                    "report_date": day,
                    "underlying": "SPY",
                    "root": "4SPY",
                    "right": right,
                    "expiry": EXPIRY,
                    "strike": strike,
                    "mark_price": 1.0,
                    "open_interest": size,
                }
                for right, strike in strikes
            ]
        )

    def test_the_collar_is_located_where_its_deep_call_is_nearest_the_described_size(self):
        rows = pd.concat(
            [self._collar(DAY, 30000), self._collar(DAY + pd.Timedelta(days=1), 37400)]
        )
        case = locate_collar(rows, "SPY", deep_strike=1.87, size=37500)
        assert case["report_date"] == DAY + pd.Timedelta(days=1)
        assert case["expiry"] == EXPIRY
        assert len(case["legs"]) == 4

    def test_no_such_collar_gives_none(self):
        assert locate_collar(self._collar(DAY, 100), "QQQ", deep_strike=1.87, size=37500) is None
