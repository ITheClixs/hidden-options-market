"""Tests for the hidden-gamma summaries."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.hidden_gamma_summary import (
    distribution,
    mark_check,
    per_underlying,
    pooled,
    signed_view,
    where,
)

D1, D2 = pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02")


def shares(rows):
    """rows: (date, symbol, listed_gross, listed_netted, listed_signed, flex_gross,
    flex_netted, flex_signed)"""
    frame = pd.DataFrame(
        rows,
        columns=[
            "date",
            "symbol",
            "listed_gross",
            "listed_netted",
            "listed_signed",
            "flex_gross",
            "flex_netted",
            "flex_signed",
        ],
    )
    frame["share_gross"] = frame["flex_gross"] / (frame["flex_gross"] + frame["listed_gross"])
    frame["share_netted"] = frame["flex_netted"] / (frame["flex_netted"] + frame["listed_gross"])
    frame["share_netted_both"] = frame["flex_netted"] / (
        frame["flex_netted"] + frame["listed_netted"]
    )
    return frame


SAMPLE = shares(
    [
        (D1, "AAA", 90, 60, 30, 10, 0, 10),
        (D2, "AAA", 70, 50, 30, 30, 10, -40),
        (D1, "BBB", 100, 100, -50, 0, 0, 0),
        (D2, "BBB", 100, 100, -50, 0, 0, 0),
    ]
)


class TestPerUnderlying:
    def test_median_over_settlements_with_group(self):
        medians = per_underlying(SAMPLE, {"AAA": "programme"})
        assert medians.loc["AAA", "share_gross"] == pytest.approx((0.1 + 0.3) / 2)
        assert medians.loc["AAA", "group"] == "programme"
        assert medians.loc["BBB", "group"] == "other"
        assert medians.loc["AAA", "settlements"] == 2


class TestDistribution:
    def test_counts_and_group_medians(self):
        medians = per_underlying(SAMPLE, {"AAA": "programme", "BBB": "control"})
        found = distribution(medians, ["programme", "control"])["share_gross"]
        assert found["at_least"] == {"0.05": 1, "0.10": 1, "0.25": 0}
        assert found["by_group"]["programme"] == pytest.approx(0.2)
        assert found["by_group"]["control"] == 0.0
        assert found["group_counts"] == {"programme": 1, "control": 1}

    def test_an_empty_group_has_no_median(self):
        medians = per_underlying(SAMPLE, {})
        assert distribution(medians, ["programme"])["share_gross"]["by_group"]["programme"] is None


class TestPooled:
    def test_sums_before_dividing(self):
        found = pooled(SAMPLE)
        assert found["share_gross"] == pytest.approx(40 / (40 + 360))
        assert found["share_netted"] == pytest.approx(10 / (10 + 360))
        assert found["share_netted_both"] == pytest.approx(10 / (10 + 310))


class TestWhere:
    def test_shares_by_bucket_sum_to_one(self):
        flex = pd.DataFrame(
            {
                "days": [3, 20, 200],
                "moneyness": [1.0, 0.5, 1.5],
                "gross": [1.0, 1.0, 2.0],
                "netted": [0.0, 1.0, 1.0],
            }
        )
        found = where(flex)
        assert found["days"]["<=7"]["gross"] == pytest.approx(0.25)
        assert found["days"][">90"]["netted"] == pytest.approx(0.5)
        assert found["moneyness"]["0.95-1.05"]["gross"] == pytest.approx(0.25)
        assert sum(v["gross"] for v in found["moneyness"].values()) == pytest.approx(1.0)


class TestSignedView:
    def test_flip_share_and_relative_size(self):
        found = signed_view(SAMPLE)
        # AAA D2: listed +30, FLEX -40 -> flips. AAA D1 and BBB do not.
        assert found["flip_share"] == pytest.approx(0.25)
        assert found["underlying_days"] == 4
        # |FLEX / listed| is 1/3, 4/3, 0 and 0: the median is 1/6.
        assert found["median_relative"] == pytest.approx(1 / 6)


class TestMarkCheck:
    def test_ratio_on_validated_series_only(self):
        flex = pd.DataFrame(
            {"open_interest": [10, 30], "gross": [100.0, 50.0], "sigma": [0.3, 0.4]}
        )
        found = mark_check(flex, pd.Series([0.33, float("nan")]), pd.Series([90.0, 80.0]))
        assert found["oi_share"] == pytest.approx(0.25)
        assert found["gamma_ratio"] == pytest.approx(0.9)
        assert found["median_vol_gap"] == pytest.approx(0.03)
        assert found["series"] == 1
