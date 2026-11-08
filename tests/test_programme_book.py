"""Tests for the check of the programme test's sign assumption against fund holdings."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.programme_book import fund_legs, programme_book

D = pd.Timestamp("2026-09-01")
E = pd.Timestamp("2026-10-16")


def holdings(rows):
    """rows: (fund, root, right, strike, contracts)"""
    return pd.DataFrame(
        [
            {
                "fund": f,
                "as_of": D,
                "option_root": r,
                "expiry": E,
                "right": k,
                "strike": s,
                "contracts": n,
                "capture_date": D,
            }
            for f, r, k, s, n in rows
        ]
    )


def report(rows):
    """rows: (root, underlying, right, strike, open_interest)"""
    return pd.DataFrame(
        [
            {
                "report_date": D,
                "root": r,
                "underlying": u,
                "expiry": E,
                "right": k,
                "strike": s,
                "open_interest": n,
            }
            for r, u, k, s, n in rows
        ]
    )


FUNDS = holdings(
    [
        # A synthetic in FLEX (long call, short put at 100), a lone FLEX short put at 90,
        # and calls written in the listed series.
        ("AAAY", "1AAA", "C", 100.0, 50),
        ("AAAY", "1AAA", "P", 100.0, -50),
        ("AAAY", "1AAA", "P", 90.0, -20),
        ("AAAY", "AAA", "C", 120.0, -40),
    ]
)


def test_fund_legs_split_by_market_and_side():
    legs = fund_legs(FUNDS, {"AAA"})
    assert legs["written_call_flex_share"] == pytest.approx(0.0)
    assert legs["short_put_flex_share"] == pytest.approx(1.0)
    assert legs["short_puts_paired"] == pytest.approx(50 / 70)
    assert legs["funds"] == 1


def test_fund_share_of_the_netted_flex_book():
    reports = report(
        [
            ("1AAA", "AAA", "C", 100.0, 50),
            ("1AAA", "AAA", "P", 100.0, 50),  # nets out
            ("1AAA", "AAA", "P", 90.0, 20),  # the fund's lone put
            ("1AAA", "AAA", "C", 130.0, 180),  # someone else's calls
        ]
    )
    found = programme_book(FUNDS, reports, {"AAA"})
    assert found["netted_call_share"] == pytest.approx(180 / 200)
    assert found["fund_share"] == pytest.approx(20 / 200)
    assert found["dates"] == 1


def test_macros_format_every_figure():
    from hidden_options.measure.programme_book_result import programme_book_result

    reports = report([("1AAA", "AAA", "C", 130.0, 180), ("1AAA", "AAA", "P", 90.0, 20)])
    found = programme_book_result(FUNDS, reports, frozenset({"AAA"}))
    assert found.macros["PBookWrittenFlex"] == "0\\%"
    assert found.macros["PBookFundShare"] == "10.0\\%"
