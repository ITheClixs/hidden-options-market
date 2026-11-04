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
        assert set(ratios["rates_gross"]) == {"0.03", "0.05"}

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


class TestTable:
    def test_the_table_states_its_denominators(self, result):
        from hidden_options.measure.positions_table import validation_table

        table = validation_table({"positions": result})
        assert "\\label{tab:positions}" in table
        assert "Synthetic" in table
        assert "50.0\\%" in table
        assert "consistent with a disclosed holder" in table

    def test_the_table_asks_for_its_result(self):
        from hidden_options.measure.positions_table import validation_table

        with pytest.raises(KeyError, match="positions"):
            validation_table({})

    def test_an_unnamed_type_is_labelled_by_its_legs(self):
        from hidden_options.measure.positions_table import _by_type

        row = _by_type(
            "5_leg",
            {"truth": 0, "recall": None, "recall_grouped": None, "touching": 2, "precision": 0.5},
        )
        assert row["label"] == "5 legs"
        assert row["recall"] is None
        assert row["precision"] == "50.0\\%"


class TestFloorDelta:
    def test_a_mark_below_the_floor_takes_a_delta_of_one(self):
        from hidden_options.measure.positions_result import with_floor_delta

        priced = pd.DataFrame(
            {
                "right": ["C", "P", "C"],
                "iv_status": ["below_intrinsic", "below_intrinsic", "no_spot"],
                "open_interest": [10, 10, 10],
                "spot": [100.0, 100.0, float("nan")],
                "delta_dollars": [float("nan")] * 3,
            }
        )
        filled = with_floor_delta(priced)
        assert filled["delta_dollars"].iloc[0] == pytest.approx(100_000.0)
        assert filled["delta_dollars"].iloc[1] == pytest.approx(-100_000.0)
        assert pd.isna(filled["delta_dollars"].iloc[2])
        assert pd.isna(priced["delta_dollars"].iloc[0])

    def test_the_result_reports_the_leg_level_and_floor_readings(self, result):
        ratios = result.values["ratios"]
        assert 0 <= ratios["legs"]["understated_share"] <= 1
        assert ratios["legs"]["below_floor_share"] == 0
        assert ratios["floor_delta"]["n"] >= ratios["rule"]["n"]
        assert ratios["floor_delta_gross"]["n"] == ratios["floor_delta"]["n"]


class TestMacros:
    def test_scores_and_denominators_print(self, result):
        macros = result.macros
        assert macros["PosRecall"] == "50.0\\%"
        assert macros["PosPrecision"] == "100.0\\%"
        assert macros["PosTruth"] == "2"
        assert macros["PosFunds"] == "2 funds"
        assert macros["PosUnderlyings"] == "2 underlyings"
        assert macros["PosStaleFiles"] == "1 file"

    def test_cases_print_from_their_values(self, result):
        macros = result.macros
        assert macros["PosButterflyName"] == "MSFT"
        assert macros["PosButterflyLines"] == "9"
        assert macros["PosCollarName"] == "SPY"
        assert macros["PosDeepStrike"] == "\\$1.87"

    def test_dollars_read_at_their_scale(self):
        from hidden_options.measure.positions_macros import usd

        assert usd(7_013_435) == "\\$7.0m"
        assert usd(1.3e9) == "\\$1.30bn"
        assert usd(63.8e9) == "\\$63.8bn"
        assert usd(4.256e12) == "\\$4.26tn"
        assert usd(None) == "--"

    def test_a_missing_case_prints_a_dash_and_no_macro_is_lost(self, result):
        from hidden_options.measure.positions_macros import positions_macros

        values = {**result.values, "cases": {"butterfly": None, "collar": None}}
        macros = positions_macros(values)
        assert set(macros) == set(result.macros)
        assert macros["PosButterflyTimes"] == "--"
        assert macros["PosDeepTimes"] == "--"

    def test_names_are_letters_only(self, result):
        assert all(name.isalpha() for name in result.macros)


class TestScoredLegs:
    def test_a_structure_keeps_its_legs_of_another_root(self):
        """Grouping does not look at the root, so the score must see every leg of a structure."""
        from hidden_options.measure.positions_result import scored_legs

        legs = pd.DataFrame(
            {
                "underlying": ["AAA", "AAA", "ZZZ"],
                "root": ["2AAA", "1AAA", "2ZZZ"],
                "structure_id": [0, 0, 1],
            }
        )
        assert list(scored_legs(legs, {"AAA"})["root"]) == ["2AAA", "1AAA"]


class TestCaptureCut:
    def test_a_capture_after_the_panel_end_is_ignored(self, result):
        from hidden_options.measure.positions_result import positions_result
        from positions_stub import AFTER_END, D2, globalx, holdings

        late = (
            holdings()
            .query("fund == 'AAAY' and as_of == @D2")
            .assign(capture_date=AFTER_END, contracts=lambda rows: rows["contracts"] * 5)
        )
        late_globalx = globalx().iloc[[0]].assign(capture_date=AFTER_END, strike=4000.0)
        again = positions_result(
            inputs(
                holdings=pd.concat([holdings(), late], ignore_index=True),
                globalx=pd.concat([globalx(), late_globalx], ignore_index=True),
            )
        )
        assert again.values == result.values
        assert again.inputs["holding_rows"] == result.inputs["holding_rows"]

    def test_holding_rows_count_only_captures_up_to_the_end(self, result):
        from positions_stub import holdings

        rows = holdings()
        kept = rows[(rows["capture_date"] <= "2026-10-22") & (rows["as_of"] <= "2026-10-22")]
        assert result.inputs["holding_rows"] == len(kept)


class TestGrossMacros:
    NAMES = (
        "PosGrossQuarter",
        "PosGrossThreeQuarters",
        "PosGrossTen",
        "PosGrossNinety",
        "PosGrossAboveOne",
        "PosGrossAboveTen",
        "PosGrossBelowOne",
        "PosGrossRateLow",
        "PosGrossRateHigh",
        "PosFloorGrossMedian",
        "PosFloorGrossBelowOne",
    )

    def test_the_unnetted_macros_render(self, result):
        ratios = result.values["ratios"]
        gross, floor = ratios["gross"], ratios["floor_delta_gross"]
        macros = result.macros
        for name in self.NAMES:
            assert macros[name] and macros[name] != "--", name
        assert macros["PosGrossQuarter"] == f"{gross['quantiles']['0.25']:.1f}"
        assert macros["PosGrossBelowOne"] == f"{gross['below_one'] * 100:.1f}\\%"
        assert macros["PosFloorGrossMedian"] == f"{floor['quantiles']['0.50']:.2f}"
        low = ratios["rates_gross"]["0.03"]["quantiles"]["0.50"]
        assert macros["PosGrossRateLow"] == f"{low:.2f}"
