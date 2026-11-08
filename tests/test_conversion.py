"""Tests for the FLEX-to-listed conversion check."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.conversion import conversion_check

D0, D1, D2 = pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02"), pd.Timestamp("2026-09-03")
EXPIRY = pd.Timestamp("2026-10-16")


def flex(rows):
    """rows: (date, strike, open_interest)"""
    return pd.DataFrame(
        [
            {
                "date": d,
                "root": "1AAA",
                "symbol": "AAA",
                "expiry": EXPIRY,
                "right": "C",
                "strike": k,
                "open_interest": n,
            }
            for d, k, n in rows
        ]
    )


def listed(rows):
    """rows: (date, strike, open_interest)"""
    return pd.DataFrame(
        [
            {
                "date": d,
                "symbol": "AAA",
                "expiry": EXPIRY,
                "right": "C",
                "strike": k,
                "open_interest": n,
            }
            for d, k, n in rows
        ]
    )


def test_a_conversion_is_matched_and_a_closing_trade_is_not():
    found = conversion_check(
        # Strike 100 converts on 2 September; strike 110 is simply closed.
        flex([(D0, 100.0, 500), (D0, 110.0, 500), (D1, 110.0, 0)]),
        listed(
            [(d, 100.0, n) for d, n in ((D0, 0), (D1, 500), (D2, 500))]
            + [(d, 110.0, 50) for d in (D0, D1, D2)]
        ),
    )
    assert found["dropped_contracts"] == 1000
    assert found["dropped_matched"] == pytest.approx(0.5)
    assert found["dropped_with_twin"] == pytest.approx(1.0)


def test_creations_give_the_coincidence_baseline():
    found = conversion_check(
        flex([(D0, 100.0, 0), (D1, 100.0, 300)]),
        listed([(D0, 100.0, 10), (D1, 100.0, 400), (D2, 100.0, 400)]),
    )
    assert found["created_contracts"] == 300
    assert found["created_matched"] == pytest.approx(1.0)


def test_twin_share_counts_flex_open_interest_with_a_listed_series():
    found = conversion_check(
        flex([(D0, 100.0, 300), (D0, 105.5, 100)]),
        listed([(D0, 100.0, 1), (D1, 100.0, 1)]),
    )
    assert found["twin_oi_share"] == pytest.approx(0.75)


def test_macros_format_every_figure():
    from hidden_options.measure.conversion_result import conversion_macros

    values = {
        "twin_oi_share": 0.36,
        "dropped_contracts": 7.85e6,
        "dropped_with_twin": 0.5,
        "dropped_matched": 0.016,
        "created_matched": 0.012,
        "settlements": 49,
        "match_share": 0.9,
    }
    macros = conversion_macros(values)
    assert macros["ConvMatched"] == "1.6\\%"
    assert macros["ConvSettlements"] == "49"
