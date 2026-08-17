"""Tests for the N-PORT scale collector.

The dose variable depends entirely on this, and the first pilot failed partly because
dose was mismeasured. The behaviour that matters most is `as_of_series`: it must never
carry a value backwards to a date before it was reported, which would leak the future
into the dose sort.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from absorb.collect.nport import (
    NportParseError,
    NportReport,
    as_of_series,
    parse_report,
    to_frame,
)

DOCUMENT = """<?xml version="1.0"?>
<edgarSubmission>
  <genInfo>
    <seriesName>YieldMaxTM MSTR Option Income Strategy ETF</seriesName>
    <repPdDate>2026-01-31</repPdDate>
  </genInfo>
  <fundInfo>
    <totAssets>1516133609.510000000000</totAssets>
    <netAssets>1277147138.370000000000</netAssets>
  </fundInfo>
</edgarSubmission>
"""


class TestParseReport:
    def test_extracts_net_assets(self):
        report = parse_report("MSTY", "S000084087", DOCUMENT)
        assert report.net_assets == pytest.approx(1_277_147_138.37)

    def test_extracts_total_assets(self):
        assert parse_report("MSTY", "S1", DOCUMENT).total_assets == pytest.approx(1_516_133_609.51)

    def test_extracts_report_date(self):
        assert parse_report("MSTY", "S1", DOCUMENT).report_date == date(2026, 1, 31)

    def test_extracts_series_name(self):
        assert "MSTR" in parse_report("MSTY", "S1", DOCUMENT).series_name

    def test_raises_when_fields_absent(self):
        with pytest.raises(NportParseError, match="lacks repPdDate or netAssets"):
            parse_report("MSTY", "S1", "<edgarSubmission></edgarSubmission>")

    def test_raises_on_unparseable_values(self):
        broken = DOCUMENT.replace("1277147138.370000000000", "not-a-number")
        with pytest.raises(NportParseError, match="unparseable"):
            parse_report("MSTY", "S1", broken)


def _reports() -> pd.DataFrame:
    return to_frame(
        [
            NportReport("MSTY", "S1", "n", date(2024, 9, 30), 300e6, 320e6),
            NportReport("MSTY", "S1", "n", date(2024, 12, 31), 900e6, 950e6),
            NportReport("MSTY", "S1", "n", date(2026, 1, 31), 1277e6, 1516e6),
            NportReport("NVDY", "S2", "n", date(2024, 12, 31), 500e6, 520e6),
        ]
    )


class TestAsOfSeries:
    def test_uses_the_most_recent_prior_report(self):
        dates = pd.Series(pd.to_datetime(["2025-06-01"]))
        assert as_of_series(_reports(), dates, "MSTY").iloc[0] == pytest.approx(900e6)

    def test_steps_up_only_after_a_new_report(self):
        dates = pd.Series(pd.to_datetime(["2024-12-30", "2025-01-02"]))
        out = as_of_series(_reports(), dates, "MSTY")
        assert out.iloc[0] == pytest.approx(300e6)
        assert out.iloc[1] == pytest.approx(900e6)

    def test_never_backfills_before_the_first_report(self):
        """Back-filling would leak a fund's later size into its pre-launch period,
        which is exactly the contamination this replaces."""
        dates = pd.Series(pd.to_datetime(["2023-01-01"]))
        assert pd.isna(as_of_series(_reports(), dates, "MSTY").iloc[0])

    def test_is_fund_specific(self):
        dates = pd.Series(pd.to_datetime(["2025-06-01"]))
        assert as_of_series(_reports(), dates, "NVDY").iloc[0] == pytest.approx(500e6)

    def test_unknown_fund_returns_nan(self):
        dates = pd.Series(pd.to_datetime(["2025-06-01"]))
        assert pd.isna(as_of_series(_reports(), dates, "ABSENT").iloc[0])

    def test_preserves_input_index_and_order(self):
        dates = pd.Series(pd.to_datetime(["2026-02-01", "2024-10-01"]), index=[42, 7])
        out = as_of_series(_reports(), dates, "MSTY")
        assert list(out.index) == [42, 7]
        assert out.loc[42] == pytest.approx(1277e6)
        assert out.loc[7] == pytest.approx(300e6)


class TestToFrame:
    def test_empty_input_returns_typed_frame(self):
        frame = to_frame([])
        assert frame.empty
        assert "net_assets" in frame.columns

    def test_sorts_by_fund_then_date(self):
        frame = _reports()
        msty = frame[frame.fund == "MSTY"]["report_date"].tolist()
        assert msty == sorted(msty)
