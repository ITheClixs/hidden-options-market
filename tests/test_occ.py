"""Parser tests for the OCC open-interest collector.

The fixture reproduces the real report layout, including the ragged tab runs and the
trailing-space product symbol that the live endpoint emits.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from absorb.collect.occ import OccParseError, parse_open_interest, snapshot_partition

REPORT = (
    b"Series Search Results for AAPL\n"
    b"\n"
    b"Products for this underlying symbol are traded on: \n"
    b"AMEX ARCA BATS BOX C2 CBOE EDGX\n"
    b"\n"
    b"\t\tSeries/contract\t\tStrike\t\t\tOpen Interest\t\t\t\n"
    b"ProductSymbol\tyear\tMonth\tDay\tInteger\tDec\tC/P\tCall\tPut\tPosition Limit\t\n"
    b"AAPL  \t\t2026\t08\t14\t110\t000\tC P \t0\t113\t25000000\n"
    b"AAPL  \t\t2026\t08\t14\t222\t500\tC P \t41\t7\t25000000\n"
    b"AAPL  \t\t2026\t12\t18\t300\t000\tC P \t9182\t4410\t25000000\n"
)


class TestParseOpenInterest:
    def test_parses_every_data_row(self):
        snapshot = parse_open_interest("AAPL", REPORT)
        assert snapshot.n_series == 3

    def test_reconstructs_strike_from_integer_and_decimal_parts(self):
        snapshot = parse_open_interest("AAPL", REPORT)
        assert snapshot.frame.iloc[1]["strike"] == pytest.approx(222.5)

    def test_parses_expiry(self):
        snapshot = parse_open_interest("AAPL", REPORT)
        assert snapshot.frame.iloc[2]["expiry"] == date(2026, 12, 18)

    def test_keeps_call_and_put_open_interest_separate(self):
        row = parse_open_interest("AAPL", REPORT).frame.iloc[2]
        assert (row["call_open_interest"], row["put_open_interest"]) == (9182, 4410)

    def test_captures_position_limit(self):
        assert parse_open_interest("AAPL", REPORT).frame.iloc[0]["position_limit"] == 25_000_000

    def test_strips_padding_from_product_symbol(self):
        assert parse_open_interest("AAPL", REPORT).frame.iloc[0]["product_symbol"] == "AAPL"

    def test_hashes_payload_for_provenance(self):
        assert len(parse_open_interest("AAPL", REPORT).payload_sha256) == 64

    def test_ignores_preamble_lines(self):
        """Header text contains tabs too; only rows after the column header count."""
        symbols = set(parse_open_interest("AAPL", REPORT).frame["product_symbol"])
        assert symbols == {"AAPL"}

    def test_raises_when_header_missing(self):
        with pytest.raises(OccParseError, match="header"):
            parse_open_interest("AAPL", b"upstream error page")

    def test_raises_when_header_present_but_no_rows_parse(self):
        """A layout change must fail loudly, not look like a symbol with no series."""
        broken = (
            b"ProductSymbol\tyear\tMonth\tDay\tInteger\tDec\tC/P\tCall\tPut\tPosition Limit\t\n"
            b"AAPL\t2026\t08\n"
        )
        with pytest.raises(OccParseError, match="no parseable data rows"):
            parse_open_interest("AAPL", broken)


class TestPartitioning:
    def test_path_is_partitioned_by_capture_date(self):
        snapshot = parse_open_interest("AAPL", REPORT)
        path = snapshot_partition(snapshot, datetime(2026, 8, 16, 21, 5))
        assert path == "occ_open_interest/date=2026-08-16/AAPL.parquet"
