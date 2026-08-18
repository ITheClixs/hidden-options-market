"""Tests for leg grouping and exposure valuation.

Every case here is drawn from a real position that the previous, per-series approach
got wrong. The point of the module is that a structure is counted once and valued on
the underlying, so those are the two properties tested hardest.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from absorb.measure.structures import GroupingConfig, group_structures

EXPIRY = date(2026, 9, 30)
SPOT = {"SPY": 765.0, "MSFT": 495.25, "MSTR": 93.10}


def _census(rows):
    """rows: (symbol, strike, call_oi, put_oi)"""
    return pd.DataFrame(
        [
            {
                "symbol": s,
                "expiry": EXPIRY,
                "strike": k,
                "call_open_interest": c,
                "put_open_interest": p,
            }
            for s, k, c, p in rows
        ]
    )


# The real SPY buffer fund: four legs near 37,500 contracts.
BUFFER = _census(
    [
        ("SPY", 1.87, 37507, 0),
        ("SPY", 765.66, 37507, 0),
        ("SPY", 746.77, 0, 38317),
        ("SPY", 597.42, 0, 37540),
    ]
)


class TestBufferFund:
    def test_four_legs_become_one_structure(self):
        out = group_structures(BUFFER, SPOT)
        assert len(out) == 1
        assert out.iloc[0]["n_legs"] == 4

    def test_labelled_as_a_collar(self):
        assert group_structures(BUFFER, SPOT).iloc[0]["structure"] == "collar_buffer"

    def test_exposure_is_on_the_underlying_not_the_strike(self):
        """The census valued these four legs at $8.02bn. The fund is ~$2.87bn."""
        exposure = group_structures(BUFFER, SPOT).iloc[0]["exposure"]
        assert exposure == pytest.approx(37540 * 100 * 765.0, rel=0.02)
        assert 2.5e9 < exposure < 3.2e9

    def test_deep_itm_leg_is_not_valued_at_its_strike(self):
        """Strike x contracts prices the $1.87 synthetic call at $7m; it is $2.9bn."""
        out = group_structures(BUFFER, SPOT)
        naive_strike_notional = 37507 * 100 * 1.87
        assert out.iloc[0]["exposure"] > 100 * naive_strike_notional

    def test_counts_the_structure_once_not_per_leg(self):
        out = group_structures(BUFFER, SPOT)
        assert out["exposure"].sum() < 3.2e9


class TestButterfly:
    def test_one_two_one_at_equal_spacing(self):
        census = _census(
            [("MSFT", 510.01, 100000, 0), ("MSFT", 550.01, 200000, 0), ("MSFT", 590.01, 100000, 0)]
        )
        out = group_structures(census, SPOT)
        # The body is twice the wings, so it clusters separately from them.
        wings = out[out["n_legs"] == 2]
        assert len(wings) == 1
        assert wings.iloc[0]["structure"] == "vertical_spread"

    def test_equal_sized_three_leg_is_labelled_butterfly(self):
        census = _census(
            [("MSFT", 430.0, 50000, 0), ("MSFT", 470.0, 50000, 0), ("MSFT", 510.0, 50000, 0)]
        )
        assert group_structures(census, SPOT).iloc[0]["structure"] == "butterfly"


class TestSyntheticAndSpreads:
    def test_call_and_put_at_one_strike_is_a_synthetic(self):
        census = _census([("MSTR", 95.00, 45115, 0), ("MSTR", 95.01, 0, 45115)])
        assert group_structures(census, SPOT).iloc[0]["structure"] == "synthetic"

    def test_call_and_put_at_different_strikes_is_a_risk_reversal(self):
        census = _census([("MSTR", 110.0, 20000, 0), ("MSTR", 80.0, 0, 20000)])
        assert group_structures(census, SPOT).iloc[0]["structure"] == "risk_reversal"

    def test_two_calls_is_a_vertical(self):
        census = _census([("MSTR", 100.0, 20000, 0), ("MSTR", 120.0, 20000, 0)])
        assert group_structures(census, SPOT).iloc[0]["structure"] == "vertical_spread"


class TestGrouping:
    def test_differently_sized_positions_do_not_merge(self):
        census = _census(
            [("SPY", 700.0, 50000, 0), ("SPY", 750.0, 50000, 0), ("SPY", 800.0, 900, 0)]
        )
        out = group_structures(census, SPOT)
        assert len(out) == 1
        assert out.iloc[0]["contracts"] == pytest.approx(50000)

    def test_tolerance_absorbs_small_mismatches(self):
        """Real legs drift apart through exercise and assignment."""
        census = _census([("SPY", 700.0, 38317, 0), ("SPY", 750.0, 0, 37540)])
        assert len(group_structures(census, SPOT)) == 1

    def test_tolerance_is_configurable(self):
        census = _census([("SPY", 700.0, 50000, 0), ("SPY", 750.0, 0, 40000)])
        assert group_structures(census, SPOT, GroupingConfig(count_tolerance=0.01)).empty
        assert len(group_structures(census, SPOT, GroupingConfig(count_tolerance=0.30))) == 1

    def test_single_legs_are_not_structures(self):
        assert group_structures(_census([("SPY", 700.0, 50000, 0)]), SPOT).empty

    def test_tiny_legs_are_dropped(self):
        census = _census([("SPY", 700.0, 100, 0), ("SPY", 750.0, 100, 0)])
        assert group_structures(census, SPOT).empty

    def test_symbols_without_a_spot_are_skipped(self):
        census = _census([("ZZZZ", 700.0, 50000, 0), ("ZZZZ", 750.0, 50000, 0)])
        assert group_structures(census, SPOT).empty

    def test_expiries_are_grouped_separately(self):
        a = _census([("SPY", 700.0, 50000, 0), ("SPY", 750.0, 50000, 0)])
        b = a.copy()
        b["expiry"] = date(2026, 10, 30)
        assert len(group_structures(pd.concat([a, b]), SPOT)) == 2

    def test_empty_input_returns_typed_frame(self):
        out = group_structures(_census([]).reindex(columns=BUFFER.columns), SPOT)
        assert out.empty
        assert "exposure" in out.columns

    def test_does_not_mutate_input(self):
        before = BUFFER.copy()
        group_structures(BUFFER, SPOT)
        pd.testing.assert_frame_equal(BUFFER, before)
