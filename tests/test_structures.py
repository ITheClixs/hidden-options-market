"""Tests for leg grouping and exposure valuation.

Every case here is drawn from a real position that the previous, per-series approach
got wrong. The point of the module is that a structure is counted once and valued on
the underlying, so those are the two properties tested hardest.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.structures import (
    LEG_COLUMNS,
    GroupingConfig,
    group_legs,
    group_structures,
    structure_type,
)

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

    def test_tolerance_forgives_small_mismatches(self):
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


def _legs(rows):
    """rows: (underlying, expiry, right, strike, contracts)"""
    return pd.DataFrame(rows, columns=list(LEG_COLUMNS))


COLLAR_LEGS = _legs(
    [
        ("SPY", EXPIRY, "C", 1.87, 37507),
        ("SPY", EXPIRY, "C", 765.66, 37507),
        ("SPY", EXPIRY, "P", 746.77, 38317),
        ("SPY", EXPIRY, "P", 597.42, 37540),
    ]
)


class TestGroupLegs:
    def test_group_legs_recovers_collar(self):
        legs, structures = group_legs(COLLAR_LEGS, SPOT)
        assert legs["structure_id"].nunique() == 1
        assert (legs["structure_id"] >= 0).all()
        assert len(structures) == 1
        row = structures.iloc[0]
        assert row["structure_id"] == legs["structure_id"].iloc[0]
        assert row["structure"] == "collar_buffer"
        assert row["n_legs"] == 4

    def test_group_legs_leaves_singletons_ungrouped(self):
        legs, structures = group_legs(
            _legs([("SPY", EXPIRY, "C", 700.0, 50000), ("SPY", EXPIRY, "P", 650.0, 9000)]), SPOT
        )
        assert (legs["structure_id"] == -1).all()
        assert structures.empty
        assert "structure_id" in structures.columns

    def test_legs_below_the_minimum_stay_ungrouped_beside_a_structure(self):
        legs, _ = group_legs(
            _legs(
                [
                    ("SPY", EXPIRY, "C", 700.0, 50000),
                    ("SPY", EXPIRY, "P", 700.0, 50000),
                    ("SPY", EXPIRY, "C", 800.0, 100),
                    ("SPY", EXPIRY, "P", 800.0, 100),
                ]
            ),
            SPOT,
        )
        assert list(legs["structure_id"] >= 0) == [True, True, False, False]

    def test_each_expiry_and_underlying_has_its_own_structures(self):
        other = date(2026, 10, 30)
        legs, structures = group_legs(
            _legs(
                [
                    ("SPY", EXPIRY, "C", 700.0, 50000),
                    ("SPY", EXPIRY, "P", 700.0, 50000),
                    ("SPY", other, "C", 700.0, 50000),
                    ("MSFT", other, "P", 700.0, 50000),
                ]
            ),
            SPOT,
        )
        assert list(legs["structure_id"] >= 0) == [True, True, False, False]
        assert len(structures) == 1

    def test_an_underlying_without_a_spot_is_grouped_but_has_no_exposure(self):
        legs, structures = group_legs(
            _legs([("ZZZZ", EXPIRY, "C", 10.0, 900), ("ZZZZ", EXPIRY, "P", 10.0, 900)]), SPOT
        )
        assert (legs["structure_id"] >= 0).all()
        assert np.isnan(structures.iloc[0]["exposure"])

    def test_extra_columns_are_kept_and_the_input_is_untouched(self):
        rows = COLLAR_LEGS.assign(root="4SPY")
        before = rows.copy()
        legs, _ = group_legs(rows, SPOT)
        assert (legs["root"] == "4SPY").all()
        pd.testing.assert_frame_equal(rows, before)

    def test_no_legs_gives_typed_frames(self):
        legs, structures = group_legs(_legs([]), SPOT)
        assert legs.empty and "structure_id" in legs.columns
        assert structures.empty and "structure_id" in structures.columns

    def test_config_sets_the_tolerance(self):
        rows = _legs([("SPY", EXPIRY, "C", 700.0, 50000), ("SPY", EXPIRY, "P", 700.0, 40000)])
        assert (group_legs(rows, SPOT)[0]["structure_id"] == -1).all()
        wide = group_legs(rows, SPOT, GroupingConfig(count_tolerance=0.3))[0]
        assert (wide["structure_id"] >= 0).all()


class TestStructureType:
    def test_labels_are_those_of_the_grouped_structures(self):
        assert structure_type(["C", "P"], [95.0, 95.01], [10, 10]) == "synthetic"
        assert structure_type(["C", "P"], [110.0, 80.0], [10, 10]) == "risk_reversal"
        assert structure_type(["C", "C"], [100.0, 120.0], [10, 10]) == "vertical_spread"
        assert structure_type(["C", "C", "C"], [1.0, 2.0, 3.0], [1, 1, 1]) == "butterfly"
        assert structure_type(["C", "C", "P"], [1.0, 2.0, 4.0], [1, 1, 1]) == "three_leg"
        assert structure_type(["C", "C", "P", "P"], [1.0, 2, 3, 4], [1, 1, 1, 1]) == "collar_buffer"
        assert structure_type(["C"] * 5, [1.0, 2, 3, 4, 5], [1] * 5) == "5_leg"


def test_grouping_values_are_the_ones_frozen_before_scoring():
    assert GroupingConfig() == GroupingConfig(count_tolerance=0.05, min_contracts=500, min_legs=2)
