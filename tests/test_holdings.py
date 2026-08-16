"""Parser tests for issuer daily holdings.

The fixture is a trimmed copy of a real YieldMax MSTY file, preserving the details
that matter: space-padded OSI tickers, the ``2MSTR`` non-standard-deliverable root
used for the synthetic put leg, negative share counts for written options, and
non-option rows (bills, cash) that must not be mistaken for contracts.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from absorb.collect.holdings import (
    HoldingsParseError,
    parse_holdings,
    snapshot_partition,
    split_option_ticker,
)
from absorb.config import load_programmes

HEADER = (
    "Date,Account,StockTicker,CUSIP,SecurityName,Shares,Price,MarketValue,"
    "Weightings,NetAssets,SharesOutstanding,CreationUnits\n"
)
ROWS = (
    "08/17/2026,MSTY,MSTR  261016C00095000,MSTR  261016C00095000,MSTR US 10/16/26 C95,"
    "45115,10.2,46017300.0,6.34%,726038557.76,60844959,2433.8\n"
    "08/17/2026,MSTY,2MSTR 261016P00095010,2MSTR 261016P00095010,MSTR 10/16/2026 95.01 P,"
    "-45115,11.3156,-51050329.4,-7.03%,726038557.76,60844959,2433.8\n"
    "08/17/2026,MSTY,MSTR  260821C00098000,MSTR  260821C00098000,MSTR US 08/21/26 C98,"
    "-15450,1.39,-2147550.0,-0.30%,726038557.76,60844959,2433.8\n"
    "08/17/2026,MSTY,912797UK1,912797UK1,United States Treasury Bill 10/15/2026,"
    "150141000,99.400855,149241437.71,20.56%,726038557.76,60844959,2433.8\n"
    "08/17/2026,MSTY,Cash&Other,Cash&Other,Cash & Other,"
    "194966922,1.0,194966921.85,26.85%,726038557.76,60844959,2433.8\n"
)
PAYLOAD = (HEADER + ROWS).encode()


class TestSplitOptionTicker:
    def test_parses_space_padded_standard_root(self):
        assert split_option_ticker("MSTR  261016C00095000") == (
            "MSTR",
            date(2026, 10, 16),
            "C",
            95.0,
        )

    def test_parses_non_standard_deliverable_root(self):
        """The synthetic put leg is written on a '2'-prefixed root at a .01 offset strike."""
        root, expiry, right, strike = split_option_ticker("2MSTR 261016P00095010")
        assert (root, expiry, right) == ("2MSTR", date(2026, 10, 16), "P")
        assert strike == pytest.approx(95.01)

    def test_returns_none_for_cusip(self):
        assert split_option_ticker("912797UK1") is None

    def test_returns_none_for_cash(self):
        assert split_option_ticker("Cash&Other") is None

    def test_returns_none_for_plain_equity_ticker(self):
        assert split_option_ticker("MSTR") is None


class TestParseHoldings:
    def test_row_count_matches_source(self):
        assert parse_holdings("MSTY", PAYLOAD).n_positions == 5

    def test_counts_only_option_legs(self):
        assert parse_holdings("MSTY", PAYLOAD).n_option_legs == 3

    def test_preserves_sign_of_written_options(self):
        """Sign is the whole signal: written calls must stay negative."""
        frame = parse_holdings("MSTY", PAYLOAD).frame
        written = frame[frame.position_ticker == "MSTR260821C00098000"].iloc[0]
        assert written["contracts"] == -15450

    def test_synthetic_pair_has_offsetting_quantities(self):
        frame = parse_holdings("MSTY", PAYLOAD).frame
        call = frame[frame.position_ticker == "MSTR261016C00095000"].iloc[0]
        put = frame[frame.position_ticker == "2MSTR261016P00095010"].iloc[0]
        assert call["contracts"] == -put["contracts"] == 45115

    def test_captures_fund_scale(self):
        row = parse_holdings("MSTY", PAYLOAD).frame.iloc[0]
        assert row["net_assets"] == pytest.approx(726_038_557.76)
        assert row["shares_outstanding"] == 60_844_959

    def test_reads_as_of_date(self):
        assert parse_holdings("MSTY", PAYLOAD).as_of == date(2026, 8, 17)

    def test_non_option_rows_have_null_option_fields(self):
        frame = parse_holdings("MSTY", PAYLOAD).frame
        bill = frame[frame.position_ticker == "912797UK1"].iloc[0]
        assert not bill["is_option"]
        assert bill["expiry"] is None
        assert pd.isna(bill["strike"])

    def test_hashes_payload_for_provenance(self):
        assert len(parse_holdings("MSTY", PAYLOAD).payload_sha256) == 64

    def test_rejects_file_with_missing_columns(self):
        with pytest.raises(HoldingsParseError, match="missing required columns"):
            parse_holdings("MSTY", b"Date,StockTicker\n08/17/2026,MSTR\n")

    def test_rejects_header_only_file(self):
        with pytest.raises(HoldingsParseError, match="no rows"):
            parse_holdings("MSTY", HEADER.encode())

    def test_rejects_html_error_page(self):
        with pytest.raises(HoldingsParseError):
            parse_holdings("MSTY", b"<!DOCTYPE html><html><body>404</body></html>")


class TestProgrammeRegistry:
    def test_shipped_registry_loads(self):
        programmes = load_programmes()
        by_fund = {p.fund: p for p in programmes}
        assert by_fund["MSTY"].underlying == "MSTR"
        assert by_fund["MSTY"].issuer == "yieldmax"

    def test_url_template_formats_to_a_real_path(self):
        msty = next(p for p in load_programmes() if p.fund == "MSTY")
        assert msty.url_template.format(ticker="MSTY").endswith("TidalFG_Holdings_MSTY.csv")

    def test_missing_registry_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_programmes(tmp_path / "absent.json")


class TestPartitioning:
    def test_partitions_by_capture_date_not_file_date(self):
        """The file is dated one day ahead; storage must key off capture time."""
        snapshot = parse_holdings("MSTY", PAYLOAD)
        path = snapshot_partition(snapshot, datetime(2026, 8, 16, 21, 5))
        assert path == "fund_holdings/date=2026-08-16/MSTY.parquet"
