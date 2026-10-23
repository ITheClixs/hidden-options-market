"""The pipeline from report text to published number, run on committed fixtures.

CI checks out only what is committed, and `data/` is git-ignored, so none of the raw
captures exist there. Everything below runs on the small real files in `tests/fixtures/`
and refuses to touch the network:

* ``flex_equity_2026-10-22.txt`` and ``flex_index_2026-10-22.txt`` are OCC's FLEX open
  interest reports for activity date 2026-10-22, cut down to whole option classes so
  that every ``CLASS TOTALS`` line still reconciles with the rows above it, with the
  trailing padding stripped from each line. The equity one keeps a class that straddles
  a page break.
* ``holdings_CONY_2026-10-22.csv`` is a fund's holdings file, reduced to the option legs
  that match the open interest below and a few non-option rows.
* ``occ_open_interest_COIN_2026-10-22.csv`` and ``cboe_chain_COIN_2026-10-22.csv`` are the
  series-level open interest and the listed chain for COIN, limited to two expiries and
  to strikes from 160 to 190.

Rows are as the sources published them. The CSV files hold the frames the collectors
store, so the tests below check them against the collectors' column lists.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from hidden_options.collect import http, occ_flex
from hidden_options.collect.cboe import CHAIN_COLUMNS
from hidden_options.collect.holdings import HOLDINGS_COLUMNS
from hidden_options.collect.http import build_session
from hidden_options.collect.occ import OPEN_INTEREST_COLUMNS
from hidden_options.collect.storage import write_frame
from hidden_options.measure.flex_panel import daily_inventory, load_panel, summarise_panel
from hidden_options.measure.gamma_gap import gamma_gap
from hidden_options.measure.synthetic import (
    find_combo_candidates,
    find_synthetic_legs,
    reconcile_with_holdings,
)
from hidden_options.publish import Result, read_results, render_macros, write_result

FIXTURES = Path(__file__).parent / "fixtures"
REPORT_DATE = date(2026, 10, 22)
MAX_FIXTURE_SERIES = 60

HOLDINGS_FILE = "holdings_CONY_2026-10-22.csv"
OPEN_INTEREST_FILE = "occ_open_interest_COIN_2026-10-22.csv"
CHAIN_FILE = "cboe_chain_COIN_2026-10-22.csv"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("fixture tests must not use the network")

    monkeypatch.setattr(requests.Session, "get", refuse)


def read_payload(kind: str) -> bytes:
    return (FIXTURES / f"flex_{kind}_{REPORT_DATE}.txt").read_bytes()


def read_frame(name: str, date_columns: Iterable[str]) -> pd.DataFrame:
    """A fixture CSV with dates as `datetime.date`, the way the collectors store them."""
    frame = pd.read_csv(FIXTURES / name)
    for column in date_columns:
        frame[column] = pd.to_datetime(frame[column]).dt.date
    return frame


def parse_fixture_reports() -> dict[str, occ_flex.FlexReport]:
    return {
        kind: occ_flex.parse_report(read_payload(kind), kind, REPORT_DATE)
        for kind in occ_flex.REPORT_KINDS
    }


def store_reports(root: Path, reports: Iterable[occ_flex.FlexReport]) -> None:
    """Write each report where the collector files it, so `load_panel` can find it."""
    for report in reports:
        write_frame(report.frame, root / occ_flex.snapshot_path(report))


class TestFlexReports:
    @pytest.mark.parametrize("kind", sorted(occ_flex.REPORT_KINDS))
    def test_report_parses_and_every_class_total_reconciles(self, kind):
        report = occ_flex.parse_report(read_payload(kind), kind, REPORT_DATE)

        assert 0 < report.n_series <= MAX_FIXTURE_SERIES
        assert report.class_totals_checked > 0
        assert report.class_totals_matched == report.class_totals_checked
        assert occ_flex.stated_activity_date(read_payload(kind)) == REPORT_DATE

    def test_fetch_report_reads_a_payload_without_the_network(self, monkeypatch):
        """The whole fetch path, including the date the header states, on fixture bytes."""
        monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)
        asked: list[dict] = []

        class FixtureSession:
            def get(self, _url, params, timeout):
                asked.append(params)
                return SimpleNamespace(status_code=200, ok=True, content=read_payload("index"))

        report = occ_flex.fetch_report(FixtureSession(), date(2026, 10, 23), "index")

        assert report.report_date == REPORT_DATE  # the header's date, not the one asked for
        assert report.kind == "index"
        assert asked[0]["optionType"] == "I"
        assert report.class_totals_matched == report.class_totals_checked

    def test_the_network_guard_is_in_force(self):
        with pytest.raises(AssertionError, match="network"):
            build_session().get("https://marketdata.theocc.com/flex-reports")


class TestPanelFromReports:
    @pytest.fixture
    def panel(self, tmp_path):
        store_reports(tmp_path, parse_fixture_reports().values())
        return load_panel(tmp_path)

    def test_both_kinds_load_as_one_dated_panel(self, panel):
        assert panel["kind"].value_counts().to_dict() == {"equity": 29, "index": 28}
        assert set(panel["report_date"]) == {pd.Timestamp(REPORT_DATE)}
        assert summarise_panel(panel).underlyings == 13

    def test_availability_is_the_next_weekday(self, panel):
        """2026-10-22 is the panel's last date, so it takes the following business day."""
        assert set(panel["available_at"]) == {pd.Timestamp("2026-10-23")}

    def test_exercise_style_comes_from_the_class_heading(self, panel):
        styles = panel.groupby("class_name")["exercise_style"].first().to_dict()

        assert styles["Apple Inc (AMER/FLEX)"] == "american"
        assert styles["Aurora Innovation, Inc. (AMER/"] == "american"  # marker clipped
        assert styles["Alcoa Corporation (EURO/FLEX)"] == "european"
        assert styles["ABEONA THERAPEUTICS INC. (EURO"] == "european"
        assert styles["Cboe Bitcoin U.S. ETF Index Op"] == "european"  # index default
        assert styles["American Airlines Group, Inc."] is None  # unmarked equity

    def test_daily_inventory_adds_a_known_underlying_up(self, panel):
        """American Airlines, summed by hand from the report rows."""
        daily = daily_inventory(panel).set_index("underlying")
        row = daily.loc["AAL"]

        assert row["series"] == 9
        assert row["open_interest"] == 73440
        assert row["call_open_interest"] == 10680 + 10150 + 23258 + 4295 + 11575
        assert row["put_open_interest"] == 817 + 1465 + 2450 + 8750
        # Only the 11/06/2026 and 11/23/2026 calls expire within sixty days of 10/22.
        assert row["near_dated_open_interest"] == 10680 + 10150

    def test_inventory_conserves_the_reports_open_interest(self, panel):
        daily = daily_inventory(panel)
        reports = parse_fixture_reports().values()

        assert len(daily) == 13
        assert daily["open_interest"].sum() == sum(r.open_interest for r in reports)
        assert (daily["call_open_interest"] + daily["put_open_interest"]).equals(
            daily["open_interest"]
        )


