"""Tests for synthetic-leg detection in OCC open interest.

Fixtures reproduce the real MSTR 2026-10-16 cluster observed on 2026-08-16, where
the listed 95.00 series, the fund's written put leg at 95.01, and an unrelated combo
at 95.02 all coexist. Separating those three is the whole job.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from absorb.measure.synthetic import (
    DetectionConfig,
    find_combo_candidates,
    find_synthetic_legs,
    is_offset_strike,
    reconcile_with_holdings,
    underlying_from_root,
)

EXPIRY = date(2026, 10, 16)

# Real shape: listed series, fund put leg, unrelated matched combo.
MSTR_CLUSTER = pd.DataFrame(
    [
        {
            "symbol": "MSTR",
            "expiry": EXPIRY,
            "strike": 95.00,
            "call_open_interest": 46125,
            "put_open_interest": 1746,
        },
        {
            "symbol": "MSTR",
            "expiry": EXPIRY,
            "strike": 95.00,
            "call_open_interest": 7000,
            "put_open_interest": 7000,
        },
        {
            "symbol": "MSTR",
            "expiry": EXPIRY,
            "strike": 95.01,
            "call_open_interest": 0,
            "put_open_interest": 45115,
        },
        {
            "symbol": "MSTR",
            "expiry": EXPIRY,
            "strike": 95.02,
            "call_open_interest": 6620,
            "put_open_interest": 6620,
        },
    ]
)

MSTY_HOLDINGS = pd.DataFrame(
    [
        {
            "fund": "MSTY",
            "option_root": "MSTR",
            "expiry": EXPIRY,
            "strike": 95.00,
            "right": "C",
            "contracts": 45115.0,
            "is_option": True,
        },
        {
            "fund": "MSTY",
            "option_root": "2MSTR",
            "expiry": EXPIRY,
            "strike": 95.01,
            "right": "P",
            "contracts": -45115.0,
            "is_option": True,
        },
        {
            "fund": "MSTY",
            "option_root": None,
            "expiry": None,
            "strike": None,
            "right": None,
            "contracts": 150141000.0,
            "is_option": False,
        },
    ]
)


class TestIsOffsetStrike:
    @pytest.mark.parametrize("strike", [95.01, 95.02, 100.01, 11.51, 35.01, 260.01, 155.01])
    def test_flags_non_standard_cents(self, strike):
        assert is_offset_strike(strike)

    @pytest.mark.parametrize("strike", [95.0, 100.0, 157.5, 12.25, 0.75, 330.0])
    def test_accepts_standard_grid(self, strike):
        assert not is_offset_strike(strike)


class TestUnderlyingFromRoot:
    def test_strips_non_standard_prefix(self):
        assert underlying_from_root("2MSTR") == "MSTR"

    def test_passes_through_standard_root(self):
        assert underlying_from_root("MSTR") == "MSTR"

    def test_handles_missing(self):
        assert underlying_from_root(None) is None
        assert underlying_from_root(float("nan")) is None


class TestFindSyntheticLegs:
    def test_isolates_the_written_put_leg(self):
        legs = find_synthetic_legs(MSTR_CLUSTER)
        assert len(legs) == 1
        leg = legs.iloc[0]
        assert (leg["strike"], leg["leg_right"], leg["leg_open_interest"]) == (95.01, "P", 45115)

    def test_excludes_the_listed_series(self):
        """46,125 calls vs 1,746 puts is one-sided but sits on a standard strike."""
        assert 95.00 not in set(find_synthetic_legs(MSTR_CLUSTER)["strike"])

    def test_excludes_the_matched_combo_at_an_offset_strike(self):
        """95.02 is offset but perfectly two-sided, so it is a combo, not a fund leg."""
        assert 95.02 not in set(find_synthetic_legs(MSTR_CLUSTER)["strike"])

    def test_reports_one_sidedness(self):
        assert find_synthetic_legs(MSTR_CLUSTER).iloc[0]["one_sidedness"] == pytest.approx(1.0)

    def test_small_series_are_ignored(self):
        tiny = MSTR_CLUSTER.assign(put_open_interest=[1746, 7000, 12, 6620])
        assert find_synthetic_legs(tiny).empty

    def test_one_sidedness_threshold_is_configurable(self):
        leaky = MSTR_CLUSTER.copy()
        leaky.loc[2, "call_open_interest"] = 9000  # 45115 / 54115 = 0.83
        assert find_synthetic_legs(leaky).empty
        loosened = find_synthetic_legs(leaky, DetectionConfig(min_one_sidedness=0.8))
        assert len(loosened) == 1

    def test_offset_requirement_can_be_relaxed(self):
        relaxed = find_synthetic_legs(MSTR_CLUSTER, DetectionConfig(require_offset_strike=False))
        assert 95.00 in set(relaxed["strike"])

    def test_does_not_mutate_input(self):
        before = MSTR_CLUSTER.copy()
        find_synthetic_legs(MSTR_CLUSTER)
        pd.testing.assert_frame_equal(MSTR_CLUSTER, before)

    def test_rejects_wrong_schema(self):
        with pytest.raises(ValueError, match="missing columns"):
            find_synthetic_legs(pd.DataFrame({"symbol": ["MSTR"]}))

    def test_empty_input_returns_typed_empty(self):
        empty = MSTR_CLUSTER.iloc[0:0]
        result = find_synthetic_legs(empty)
        assert result.empty
        assert "leg_open_interest" in result.columns


class TestFindComboCandidates:
    def test_finds_matched_series_only(self):
        combos = find_combo_candidates(MSTR_CLUSTER)
        assert set(combos["paired_open_interest"]) == {7000, 6620}

    def test_does_not_pick_up_the_fund_leg(self):
        """The whole point of separating the two detectors."""
        assert 95.01 not in set(find_combo_candidates(MSTR_CLUSTER)["strike"])


class TestReconcileWithHoldings:
    def test_attributes_the_leg_to_the_disclosing_fund(self):
        legs = find_synthetic_legs(MSTR_CLUSTER)
        result = reconcile_with_holdings(legs, MSTY_HOLDINGS)
        assert result.iloc[0]["matched_fund"] == "MSTY"
        assert result.iloc[0]["disclosed_contracts"] == -45115.0

    def test_requires_the_underlying_to_match(self):
        """Regression: matching on (expiry, strike) alone attributed MSTY to INTC."""
        legs = find_synthetic_legs(MSTR_CLUSTER.assign(symbol="INTC"))
        result = reconcile_with_holdings(legs, MSTY_HOLDINGS)
        assert result.iloc[0]["matched_fund"] is None

    def test_requires_the_right_to_match(self):
        legs = find_synthetic_legs(MSTR_CLUSTER)
        calls_only = MSTY_HOLDINGS[MSTY_HOLDINGS["right"] != "P"]
        assert reconcile_with_holdings(legs, calls_only).iloc[0]["matched_fund"] is None

    def test_unattributed_legs_are_retained(self):
        legs = find_synthetic_legs(MSTR_CLUSTER)
        empty_book = MSTY_HOLDINGS.iloc[0:0]
        result = reconcile_with_holdings(legs, empty_book)
        assert len(result) == 1
        assert result.iloc[0]["matched_fund"] is None

    def test_ignores_non_option_rows(self):
        legs = find_synthetic_legs(MSTR_CLUSTER)
        assert reconcile_with_holdings(legs, MSTY_HOLDINGS).iloc[0]["matched_fund"] == "MSTY"

    def test_rejects_wrong_holdings_schema(self):
        legs = find_synthetic_legs(MSTR_CLUSTER)
        with pytest.raises(ValueError, match="missing columns"):
            reconcile_with_holdings(legs, pd.DataFrame({"fund": ["MSTY"]}))
