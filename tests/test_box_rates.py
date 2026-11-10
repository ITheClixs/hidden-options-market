"""Tests for box trades in the FLEX execution reports and their rates (`measure.box_rates`)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.box_rates import (
    benchmark_rates,
    box_trades,
    continuous_curve,
    executions,
    mark_rates,
    rate_sample,
    spread_summary,
)

D = pd.Timestamp("2026-10-22")
T = pd.Timestamp("2026-10-22 09:15:00")
E = pd.Timestamp("2026-12-18")  # 57 days


def rows(legs, *, time=T, expiry=E, root="2SPY", size=52, spread=True, copies=2):
    """legs: (right, strike, price). Each row is repeated `copies` times, as published."""
    frame = pd.DataFrame(
        [
            {
                "trade_date": time.normalize(),
                "time": time,
                "price": price,
                "size": size,
                "root": root,
                "expiry": expiry,
                "right": right,
                "strike": strike,
                "spread": spread,
            }
            for right, strike, price in legs
        ]
    )
    return pd.concat([frame] * copies, ignore_index=True)


BOX = [("C", 10.01, 752.33), ("P", 10.01, 0.01), ("C", 10010.01, 0.02), ("P", 10010.01, 9178.2)]


class TestExecutions:
    def test_identical_rows_are_one_execution_seen_from_both_sides(self):
        found = executions(rows(BOX))
        assert len(found) == 4
        assert found["executions"].tolist() == [1, 1, 1, 1]

    def test_an_odd_count_rounds_up(self):
        found = executions(rows(BOX[:1], copies=3))
        assert found["executions"].tolist() == [2]


class TestBoxTrades:
    def test_four_legs_at_two_strikes_are_a_box(self):
        boxes, unresolved = box_trades(executions(rows(BOX)))
        assert unresolved == 0
        (box,) = boxes.to_dict("records")
        assert (box["root"], box["underlying"]) == ("2SPY", "SPY")
        assert (box["lower"], box["upper"], box["size"]) == (10.01, 10010.01, 52)
        assert box["price"] == pytest.approx((752.33 - 0.01) - (0.02 - 9178.2))
        assert box["face"] == pytest.approx(10000 * 100 * 52)
        assert box["days"] == 57
        assert box["rate"] == pytest.approx(-np.log(box["price"] / 10000) * 365 / 57)

    def test_a_box_done_twice_at_one_instant_counts_twice(self):
        boxes, _ = box_trades(executions(rows(BOX, copies=4)))
        assert boxes["size"].tolist() == [104]

    def test_legs_not_flagged_as_a_spread_are_not_a_box(self):
        boxes, _ = box_trades(executions(rows(BOX, spread=False)))
        assert boxes.empty

    def test_three_legs_are_not_a_box(self):
        boxes, unresolved = box_trades(executions(rows(BOX[:3])))
        assert boxes.empty and unresolved == 0

    def test_three_paired_strikes_at_one_instant_are_left_unresolved(self):
        legs = [*BOX, ("C", 500.0, 262.0), ("P", 500.0, 0.5)]
        boxes, unresolved = box_trades(executions(rows(legs)))
        assert boxes.empty and unresolved == 1

    def test_stock_legs_are_ignored(self):
        stock = rows([(None, 0.0, 766.0)], root=None, size=5000)
        boxes, _ = box_trades(executions(pd.concat([rows(BOX), stock], ignore_index=True)))
        assert len(boxes) == 1


class TestBenchmark:
    CURVE = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-10-21"), D],
            "1 Mo": [4.00, 4.10],
            "3 Mo": [4.00, 4.30],
            "6 Mo": [4.00, np.nan],
            "1 Yr": [4.00, 4.00],
            "2 Yr": [4.00, 3.80],
        }
    )

    def test_nodes_convert_to_continuous_compounding(self):
        years, rates = continuous_curve(self.CURVE.iloc[1])
        assert years.tolist() == pytest.approx([1 / 12, 0.25, 1.0, 2.0])  # the missing node is out
        assert rates[0] == pytest.approx(np.log(1 + 0.041 / 12) * 12)
        assert rates[2] == pytest.approx(2 * np.log(1 + 0.04 / 2))

    def test_interpolates_in_maturity_and_is_flat_below_a_month(self):
        dates = pd.Series([D, D, D])
        days = np.array([10, 61, 365])
        found = benchmark_rates(self.CURVE, dates, days)
        one_month = np.log(1 + 0.041 / 12) * 12
        three_month = np.log(1 + 0.043 * 0.25) / 0.25
        assert found[0] == pytest.approx(one_month)
        weight = (61 / 365 - 1 / 12) / (0.25 - 1 / 12)
        assert found[1] == pytest.approx(one_month + weight * (three_month - one_month))
        assert found[2] == pytest.approx(2 * np.log(1.02))

    def test_a_date_without_a_curve_takes_the_one_before(self):
        found = benchmark_rates(
            self.CURVE, pd.Series([pd.Timestamp("2026-10-24")]), np.array([365])
        )
        assert found[0] == pytest.approx(2 * np.log(1.02))

    def test_a_date_before_every_curve_has_no_benchmark(self):
        found = benchmark_rates(
            self.CURVE, pd.Series([pd.Timestamp("2026-10-01")]), np.array([365])
        )
        assert np.isnan(found[0])


def boxes(spec):
    """spec: (trade_date, days, rate, face, underlying)"""
    return pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp(day),
                "days": days,
                "rate": rate,
                "face": face,
                "price": 1.0,
                "underlying": underlying,
            }
            for day, days, rate, face, underlying in spec
        ]
    )


class TestSample:
    def test_short_dated_and_wild_rates_are_dropped_and_counted(self):
        trades = boxes(
            [
                ("2026-10-22", 57, 0.045, 1e6, "SPY"),
                ("2026-10-22", 3, 0.045, 1e6, "SPY"),  # under 7 days
                ("2026-10-22", 57, 0.90, 1e6, "SPY"),  # an error
            ]
        )
        sample, dropped = rate_sample(trades)
        assert len(sample) == 1
        assert dropped == {"short": 1, "out_of_range": 1, "no_price": 0}


class TestSpread:
    def test_face_weighted_mean_and_quantiles(self):
        trades = boxes(
            [
                ("2026-10-21", 57, 0.045, 3e6, "SPY"),
                ("2026-10-22", 57, 0.041, 1e6, "SPX"),
            ]
        ).assign(spread=[0.0050, 0.0010])
        found = spread_summary(trades)
        assert found["trades"] == 2
        assert found["face"] == pytest.approx(4e6)
        assert found["mean"] == pytest.approx((3 * 0.0050 + 1 * 0.0010) / 4)
        assert found["median"] == pytest.approx(0.0030)
        assert found["std_error"] is not None and found["std_error"] > 0
        assert found["dates"] == 2

    def test_an_empty_sample_is_reported_as_empty(self):
        found = spread_summary(boxes([]).assign(spread=[]))
        assert found["trades"] == 0 and found["mean"] is None


class TestMarks:
    def test_the_rate_in_the_marks_for_the_traded_box(self):
        trades = pd.DataFrame(
            {
                "trade_date": [D],
                "root": ["2SPY"],
                "expiry": [E],
                "lower": [10.01],
                "upper": [10010.01],
                "days": [57],
            }
        )
        report = pd.DataFrame(
            {
                "report_date": [D] * 4,
                "root": ["2SPY"] * 4,
                "expiry": [E] * 4,
                "right": ["C", "P", "C", "P"],
                "strike": [10.01, 10.01, 10010.01, 10010.01],
                "mark_price": [752.3348, 0.0001, 0.0001, 9185.263],
            }
        )
        found = mark_rates(trades, report)
        value = (752.3348 - 0.0001) - (0.0001 - 9185.263)
        assert found[0] == pytest.approx(-np.log(value / 10000) * 365 / 57)

    def test_a_box_missing_a_series_has_no_mark_rate(self):
        trades = pd.DataFrame(
            {
                "trade_date": [D],
                "root": ["2SPY"],
                "expiry": [E],
                "lower": [10.01],
                "upper": [10010.01],
                "days": [57],
            }
        )
        report = pd.DataFrame(
            {
                "report_date": [D],
                "root": ["2SPY"],
                "expiry": [E],
                "right": ["C"],
                "strike": [10.01],
                "mark_price": [752.3348],
            }
        )
        assert np.isnan(mark_rates(trades, report)[0])
