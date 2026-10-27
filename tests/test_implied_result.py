"""The `implied_validation` result, its macros and its tables, on the stub world."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.implied_data import STYLE_COLUMNS
from hidden_options.publish.latex import collect_macros
from hidden_options.publish.results import Result, read_results, write_result
from implied_stub import bars, chains, panel


def inputs():
    from hidden_options.measure.implied_data import ImpliedInputs, close_readings

    rows = panel()
    styles = rows.loc[rows["kind"] == "equity", list(STYLE_COLUMNS)]
    return ImpliedInputs(rows, styles, close_readings(chains()), bars(), ["2026-09-03"], False)


@pytest.fixture(scope="module")
def result() -> Result:
    from hidden_options.measure.implied_result import implied_validation_result

    return implied_validation_result(inputs())


class TestResult:
    def test_named_with_valid_macros(self, result):
        assert result.name == "implied_validation"
        collect_macros({result.name: result})

    def test_values_survive_a_round_trip_through_json(self, result, tmp_path):
        write_result(result, tmp_path)
        assert read_results(tmp_path)["implied_validation"].values == result.values

    def test_settings_are_recorded(self, result):
        settings = result.values["settings"]
        assert (settings["rate"], settings["carry"]) == (0.04, 0.0)
        assert settings["sensitivity_rates"] == [0.03, 0.05]
        assert settings["sigma_bounds"] == [1e-4, 5.0]
        assert settings["tree_steps"] == 200
        assert (settings["within"], settings["min_matched"]) == (0.02, 50)
        assert settings["deep_moneyness"] == 0.9

    def test_window(self, result):
        window = result.values["window"]
        assert (window["first_date"], window["last_date"]) == ("2026-09-01", "2026-09-02")
        assert (window["dates"], window["rows"]) == (2, 15)

    def test_every_row_has_a_status(self, result):
        coverage = result.values["coverage"]
        assert coverage["by_status"] == {
            "ok": 9,
            "below_intrinsic": 1,
            "zero_price": 1,
            "expired": 1,
            "no_spot": 2,
            "no_convergence": 1,
        }
        assert coverage["by_kind"]["index"]["ok"] == 2
        assert coverage["by_kind"]["index"]["no_spot"] == 1
        assert coverage["below_intrinsic"] == {
            "rows": 1,
            "deep_calls": 1,
            "top": [{"symbol": "AAA", "rows": 1}],
            "top_share": 1.0,
        }
        assert coverage["no_spot_underlyings"] == ["BBB", "DJX"]
        assert coverage["at_floor"] == 0

    def test_spots(self, result):
        spots = result.values["spots"]
        assert (spots["pairs"], spots["with_spot"]) == (7, 5)
        assert spots["by_source"] == {"bars": 3, "chain": 1, "fraction": 1}
        agreement = spots["agreement"]
        assert (agreement["readings"], agreement["set_aside"]) == (3, 1)

    def test_matches(self, result):
        validation = result.values["validation"]
        assert (validation["matched"], validation["matched_series"]) == (6, 5)
        assert validation["compared"] == 6
        assert validation["by_status"] == {"ok": 6}
        assert validation["by_kind"]["index"]["n"] == 1

    def test_gaps(self, result):
        overall = result.values["validation"]["overall"]
        gaps = np.array([0.01, -0.03, 0.0, 0.0, 0.01, 0.0])
        assert overall["n"] == 6
        assert overall["median_abs"] == pytest.approx(np.median(np.abs(gaps)), abs=1e-6)
        assert overall["within"] == pytest.approx(np.mean(np.abs(gaps) <= 0.02 + 1e-9))
        assert overall["median_diff"] == pytest.approx(np.median(gaps), abs=1e-6)

    def test_gaps_by_style_group(self, result):
        groups = result.values["validation"]["by_group"]
        assert {name: stats["n"] for name, stats in groups.items()} == {
            "strict": 3,
            "clipped": 1,
            "prefix": 1,
            "fallback": 0,
            "index": 1,
        }
        # The unmarked put is European by its prefix, as it was priced.
        assert groups["prefix"]["median_diff"] == pytest.approx(0.0, abs=1e-6)
        assert result.values["validation"]["by_group_right"]["prefix|P"]["n"] == 1

    def test_buckets(self, result):
        validation = result.values["validation"]
        assert validation["by_moneyness"]["1.00-1.05"]["n"] == 4
        assert validation["by_dte"]["8-30"]["n"] == 2
        assert validation["by_bucket"]["1.00-1.05|91-365"]["n"] == 3
        # Buckets with nothing in them are listed too, empty.
        assert validation["by_moneyness"]["<0.70"] == {
            "n": 0,
            "median_abs": None,
            "within": None,
            "median_diff": None,
        }

    def test_rate_sensitivity(self, result):
        rates = result.values["rates"]
        assert set(rates) == {"0.03", "0.05"}
        assert rates["0.03"]["overall"]["n"] == 6
        # A higher rate raises the forward: call volatilities fall, put volatilities rise.
        assert rates["0.05"]["overall"]["median_diff"] != rates["0.03"]["overall"]["median_diff"]

    def test_too_few_matches_validate_no_bucket(self, result):
        domain = result.values["domain"]
        assert (domain["cells"], domain["buckets"]) == (0, [])
        assert domain["of_cells"] == 50
        assert domain["failing_short"] == 10
        assert (result.macros["IvDomainFail"], result.macros["IvDomainFailShort"]) == ("50", "10")

    def test_styles(self, result):
        styles = result.values["styles"]
        assert styles["panel"]["equity_rows"] == 17
        assert styles["panel"]["by_group"] == {
            "strict": 12,
            "clipped": 1,
            "prefix": 3,
            "fallback": 1,
        }
        assert styles["panel"]["unread_share"] == pytest.approx(4 / 17)
        assert styles["window"]["equity_rows"] == 12
        agreement = styles["prefix_agreement"]
        # 2AAA under an AMER/FLEX heading on 3 August contradicts the pairing.
        assert (agreement["checked"], agreement["agree"]) == (13, 12)
        assert (agreement["contradict"], agreement["other"]) == (1, 0)

    def test_macros(self, result):
        macros = result.macros
        assert macros["IvRate"] == "4\\%"
        assert macros["IvRateLow"] == "3\\%"
        assert macros["IvRateHigh"] == "5\\%"
        assert macros["IvTreeSteps"] == "200"
        assert macros["IvFirstDate"] == "1 September 2026"
        assert macros["IvLastDate"] == "2 September 2026"
        assert macros["IvDates"] == "2"
        assert macros["IvRows"] == "15"
        assert macros["IvOkShare"] == "60.0\\%"
        assert macros["IvNoSpot"] == "2"
        assert macros["IvMatched"] == "6"
        assert macros["IvMatchedSeries"] == "5"
        assert macros["IvIndexMatched"] == "1"
        assert macros["IvDomainCells"] == "0"
        assert macros["IvUnreadShare"] == "23.5\\%"
        assert macros["IvMedianBiasCalls"] == "1.00"
        assert macros["IvMedianBiasPuts"] == "0.00"
        assert macros["IvAtFloor"] == "0"
        assert macros["IvFallbackRows"] == "1 series-day"
        assert macros["IvPrefixGap"] == "0.00"
        assert macros["IvBelowTopNames"] == "AAA"
        assert macros["IvBelowTopShare"] == "100.0\\%"
        assert macros["IvSpotSetAside"] == "1"
        assert macros["IvSpotAgreement"] == "0.5\\%"
        assert macros["IvPrefixContradict"] == "1"
        assert macros["IvSigmaLow"] == "0.01\\%"
        assert macros["IvSigmaHigh"] == "500\\%"
        assert macros["IvDeepMoneyness"] == "90\\%"
        assert macros["IvWithinPoints"] == "2"

    def test_records_its_inputs(self, result):
        assert result.inputs["ci_runs"] == ["2026-09-03"]
        assert result.inputs["local_only"] is False
        assert result.inputs["panel_rows"] == 20
        assert result.inputs["style_rows"] == 17
        assert result.inputs["bar_rows"] == 6
        assert result.inputs["panel_end"] == "2026-10-22"


class TestPanelEnd:
    def test_dates_after_the_frozen_panel_end_are_left_out(self, monkeypatch):
        from hidden_options.measure import implied_result

        monkeypatch.setattr(implied_result, "PANEL_END", pd.Timestamp("2026-09-01").date())
        values = implied_result.implied_validation_result(inputs()).values
        assert (values["window"]["last_date"], values["window"]["dates"]) == ("2026-09-01", 1)
        assert values["window"]["panel_end"] == "2026-09-01"
        # The full-panel style counts, the readings and the bars stop at the panel end too.
        assert values["styles"]["panel"]["equity_rows"] == 16
        result = implied_result.implied_validation_result(inputs())
        assert result.inputs["bar_rows"] == 4
        assert result.inputs["reading_rows"] == 9

    def test_the_panel_end_is_one_constant(self):
        from hidden_options import config

        assert pd.Timestamp("2026-10-22").date() == config.PANEL_END


class TestDomain:
    def test_buckets_pass_with_enough_matches(self, monkeypatch):
        from hidden_options.measure import implied_result

        monkeypatch.setattr(implied_result, "MIN_MATCHED", 1)
        values = implied_result.implied_validation_result(inputs()).values
        assert values["domain"]["cells"] > 0
        assert ["1.00-1.05", "91-365"] in values["domain"]["buckets"]
        domain = values["domain"]
        assert 0 < domain["usable_open_interest"] <= domain["ok_open_interest"]
        by_kind = domain["usable_open_interest_by_kind"]
        assert set(by_kind) == {"equity", "index"}
        assert 0 < by_kind["equity"] <= domain["ok_open_interest_by_kind"]["equity"]


class TestAnalysis:
    def test_the_registered_analysis_reads_the_inputs(self, monkeypatch):
        from hidden_options.measure import implied_result

        monkeypatch.setattr(implied_result, "load_inputs", inputs)
        assert implied_result.implied_validation_analysis().values["window"]["rows"] == 15


class TestTables:
    def test_validation_table(self, result):
        from hidden_options.measure.implied_table import validation_table

        text = validation_table({"implied_validation": result})
        assert "\\label{tab:implied}" in text
        assert "0.95--1.00" in text
        assert "$\\leq 7$" in text
        assert "Product prefix" in text

    def test_domain_table(self, result):
        from hidden_options.measure.implied_table import domain_table

        text = domain_table({"implied_validation": result})
        assert "\\label{tab:implied-domain}" in text
        assert "$\\geq 1.30$" in text

    def test_tables_need_the_result(self):
        from hidden_options.measure.implied_table import domain_table, validation_table

        for table in (validation_table, domain_table):
            with pytest.raises(KeyError, match="implied_validation"):
                table({})
