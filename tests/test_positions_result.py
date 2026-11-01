"""The `positions` result on the stub world."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.publish.latex import collect_macros
from hidden_options.publish.results import Result, read_results, write_result
from positions_stub import inputs, rows_of


@pytest.fixture(scope="module")
def result() -> Result:
    from hidden_options.measure.positions_result import positions_result

    return positions_result(inputs())


class TestResult:
    def test_named_with_valid_macros(self, result):
        assert result.name == "positions"
        collect_macros({result.name: result})

    def test_values_survive_a_round_trip_through_json(self, result, tmp_path):
        write_result(result, tmp_path)
        assert read_results(tmp_path)["positions"].values == result.values

    def test_it_stops_at_the_panel_end(self, result):
        window = result.values["window"]
        assert window["dates"] == 3
        assert window["last_date"] == "2026-09-16"
        assert result.inputs["panel_end"] == "2026-10-22"

    def test_settings_record_what_was_frozen(self, result):
        settings = result.values["settings"]
        assert settings["grouping"] == {
            "count_tolerance": 0.05,
            "min_contracts": 500,
            "min_legs": 2,
        }
        assert settings["max_staleness_bdays"] == 3
        assert settings["rate"] == 0.04


class TestValidation:
    def test_one_structure_of_two_is_recovered(self, result):
        score = result.values["validation"]["score"]
        assert score["n_truth_structures"] == 2
        assert score["n_funds"] == 2
        assert score["n_underlyings"] == 2
        assert score["recall"] == pytest.approx(0.5)
        assert score["precision"] == pytest.approx(1.0)
        assert score["type_agreement"] == pytest.approx(1.0)

    def test_scores_under_the_floor_restrict_the_claim(self, result):
        assert result.values["restricted"] is False

    def test_a_low_score_sets_the_restriction(self):
        from hidden_options.measure.positions_result import _restricted

        assert _restricted({"precision": 0.9, "recall": 0.49}) is True
        assert _restricted({"precision": 0.49, "recall": 0.9}) is True
        assert _restricted({"precision": 0.5, "recall": 0.5}) is False

    def test_stale_files_are_counted_and_as_of_is_cut_at_the_end(self, result):
        truth = result.values["validation"]["truth"]
        assert truth["stale_files"] == 1
        assert truth["last_as_of"] == "2026-09-16"
        assert truth["funds_with_flex"] == 2

    def test_the_floor_check_and_holder_share_are_reported(self, result):
        validation = result.values["validation"]
        assert validation["floor"]["as_of_previous"]["legs"] == 8
        assert validation["floor"]["as_of_previous"]["found"] == 8
        assert validation["holder_share"] == pytest.approx(0.9)

    def test_disclosed_signs_show_what_all_long_netting_misses(self, result):
        signs = result.values["validation"]["signs"]
        assert signs["structures"] >= 1
        # A synthetic held long the call and short the put: all-long nets it near zero.
        assert signs["signed_over_gross"] == pytest.approx(1.0)
        assert signs["rule_over_signed"] < 0.5

    def test_scores_by_date_and_type_are_kept(self, result):
        validation = result.values["validation"]
        assert validation["by_date"]["dates"] == 2
        assert validation["by_type"]["synthetic"]["truth"] == 2
        assert validation["truth"]["types"] == {"synthetic": 2}

    def test_globalx_is_counted_up_to_the_end(self, result):
        overlap = result.values["validation"]["globalx"]
        assert overlap["fund_dates"] == 1
        assert overlap["legs"] == 1
        assert overlap["legs_on_flex_report"] == 1
        assert overlap["multi_leg_holdings"] == 0


class TestMarket:
    def test_structured_share_is_of_contracts(self, result):
        rows = rows_of(pd.Timestamp("2026-09-14"))
        total = rows["open_interest"].sum()
        market = result.values["market"]
        assert 0 < market["structured_last"] < 1
        assert market["structured_last"] <= (total - 3000 - 9000 - 700 - 900) / total + 1e-9

    def test_chance_and_tolerances_are_read(self, result):
        market = result.values["market"]
        assert market["chance_dates"] == 1
        assert set(market["tolerance_last"]) == {"0.00", "0.01", "0.10"}

    def test_ratios_cover_each_priced_underlying_once(self, result):
        ratios = result.values["ratios"]
        symbols = {row["symbol"] for row in ratios["by_underlying"]}
        assert {"AAA", "BBB", "MSFT"} <= symbols
        assert ratios["underlyings"] == len(ratios["by_underlying"])
        assert ratios["rule"]["n"] == ratios["underlyings"]
        assert set(ratios["rates"]) == {"0.03", "0.05"}

    def test_coverage_shares_are_shares(self, result):
        coverage = result.values["ratios"]["coverage"]
        assert 0 < coverage["covered_share"] <= 1
        assert coverage["outside_share"] == pytest.approx(1 - coverage["covered_share"])
        assert coverage["no_spot_share"] == 0


class TestCases:
    def test_the_butterfly_is_recomputed(self, result):
        case = result.values["cases"]["butterfly"]
        assert case["underlying"] == "MSFT"
        assert case["lines"] == 9
        assert case["max_value"] == pytest.approx(3 * 40 * 100_000 * 100)
        assert case["overstatement"] == pytest.approx(case["strike_notional"] / case["max_value"])
        assert case["wings_grouped"] == 3

    def test_the_collar_is_recomputed(self, result):
        case = result.values["cases"]["collar"]
        assert case["detected_as_one"] is True
        assert case["size"] == pytest.approx(37_523.5)
        assert case["strike_notional"] == pytest.approx(
            (1.87 * 37_507 + 765.66 * 37_507 + 746.77 * 38_317 + 597.42 * 37_540) * 100
        )
        assert case["max_value"] == pytest.approx(37_507 * 100 * (765.66 - 1.87), rel=0.05)

    def test_the_deep_call_is_recomputed(self, result):
        deep = result.values["cases"]["collar"]["deep_call"]
        assert deep["strike"] == 1.87
        assert deep["strike_notional"] == pytest.approx(1.87 * 37_507 * 100)
        assert deep["exposure"] > 300 * deep["strike_notional"]

    def test_a_case_missing_from_the_panel_is_none(self):
        from hidden_options.measure.positions_result import _cases

        rows = rows_of(pd.Timestamp("2026-09-14"))
        rows = rows[~rows["underlying"].isin(["MSFT", "SPY"])]
        assert _cases(rows, inputs()) == {"butterfly": None, "collar": None}
