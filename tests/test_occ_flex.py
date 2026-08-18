"""Tests for the authoritative OCC FLEX report parser.

The report is fixed-layout text and carries its own per-class totals, so the parser is
checked against those totals as well as against the fields. The fixture reproduces the
real layout, including a FLEX series struck on the standard grid, which is the case
that defeats any strike-based heuristic.
"""

from __future__ import annotations

from datetime import date

import pytest

from absorb.collect.occ_flex import (
    FlexReportError,
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
