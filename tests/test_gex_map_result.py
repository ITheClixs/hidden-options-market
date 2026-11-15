"""Tests for the `gex_map` result on a small synthetic SPY book."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.gex_map_result import gex_map_macros, gex_map_result

D = pd.Timestamp("2026-11-09")
E1, E2 = pd.Timestamp("2026-12-18"), pd.Timestamp("2027-03-19")


def chain():
    rows = []
    for expiry in (E1, E2):
        for strike, iv in ((650.0, 0.28), (700.0, 0.24), (750.0, 0.2), (800.0, 0.17)):
            for right in ("C", "P"):
                rows.append((expiry, right, strike, iv, 2000))
    return pd.DataFrame(
        [
            {
                "date": D,
                "symbol": "SPY",
                "root": "SPY",
                "expiry": expiry,
                "right": right,
                "strike": strike,
                "open_interest": count,
                "bid": 1.0,
                "ask": 1.1,
                "theo": 1.05,
                "underlying_price": 750.0,
                "iv": iv,
            }
            for expiry, right, strike, iv, count in rows
        ]
    )


REPORT = pd.DataFrame(
    [
        {
            "report_date": D,
            "kind": "equity",
            "root": "4SPY",
            "underlying": "SPY",
            "right": right,
            "expiry": pd.Timestamp("2026-12-31"),
            "strike": strike,
            "mark_price": 1.0,
            "open_interest": count,
        }
        for right, strike, count in (("P", 690.0, 4000), ("P", 620.0, 4000), ("C", 790.0, 4000))
    ]
)
HOLDINGS = pd.DataFrame(
    [
        {
            "fund": "BJAN",
            "as_of": pd.Timestamp("2026-11-10"),
            "position_ticker": "x",
            "option_root": "4SPY",
            "expiry": pd.Timestamp("2026-12-31"),
            "right": right,
            "strike": strike,
            "contracts": contracts,
            "price": 1.0,
            "net_assets": 1e9,
        }
        for right, strike, contracts in (("P", 690.0, 4000), ("P", 620.0, -4000))
    ]
)


@pytest.fixture(scope="module")
def result():
    return gex_map_result(chain(), REPORT, HOLDINGS)


def test_counts_and_readings(result):
    values = result.values
    assert values["counts"]["flex_series"] == 3
    assert values["counts"]["matched_series"] == 2
    spot = values["at_spot"]
    # Adding FLEX puts and a call under the convention changes the net.
    assert spot["convention"] != spot["listed"]
    # Signing the lower put (fund short, dealer long) and the upper put (fund long,
    # dealer short) differs from the convention only through the lower put.
    assert spot["signed"] > spot["convention"]


def test_macros(result):
    macros = gex_map_macros(result.values)
    assert macros["GexDate"] == "9 November 2026"
    assert macros["GexDrop"] == "10\\%"
    assert macros["GexSignedSpot"].endswith("bn")
    assert result.macros == macros
