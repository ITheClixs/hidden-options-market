"""Tests for FLEX classification.

The census is only meaningful if the categories are separable. These tests pin each
signature against the real examples they were derived from, and pin the boundaries
where two signatures could be confused.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from absorb.measure.flex import (
    ClassifierConfig,
    build_census,
    classify,
    detect_multileg,
    is_flex_strike,
    strike_cents,
    summarise,
)

CFG = ClassifierConfig()


def _row(strike, call, put):
    return pd.Series(
        {
            "symbol": "X",
            "expiry": date(2026, 10, 16),
            "strike": strike,
            "call_open_interest": call,
            "put_open_interest": put,
        }
    )


class TestStrikeCents:
    @pytest.mark.parametrize(
        "strike,cents", [(95.00, 0), (95.01, 1), (95.02, 2), (157.50, 50), (765.66, 66)]
    )
    def test_extracts_cents(self, strike, cents):
        assert strike_cents(strike) == cents

    def test_floating_point_does_not_leak(self):
        """0.1+0.2 style error must not turn a 10-cent strike into 9 cents."""
        assert strike_cents(95.10) == 10

    @pytest.mark.parametrize("strike", [95.0, 12.25, 157.5, 0.75])
    def test_standard_grid_is_not_flex(self, strike):
        assert not is_flex_strike(strike)

    @pytest.mark.parametrize("strike", [95.01, 765.66, 11.51, 597.42])
    def test_off_grid_is_flex(self, strike):
        assert is_flex_strike(strike)


class TestClassify:
    def test_fund_synthetic_from_cent_offset_and_one_sidedness(self):
        """The real MSTY leg: 95.01, all open interest on the put side."""
        assert classify(_row(95.01, 0, 45115), CFG) == "fund_synthetic"

    def test_one_sided_calls_at_cent_offset_are_not_a_fund_synthetic(self):
        """Regression: a fund synthetic writes puts. An observed MSFT ladder of
        200,000-contract call lines at 550.01 was misread as a fund leg before the
        put-dominance condition was added."""
        assert classify(_row(550.01, 200000, 0), CFG) != "fund_synthetic"

    def test_matched_combination_takes_precedence(self):
        """Equal legs at an offset strike are a financing structure, not a fund leg."""
        assert classify(_row(95.02, 6620, 6620), CFG) == "matched_combination"

    def test_index_linked_from_arbitrary_decimal(self):
        """Buffer funds strike caps and floors off an index level: SPY 765.66."""
        assert classify(_row(765.66, 37507, 0), CFG) == "index_linked"

    def test_block_from_round_lot_on_grid(self):
        assert classify(_row(550.00, 200000, 0), CFG) == "block"

    def test_on_grid_one_sided_but_not_round_is_unclassified(self):
        assert classify(_row(550.00, 12345, 0), CFG) == "unclassified"

    def test_two_sided_off_grid_is_unclassified(self):
        assert classify(_row(95.01, 5000, 4000), CFG) == "unclassified"

    def test_small_series_are_excluded(self):
        assert classify(_row(95.01, 0, 10), CFG) == "below_threshold"

    def test_zero_series_are_excluded(self):
        assert classify(_row(95.01, 0, 0), CFG) == "below_threshold"

    def test_one_sidedness_threshold_is_respected(self):
        """85% on one side is not one-sided enough to be a fund leg."""
        assert classify(_row(95.01, 1500, 8500), CFG) == "unclassified"

    def test_thresholds_are_configurable(self):
        loose = ClassifierConfig(one_sided_threshold=0.80)
        assert classify(_row(95.01, 1500, 8500), loose) == "fund_synthetic"


def _frame(rows):
    return pd.DataFrame(
        [
            {
                "symbol": s,
                "expiry": date(2026, 10, 16),
                "strike": k,
                "call_open_interest": c,
                "put_open_interest": p,
            }
            for s, k, c, p in rows
        ]
    )


class TestBuildCensus:
    def test_separates_the_real_mstr_cluster(self):
        census = build_census(
            _frame(
                [
                    ("MSTR", 95.00, 46125, 1746),  # listed, on grid -> excluded
                    ("MSTR", 95.00, 7000, 7000),  # matched but on grid -> excluded
                    ("MSTR", 95.01, 0, 45115),  # fund synthetic
                    ("MSTR", 95.02, 6620, 6620),  # matched combination
                ]
            )
        )
        assert set(census["category"]) == {"fund_synthetic", "matched_combination"}
        assert len(census) == 2

    def test_computes_notional(self):
        census = build_census(_frame([("MSTR", 95.01, 0, 45115)]))
        assert census.iloc[0]["notional"] == pytest.approx(45115 * 100 * 95.01)

    def test_orders_by_notional(self):
        census = build_census(_frame([("A", 10.01, 0, 5000), ("B", 500.01, 0, 5000)]))
        assert census.iloc[0]["symbol"] == "B"

    def test_on_grid_blocks_are_retained(self):
        """A negotiated block can sit on a standard strike and still be of interest."""
        census = build_census(_frame([("MSFT", 550.00, 200000, 0)]))
        assert census.iloc[0]["category"] == "block"

    def test_ordinary_listed_series_are_excluded(self):
        census = build_census(_frame([("AAPL", 300.00, 5000, 4000)]))
        assert census.empty

    def test_rejects_wrong_schema(self):
        with pytest.raises(ValueError, match="missing columns"):
            build_census(pd.DataFrame({"symbol": ["X"]}))

    def test_empty_input_returns_typed_frame(self):
        census = build_census(_frame([]).reindex(columns=list(_frame([("A", 1, 1, 1)]).columns)))
        assert census.empty
        assert "category" in census.columns

    def test_does_not_mutate_input(self):
        frame = _frame([("MSTR", 95.01, 0, 45115)])
        before = frame.copy()
        build_census(frame)
        pd.testing.assert_frame_equal(frame, before)


class TestSummarise:
    def test_shares_sum_to_one(self):
        census = build_census(_frame([("MSTR", 95.01, 0, 45115), ("SPY", 765.66, 37507, 0)]))
        assert summarise(census)["share_contracts"].sum() == pytest.approx(1.0)

    def test_reports_contracts_alongside_notional(self):
        """Notional misleads for boxes struck far from spot, so contracts are also
        reported: an SPY box at strike 10,010 carries $29bn of meaningless notional."""
        census = build_census(_frame([("SPY", 10010.01, 14494, 14494)]))
        row = summarise(census).iloc[0]
        assert row["category"] == "matched_combination"
        assert row["contracts_m"] == pytest.approx(28988 / 1e6)

    def test_empty_census_summarises_empty(self):
        assert summarise(pd.DataFrame(columns=["category", "strike", "notional"])).empty


class TestDetectMultileg:
    """A butterfly counted leg by leg looks like three outright positions and is
    credited with notional ~49x its maximum possible value."""

    def _butterfly(self):
        return build_census(
            _frame(
                [
                    ("MSFT", 510.01, 100000, 0),
                    ("MSFT", 550.01, 200000, 0),
                    ("MSFT", 590.01, 100000, 0),
                ]
            )
        )

    def test_labels_all_three_legs(self):
        out = detect_multileg(self._butterfly())
        assert (out["structure"] == "butterfly").sum() == 3

    def test_max_value_is_spacing_times_wing(self):
        out = detect_multileg(self._butterfly())
        assert out["max_value"].iloc[0] == pytest.approx(40 * 100000 * 100)

    def test_max_value_is_far_below_notional(self):
        out = detect_multileg(self._butterfly())
        assert out["max_value"].iloc[0] < out["notional"].sum() / 20

    def test_unequal_spacing_is_not_a_butterfly(self):
        census = build_census(
            _frame([("X", 100.01, 100000, 0), ("X", 150.01, 200000, 0), ("X", 175.01, 100000, 0)])
        )
        assert detect_multileg(census)["structure"].isna().all()

    def test_wrong_ratio_is_not_a_butterfly(self):
        census = build_census(
            _frame([("X", 100.01, 100000, 0), ("X", 140.01, 100000, 0), ("X", 180.01, 100000, 0)])
        )
        assert detect_multileg(census)["structure"].isna().all()

    def test_small_wings_are_ignored(self):
        census = build_census(
            _frame([("X", 100.01, 200, 0), ("X", 140.01, 400, 0), ("X", 180.01, 200, 0)])
        )
        assert detect_multileg(census)["structure"].isna().all()

    def test_unrelated_series_keep_their_category(self):
        census = build_census(_frame([("MSTR", 95.01, 0, 45115)]))
        out = detect_multileg(census)
        assert out["structure"].isna().all()
        assert out["category"].iloc[0] == "fund_synthetic"

    def test_empty_census_is_handled(self):
        empty = build_census(_frame([]).reindex(columns=list(_frame([("A", 1, 1, 1)]).columns)))
        assert detect_multileg(empty).empty
