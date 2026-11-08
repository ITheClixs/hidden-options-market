"""Tests for split events and the un-adjustment of split-adjusted bars."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from hidden_options.collect.splits import parse_splits, split_factors, unadjust


def payload(splits):
    return json.dumps(
        {"chart": {"result": [{"meta": {"symbol": "NFLX"}, "events": {"splits": splits}}]}}
    ).encode()


class TestParseSplits:
    def test_reads_ratio_and_new_york_session(self):
        # 2025-11-17 14:30 UTC is 09:30 in New York, the ex-date's open.
        found = parse_splits(
            "NFLX", payload({"1": {"date": 1763389800, "numerator": 10.0, "denominator": 1.0}})
        )
        assert found.loc[0, "session"] == pd.Timestamp("2025-11-17")
        assert found.loc[0, "ratio"] == pytest.approx(10.0)

    def test_reverse_split(self):
        found = parse_splits(
            "XYZ", payload({"1": {"date": 1763389800, "numerator": 1.0, "denominator": 8.0}})
        )
        assert found.loc[0, "ratio"] == pytest.approx(0.125)

    def test_no_events_is_an_empty_frame(self):
        empty = json.dumps({"chart": {"result": [{"meta": {}}]}}).encode()
        assert parse_splits("XYZ", empty).empty


def bars(symbol, closes, volumes, start="2025-11-13"):
    days = pd.bdate_range(start, periods=len(closes))
    stamps = [d.tz_localize("America/New_York") + pd.Timedelta(hours=9.5) for d in days]
    return pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": stamps,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
        }
    )


class TestUnadjust:
    def test_prices_before_the_ex_date_are_scaled_back_up_and_volume_down(self):
        frame = bars("NFLX", [110.0, 111.0, 112.0, 113.0], [1000.0] * 4)  # 13, 14, 17, 18 Nov
        splits = pd.DataFrame(
            {"symbol": ["NFLX"], "session": [pd.Timestamp("2025-11-17")], "ratio": [10.0]}
        )
        found = unadjust(frame, splits)
        assert list(found["close"]) == pytest.approx([1100.0, 1110.0, 112.0, 113.0])
        assert list(found["volume"]) == pytest.approx([100.0, 100.0, 1000.0, 1000.0])
        assert list(found["high"])[:2] == pytest.approx([1100.0, 1110.0])

    def test_dollar_volume_and_returns_within_a_side_are_unchanged(self):
        frame = bars("NFLX", [110.0, 111.0, 112.0, 113.0], [1000.0] * 4)
        splits = pd.DataFrame(
            {"symbol": ["NFLX"], "session": [pd.Timestamp("2025-11-17")], "ratio": [10.0]}
        )
        found = unadjust(frame, splits)
        assert list(found["close"] * found["volume"]) == pytest.approx(
            list(frame["close"] * frame["volume"])
        )

    def test_a_split_after_the_last_bar_is_not_applied(self):
        frame = bars("NFLX", [110.0, 111.0], [1000.0] * 2)  # 13 and 14 Nov only
        splits = pd.DataFrame(
            {"symbol": ["NFLX"], "session": [pd.Timestamp("2025-11-17")], "ratio": [10.0]}
        )
        assert list(unadjust(frame, splits)["close"]) == pytest.approx([110.0, 111.0])

    def test_two_splits_compound(self):
        frame = bars("ABC", [10.0] * 5, [1.0] * 5, start="2025-11-10")  # 10-14 Nov
        splits = pd.DataFrame(
            {
                "symbol": ["ABC", "ABC"],
                "session": pd.to_datetime(["2025-11-11", "2025-11-13"]),
                "ratio": [2.0, 3.0],
            }
        )
        assert list(unadjust(frame, splits)["close"]) == pytest.approx(
            [60.0, 30.0, 30.0, 10.0, 10.0]
        )

    def test_other_symbols_are_untouched_and_input_unchanged(self):
        frame = pd.concat(
            [
                bars("NFLX", [110.0, 112.0], [1.0, 1.0], start="2025-11-14"),
                bars("AAA", [5.0, 5.0], [1.0, 1.0], start="2025-11-14"),
            ]
        )
        before = frame.copy()
        splits = pd.DataFrame(
            {"symbol": ["NFLX"], "session": [pd.Timestamp("2025-11-17")], "ratio": [10.0]}
        )
        found = unadjust(frame, splits)
        assert list(found.loc[found["symbol"] == "AAA", "close"]) == [5.0, 5.0]
        pd.testing.assert_frame_equal(frame, before)


def test_split_factors_are_the_multipliers_unadjust_applies():
    frame = bars("ABC", [10.0] * 5, [1.0] * 5, start="2025-11-10")
    splits = pd.DataFrame(
        {
            "symbol": ["ABC", "ABC"],
            "session": pd.to_datetime(["2025-11-11", "2025-11-13"]),
            "ratio": [2.0, 3.0],
        }
    )
    assert list(split_factors(frame, splits)) == pytest.approx([6.0, 3.0, 3.0, 1.0, 1.0])
    assert list(split_factors(frame, splits.iloc[:0])) == [1.0] * 5


def test_read_bars_applies_the_stored_splits(tmp_path, monkeypatch):
    from hidden_options.collect import splits as module

    stored = tmp_path / "splits.parquet"
    pd.DataFrame(
        {"symbol": ["NFLX"], "session": [pd.Timestamp("2025-11-17")], "ratio": [10.0]}
    ).to_parquet(stored, index=False)
    monkeypatch.setattr(module, "SPLITS_PATH", stored)
    path = tmp_path / "bars.parquet"
    bars("NFLX", [110.0, 111.0, 112.0, 113.0], [1000.0] * 4).to_parquet(path, index=False)
    found = module.read_bars(path, ["symbol", "timestamp", "close"])
    assert list(found["close"]) == pytest.approx([1100.0, 1110.0, 112.0, 113.0])


def test_missing_splits_file_is_refused(tmp_path, monkeypatch):
    from hidden_options.collect import splits as module

    monkeypatch.setattr(module, "SPLITS_PATH", tmp_path / "absent.parquet")
    with pytest.raises(FileNotFoundError, match="refresh-splits"):
        module.load_splits()
