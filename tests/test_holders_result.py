"""Tests for the `holders` result on a small synthetic snapshot."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.holders_macros import holders_macros
from hidden_options.measure.holders_result import holders_result

D = pd.Timestamp("2026-11-09")
E = pd.Timestamp("2026-12-31")


def lines(rows):
    return pd.DataFrame(
        [
            {
                "fund": fund,
                "as_of": pd.Timestamp("2026-11-10"),
                "position_ticker": "x",
                "option_root": root,
                "expiry": E,
                "right": right,
                "strike": strike,
                "contracts": contracts,
                "price": price,
                "net_assets": 350e6,
            }
            for fund, root, right, strike, contracts, price in rows
        ]
    )


FAMILY = lines(
    [
        ("BJAN", "4SPY", "C", 6.83, 4623, 743.4),
        ("BJAN", "4SPY", "P", 681.93, 4623, 20.0),
        ("BJAN", "4SPY", "P", 620.56, -4623, 6.0),
        ("BJAN", "4SPY", "C", 794.23, -4623, 9.0),
    ]
)
BOX = lines(
    [
        ("BOXX", "2SPY", "C", 10.01, 100, 739.0),
        ("BOXX", "2SPY", "P", 10.01, -100, 0.05),
        ("BOXX", "2SPY", "C", 10010.01, -100, 0.05),
        ("BOXX", "2SPY", "P", 10010.01, 100, 9212.0),
    ]
)
REPORT = pd.DataFrame(
    [
        {
            "report_date": D,
            "kind": "equity",
            "class_name": "SPDR S&P 500",
            "root": root,
            "underlying": "SPY",
            "right": right,
            "expiry": E,
            "strike": strike,
            "mark_price": mark,
            "open_interest": count,
            "exercise_style": "european",
        }
        for root, right, strike, mark, count in [
            ("4SPY", "C", 6.83, 743.2, 4623),
            ("4SPY", "P", 681.93, 20.0, 4623),
            ("4SPY", "P", 620.56, 6.0, 4623),
            ("4SPY", "C", 794.23, 9.0, 4623),
            ("2SPY", "C", 10.01, 739.0, 125),
            ("2SPY", "P", 10.01, 0.05, 125),
            ("2SPY", "C", 10010.01, 0.05, 125),
            ("2SPY", "P", 10010.01, 9212.0, 125),
        ]
    ]
)


@pytest.fixture(scope="module")
def result():
    return holders_result(FAMILY, BOX, REPORT)


def test_matching_and_rules(result):
    values = result.values
    assert values["report_date"] == "2026-11-09" and values["file_date"] == "2026-11-10"
    assert values["matching"]["found_lines_share"] == pytest.approx(1.0)
    assert values["rule_recall"] == pytest.approx({"stock_leg": 1.0, "package_leg": 1.0})
    assert values["design"]["all"] == pytest.approx(1.0)
    assert values["family"]["funds"] == 1


def test_dealer_gamma_is_signed(result):
    spy = result.values["dealer_gamma"]["SPY"]
    assert spy["dealer_long"] > 0 and spy["dealer_short"] > 0
    assert spy["net"] == pytest.approx(spy["dealer_long"] - spy["dealer_short"])
    assert 0 < spy["convention_wrong_share"] < 1  # the lower put
    assert result.values["priced_share"] == pytest.approx(1.0)


def test_box_fund_against_the_market(result):
    box = result.values["box"]
    assert box["lent_face"] == pytest.approx(10000 * 100 * 100)
    assert box["share_of_its_box"] == pytest.approx(100 / 125)
    assert box["share_of_box_face"] == pytest.approx(100 / 125)
    assert box["its_box_is_a_box"] is True


def test_macros(result):
    macros = holders_macros(result.values)
    assert macros["HoldDesign"] == "100.0\\%"
    assert macros["HoldBoxShareOfItsBox"] == "80\\%"
    assert macros["HoldGammaSPYNet"].startswith("\\$")
    assert result.macros == macros


def test_profile_across_spot_levels(result):
    profile = result.values["profile"]
    assert profile["underlying"] == "SPY"
    assert len(profile["dealer"]) == len(profile["moves"]) == 61
    middle = profile["moves"].index(0.0)
    assert profile["dealer"][middle] == pytest.approx(result.values["dealer_gamma"]["SPY"]["net"])
