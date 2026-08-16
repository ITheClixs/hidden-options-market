"""Parser tests for the Cboe chain collector."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from absorb.collect.cboe import (
    ChainParseError,
    parse_chain,
    parse_contract,
    snapshot_partition,
)


def _payload(options: list[dict], *, timestamp: str = "2026-08-14T16:15:00") -> bytes:
    return json.dumps(
        {
            "timestamp": timestamp,
            "symbol": "MSTR",
            "data": {"current_price": 321.5, "options": options},
        }
    ).encode()


def _option(contract: str = "MSTR260814C00030000", **overrides) -> dict:
    base = {
        "option": contract,
        "bid": 58.7,
        "bid_size": 260.0,
        "ask": 67.15,
        "ask_size": 254.0,
        "iv": 0.61,
        "open_interest": 5077.0,
        "volume": 5078.0,
        "delta": 1.0,
        "gamma": 0.0,
        "vega": 0.0,
        "theta": 0.0,
        "rho": 0.0,
        "theo": 63.065,
        "last_trade_price": 63.15,
        "prev_day_close": 67.5,
        "last_trade_time": "2026-08-14T15:58:10",
    }
    return {**base, **overrides}


class TestParseContract:
    def test_decodes_expiry_right_and_strike(self):
        assert parse_contract("MSTR260814C00030000") == (date(2026, 8, 14), "C", 30.0)

    def test_decodes_fractional_strike(self):
        assert parse_contract("SPY260918P00612500")[2] == pytest.approx(612.5)

    def test_decodes_put(self):
        assert parse_contract("NVDA261218P00100000")[1] == "P"

    def test_handles_short_root(self):
        assert parse_contract("F260814C00012000") == (date(2026, 8, 14), "C", 12.0)

    @pytest.mark.parametrize(
        "bad", ["", "NOTACONTRACT", "MSTR2608C00030000", "MSTR260814X00030000"]
    )
    def test_rejects_malformed(self, bad):
        with pytest.raises(ChainParseError):
            parse_contract(bad)

    def test_rejects_impossible_date(self):
        with pytest.raises(ChainParseError):
            parse_contract("MSTR261332C00030000")


class TestParseChain:
    def test_returns_one_row_per_contract(self):
        snapshot = parse_chain("MSTR", _payload([_option(), _option("MSTR260814P00030000")]))
        assert snapshot.n_contracts == 2

    def test_preserves_quote_sizes(self):
        """Quote sizes are the reason this source is used; they must survive parsing."""
        snapshot = parse_chain("MSTR", _payload([_option()]))
        row = snapshot.frame.iloc[0]
        assert row["bid_size"] == 260.0
        assert row["ask_size"] == 254.0

    def test_explodes_contract_into_columns(self):
        snapshot = parse_chain("MSTR", _payload([_option()]))
        row = snapshot.frame.iloc[0]
        assert (row["expiry"], row["right"], row["strike"]) == (date(2026, 8, 14), "C", 30.0)

    def test_records_underlying_price_and_timestamp(self):
        snapshot = parse_chain("MSTR", _payload([_option()]))
        assert snapshot.frame.iloc[0]["underlying_price"] == 321.5
        assert snapshot.quote_timestamp == "2026-08-14T16:15:00"

    def test_hashes_payload_for_provenance(self):
        payload = _payload([_option()])
        first = parse_chain("MSTR", payload).payload_sha256
        second = parse_chain("MSTR", payload).payload_sha256
        assert first == second
        assert len(first) == 64

    def test_tolerates_missing_optional_fields(self):
        thin = {"option": "MSTR260814C00030000", "bid": 1.0}
        snapshot = parse_chain("MSTR", _payload([thin]))
        assert snapshot.frame.iloc[0]["bid"] == 1.0
        assert snapshot.frame.iloc[0]["ask"] is None

    def test_rejects_non_json(self):
        with pytest.raises(ChainParseError):
            parse_chain("MSTR", b"<html>rate limited</html>")

    def test_rejects_payload_without_data(self):
        with pytest.raises(ChainParseError):
            parse_chain("MSTR", json.dumps({"timestamp": "x"}).encode())

    def test_rejects_empty_option_list(self):
        """An empty chain means the endpoint changed or the symbol is wrong; it must
        not be written out as a valid zero-row snapshot."""
        with pytest.raises(ChainParseError):
            parse_chain("MSTR", _payload([]))

    def test_rejects_record_without_contract_id(self):
        with pytest.raises(ChainParseError):
            parse_chain("MSTR", _payload([{"bid": 1.0}]))


class TestPartitioning:
    def test_equity_path(self):
        snapshot = parse_chain("MSTR", _payload([_option()]))
        path = snapshot_partition(snapshot, datetime(2026, 8, 16, 21, 5))
        assert path == "cboe_chain/date=2026-08-16/equity_MSTR.parquet"

    def test_index_symbols_are_labelled_and_stripped(self):
        snapshot = parse_chain("_SPX", _payload([_option("SPXW260814C05000000")]))
        path = snapshot_partition(snapshot, datetime(2026, 8, 16))
        assert path == "cboe_chain/date=2026-08-16/index_SPX.parquet"
