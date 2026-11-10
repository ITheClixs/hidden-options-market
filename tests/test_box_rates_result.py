"""Tests for the `box_rates` result: traded box rates against Treasuries and marks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.box_rates import benchmark_rates
from hidden_options.measure.box_rates_macros import box_rates_macros
from hidden_options.measure.box_rates_result import box_rates_result

D1 = pd.Timestamp("2026-10-21")
D2 = pd.Timestamp("2026-10-22")
E = pd.Timestamp("2026-12-18")
FAR = pd.Timestamp("2028-12-15")


def box_rows(day, *, root, lower, upper, price, size, expiry=E, minute=0):
    """The eight published rows of one box trade: four legs, each from both sides."""
    time = day + pd.Timedelta(hours=9, minutes=minute)
    legs = [("C", lower, price), ("P", lower, 0.0), ("C", upper, 0.0), ("P", upper, 0.0)]
    frame = pd.DataFrame(
        [
            {
                "trade_date": day,
                "time": time,
                "price": leg_price,
                "size": size,
                "root": root,
                "expiry": expiry,
                "right": right,
                "strike": strike,
                "spread": True,
            }
            for right, strike, leg_price in legs
        ]
    )
    return pd.concat([frame, frame], ignore_index=True)


def price_at(rate: float, width: float, day: pd.Timestamp, expiry: pd.Timestamp) -> float:
    return width * np.exp(-rate * (expiry - day).days / 365)


CURVE = pd.DataFrame(
    {
        "date": [D1, D2],
        "1 Mo": [4.0, 4.0],
        "3 Mo": [4.0, 4.0],
        "1 Yr": [4.0, 4.0],
        "5 Yr": [4.0, 4.0],
    }
)
# The curve is flat in quoted yields, not in continuous rates, so each trade has its own.
BENCHMARKS = benchmark_rates(CURVE, pd.Series([D1, D2]), np.array([58, 57]))


def report_for(day):
    """OCC marks that put the 2SPY box at exactly 4%."""
    value = price_at(0.04, 1000.0, day, E)
    return pd.DataFrame(
        {
            "report_date": [day] * 4,
            "root": ["2SPY"] * 4,
            "expiry": [E] * 4,
            "right": ["C", "P", "C", "P"],
            "strike": [100.0, 100.0, 1100.0, 1100.0],
            "mark_price": [value, 0.0, 0.0, 0.0],
        }
    )


LAST_BOXES = pd.DataFrame(
    {
        "root": ["2SPY", "2SPX"],
        "expiry": [E, E],
        "lower": [100.0, 4001.0],
        "upper": [1100.0, 9001.0],
        "face": [3e6, 1e6],
    }
)


@pytest.fixture
def result():
    days = [
        box_rows(
            D1,
            root="2SPY",
            lower=100.0,
            upper=1100.0,
            size=30,
            price=price_at(0.045, 1000.0, D1, E),
        ),
        pd.concat(
            [
                box_rows(
                    D2,
                    root="2SPY",
                    lower=100.0,
                    upper=1100.0,
                    size=10,
                    price=price_at(0.043, 1000.0, D2, E),
                ),
                box_rows(
                    D2,
                    root="2SPX",
                    lower=5000.0,
                    upper=6000.0,
                    size=5,
                    expiry=FAR,
                    minute=5,
                    price=price_at(0.05, 1000.0, D2, FAR),
                ),
            ],
            ignore_index=True,
        ),
    ]
    return box_rates_result(days, CURVE, report_for, LAST_BOXES)


def test_sample_counts(result):
    sample = result.values["sample"]
    assert sample["files"] == 2
    assert sample["box_trades"] == 3
    assert sample["executions"] == 12
    assert sample["box_face"] == pytest.approx(1000 * 100 * (30 + 10 + 5))
    assert sample["unresolved"] == 0
    assert (sample["first_date"], sample["last_date"]) == ("2026-10-21", "2026-10-22")


def test_headline_is_face_weighted_over_boxes_up_to_a_year(result):
    headline = result.values["headline"]
    assert headline["trades"] == 2
    benchmark = (30 * BENCHMARKS[0] + 10 * BENCHMARKS[1]) / 40
    assert headline["mean"] == pytest.approx((30 * 0.045 + 10 * 0.043) / 40 - benchmark)
    assert headline["rate"] == pytest.approx((30 * 0.045 + 10 * 0.043) / 40)
    assert headline["benchmark"] == pytest.approx(benchmark)


def test_long_boxes_are_in_their_own_bucket(result):
    buckets = result.values["by_maturity"]
    assert buckets["1m_3m"]["trades"] == 2
    assert buckets["over_2y"]["trades"] == 1
    assert buckets["over_2y"]["mean"] == pytest.approx(0.05 - 2 * np.log(1.02))
    assert buckets["to_1m"]["trades"] == 0


def test_groups_and_months(result):
    groups = result.values["by_underlying"]
    assert groups["SPY"]["trades"] == 2 and groups["SPX"]["trades"] == 0
    (month,) = result.values["monthly"]
    assert month["month"] == "2026-10"
    assert month["traded_face"] == pytest.approx(1000 * 100 * 45)
    assert month["trades"] == 2


def test_size_bands_are_a_diagnostic(result):
    bands = result.values["by_size"]
    assert bands["to_1m"]["trades"] == 1  # exactly 1m of face
    assert bands["1m_10m"]["trades"] == 1  # 3m of face
    assert bands["over_1bn"]["trades"] == 0
    macros = box_rates_macros(result.values)
    assert float(macros["BoxRSizeMedianLow"]) < float(macros["BoxRSizeMedianHigh"])


def test_marks_against_trades(result):
    marks = result.values["marks"]
    assert marks["matched"] == 2
    assert marks["mean"] == pytest.approx(0.04 - (30 * 0.045 + 10 * 0.043) / 40)


def test_open_interest_boxes_seen_trading(result):
    assert result.values["open_interest"]["traded_face_share"] == pytest.approx(0.75)


def test_macros(result):
    macros = box_rates_macros(result.values)
    assert macros["BoxRTrades"] == "3"
    assert macros["BoxRSpread"] == f"{(result.values['headline']['mean']) * 1e4:.0f}"
    assert macros["BoxRTradedShare"] == "75\\%"
    assert macros["BoxRTradedFace"] == "\\$0.0bn"
    assert macros["BoxRMonths"] == "1"
    assert macros["BoxRQuarterEndShare"] == "0\\%"
    assert result.macros == macros


def test_a_day_without_boxes_does_not_disturb_the_rest():
    quiet = box_rows(D1, root="2SPY", lower=100.0, upper=1100.0, size=30, price=950.0).iloc[:2]
    busy = box_rows(
        D2, root="2SPY", lower=100.0, upper=1100.0, size=10, price=price_at(0.043, 1000.0, D2, E)
    )
    found = box_rates_result([quiet, busy], CURVE, report_for, LAST_BOXES)
    assert found.values["sample"]["files"] == 2
    assert found.values["sample"]["box_trades"] == 1


def test_no_box_at_all_is_an_error():
    quiet = box_rows(D1, root="2SPY", lower=100.0, upper=1100.0, size=30, price=950.0).iloc[:2]
    with pytest.raises(ValueError, match="No box trade"):
        box_rates_result([quiet], CURVE, report_for, LAST_BOXES)
