"""Tests for the `predictive` result, its macros and its two paper tables.

The result is what the paper and README print, so the checks are on its shape and on the
strings: every macro is a legal value, the tables render from the values alone, the index
underlying stays out of the sample, and a missing result says what to run.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.predict import result as result_module
from hidden_options.predict.macros import bp, p_value, predictive_macros
from hidden_options.predict.regressions import TABLE_SPECS
from hidden_options.predict.tables import predictive_table, windows_table
from hidden_options.publish import registry
from hidden_options.publish.latex import collect_macros
from hidden_options.publish.results import read_results, write_result
from predict_stub import synthetic_bars, synthetic_daily, synthetic_flex_panel

FLEX = synthetic_flex_panel(names=30)
BARS = synthetic_bars(synthetic_daily(names=30, dates=90))
STARTS = ("2025-02-03", "2025-03-03")


@pytest.fixture(scope="module")
def result():
    return result_module.predictive_result(FLEX, BARS, n_perm=60, later_starts=STARTS)


class TestResult:
    def test_named_and_written_as_json(self, result, tmp_path):
        assert result.name == "predictive"
        write_result(result, tmp_path)
        assert read_results(tmp_path)["predictive"].values == result.values

    def test_six_rows_in_table_order_each_with_a_permutation_p(self, result):
        rows = result.values["rows"]
        assert [(r["predictor"], r["outcome"], r["placebo"]) for r in rows] == list(TABLE_SPECS)
        assert [r["key"] for r in rows] == list(result_module.ROW_KEYS)
        assert all(1 / 61 <= r["permutation_p"] <= 1 for r in rows)

    def test_the_main_rows_permutation_draws_are_kept_for_the_figure(self, result):
        permutation = result.values["permutation"]
        assert len(permutation["null"]) == permutation["n_perm"] == 60
        assert permutation["observed"] == pytest.approx(result.values["rows"][0]["coefficient"])
        assert permutation["p_value"] == result.values["rows"][0]["permutation_p"]

    def test_index_underlyings_stay_out_of_the_sample(self, result):
        sample = result.values["sample"]
        assert sample["index_underlyings"] == 1
        assert sample["equity_underlyings"] == 30
        assert sample["underlyings"] == 30

    def test_windows_start_with_the_full_panel(self, result):
        windows = result.values["windows"]
        assert [w["start"] for w in windows] == ["2025-01-02", *STARTS]
        assert windows[0]["main"] == {
            k: v for k, v in result.values["rows"][0].items() if k not in ("key", "permutation_p")
        }

    def test_robustness_values_are_present(self, result):
        values = result.values
        assert [h["days"] for h in values["horizons"]] == [3, 5, 10]
        assert values["timing"]["outcome"] == "oc_abs_next"
        assert values["top_decile"]["share"] == 0.1
        assert values["max_abs_t"] >= abs(values["rows"][0]["t_stat"])

    def test_qualifying_names_without_bars_are_counted_by_reason(self):
        """A name whose symbol the bar provider does not serve drops out at the join. Only
        delisted and renamed tickers tilt the sample, so the reasons are counted apart."""
        names = {"N05": "GME1", "N06": "BRKB", "N07": "XYZ"}
        flex = FLEX.replace({"underlying": names})
        bars = BARS[~BARS["symbol"].isin(names)]
        found = result_module.predictive_result(flex, bars, n_perm=10, later_starts=STARTS)
        sample = found.values["sample"]
        assert sample["qualifying_underlyings"] == 30
        assert sample["qualifying_min_dates"] == 40
        assert sample["without_bars"] == ["BRKB", "GME1", "XYZ"]
        assert sample["without_bars_by_reason"] == {
            "adjusted_deliverable": 1,
            "share_class": 1,
            "other": 1,
        }
        macros = found.macros
        assert (macros["PredQualifying"], macros["PredQualifyingDates"]) == ("30", "40")
        assert macros["PredNoBars"] == "3"
        assert (macros["PredNoBarsAdjusted"], macros["PredNoBarsShareClass"]) == ("1", "1")
        assert macros["PredNoBarsOther"] == "1"
        assert sample["underlyings"] == 27

    def test_inputs_record_the_data(self, result):
        assert result.inputs["first_date"] == "2025-01-02"
        assert result.inputs["bar_symbols"] == 30


class TestMacros:
    def test_every_macro_is_a_legal_value(self, result):
        macros = collect_macros({"predictive": result})
        assert macros["PredUnderlyings"] == "30"
        assert macros["PredPermutations"] == "60"
        assert macros["PredWindowOneStart"] == "2025-01-02"
        assert {"PredInnovBeta", "PredPlaceboT", "PredHorizonTenT", "PredOpenCloseT"} <= set(macros)

    def test_power_is_the_main_mde_against_the_mean_absolute_return(self, result):
        macros = result.macros
        sample, main = result.values["sample"], result.values["rows"][0]
        share = main["mde80"] / sample["mean_abs_ret"]
        assert macros["PredMDEShare"] == f"{share * 100:.1f}\\%"
        assert macros["PredMeanAbsRet"] == f"{sample['mean_abs_ret'] * 1e4:.0f}"
        assert "PredDetectable" not in macros

    def test_smallest_genuine_p_values_and_each_rows_clustered_p_are_printed(self, result):
        rows = result.values["rows"]
        genuine = [r for r in rows if not r["placebo"]]
        macros = result.macros
        assert macros["PredMinGenuinePermP"] == p_value(min(r["permutation_p"] for r in genuine))
        assert macros["PredMinGenuineClusterP"] == p_value(min(r["p_value"] for r in genuine))
        assert macros["PredPlaceboClusterP"] == p_value(rows[-1]["p_value"])
        # Table-wide minima would point the reader at the placebo row without saying so.
        assert "PredMinPermP" not in macros and "PredMinClusterP" not in macros

    def test_rows_print_their_clustered_standard_error(self, result):
        main = result.values["rows"][0]
        assert result.macros["PredInnovSE"] == bp(main["std_error"])

    def test_the_decile_cut_is_a_change_in_log_open_interest(self, result):
        cut = result.values["top_decile"]["threshold"]
        assert result.macros["PredDecileCut"] == f"{cut:.3f}"

    def test_coefficients_print_in_units_of_ten_to_the_minus_four(self):
        assert bp(-0.0000304) == "-0.30"
        assert bp(0.00062) == "6.20"
        assert bp(-0.0000001) == "0.00"

    def test_small_p_values_keep_a_digit(self):
        assert p_value(0.4321) == "0.43"
        assert p_value(0.0479) == "0.048"
        assert p_value(1 / 1001) == "0.001"

    def test_more_windows_than_names_is_an_error(self, result):
        values = dict(result.values)
        values["windows"] = [values["windows"][0]] * 4
        with pytest.raises(ValueError, match="windows"):
            predictive_macros(values)


class TestTables:
    def test_predictive_table_has_the_six_rows_and_its_notes(self, result):
        tex = predictive_table({"predictive": result})
        assert "\\label{tab:pred}" in tex
        body = tex.split("\\midrule")[1].split("\\bottomrule")[0]
        assert body.count("\\\\") == 6
        assert "Placebo" in body
        assert "60 re-estimations" in tex

    def test_windows_table_has_one_row_per_start(self, result):
        tex = windows_table({"predictive": result})
        body = tex.split("\\midrule")[1].split("\\bottomrule")[0]
        assert body.count("\\\\") == 3
        assert "2025-03-03" in body

    def test_no_negative_zero_is_printed(self, result):
        tex = predictive_table({"predictive": result}) + windows_table({"predictive": result})
        assert "-0.00$" not in tex

    @pytest.mark.parametrize("table", [predictive_table, windows_table])
    def test_a_missing_result_says_what_to_run(self, table):
        with pytest.raises(KeyError, match="hidden-options results --only predictive"):
            table({})


class TestRegistration:
    def test_analysis_and_tables_are_registered(self):
        registry.load_registrations()
        assert "predictive" in registry.ANALYSES.select()
        assert {"predictive", "windows"} <= set(registry.TABLES.select())

    def test_the_registered_analysis_reads_the_panel_and_the_bars_file(self, monkeypatch):
        """Through the real later starts, so the panel runs to December 2025."""
        flex = synthetic_flex_panel(names=30, dates=260)
        bars = synthetic_bars(synthetic_daily(names=30, dates=260))
        seen = {}

        def load(root):
            seen["raw"] = root
            return flex

        def read(path):
            seen["bars"] = path
            return bars

        monkeypatch.setattr(result_module, "load_panel", load)
        monkeypatch.setattr(pd, "read_parquet", read)
        found = result_module.predictive()
        assert found.name == "predictive"
        assert [w["start"] for w in found.values["windows"]][1:] == list(result_module.LATER_STARTS)
        assert seen == {"raw": result_module.RAW_DIR, "bars": result_module.BARS_PATH}
