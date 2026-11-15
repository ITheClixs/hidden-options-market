"""Tests for the SOFR collector."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from hidden_options.collect.sofr import SNAPSHOT, SofrParseError, collect_sofr, parse_sofr

PAYLOAD = (
    b'{ "refRates": [ { "effectiveDate": "2026-10-23", "type": "SOFR", "percentRate": 3.92 },'
    b' { "effectiveDate": "2026-10-22", "type": "SOFR", "percentRate": 3.90 } ] }'
)


def test_rates_are_dated_and_sorted():
    frame = parse_sofr(PAYLOAD)
    assert frame["date"].tolist() == [pd.Timestamp("2026-10-22"), pd.Timestamp("2026-10-23")]
    assert frame["rate"].tolist() == [3.90, 3.92]


def test_a_payload_without_rates_is_an_error():
    with pytest.raises(SofrParseError):
        parse_sofr(b"{}")


def test_collect_writes_the_series(tmp_path, monkeypatch):
    class Found:
        content = PAYLOAD

    monkeypatch.setattr("hidden_options.collect.sofr.fetch", lambda *a, **k: Found())
    collect_sofr(date(2026, 10, 22), date(2026, 10, 23), tmp_path, session=object())
    assert len(pd.read_parquet(tmp_path / SNAPSHOT)) == 2
