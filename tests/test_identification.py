"""Why a strike rule cannot find FLEX (M3): the listing grid and the score."""

from __future__ import annotations

import math

import pytest

from hidden_options.measure.identification import (
    GRID_POSITIONS,
    Confusion,
    grid_position,
    grid_shares,
    score_strike_rule,
    scored_series,
)
from identification_stub import ROWS, census


class TestGridPosition:
    def test_grid_position_cases(self):
        assert grid_position(99.00) == "dollar"
        assert grid_position(12.50) == "half"
        assert grid_position(7.25) == "quarter"
        assert grid_position(7.75) == "quarter"
        assert grid_position(130.01) == "off_grid"

    def test_floating_point_noise_does_not_move_a_strike_off_the_grid(self):
        assert grid_position(0.1 + 0.2 + 99.7) == "dollar"
        assert grid_position(2.675) == "off_grid"

    def test_positions_are_ordered_from_the_whole_dollar_out(self):
        assert GRID_POSITIONS == ("dollar", "half", "quarter", "off_grid")


class TestConfusion:
    def test_confusion_metrics(self):
        score = Confusion(tp=4914, fp=2389, fn=9321, tn=470271)
        assert round(score.precision, 3) == 0.673
        assert round(score.recall, 3) == 0.345
        assert round(score.f1, 3) == 0.456
        assert score.total == 486_895

    def test_metrics_without_flags_or_without_flex_are_undefined(self):
        assert math.isnan(Confusion(tp=0, fp=0, fn=3, tn=5).precision)
        assert math.isnan(Confusion(tp=0, fp=2, fn=0, tn=5).recall)
        assert math.isnan(Confusion(tp=0, fp=0, fn=0, tn=5).f1)
        assert Confusion(tp=0, fp=2, fn=3, tn=5).f1 == 0.0

    def test_is_frozen(self):
        score = Confusion(tp=1, fp=1, fn=1, tn=1)
        with pytest.raises(AttributeError):
            score.tp = 2  # type: ignore[misc]

    def test_as_dict_carries_counts_and_metrics(self):
        score = Confusion(tp=2, fp=1, fn=3, tn=3).as_dict()
        assert score == {
            "tp": 2,
            "fp": 1,
            "fn": 3,
            "tn": 3,
            "precision": pytest.approx(2 / 3),
            "recall": pytest.approx(0.4),
            "f1": pytest.approx(0.5),
        }


class TestSeries:
    def test_a_call_and_a_put_at_one_strike_are_one_series(self):
        series = scored_series(census())
        both = series[(series["product_symbol"] == "2AAA") & (series["strike"] == 101.37)]
        assert len(both) == 1
        assert both["open_interest"].iloc[0] == 400

    def test_series_with_nothing_open_are_left_out(self):
        series = scored_series(census())
        assert not ((series["strike"] == 105.25) | (series["strike"] == 50.01)).any()
        assert (series["open_interest"] > 0).all()

    def test_adjusted_deliverable_classes_are_left_out(self):
        series = scored_series(census())
        assert not series["product_symbol"].isin({"AAA1", "1AAA1"}).any()

    def test_a_listed_and_a_flex_series_at_one_strike_stay_two(self):
        series = scored_series(census())
        assert len(series[(series["symbol"] == "AAA") & (series["strike"] == 100.0)]) == 2

    def test_truth_and_grid_are_carried(self):
        series = scored_series(census()).set_index(["product_symbol", "strike"])
        assert bool(series.loc[("1BBB", 55.0), "flex"])
        assert not bool(series.loc[("AAA", 33.33), "flex"])
        assert series.loc[("2AAA", 97.75), "grid"] == "quarter"
        assert len(series) == 9


class TestScore:
    def test_counts_the_rule_against_the_product_symbol(self):
        score = score_strike_rule(scored_series(census()))
        assert score == Confusion(tp=2, fp=1, fn=3, tn=3)

    def test_scores_a_raw_census_as_given(self):
        score = score_strike_rule(census())
        # Every row counts here, the empty and the adjusted ones too.
        assert score.total == len(ROWS)
        assert score == Confusion(tp=4, fp=1, fn=3, tn=5)

    def test_weighted_by_open_interest(self):
        score = score_strike_rule(scored_series(census()), weight="open_interest")
        assert score == Confusion(tp=700, fp=8, fn=2540, tn=32)


class TestGridShares:
    def test_shares_of_series_and_open_interest_per_group(self):
        shares = grid_shares(scored_series(census()))
        assert list(shares.index) == list(GRID_POSITIONS)
        assert shares["flex_series"].tolist() == pytest.approx([0.4, 0.0, 0.2, 0.4])
        assert shares["listed_series"].tolist() == pytest.approx([0.5, 0.25, 0.0, 0.25])
        flex_oi = [2500 / 3240, 0.0, 40 / 3240, 700 / 3240]
        assert shares["flex_open_interest"].tolist() == pytest.approx(flex_oi)
        listed_oi = [29 / 40, 3 / 40, 0.0, 8 / 40]
        assert shares["listed_open_interest"].tolist() == pytest.approx(listed_oi)

    def test_each_column_sums_to_one(self):
        shares = grid_shares(scored_series(census()))
        assert shares.sum().tolist() == pytest.approx([1.0] * 4)