def test_fixture_pipeline_runs_end_to_end(tmp_path):
    reports = parse_fixture_reports()
    store_reports(tmp_path / "raw", reports.values())

    panel = load_panel(tmp_path / "raw")
    daily = daily_inventory(panel)
    total_oi = int(daily["open_interest"].sum())
    total_mark = float(daily["mark_value"].sum())

    result = Result(
        name="fixture_inventory",
        # numpy scalars, as an analysis computes them
        values={
            "series": daily["series"].sum(),
            "open_interest": daily["open_interest"].sum(),
            "mark_value": daily["mark_value"].sum(),
        },
        macros={
            "FixtureOi": f"{total_oi:,}",
            "FixtureMark": f"\\${total_mark / 1e6:,.1f}m",
        },
        inputs={"report_date": str(REPORT_DATE), "rows": len(panel)},
        generated_at="2026-10-23T12:00:00+00:00",
    )
    write_result(result, tmp_path / "results")
    macros = render_macros(read_results(tmp_path / "results"))

    assert len(panel) == sum(report.n_series for report in reports.values())
    assert total_oi == sum(report.open_interest for report in reports.values())
    assert f"\\newcommand{{\\FixtureOi}}{{{total_oi:,}}}\n" in macros
    assert "\\newcommand{\\FixtureMark}{\\$312.2m}\n" in macros
    assert macros.count("\\newcommand") == 2


class TestFundLegs:
    @pytest.fixture
    def open_interest(self):
        return read_frame(OPEN_INTEREST_FILE, ["expiry"])

    @pytest.fixture
    def holdings(self):
        return read_frame(HOLDINGS_FILE, ["as_of", "expiry"])

    def test_synthetic_legs_are_attributed_to_the_fund_that_holds_them(
        self, open_interest, holdings
    ):
        legs = find_synthetic_legs(open_interest)

        matched = reconcile_with_holdings(legs, holdings)

        assert matched["strike"].tolist() == [170.01, 185.01]
        assert matched["leg_right"].tolist() == ["P", "P"]
        assert matched["matched_fund"].tolist() == ["CONY", "CONY"]
        # The fund reports 11,740 written puts; the series carries a little more.
        assert matched["disclosed_contracts"].tolist() == [-11740.0, -9525.0]
        assert matched["leg_open_interest"].tolist() == [12540.0, 9525.0]

    def test_matched_call_and_put_series_are_not_fund_legs(self, open_interest):
        combos = find_combo_candidates(open_interest)

        assert combos["strike"].tolist() == [175.0, 180.0, 190.02, 190.0]
        assert combos.loc[combos["is_offset_strike"], "strike"].tolist() == [190.02]
        assert not set(combos["strike"]) & {170.01, 185.01}


class TestGammaGap:
    def test_series_missing_from_the_listed_chain_are_priced(self):
        chain = read_frame(CHAIN_FILE, ["expiry"])
        open_interest = read_frame(OPEN_INTEREST_FILE, ["expiry"])

        found = gamma_gap(chain, open_interest, pd.Timestamp(REPORT_DATE))

        assert found is not None
        assert found["symbol"] == "COIN"
        # The three series the chain does not list: 170.01 and 185.01 puts, 190.02 both.
        assert found["flex_series"] == 3
        assert found["flex_open_interest"] == 12540 + 9525 + 1760 + 1760
        assert 0 < found["share_residual"] < found["share_gross"]


class TestFixtureSchemas:
    """A collector that changes its columns must be noticed here, not by a stale fixture."""

    @pytest.mark.parametrize(
        "name, date_columns, columns",
        [
            (HOLDINGS_FILE, ["as_of", "expiry"], HOLDINGS_COLUMNS),
            (OPEN_INTEREST_FILE, ["expiry"], OPEN_INTEREST_COLUMNS),
            (CHAIN_FILE, ["expiry"], CHAIN_COLUMNS),
        ],
    )
    def test_columns_match_what_the_collector_stores(self, name, date_columns, columns):
        assert tuple(read_frame(name, date_columns).columns) == columns

    def test_chain_fixture_stays_small(self):
        assert len(read_frame(CHAIN_FILE, ["expiry"])) <= 100
