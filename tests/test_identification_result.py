"""The `identification` result: the strike rule scored on the census, its macros and table."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.identification import Confusion
from hidden_options.publish import formats
from hidden_options.publish.latex import collect_macros
from hidden_options.publish.results import Result, read_results, write_result
from identification_stub import DATED, ROWS, census


@pytest.fixture(scope="module")
def result() -> Result:
    from hidden_options.measure.identification_result import identification_result

    return identification_result(census(), DATED)


class TestResult:
    def test_named_with_valid_macros(self, result):
        assert result.name == "identification"
        collect_macros({result.name: result})

    def test_values_survive_a_round_trip_through_json(self, result, tmp_path):
        write_result(result, tmp_path)
        assert read_results(tmp_path)["identification"].values == result.values

    def test_census_counts_say_what_was_left_out(self, result):
        counts = result.values["census"]
        assert counts["date"] == "2026-08-14"
        assert (counts["support"], counts["compared"]) == (2, 2)
        assert counts["rows"] == 13
        assert counts["adjusted"] == 2
        assert counts["empty"] == 2
        assert counts["series"] == 9
        assert (counts["flex"], counts["listed"]) == (5, 4)
        assert counts["symbols"] == 2

    def test_rule_scores(self, result):
        values = result.values
        assert values["rule"]["tp"] == 2
        assert values["rule"]["precision"] == pytest.approx(2 / 3)
        assert values["rule_open_interest"]["fn"] == 2540
        # With the series that hold nothing counted too.
        assert values["rule_with_empty"] == Confusion(tp=3, fp=1, fn=3, tn=4).as_dict()

    def test_grid_shares_by_group_and_measure(self, result):
        grid = result.values["grid"]
        assert grid["flex"]["series"]["dollar"] == pytest.approx(0.4)
        assert grid["listed"]["open_interest"]["off_grid"] == pytest.approx(0.2)

    def test_listed_series_the_rule_flags(self, result):
        flagged = result.values["listed_flagged"]
        assert flagged["underlyings"] == 1
        assert flagged["top"] == [{"symbol": "AAA", "series": 1}]
        assert flagged["top_share"] == pytest.approx(1.0)

    def test_largest_flex_series_on_a_whole_dollar(self, result):
        line = result.values["largest_whole_dollar"]
        assert line == {
            "symbol": "BBB",
            "product_symbol": "1BBB",
            "expiry": "2026-12-18",
            "strike": 55.0,
            "open_interest": 2000,
        }

    def test_a_census_without_flex_on_a_whole_dollar_says_so(self):
        from hidden_options.measure.identification_result import identification_result

        rows = tuple(row for row in ROWS if not (row[1][0].isdigit() and row[3] % 1 == 0))
        with pytest.raises(ValueError, match="whole-dollar"):
            identification_result(census(rows), DATED)

    def test_macros(self, result):
        macros = result.macros
        assert macros["CensusSeries"] == "9"
        assert macros["CensusRows"] == "13"
        assert macros["RulePrecision"] == "0.667"
        assert macros["RuleRecall"] == "0.400"
        assert macros["RuleFOne"] == "0.500"
        assert macros["FlexOnGridShare"] == "60.0\\%"
        assert macros["FlexOnGridOpenInterest"] == "78.4\\%"
        assert macros["RuleFalseShare"] == "33.3\\%"
        assert macros["RulePrecisionOpenInterest"] == "0.989"
        assert macros["RulePrecisionWithEmpty"] == "0.750"
        assert macros["RuleRecallWithEmpty"] == "0.500"
        assert macros["RuleFlexMissed"] == "3"
        assert macros["RuleListedFlaggedUnderlyings"] == "1 underlying"
        assert macros["RuleListedFlaggedTopNames"] == "AAA"
        assert macros["RuleExampleProduct"] == "1BBB"
        assert macros["RuleExampleStrike"] == "\\$55.00"
        assert macros["RuleExampleExpiry"] == "18 December 2026"
        assert macros["RuleExampleOpenInterest"] == "2,000 contracts"
        assert macros["FlexDollarShare"] == "40.0\\%"
        assert macros["ListedDollarShare"] == "50.0\\%"

    def test_records_its_inputs(self, result):
        assert result.inputs["census_rows"] == 13
        assert result.inputs["sources"]["census"] == "data/raw/occ_census"


class TestAnalysis:
    def test_registered_analysis_scores_the_dated_census(self, monkeypatch, tmp_path):
        from hidden_options.measure import identification_result as module

        monkeypatch.setattr(module, "load_dated_census", lambda: (census(), DATED))
        monkeypatch.setattr(module, "RESULTS_DIR", tmp_path)
        assert module.identification_analysis().values["census"]["series"] == 9

    def test_refuses_a_census_other_than_the_hidden_share_one(self, monkeypatch, tmp_path):
        from hidden_options.measure import identification_result as module

        stored = Result("hidden_share", {"census": {"date": "2026-08-17"}}, {}, {}, "t")
        write_result(stored, tmp_path)
        monkeypatch.setattr(module, "load_dated_census", lambda: (census(), DATED))
        monkeypatch.setattr(module, "RESULTS_DIR", tmp_path)
        with pytest.raises(ValueError, match="2026-08-17"):
            module.identification_analysis()

    def test_agrees_with_the_hidden_share_census(self, monkeypatch, tmp_path):
        from hidden_options.measure import identification_result as module

        stored = Result("hidden_share", {"census": {"date": "2026-08-14"}}, {}, {}, "t")
        write_result(stored, tmp_path)
        monkeypatch.setattr(module, "load_dated_census", lambda: (census(), DATED))
        monkeypatch.setattr(module, "RESULTS_DIR", tmp_path)
        assert module.identification_analysis().name == "identification"

    def test_dates_the_census_by_its_listed_side(self, monkeypatch, tmp_path):
        from hidden_options.measure import identification_result as module

        seen = {}

        def date_capture(frame, chain_oi):
            seen["rows"], seen["chain"] = len(frame), list(chain_oi["date"])
            return DATED

        def trading_calendar(raw, until):
            seen["until"] = until
            return "calendar"

        def chain_open_interest(chains):
            assert chains == "chains on calendar"
            return pd.DataFrame({"date": pd.to_datetime(["2026-10-22", "2026-10-23"])})

        monkeypatch.setattr(module, "PANEL_END", pd.Timestamp("2026-10-22").date())
        monkeypatch.setattr(module, "load_census", lambda raw: census())
        monkeypatch.setattr(module, "trading_calendar", trading_calendar)
        monkeypatch.setattr(module, "load_chains", lambda raw, calendar: f"chains on {calendar}")
        monkeypatch.setattr(module, "chain_open_interest", chain_open_interest)
        monkeypatch.setattr(module, "date_capture", date_capture)
        frame, dated = module.load_dated_census(tmp_path)
        assert (len(frame), dated) == (len(ROWS), DATED)
        # The calendar and the settlements the census is dated against stop at the panel end.
        assert seen == {
            "rows": len(ROWS),
            "chain": [pd.Timestamp("2026-10-22")],
            "until": pd.Timestamp("2026-10-22"),
        }


class TestTable:
    def test_confusion_table(self, result):
        from hidden_options.measure.identification_table import confusion_table

        text = confusion_table({"identification": result})
        assert "\\label{tab:confusion}" in text
        assert "Strike off the grid & 2 & 1 \\\\" in text
        assert "Strike on the grid & 3 & 3 \\\\" in text
        assert "$0.667$" in text and "$0.400$" in text and "$0.500$" in text

    def test_missing_result_is_named(self):
        from hidden_options.measure.identification_table import confusion_table

        with pytest.raises(KeyError, match="identification"):
            confusion_table({})

    def test_registered_without_matplotlib(self):
        from hidden_options.publish import registry

        assert "hidden_options.measure.identification_result" in registry.REGISTRATION_MODULES
        assert "hidden_options.measure.identification_table" in registry.REGISTRATION_MODULES
        registry.load_registrations()
        assert "confusion" in registry.TABLES.select()
        assert "identification" in registry.ANALYSES.select()


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1, "1 underlying"),
        (0, "0 underlyings"),
        (15, "15 underlyings"),
        (2_000, "2,000 underlyings"),
    ],
)
def test_counted_agrees_in_number(value, text):
    assert formats.counted(value, "underlying") == text


def test_counted_takes_an_irregular_plural():
    assert formats.counted(2, "series", "series") == "2 series"
