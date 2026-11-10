"""Tests for the check of product rules and dealer sides against fund holdings."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.anatomy import classify
from hidden_options.measure.holders import (
    box_positions,
    category_shares,
    dealer_gamma,
    design_agreement,
    flex_lines,
    match,
    matching,
    rule_recall,
    spots_from_stock_legs,
    with_roles,
)

D = pd.Timestamp("2026-11-09")
E = pd.Timestamp("2026-12-31")


def holdings(rows):
    """rows: (fund, root, right, strike, contracts, price)"""
    return pd.DataFrame(
        [
            {
                "fund": fund,
                "as_of": D,
                "position_ticker": "x",
                "option_root": root,
                "expiry": E,
                "right": right,
                "strike": strike,
                "contracts": contracts,
                "price": price,
                "net_assets": 1e9,
            }
            for fund, root, right, strike, contracts, price in rows
        ]
    )


def report(rows):
    """rows: (root, underlying, right, strike, mark, open_interest)"""
    return pd.DataFrame(
        [
            {
                "report_date": D,
                "kind": "equity",
                "root": root,
                "underlying": underlying,
                "right": right,
                "strike": strike,
                "mark_price": mark,
                "open_interest": count,
                "expiry": E,
            }
            for root, underlying, right, strike, mark, count in rows
        ]
    )


FUND = holdings(
    [
        ("BJAN", "4SPY", "C", 6.83, 4623, 743.4),  # the stock leg
        ("BJAN", "4SPY", "P", 681.93, 4623, 4.07),  # long the upper put
        ("BJAN", "4SPY", "P", 620.56, -4623, 1.67),  # short the lower put
        ("BJAN", "4SPY", "C", 794.23, -4623, 2.68),  # short the cap
        ("BJAN", "SPY", "C", 800.0, -10, 1.0),  # a listed line: not FLEX
    ]
)
REPORT = report(
    [
        ("4SPY", "SPY", "C", 6.83, 743.5, 4623),
        ("4SPY", "SPY", "P", 681.93, 4.1, 4623),
        ("4SPY", "SPY", "P", 620.56, 1.7, 4623),
        ("4SPY", "SPY", "C", 794.23, 2.7, 4700),  # someone else holds 77 more
        ("4SPY", "SPY", "P", 700.0, 6.0, 900),  # nobody in the file holds this
    ]
)
SERIES = classify(REPORT).series


def test_only_flex_roots_are_kept():
    lines = flex_lines(FUND)
    assert len(lines) == 4
    assert set(lines["root"]) == {"4SPY"}


def test_roles_come_from_the_funds_own_prices():
    roles = with_roles(flex_lines(FUND)).set_index("strike")["role"]
    assert roles[6.83] == "stock_leg"
    assert roles[681.93] == "package_leg"
    assert roles[794.23] == "package_leg"


def test_matching_reports_the_funds_share_of_each_series():
    found = match(with_roles(flex_lines(FUND)), SERIES)
    summary = matching(found)
    assert summary["lines"] == 4 and summary["found_lines_share"] == pytest.approx(1.0)
    assert summary["median_share_of_open_interest"] == pytest.approx(1.0)
    assert summary["series_at_least_95"] == pytest.approx(1.0)  # 4623 of 4700 is 98%


def test_a_line_absent_from_the_report_is_counted():
    extra = holdings([("BJAN", "4SPY", "P", 500.0, -100, 0.3)])
    found = match(with_roles(flex_lines(pd.concat([FUND, extra], ignore_index=True))), SERIES)
    summary = matching(found)
    assert summary["found_lines_share"] == pytest.approx(4 / 5)
    assert summary["found_contracts_share"] == pytest.approx(4 * 4623 / (4 * 4623 + 100))


def test_rule_recall_by_contracts():
    found = match(with_roles(flex_lines(FUND)), SERIES)
    recall = rule_recall(found)
    assert recall["stock_leg"] == pytest.approx(1.0)
    # The cap's count is 4700 in the report, so the equal-count rule misses it.
    assert recall["package_leg"] == pytest.approx(2 / 3)


def test_share_of_each_category_in_series_the_funds_hold():
    found = match(with_roles(flex_lines(FUND)), SERIES)
    shares = category_shares(found, SERIES)
    assert shares["stock_leg"] == pytest.approx(1.0)
    assert shares["package_leg"] == pytest.approx(1.0)


def test_design_predicts_each_side():
    found = match(with_roles(flex_lines(FUND)), SERIES)
    assert design_agreement(found)["all"] == pytest.approx(1.0)
    flipped = FUND.copy()
    flipped.loc[flipped["strike"] == 620.56, "contracts"] = 4623  # long the lower put too
    found = match(with_roles(flex_lines(flipped)), SERIES)
    agreement = design_agreement(found)
    assert agreement["all"] == pytest.approx(2 / 3)
    assert agreement["lower_put"] == pytest.approx(0.0)
    assert agreement["upper_put"] == pytest.approx(1.0)


def test_spot_is_the_nearest_stock_leg_mark_plus_strike():
    assert spots_from_stock_legs(SERIES)["SPY"] == pytest.approx(743.5 + 6.83)


def test_dealer_gamma_takes_the_opposite_side():
    found = match(with_roles(flex_lines(FUND)), SERIES)
    gamma = pd.DataFrame(
        {
            "root": ["4SPY"] * 5,
            "expiry": [E] * 5,
            "right": ["C", "P", "P", "C", "P"],
            "strike": [6.83, 681.93, 620.56, 794.23, 700.0],
            "gamma": [0.0, 0.004, 0.002, 0.003, 0.005],
            "spot": [750.0] * 5,
            "open_interest": [4623, 4623, 4623, 4700, 900],
            "underlying": ["SPY"] * 5,
        }
    )
    out = dealer_gamma(found, gamma)["SPY"]
    unit = 4623 * 100 * 750.0**2 * 0.01
    assert out["dealer_long"] == pytest.approx((0.002 + 0.003) * unit)  # lower put, cap
    assert out["dealer_short"] == pytest.approx(0.004 * unit)  # upper put
    assert out["net"] == pytest.approx(0.001 * unit)
    # Vendors call every put dealer-short: wrong on the lower put only.
    assert out["convention_wrong_share"] == pytest.approx(0.002 / 0.009)
    assert out["convention_net"] == pytest.approx((0.003 - 0.004 - 0.002) * unit)
    total = (0.004 + 0.002) * unit + 0.003 * 4700 * 100 * 750.0**2 * 0.01
    total += 0.005 * 900 * 100 * 750.0**2 * 0.01
    assert out["share_of_flex_gamma"] == pytest.approx((0.009 * unit) / total)


def test_box_positions_of_a_fund():
    box = holdings(
        [
            ("BOXX", "2SPY", "C", 10.01, 100, 739.0),
            ("BOXX", "2SPY", "P", 10.01, -100, 0.05),
            ("BOXX", "2SPY", "C", 10010.01, -100, 0.05),
            ("BOXX", "2SPY", "P", 10010.01, 100, 9212.0),
            ("BOXX", "2QQQ", "C", 15.01, -5, 663.0),
            ("BOXX", "2QQQ", "P", 15.01, 5, 0.1),
            ("BOXX", "2QQQ", "C", 10005.01, 5, 0.1),
            ("BOXX", "2QQQ", "P", 10005.01, -5, 9263.0),
        ]
    )
    found = box_positions(flex_lines(box))
    lent = found[found["side"] == "lent"].iloc[0]
    borrowed = found[found["side"] == "borrowed"].iloc[0]
    assert (lent["root"], lent["contracts"]) == ("2SPY", 100)
    assert lent["face"] == pytest.approx(10000 * 100 * 100)
    assert (borrowed["root"], borrowed["contracts"]) == ("2QQQ", 5)
    assert borrowed["face"] == pytest.approx(9990 * 100 * 5)
