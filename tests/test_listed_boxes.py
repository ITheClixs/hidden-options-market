"""Tests for listed SPX box rates by put-call parity (`measure.listed_boxes`)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.box_rates import settlement_days
from hidden_options.measure.listed_boxes import listed_curve, rate_at

D = pd.Timestamp("2026-10-22")


def chain(rate, expiries, *, spot=7600.0, carry=0.012, spread=0.4, strikes=None):
    """Quotes that satisfy put-call parity at `rate` exactly, with a symmetric spread."""
    strikes = strikes if strikes is not None else np.arange(6200.0, 9000.0, 100.0)
    rows = []
    for expiry in expiries:
        days = settlement_days(pd.Series([D]), pd.Series([expiry]))[0]
        years = days / 365
        for strike in strikes:
            forward_value = spot * np.exp(-carry * years) - strike * np.exp(-rate * years)
            put = max(0.0, -forward_value) + 20.0  # intrinsic plus some time value
            call = put + forward_value  # at least 20 as well
            for right, mid in (("C", call), ("P", put)):
                rows.append(
                    {
                        "date": D,
                        "symbol": "SPX",
                        "expiry": expiry,
                        "right": right,
                        "strike": float(strike),
                        "bid": mid - spread / 2,
                        "ask": mid + spread / 2,
                        "underlying_price": spot,
                    }
                )
    return pd.DataFrame(rows)


E1, E2 = pd.Timestamp("2026-12-18"), pd.Timestamp("2027-06-17")


def test_parity_regression_recovers_the_rate():
    curve = listed_curve(chain(0.042, [E1, E2]), D)
    assert len(curve) == 2
    assert curve["rate"].to_numpy() == pytest.approx([0.042, 0.042], abs=1e-9)
    assert (curve["strikes"] >= 10).all()
    assert curve["r2"].min() > 0.999


def test_strikes_far_from_spot_and_bad_quotes_are_left_out():
    quotes = chain(0.042, [E1])
    quotes.loc[quotes["strike"] == 7000.0, "bid"] = 0.0  # no bid: out
    quotes.loc[quotes["strike"] == 7100.0, "ask"] = quotes["bid"] - 1  # crossed: out
    curve = listed_curve(quotes, D)
    inside = np.arange(6200.0, 9000.0, 100.0)
    within = inside[np.abs(inside / 7600.0 - 1) <= 0.2]
    assert curve["strikes"].iloc[0] == len(within) - 2


def test_an_expiry_with_too_few_strikes_is_dropped():
    curve = listed_curve(chain(0.042, [E1], strikes=np.arange(7400.0, 7800.0, 100.0)), D)
    assert curve.empty


def test_rate_at_interpolates_in_days_and_is_flat_outside():
    curve = pd.DataFrame({"settle_days": [30, 90], "rate": [0.04, 0.046]})
    assert rate_at(curve, 60) == pytest.approx(0.043)
    assert rate_at(curve, 10) == pytest.approx(0.04)
    assert rate_at(curve, 400) == pytest.approx(0.046)
    assert np.isnan(rate_at(curve.iloc[0:0], 60))


def test_result_matches_flex_trades_to_the_curve_of_their_date():
    from hidden_options.measure.listed_boxes_result import listed_boxes_result

    quotes = chain(0.042, [E1, E2])
    days = settlement_days(pd.Series([D, D]), pd.Series([E1, E2]))
    headline = pd.DataFrame(
        {
            "trade_date": [D, D, pd.Timestamp("2026-10-23")],
            "settle_days": [days[0], days[1], days[0]],
            "rate": [0.045, 0.044, 0.045],
            "benchmark": [0.039, 0.039, 0.039],
            "face": [1e9, 2e9, 1e9],
            "underlying": ["SPY", "SPX", "SPY"],
        }
    )
    found = listed_boxes_result(headline, quotes)
    values = found.values
    assert values["sessions"] == 1
    assert values["window_trades"] == 2  # the 23rd is after the last session
    assert values["difference"]["trades"] == 2
    assert values["difference"]["median"] == pytest.approx((0.003 + 0.002) / 2)
    assert values["by_underlying"]["SPY"]["median"] == pytest.approx(0.003)
    assert values["listed_over_treasury"]["median"] == pytest.approx(0.003)
    assert found.macros["LBoxDiffMedian"] == "25"


def test_a_session_without_quotes_has_no_curve():
    quotes = chain(0.042, [E1]).assign(bid=np.nan, ask=np.nan, underlying_price=np.nan)
    assert listed_curve(quotes, D).empty
