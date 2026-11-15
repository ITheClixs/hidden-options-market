"""Tests for SPY's gamma exposure under the three readings (`measure.gex_map`)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.gex_map import LEVELS, gex_profiles, zero_level

D = pd.Timestamp("2026-11-09")
E = pd.Timestamp("2026-12-31")


def series(rows):
    """rows: (source, right, strike, contracts, sigma, signed_share, dealer_sign)"""
    return pd.DataFrame(
        [
            {
                "source": source,
                "expiry": E,
                "right": right,
                "strike": strike,
                "open_interest": count,
                "sigma": sigma,
                "signed": signed,
                "dealer_sign": dealer,
            }
            for source, right, strike, count, sigma, signed, dealer in rows
        ]
    )


BOOK = series(
    [
        ("listed", "C", 760.0, 1000, 0.2, 0.0, 0.0),
        ("listed", "P", 700.0, 3000, 0.25, 0.0, 0.0),
        ("flex", "P", 680.0, 500, 0.25, 1.0, 1.0),  # a fund's short lower put: dealer long
        ("flex", "P", 720.0, 500, 0.22, 1.0, -1.0),  # a fund's long upper put: dealer short
        ("flex", "C", 790.0, 400, 0.18, 0.0, 0.0),  # unmatched: convention
    ]
)


def test_three_readings_differ_only_where_they_should():
    found = gex_profiles(BOOK, spot=750.0, as_of=D, rate=0.04)
    moves = found["moves"]
    assert len(moves) == len(LEVELS)
    listed, convention, signed = found["listed"], found["convention"], found["signed"]
    middle = moves.index(0.0)
    # The convention signs puts as dealer-short, so adding FLEX puts lowers the net.
    assert convention[middle] < listed[middle]
    # Signing the lower put as dealer-long raises the net against the convention.
    assert signed[middle] > convention[middle]
    # Reading 3 equals reading 2 once the signed legs are taken out of the comparison.
    unsigned = gex_profiles(BOOK.assign(signed=0.0), spot=750.0, as_of=D, rate=0.04)
    assert unsigned["signed"] == pytest.approx(unsigned["convention"])


def test_a_partly_matched_series_is_signed_in_proportion():
    half = BOOK.copy()
    half.loc[half["strike"] == 680.0, "signed"] = 0.5
    full = gex_profiles(BOOK, spot=750.0, as_of=D, rate=0.04)
    part = gex_profiles(half, spot=750.0, as_of=D, rate=0.04)
    middle = full["moves"].index(0.0)
    gap_full = full["signed"][middle] - full["convention"][middle]
    gap_part = part["signed"][middle] - part["convention"][middle]
    assert gap_part > 0
    assert gap_part < gap_full


def test_zero_level_interpolates_the_sign_change_nearest_spot():
    moves = [-0.1, -0.05, 0.0, 0.05]
    net = [-2.0, -1.0, 1.0, 3.0]
    assert zero_level(moves, net) == pytest.approx(-0.025)
    assert zero_level(moves, [1.0, 1.0, 2.0, 3.0]) is None


def test_matched_share_of_listed_gamma():
    found = gex_profiles(BOOK, spot=750.0, as_of=D, rate=0.04)
    assert 0 < found["matched_share_of_listed"] < 1
    assert 0 < found["matched_share_of_flex"] <= 1
    assert np.isfinite(found["listed"]).all()
