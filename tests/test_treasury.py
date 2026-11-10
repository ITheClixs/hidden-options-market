"""Tests for the Treasury par yield curve collector."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.collect.treasury import SNAPSHOT, TreasuryCurveError, collect_curve, parse_curve

CSV = (
    b'Date,"1 Mo","1.5 Month","3 Mo","1 Yr"\n'
    b"12/31/2025,3.74,3.75,3.67,3.48\n"
    b"12/30/2025,3.65,N/A,3.65,3.47\n"
)


def test_rows_are_dated_and_sorted_with_missing_maturities_blank():
    curve = parse_curve(CSV)
    assert curve["date"].tolist() == [pd.Timestamp("2025-12-30"), pd.Timestamp("2025-12-31")]
    assert curve["3 Mo"].tolist() == [3.65, 3.67]
    assert pd.isna(curve["1.5 Month"].iloc[0])


def test_a_file_without_a_date_column_is_an_error():
    with pytest.raises(TreasuryCurveError):
        parse_curve(b"a,b\n1,2\n")


def test_years_are_joined_and_written(tmp_path, monkeypatch):
    payloads = {
        "2025": CSV,
        "2026": b'Date,"1 Mo","3 Mo","1 Yr"\n01/02/2026,3.70,3.66,3.50\n',
    }

    class Found:
        def __init__(self, content):
            self.content = content

    def fake_fetch(session, url, *, params=None, max_attempts=4):
        return Found(payloads[params["field_tdr_date_value"]])

    monkeypatch.setattr("hidden_options.collect.treasury.fetch", fake_fetch)
    curve = collect_curve(range(2025, 2027), tmp_path, session=object())
    assert len(curve) == 3
    assert pd.read_parquet(tmp_path / SNAPSHOT)["date"].max() == pd.Timestamp("2026-01-02")
