"""Tests for the intraday bar collector.

Intraday depth cannot be downloaded, only accumulated, so the failure that matters is
writing something that looks like bars but is not: padded empty grid points, a symbol
with no data, or a provider error object.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from absorb.collect.bars import (
    INTERVAL_MAX_RANGE,
    BarParseError,
    fetch_bars,
    parse_chart,
    snapshot_partition,
)


def _payload(
    timestamps: list[int],
    *,
    close: list | None = None,
    error: object = None,
    result: object = "default",
) -> bytes:
    if error is not None:
        return json.dumps({"chart": {"result": None, "error": error}}).encode()
    if result != "default":
        return json.dumps({"chart": {"result": result, "error": None}}).encode()
    n = len(timestamps)
    return json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {"symbol": "MSTR"},
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "open": [1.0] * n,
                                    "high": [2.0] * n,
                                    "low": [0.5] * n,
                                    "close": close if close is not None else [1.5] * n,
                                    "volume": [100] * n,
                                }
                            ]
                        },
                    }
                ],
            }
        }
    ).encode()


class TestParseChart:
    def test_returns_one_row_per_bar(self):
        snapshot = parse_chart("MSTR", "5m", _payload([1755000000, 1755000300]))
        assert snapshot.n_bars == 2

    def test_timestamps_are_utc_aware(self):
        snapshot = parse_chart("MSTR", "5m", _payload([1755000000]))
        assert snapshot.frame["timestamp"].dt.tz is not None

    def test_drops_padded_empty_bars(self):
        """Providers pad the grid outside trading; a return across a padded gap is
        meaningless, so those rows must not survive."""
        snapshot = parse_chart("MSTR", "5m", _payload([1, 2, 3], close=[1.5, None, 2.0]))
        assert snapshot.n_bars == 2

    def test_reports_window_bounds(self):
        snapshot = parse_chart("MSTR", "5m", _payload([1755000000, 1755003600]))
        assert snapshot.first_timestamp < snapshot.last_timestamp

    def test_hashes_payload_for_provenance(self):
        assert len(parse_chart("MSTR", "5m", _payload([1])).payload_sha256) == 64

    def test_rejects_non_json(self):
        with pytest.raises(BarParseError):
            parse_chart("MSTR", "5m", b"<html>blocked</html>")

    def test_rejects_provider_error(self):
        with pytest.raises(BarParseError, match="provider returned error"):
            parse_chart("MSTR", "5m", _payload([], error={"code": "Not Found"}))

    def test_rejects_empty_result(self):
        with pytest.raises(BarParseError, match="no result"):
            parse_chart("MSTR", "5m", _payload([], result=[]))

    def test_rejects_symbol_with_no_bars(self):
        """A fresh listing returns a valid envelope with no timestamps; that is not
        data and must not be written as a zero-row snapshot."""
        with pytest.raises(BarParseError, match="no bars"):
            parse_chart("MSTR", "5m", _payload([]))

    def test_rejects_all_empty_bars(self):
        with pytest.raises(BarParseError, match="all bars were empty"):
            parse_chart("MSTR", "5m", _payload([1, 2], close=[None, None]))

    def test_rejects_payload_without_quote_series(self):
        broken = json.dumps(
            {"chart": {"error": None, "result": [{"timestamp": [1], "indicators": {}}]}}
        ).encode()
        with pytest.raises(BarParseError, match="no quote series"):
            parse_chart("MSTR", "5m", broken)


class TestFetchBars:
    def test_rejects_unsupported_interval(self):
        with pytest.raises(ValueError, match="Unsupported interval"):
            fetch_bars(None, "MSTR", interval="3s")

    def test_interval_table_records_honest_depth_limits(self):
        """These are provider retention limits, not preferences; asking for more
        silently returns less."""
        assert INTERVAL_MAX_RANGE["1m"] == "7d"
        assert INTERVAL_MAX_RANGE["5m"] == "60d"


class TestPartitioning:
    def test_partitions_by_interval_and_capture_date(self):
        snapshot = parse_chart("MSTR", "5m", _payload([1]))
        path = snapshot_partition(snapshot, datetime(2026, 8, 17, 21, 5, tzinfo=UTC))
        assert path == "underlying_bars/interval=5m/date=2026-08-17/MSTR.parquet"

    def test_index_carets_are_stripped_from_the_filename(self):
        snapshot = parse_chart("^SPX", "5m", _payload([1]))
        path = snapshot_partition(snapshot, datetime(2026, 8, 17, tzinfo=UTC))
        assert path.endswith("/SPX.parquet")
