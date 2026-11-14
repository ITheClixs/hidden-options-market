"""Tests for the product split of one FLEX report date (`measure.anatomy`)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.anatomy import (
    CATEGORIES,
    box_lending,
    classify,
    colocated_other_share,
    new_lines,
    pair_notional,
    shuffled,
    shuffled_pairs,
    split,
    stock_leg_value,
)

D = pd.Timestamp("2026-10-22")
E = pd.Timestamp("2026-12-18")


def report(rows, *, expiry=E, date=D):
    """rows: (root, underlying, right, strike, mark, open_interest[, expiry])"""
    return pd.DataFrame(
        [
            {
                "report_date": date,
                "kind": "equity",
                "root": r[0],
                "underlying": r[1],
                "right": r[2],
                "strike": r[3],
                "mark_price": r[4],
                "open_interest": r[5],
                "expiry": r[6] if len(r) > 6 else expiry,
            }
            for r in rows
        ]
    )


BOX = [
    ("2SPY", "SPY", "C", 100.0, 660.0, 500),
    ("2SPY", "SPY", "P", 100.0, 0.01, 500),
    ("2SPY", "SPY", "C", 1200.0, 0.01, 500),
    ("2SPY", "SPY", "P", 1200.0, 430.0, 500),
]
PACKAGE = [
    ("4SPY", "SPY", "C", 6.81, 755.0, 1800),  # the fund's stock leg
    ("4SPY", "SPY", "P", 680.59, 3.7, 1800),
    ("4SPY", "SPY", "P", 612.53, 1.6, 1800),
    ("4SPY", "SPY", "C", 780.98, 10.4, 1800),
]


def categories(found) -> dict:
    series = found.series
    return {
        (r.root, r.right, r.strike): r.category
        for r in series[["root", "right", "strike", "category"]].itertuples()
    }


class TestClassify:
    def test_a_box_is_two_paired_strikes_with_one_count(self):
        found = classify(report(BOX))
        assert set(found.series["category"]) == {"box"}
        (box,) = found.boxes.to_dict("records")
        assert (box["lower"], box["upper"], box["count"]) == (100.0, 1200.0, 500)
        assert box["face"] == pytest.approx(1100 * 100 * 500)
        assert box["value"] == pytest.approx(((660 - 0.01) - (0.01 - 430)) * 100 * 500)
        assert box["underlying"] == "SPY"

    def test_several_boxes_with_one_count_match_from_the_outside_in(self):
        rows = [
            ("2SPX", "SPX", right, strike, 1.0, 40)
            for strike in (100.0, 200.0, 300.0, 400.0)
            for right in ("C", "P")
        ]
        found = classify(report(rows))
        spans = sorted(zip(found.boxes["lower"], found.boxes["upper"], strict=True))
        assert spans == [(100.0, 400.0), (200.0, 300.0)]
        assert found.boxes["face"].sum() == pytest.approx((300 + 100) * 100 * 40)
        assert found.neighbour_face == pytest.approx((100 + 100) * 100 * 40)

    def test_the_odd_paired_strike_stays_a_pair(self):
        rows = [
            ("2SPX", "SPX", right, strike, 1.0, 40)
            for strike in (100.0, 200.0, 300.0)
            for right in ("C", "P")
        ]
        found = categories(classify(report(rows)))
        assert found[("2SPX", "C", 100.0)] == "box"
        assert found[("2SPX", "P", 300.0)] == "box"
        assert found[("2SPX", "C", 200.0)] == "pair"
        assert found[("2SPX", "P", 200.0)] == "pair"

    def test_boxes_do_not_cross_roots_or_expiries(self):
        later = E + pd.Timedelta(days=30)
        rows = [
            ("2SPY", "SPY", "C", 100.0, 660.0, 500),
            ("2SPY", "SPY", "P", 100.0, 0.01, 500),
            ("4SPY", "SPY", "C", 1200.0, 0.01, 500),
            ("4SPY", "SPY", "P", 1200.0, 430.0, 500),
            ("2SPY", "SPY", "C", 900.0, 0.5, 500, later),
            ("2SPY", "SPY", "P", 900.0, 140.0, 500, later),
        ]
        found = classify(report(rows))
        assert found.boxes.empty
        assert set(found.series["category"]) == {"pair"}

    def test_a_fund_package_is_a_stock_leg_and_the_legs_that_share_its_count(self):
        extra = [("4SPY", "SPY", "P", 650.0, 2.5, 777)]
        found = categories(classify(report(PACKAGE + extra)))
        assert found[("4SPY", "C", 6.81)] == "stock_leg"
        assert found[("4SPY", "P", 680.59)] == "package_leg"
        assert found[("4SPY", "P", 612.53)] == "package_leg"
        assert found[("4SPY", "C", 780.98)] == "package_leg"
        assert found[("4SPY", "P", 650.0)] == "other"

    def test_a_call_above_the_threshold_is_not_a_stock_leg(self):
        # 220 against a mark of 544: 29% of mark plus strike.
        rows = [("2SPY", "SPY", "C", 220.01, 544.0, 440)]
        assert categories(classify(report(rows))) == {("2SPY", "C", 220.01): "other"}

    def test_a_deep_call_at_a_paired_strike_is_a_pair(self):
        rows = [
            ("2SPY", "SPY", "C", 10.01, 752.0, 300),
            ("2SPY", "SPY", "P", 10.01, 0.0001, 300),
        ]
        assert set(categories(classify(report(rows))).values()) == {"pair"}

    def test_a_paired_strike_with_a_stock_legs_count_is_a_package_leg(self):
        rows = [
            ("4SPY", "SPY", "C", 6.79, 755.6, 1395),
            ("4SPY", "SPY", "C", 681.89, 90.4, 1395),
            ("4SPY", "SPY", "P", 681.89, 4.7, 1395),
            ("4SPY", "SPY", "P", 620.52, 1.3, 1395),
        ]
        found = categories(classify(report(rows)))
        assert found[("4SPY", "C", 6.79)] == "stock_leg"
        assert found[("4SPY", "C", 681.89)] == "package_leg"
        assert found[("4SPY", "P", 681.89)] == "package_leg"

    def test_rows_without_open_interest_are_left_out(self):
        rows = [*BOX, ("2SPY", "SPY", "C", 700.0, 80.0, 0)]
        found = classify(report(rows))
        assert len(found.series) == 4

    def test_every_series_gets_one_category(self):
        found = classify(report(BOX + PACKAGE))
        assert set(found.series["category"]) <= set(CATEGORIES)
        assert len(found.series) == 8


class TestSummaries:
    def test_split_adds_up(self):
        found = classify(report(BOX + PACKAGE + [("4SPY", "SPY", "P", 650.0, 2.5, 777)]))
        parts = split(found.series)
        assert set(parts) == set(CATEGORIES)
        assert sum(p["series"] for p in parts.values()) == 9
        assert parts["box"]["open_interest"] == 2000
        assert parts["stock_leg"]["value"] == pytest.approx(755.0 * 1800 * 100)
        assert parts["other"]["open_interest"] == 777

    def test_box_lending_by_maturity_underlying_and_style(self):
        far = D + pd.Timedelta(days=800)
        rows = [
            *BOX,  # SPY, European, 57 days, wide
            ("1AMD", "AMD", "C", 100.0, 55.0, 10, far),  # American, over 2 years, narrow
            ("1AMD", "AMD", "P", 100.0, 5.0, 10, far),
            ("1AMD", "AMD", "C", 110.0, 50.0, 10, far),
            ("1AMD", "AMD", "P", 110.0, 9.0, 10, far),
        ]
        found = classify(report(rows))
        lending = box_lending(found, D)
        spy, amd = 1100 * 100 * 500, 10 * 100 * 10
        assert lending["boxes"] == 2
        assert lending["face"] == pytest.approx(spy + amd)
        assert lending["by_maturity"]["1m_3m"] == pytest.approx(spy)
        assert lending["by_maturity"]["over_2y"] == pytest.approx(amd)
        assert lending["by_underlying"] == pytest.approx({"SPX": 0.0, "SPY": spy, "other": amd})
        assert lending["european_share"] == pytest.approx(spy / (spy + amd))
        assert lending["wide_share"] == pytest.approx(spy / (spy + amd))
        assert lending["neighbour_face"] == pytest.approx(spy + amd)

    def test_the_rate_in_the_marks_is_face_weighted_and_skips_the_last_week(self):
        soon = D + pd.Timedelta(days=3)
        year = D + pd.Timedelta(days=365)
        price = 1000 * np.exp(-0.04)  # 4% over one year on a width of 1000
        rows = [
            ("2SPX", "SPX", "C", 4000.0, price, 10, year),
            ("2SPX", "SPX", "P", 4000.0, 0.0, 10, year),
            ("2SPX", "SPX", "C", 5000.0, 0.0, 10, year),
            ("2SPX", "SPX", "P", 5000.0, 0.0, 10, year),
            ("2SPX", "SPX", "C", 4000.0, 500.0, 99, soon),  # 3 days: no rate
            ("2SPX", "SPX", "P", 4000.0, 0.0, 99, soon),
            ("2SPX", "SPX", "C", 5000.0, 0.0, 99, soon),
            ("2SPX", "SPX", "P", 5000.0, 0.0, 99, soon),
        ]
        lending = box_lending(classify(report(rows)), D)
        assert lending["mark_rate"] == pytest.approx(0.04)

    def test_pair_notional_is_count_times_the_forward(self):
        rows = [
            ("2SPX", "SPX", "C", 5877.01, 1829.8, 20),
            ("2SPX", "SPX", "P", 5877.01, 12.3, 20),
        ]
        found = classify(report(rows))
        assert pair_notional(found.series) == pytest.approx(20 * 100 * (5877.01 + 1829.8 - 12.3))

    def test_stock_leg_value_by_underlying(self):
        rows = [*PACKAGE, ("4QQQ", "QQQ", "C", 7.0, 697.0, 50)]
        value = stock_leg_value(classify(report(rows)).series)
        assert value["SPY"] == pytest.approx(755.0 * 1800 * 100)
        assert value["QQQ"] == pytest.approx(697.0 * 50 * 100)

    def test_colocated_share_of_other(self):
        elsewhere = E + pd.Timedelta(days=14)
        rows = [
            *PACKAGE,
            ("4SPY", "SPY", "P", 650.0, 2.5, 300),  # other, beside a stock leg
            ("4SPY", "SPY", "P", 650.0, 2.5, 100, elsewhere),  # other, no stock leg there
        ]
        assert colocated_other_share(classify(report(rows)).series) == pytest.approx(0.75)


class TestChance:
    def test_shuffle_keeps_each_bucket_and_breaks_the_lines(self):
        day = report(BOX + PACKAGE)
        mixed = shuffled(day, np.random.default_rng(3))
        assert len(mixed) == len(day)
        for _, bucket in mixed.groupby(["root", "expiry"]):
            original = day[(day["root"] == bucket["root"].iloc[0])]
            assert sorted(bucket["open_interest"]) == sorted(original["open_interest"])
        again = shuffled(day, np.random.default_rng(3))
        assert mixed["open_interest"].tolist() == again["open_interest"].tolist()
        assert day["open_interest"].tolist() == [500, 500, 500, 500, 1800, 1800, 1800, 1800]


class TestPairsKeptShuffle:
    def test_pairs_stay_paired_and_roots_keep_their_counts(self):
        later = E + pd.Timedelta(days=30)
        rows = [
            ("2SPX", "SPX", right, strike, 1.0, count, expiry)
            for strike, count, expiry in (
                (100.0, 40, E),
                (200.0, 40, E),
                (300.0, 7, later),
                (400.0, 9, later),
            )
            for right in ("C", "P")
        ] + [("2SPX", "SPX", "C", 555.0, 1.0, 123, E)]
        day = report(rows)
        mixed = shuffled_pairs(day, np.random.default_rng(1))
        wide = mixed.pivot_table(
            index=["expiry", "strike"], columns="right", values="open_interest", aggfunc="sum"
        )
        paired = wide.dropna()
        assert (paired["C"] == paired["P"]).all()
        assert sorted(paired["C"]) == [7, 9, 40, 40]
        lone = mixed[(mixed["strike"] == 555.0)]["open_interest"].iloc[0]
        assert lone == 123

    def test_unambiguous_face_counts_groups_of_two_only(self):
        rows = [
            ("2SPX", "SPX", right, strike, 1.0, count)
            for strike, count in (
                (100.0, 40),
                (200.0, 40),
                (300.0, 9),
                (400.0, 9),
                (500.0, 9),
                (600.0, 9),
            )
            for right in ("C", "P")
        ]
        lending = box_lending(classify(report(rows)), D)
        assert lending["unambiguous_face"] == pytest.approx(100 * 100 * 40)
        assert lending["face"] == pytest.approx(100 * 100 * 40 + (300 + 100) * 100 * 9)


def test_new_lines_record_the_first_date_a_line_has_open_interest():
    first = report([("2SPY", "SPY", "C", 100.0, 1.0, 5), ("2SPY", "SPY", "P", 100.0, 1.0, 0)])
    later = D + pd.Timedelta(days=1)
    second = report(
        [("2SPY", "SPY", "C", 100.0, 1.0, 5), ("2SPY", "SPY", "P", 200.0, 1.0, 3)], date=later
    )
    known = new_lines(pd.DataFrame(columns=["root", "expiry", "strike", "first_date"]), first, D)
    known = new_lines(known, second, later)
    dates = dict(zip(known["strike"], known["first_date"], strict=True))
    assert dates == {100.0: D, 200.0: later}
