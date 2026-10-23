"""Tests for the authoritative OCC FLEX report parser.

The report is fixed-layout text and carries its own per-class totals, so the parser is
checked against those totals as well as against the fields. The fixture reproduces the
real layout, including a FLEX series struck on the standard grid, which is the case
that defeats any strike-based heuristic.
"""

from __future__ import annotations

from datetime import date

import pytest

from hidden_options.collect import occ_flex
from hidden_options.collect.http import FetchResult
from hidden_options.collect.occ_flex import (
    FlexReportAbsent,
    FlexReportError,
    fetch_report,
    parse_report,
    snapshot_path,
    strip_flex_prefix,
)

REPORT = (
    b" THE OPTIONS CLEARING CORPORATION - CHICAGO, ILLINOIS       SYSTEM DATE 08/14/26\n"
    b" EQUITY FLEX OPEN INTEREST REPORT                         ACTIVITY DATE 08/14/26\n"
    b"\n"
    b" MARK PRICES NOTED ON THIS REPORT ARE DERIVED BY THE CORPORATION FROM FACTORS\n"
    b"\n"
    b"                   EXPIRATION  STRIKE        MARK     OPEN\n"
    b"      SYMBOL  P/C  MO DAY  YR  PRICE         PRICE    INTEREST\n"
    b"\n"
    b" American Airlines Group, Inc.\n"
    b"      1AAL     C   09 02 2026  00021 960      0.0081     52850\n"
    b"      1AAL     C   11 06 2026  00016 250      0.8880     10680\n"
    b"\n"
    b"                          ***  CLASS TOTALS  ***         63530\n"
    b"\n"
    b" AAON INC (AMER/FLEX)\n"
    b"      1AAON    C   08 21 2026  00099 000      0.3920       500\n"
    b"\n"
    b"                          ***  CLASS TOTALS  ***           500\n"
)


class TestParseReport:
    def test_parses_every_series_row(self):
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        assert report.n_series == 3

    def test_class_totals_reconcile(self):
        """The report carries its own totals; disagreement means a parse error."""
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        assert report.class_totals_checked == 2
        assert report.class_totals_matched == 2

    def test_reconstructs_split_strike(self):
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        assert report.frame.iloc[0]["strike"] == pytest.approx(21.96)

    def test_captures_mark_price(self):
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        assert report.frame.iloc[1]["mark_price"] == pytest.approx(0.888)

    def test_parses_expiry(self):
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        assert report.frame.iloc[0]["expiry"] == date(2026, 9, 2)

    def test_attaches_the_class_name(self):
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        assert "American Airlines" in report.frame.iloc[0]["class_name"]
        assert "AAON" in report.frame.iloc[2]["class_name"]

    def test_strips_the_flex_root_prefix(self):
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        assert report.frame.iloc[0]["underlying"] == "AAL"

    def test_includes_flex_struck_on_the_standard_grid(self):
        """1AAON at 99.000 is FLEX at a round strike. Any strike-based heuristic
        misses it, which is why this report supersedes that approach."""
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        aaon = report.frame[report.frame["underlying"] == "AAON"].iloc[0]
        assert aaon["strike"] == pytest.approx(99.00)

    def test_totals_open_interest(self):
        assert parse_report(REPORT, "equity", date(2026, 8, 14)).open_interest == 64030

    def test_hashes_payload(self):
        assert len(parse_report(REPORT, "equity", date(2026, 8, 14)).payload_sha256) == 64

    def test_rejects_a_non_report_payload(self):
        with pytest.raises(FlexReportError, match="not a FLEX"):
            parse_report(b"File requested does not exist.", "equity", date(2026, 8, 14))

    def test_rejects_a_report_with_no_rows(self):
        header = b" EQUITY FLEX OPEN INTEREST REPORT\n\n"
        with pytest.raises(FlexReportError, match="no series rows"):
            parse_report(header, "equity", date(2026, 8, 14))


class TestStripPrefix:
    @pytest.mark.parametrize(
        "root,expected", [("1AAL", "AAL"), ("2DJX", "DJX"), ("4SPY", "SPY"), ("AAPL", "AAPL")]
    )
    def test_removes_leading_digits(self, root, expected):
        assert strip_flex_prefix(root) == expected


class TestSnapshotPath:
    def test_partitions_by_activity_date_not_capture_date(self):
        """Capture date is meaningless for a report with a publication lag."""
        report = parse_report(REPORT, "equity", date(2026, 8, 14))
        assert snapshot_path(report) == "occ_flex/date=2026-08-14/equity.parquet"


def _serve(monkeypatch, content: bytes) -> None:
    monkeypatch.setattr(occ_flex, "fetch", lambda *_a, **_k: FetchResult("u", 200, content))


# A real report is megabytes; the fixture is padded past the short-body threshold.
FULL_SIZE = REPORT + b"\n" * 2000


class TestFetchReport:
    def test_stamps_the_date_the_report_states_about_itself(self, monkeypatch):
        """OCC can answer a request for a date it has not published with an earlier day's
        report. Trusting the requested date would file one settlement under two dates."""
        _serve(monkeypatch, FULL_SIZE)
        report = fetch_report(object(), date(2026, 8, 17), "equity")

        assert report.report_date == date(2026, 8, 14)
        assert set(report.frame["report_date"]) == {date(2026, 8, 14)}
        assert snapshot_path(report) == "occ_flex/date=2026-08-14/equity.parquet"

    def test_requested_date_stands_when_it_matches_the_header(self, monkeypatch):
        _serve(monkeypatch, FULL_SIZE)
        assert fetch_report(object(), date(2026, 8, 14), "equity").report_date == date(2026, 8, 14)

    def test_falls_back_to_the_requested_date_without_a_header_date(self, monkeypatch):
        headerless = FULL_SIZE.replace(b"ACTIVITY DATE 08/14/26", b"")
        _serve(monkeypatch, headerless)
        assert fetch_report(object(), date(2026, 8, 17), "equity").report_date == date(2026, 8, 17)

    def test_unparseable_header_date_falls_back_to_the_requested_date(self, monkeypatch):
        _serve(monkeypatch, FULL_SIZE.replace(b"ACTIVITY DATE 08/14/26", b"ACTIVITY DATE 13/45/26"))
        assert fetch_report(object(), date(2026, 8, 14), "equity").report_date == date(2026, 8, 14)

    def test_short_body_means_no_report_is_available(self, monkeypatch):
        _serve(monkeypatch, b"File requested does not exist.")
        with pytest.raises(FlexReportAbsent, match="no report available"):
            fetch_report(object(), date(2026, 8, 14), "equity")

    def test_absence_is_still_a_flex_report_error(self):
        """Existing callers catch FlexReportError and must keep working."""
        assert issubclass(FlexReportAbsent, FlexReportError)

    def test_a_full_size_payload_that_is_not_a_report_is_not_absence(self, monkeypatch):
        """Only a missing report is benign; an unrecognisable one means the layout moved."""
        _serve(monkeypatch, b"<html>maintenance</html>" * 200)
        with pytest.raises(FlexReportError, match="not a FLEX") as raised:
            fetch_report(object(), date(2026, 8, 14), "equity")
        assert not isinstance(raised.value, FlexReportAbsent)


class TestSnapshotPathFor:
    def test_matches_the_path_of_a_report_for_that_date(self):
        report = parse_report(REPORT, "index", date(2026, 8, 14))
        assert occ_flex.snapshot_path_for(date(2026, 8, 14), "index") == snapshot_path(report)
