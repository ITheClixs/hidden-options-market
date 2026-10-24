"""The `hidden_share` result end to end, on a small world written in the collectors' layout."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.config import Universe
from hidden_options.measure import hidden_share_result as results_module
from hidden_options.measure.hidden_share_macros import name_list, usd_billions
from hidden_options.measure.hidden_share_result import census_view, hidden_share_result
from hidden_options.publish.latex import collect_macros
from hidden_options.publish.results import read_results, write_result
from hidden_share_stub import CENSUS_DATE, MARK, MID, UNIVERSE, write_world


@pytest.fixture(scope="module")
def raw(tmp_path_factory):
    root = tmp_path_factory.mktemp("raw")
    write_world(root)
    return root


@pytest.fixture(scope="module")
def inputs(raw):
    patch = pytest.MonkeyPatch()
    patch.setattr(results_module, "RAW_DIR", raw)
    patch.setattr(
        results_module,
        "load_universe",
        lambda: Universe(
            treated_single_name=("AAA", "CCC"),
            treated_index_and_etf=("_SPX",),
            control_single_name=("BBB",),
        ),
    )
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
        assert (daily["dates"], daily["captures"], daily["duplicate_captures"]) == (3, 4, 1)
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

    def test_ranges_and_groups(self, result):
        aaa = result.values["daily"]["names"]["AAA"]
        low, high = (f"{aaa[k] * 100:.1f}\\%" for k in ("min", "max"))
        assert result.macros["HiddenQuarterRanges"].startswith(f"AAA from {low} to {high}")
        assert result.values["daily"]["universe_by_group"] == {"programme": 3, "control": 1}
        assert (result.macros["HiddenDailyProgramme"], result.macros["HiddenDailyControl"]) == (
            "3",
            "1",
        )


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

    def test_aaa_value_share(self, result):
        aaa = next(row for row in result.values["value"]["leaders"] if row["symbol"] == "AAA")
        # 3 September is the fourth activity date (index 3) of the world.
        listed = MID * (2030 + 4 * 3) * 100
        flex = MARK * 2500 * 100
        assert aaa["value_share"] == pytest.approx(flex / (flex + listed))


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
