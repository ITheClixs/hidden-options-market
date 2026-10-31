"""The `hidden_share` result end to end, on a small world written in the collectors' layout."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.config import Universe
from hidden_options.measure import hidden_share_result as results_module
from hidden_options.measure.hidden_share_data import CICapturesError
from hidden_options.measure.hidden_share_macros import name_list, usd_billions
from hidden_options.measure.hidden_share_result import census_view, hidden_share_result
from hidden_options.publish.latex import collect_macros
from hidden_options.publish.results import Result, read_results, write_result
from hidden_share_stub import CENSUS_DATE, MARK, MID, SPOT, UNIVERSE, write_world


@pytest.fixture(scope="module")
def raw(tmp_path_factory):
    root = tmp_path_factory.mktemp("world")
    write_world(root / "raw", root / "ci_captures")
    return root / "raw"


def point_at_world(patch, raw, results):
    """Aim the loaders at the stub world, with `results` standing in for results/."""
    patch.setattr(results_module, "RAW_DIR", raw)
    patch.setattr(results_module, "CI_CAPTURES_DIR", raw.parent / "ci_captures")
    patch.setattr(results_module, "RESULTS_DIR", results)
    patch.setattr(
        results_module,
        "load_universe",
        lambda: Universe(
            treated_single_name=("AAA", "CCC"),
            treated_index_and_etf=("_SPX",),
            control_single_name=("BBB",),
        ),
    )
    for name in (results_module.LOCAL_ONLY_ENV, results_module.ACCEPT_CI_RUNS_ENV):
        patch.setenv(name, "0")


@pytest.fixture(scope="module")
def inputs(raw, tmp_path_factory):
    patch = pytest.MonkeyPatch()
    point_at_world(patch, raw, tmp_path_factory.mktemp("results"))
    try:
        yield results_module.load_inputs()
    finally:
        patch.undo()


@pytest.fixture(scope="module")
def result(inputs):
    return hidden_share_result(inputs)


def test_inputs_carry_the_followed_symbols_and_their_groups(inputs):
    assert dict(inputs.universe) == UNIVERSE


def test_named_with_valid_macros(result):
    assert result.name == "hidden_share"
    assert collect_macros({"hidden_share": result}) == dict(sorted(result.macros.items()))


def test_values_survive_a_round_trip_through_json(result, tmp_path):
    write_result(result, tmp_path)
    assert read_results(tmp_path)["hidden_share"].values["census"] == result.values["census"]


class TestCensus:
    def test_dated_by_the_listed_side(self, result):
        census = result.values["census"]
        assert census["date"] == f"{CENSUS_DATE:%Y-%m-%d}"
        # DDD has no chain, so three symbols are compared and all three agree.
        assert (census["support"], census["compared"]) == (3, 3)
        assert result.macros["HiddenCensusDate"] == "1 September 2026"

    def test_distribution_over_ordinary_underlyings(self, result):
        census = result.values["census"]
        assert census["symbols"] == 5
        assert census["underlyings"] == 4
        assert census["only_adjusted"] == ["EEE"]
        assert census["with_flex"] == 3
        assert census["at_least"] == {"10": 1, "25": 1, "50": 1}
        assert result.macros["HiddenCensusHalfNames"] == "AAA"
        assert census["report_coverage"] == pytest.approx(1.0)

    def test_index_products_on_the_census_date(self, result):
        (spx,) = result.values["census_indices"]
        assert spx["symbol"] == "SPX"
        # SPX and SPXW both count; the mini XSP does not join the FLEX side.
        assert spx["flex_oi"] == 15_000
        assert result.macros["HiddenCensusSpx"] == f"{spx['share'] * 100:.0f}\\%"

    def test_census_view_matches_the_result(self, inputs, result):
        view = census_view(inputs)
        assert len(view.ordinary) == result.values["census"]["underlyings"]


class TestDaily:
    def test_settlements_captures_and_duplicates(self, result):
        daily = result.values["daily"]
        assert (daily["dates"], daily["span"], daily["missing_dates"]) == (3, 3, [])
        assert (daily["captures"], daily["duplicate_captures"]) == (5, 2)
        assert daily["captures_by_root"] == {"local": 3, "ci": 2}
        assert daily["first_date"] == "2026-09-01"
        assert daily["not_in_search"] == ["SPX"]
        assert daily["complete"] == 4

    def test_stable_counts_require_every_date(self, result):
        stable = result.values["daily"]["stable"]
        assert stable["10"]["symbols"] == ["AAA", "SPX"]
        assert stable["25"]["symbols"] == ["AAA", "SPX"]
        assert stable["50"]["symbols"] == ["AAA"]
        assert stable["10"]["by_group"] == {"programme": 2, "control": 0}
        assert result.macros["HiddenStableHalfNames"] == "AAA"
        assert result.macros["HiddenStableTen"] == "2"

    def test_index_range_macros(self, result):
        spx = result.values["daily"]["names"]["SPX"]
        assert result.macros["HiddenSpxLow"] == f"{spx['min'] * 100:.1f}\\%"
        either = min(spx["min"], result.values["index_full_book"]["SPX"]["min"])
        assert result.macros["HiddenSpxEitherLow"] == f"{either * 100:.1f}\\%"

    def test_ranges_and_groups(self, result):
        aaa = result.values["daily"]["names"]["AAA"]
        low, high = (f"{aaa[k] * 100:.1f}\\%" for k in ("min", "max"))
        assert result.macros["HiddenQuarterRanges"].startswith(f"AAA from {low} to {high}")
        assert result.values["daily"]["universe_by_group"] == {"programme": 3, "control": 1}
        assert (result.macros["HiddenDailyProgramme"], result.macros["HiddenDailyControl"]) == (
            "3",
            "1",
        )


class TestCoverage:
    def test_ci_fills_the_settlement_the_local_root_lacks(self, result):
        coverage = result.values["daily"]["coverage"]
        assert coverage["local"] == 2
        assert coverage["ci_only"] == ["2026-09-02"]
        assert coverage["both"] == 1

    def test_the_two_roots_agree_where_both_cover_a_settlement(self, result):
        coverage = result.values["daily"]["coverage"]
        # AAA, BBB and CCC on 3 September, each read locally and from CI.
        assert coverage["cross_root_symbols"] == 3
        assert coverage["set_aside"] == []
        assert result.macros["HiddenDailyCrossRoot"] == "3"

    def test_coverage_macros(self, result):
        assert result.macros["HiddenDailySpan"] == "3"
        assert result.macros["HiddenDailyMissing"] == "0"
        assert result.macros["HiddenDailyMissingDates"] == "none"


class TestChecks:
    def test_the_two_flex_sources_agree(self, result):
        census, daily = (result.values["reconciliation"][k] for k in ("census", "daily"))
        assert census["symbol_dates"] == 4
        assert daily["symbol_dates"] == 10
        assert daily["max_rel_diff"] == 0.0
        assert result.macros["HiddenReconAgreeing"] == "14"

    def test_adjusted_classes_are_kept_apart(self, result):
        adjusted = result.values["adjusted"]
        assert (adjusted["census"], adjusted["census_with_flex"]) == (2, 1)
        assert adjusted["census_flex"][0]["symbol"] == "AAA1"
        assert list(adjusted["daily_with_flex"]) == ["AAA1"]

    def test_whole_book_index_shares_equal_the_restricted_ones_when_nothing_expires(self, result):
        whole = result.values["index_full_book"]["SPX"]
        assert whole["dates"] == 3
        assert whole["min"] == pytest.approx(result.values["daily"]["names"]["SPX"]["min"])
        assert result.macros["HiddenSpxFullLow"] == result.macros["HiddenSpxLow"]

    def test_reconciliation_beyond_one_percent_stops_the_analysis(self):
        from hidden_options.measure.hidden_share_checks import reconciliation_summary

        frame = pd.DataFrame(
            {
                "date": pd.Timestamp("2026-09-01"),
                "symbol": ["A", "B", "C"],
                "flex_oi_search": [100, 100, 100],
                "flex_oi_report": [98, 97, 100],
                "rel_diff": [0.02, 0.03, 0.0],
            }
        )
        with pytest.raises(ValueError, match="1%"):
            reconciliation_summary(frame)

    def test_expiry_check_is_zero_when_nothing_expires(self, result):
        check = result.values["expiry_check"]
        assert check["max_abs_diff"] == 0.0
        assert check["moved"] == 0


class TestValue:
    def test_value_share_on_dates_every_name_is_priced(self, result):
        value = result.values["value"]
        assert (value["dates"], value["complete_dates"], value["names"]) == (3, 3, 4)
        assert value["theo_share"] == 0.0

    def test_largest_line_and_its_market(self, result):
        line = result.values["value"]["largest_line"]
        assert (line["symbol"], line["root"], line["right"]) == ("SPX", "2SPX", "C")
        assert line["value"] == pytest.approx(9000 * MARK * 100)
        assert line["opposite_open_interest"] == 0
        assert result.macros["HiddenLineRight"] == "call"
        listed = result.values["value"]["leaders"]
        assert {row["symbol"] for row in listed} == set(UNIVERSE)

    def test_composition_of_flex_value(self, result):
        composition = result.values["value"]["composition"]
        # Every FLEX line is a call struck at 100 against a spot of 105.
        assert composition["deep_share"] == pytest.approx(1.0)
        assert composition["paired_share"] == 0.0
        assert composition["intrinsic"] / composition["value"] == pytest.approx((SPOT - 100) / MARK)
        assert result.macros["HiddenValuePaired"] == "0\\%"
        assert result.macros["HiddenValueDeepThreshold"] == "90\\%"

    def test_aaa_value_share(self, result):
        aaa = next(row for row in result.values["value"]["leaders"] if row["symbol"] == "AAA")
        # 3 September is the fourth activity date (index 3) of the world.
        listed = MID * (2030 + 4 * 3) * 100
        flex = MARK * 2500 * 100
        assert aaa["value_share"] == pytest.approx(flex / (flex + listed))


class TestPanelEnd:
    """Settlements, reports and chain readings after the frozen panel end change nothing."""

    @staticmethod
    @pytest.fixture(scope="class")
    def frozen(inputs):
        patch = pytest.MonkeyPatch()
        patch.setattr(results_module, "PANEL_END", pd.Timestamp("2026-09-02").date())
        try:
            yield hidden_share_result(inputs)
        finally:
            patch.undo()

    def test_the_daily_shares_stop_at_the_panel_end(self, frozen):
        daily = frozen.values["daily"]
        assert (daily["first_date"], daily["last_date"], daily["dates"]) == (
            "2026-09-01",
            "2026-09-02",
            2,
        )
        # The captures of the 3 September settlement, and their duplicates, are not counted.
        assert (daily["captures"], daily["duplicate_captures"]) == (2, 0)
        assert daily["captures_by_root"] == {"local": 1, "ci": 1}
        assert daily["coverage"]["both"] == 0

    def test_the_census_does_not_move(self, frozen, result):
        assert frozen.values["census"] == result.values["census"]

    def test_the_inputs_are_cut_and_say_where(self, frozen, result):
        assert frozen.inputs["panel_end"] == "2026-09-02"
        assert frozen.inputs["report_rows"] < result.inputs["report_rows"]
        assert frozen.inputs["chain_rows"] < result.inputs["chain_rows"]
        assert frozen.inputs["capture_rows"] < result.inputs["capture_rows"]

    def test_the_value_share_uses_no_later_report(self, frozen):
        assert frozen.values["value"]["dates"] == 2

    def test_a_panel_end_after_the_data_changes_nothing(self, monkeypatch, inputs, result):
        monkeypatch.setattr(results_module, "PANEL_END", pd.Timestamp("2026-12-31").date())
        again = hidden_share_result(inputs)
        assert again.values == result.values
        assert again.macros == result.macros


class TestLoadInputsPanelEnd:
    """`load_inputs` reads no FLEX report, and builds no calendar, past the panel end."""

    def test_reports_and_the_calendar_stop_at_the_panel_end(self, monkeypatch, raw, tmp_path):
        point_at_world(monkeypatch, raw, tmp_path)
        end = pd.Timestamp("2026-09-02")
        monkeypatch.setattr(results_module, "PANEL_END", end.date())
        seen = []
        real = results_module.trading_calendar
        monkeypatch.setattr(
            results_module,
            "trading_calendar",
            lambda root, until=None: seen.append(until) or real(root, until),
        )

        loaded = results_module.load_inputs()

        assert seen == [end]
        assert loaded.reports["report_date"].max() == end
        # The stub world has reports to 4 September; the uncut loader would return them.
        monkeypatch.setattr(results_module, "PANEL_END", pd.Timestamp("2026-09-04").date())
        assert results_module.load_inputs().reports["report_date"].max() == pd.Timestamp(
            "2026-09-04"
        )


class TestCIGuard:
    """Without the CI captures the daily numbers would quietly shrink; the loader refuses."""

    def committed(self, folder, runs):
        write_result(
            Result("hidden_share", {}, {}, {"ci_runs": runs}, "2026-10-24T00:00:00+00:00"),
            folder,
        )

    def test_without_the_ci_directory_the_analysis_refuses(self, monkeypatch, raw, tmp_path):
        point_at_world(monkeypatch, raw, tmp_path / "results")
        monkeypatch.setattr(results_module, "CI_CAPTURES_DIR", tmp_path / "absent")
        with pytest.raises(CICapturesError, match="--local-only"):
            results_module.load_inputs()

    def test_local_only_reads_no_ci_and_marks_the_result(self, monkeypatch, raw, tmp_path):
        point_at_world(monkeypatch, raw, tmp_path / "results")
        monkeypatch.setattr(results_module, "CI_CAPTURES_DIR", tmp_path / "absent")

        local = results_module.load_inputs(local_only=True)
        result = hidden_share_result(local)

        assert (local.local_only, list(local.ci_runs)) == (True, [])
        assert result.inputs["local_only"] is True
        assert result.values["daily"]["missing_dates"] == ["2026-09-02"]

    def test_the_local_only_switch_can_come_from_the_environment(self, monkeypatch, raw, tmp_path):
        point_at_world(monkeypatch, raw, tmp_path / "results")
        monkeypatch.setattr(results_module, "CI_CAPTURES_DIR", tmp_path / "absent")
        monkeypatch.setenv(results_module.LOCAL_ONLY_ENV, "1")
        assert results_module.load_inputs().local_only

    def test_a_ci_run_set_unlike_the_committed_one_is_refused(self, monkeypatch, raw, tmp_path):
        point_at_world(monkeypatch, raw, tmp_path / "results")
        self.committed(tmp_path / "results", ["2026-09-03", "2026-09-05", "2026-09-09"])

        with pytest.raises(CICapturesError, match="2026-09-09"):
            results_module.load_inputs()
        accepted = results_module.load_inputs(accept_ci_runs=True)
        assert list(accepted.ci_runs) == ["2026-09-03", "2026-09-05"]

    def test_the_committed_run_set_passes(self, monkeypatch, raw, tmp_path):
        point_at_world(monkeypatch, raw, tmp_path / "results")
        self.committed(tmp_path / "results", ["2026-09-03", "2026-09-05"])
        assert results_module.load_inputs().local_only is False

    def test_cli_flags_reach_the_analysis(self, monkeypatch, tmp_path):
        import os

        from hidden_options import cli
        from hidden_options.publish import registry

        for attr, kind in (("ANALYSES", "analysis"), ("FIGURES", "figure"), ("TABLES", "table")):
            monkeypatch.setattr(registry, attr, registry.Registry(kind))
        monkeypatch.setattr(registry, "REGISTRATION_MODULES", ())
        for name in (results_module.LOCAL_ONLY_ENV, results_module.ACCEPT_CI_RUNS_ENV):
            monkeypatch.setenv(name, "0")
        seen = {}

        def analysis():
            seen.update(
                local=os.environ[results_module.LOCAL_ONLY_ENV],
                accept=os.environ[results_module.ACCEPT_CI_RUNS_ENV],
            )
            return Result("hidden_share", {}, {}, {}, "2026-10-24T00:00:00+00:00")

        registry.ANALYSES.register("hidden_share")(analysis)
        args = ["results", "--root", str(tmp_path), "--local-only", "--accept-ci-runs"]

        assert cli.main(args) == 0
        assert seen == {"local": "1", "accept": "1"}


def test_registered_analysis_runs_the_loaders(monkeypatch, inputs):
    monkeypatch.setattr(results_module, "load_inputs", lambda: inputs)
    assert results_module.hidden_share_analysis().name == "hidden_share"


@pytest.mark.parametrize(
    ("names", "text"),
    [([], "none"), (["RUT"], "RUT"), (["A", "B"], "A and B"), (["A", "B", "C"], "A, B and C")],
)
def test_name_list(names, text):
    assert name_list(names) == text


def test_usd_billions():
    assert usd_billions(14_744_184_167.6) == "\\$14.7bn"


def test_dates_are_iso_in_values(result):
    pd.Timestamp(result.values["value"]["last_date"])
    pd.Timestamp(result.values["value"]["largest_line"]["expiry"])


class TestTable:
    def test_census_and_daily_side_by_side(self, result):
        from hidden_options.measure.hidden_share_table import hidden_share_table

        text = hidden_share_table({"hidden_share": result})

        assert "\\label{tab:hidden}" in text
        assert "At least 50\\% & 1 & 1 \\\\" in text
        assert "Underlyings & 4 & 4 \\\\" in text
        assert result.macros["HiddenCensusMedian"] in text
        assert result.macros["HiddenDailyAggregateLow"] in text

    def test_the_daily_column_is_the_followed_list_and_says_so(self, result):
        from hidden_options.measure.hidden_share_table import hidden_share_table

        text = hidden_share_table({"hidden_share": result})
        assert "option-income programmes" in text
        assert "of the 3 in that span" in text

    def test_a_count_resting_on_the_index_rule_is_marked(self, result):
        from dataclasses import replace

        from hidden_options.measure.hidden_share_table import hidden_share_table

        values = {**result.values}
        values["index_full_book"] = {
            **values["index_full_book"],
            "SPX": {**values["index_full_book"]["SPX"], "min": 0.49},
        }
        daily = {**values["daily"], "stable": {**values["daily"]["stable"]}}
        daily["stable"]["50"] = {"count": 1, "symbols": ["SPX"], "by_group": {}}
        values["daily"] = daily
        text = hidden_share_table({"hidden_share": replace(result, values=values)})

        assert "At least 50\\% & 1 & 1$^{\\dagger}$ \\\\" in text
        assert "$^{\\dagger}$SPX" in text

    def test_registered_and_loaded_without_matplotlib(self):
        from hidden_options.publish import registry

        assert "hidden_options.measure.hidden_share_result" in registry.REGISTRATION_MODULES
        assert "hidden_options.measure.hidden_share_table" in registry.REGISTRATION_MODULES
        registry.load_registrations()
        assert "hidden_share" in registry.TABLES.select()
        assert "hidden_share" in registry.ANALYSES.select()

    def test_missing_result_is_named(self):
        from hidden_options.measure.hidden_share_table import hidden_share_table

        with pytest.raises(KeyError, match="hidden_share"):
            hidden_share_table({})
