"""Tests for the `hidden_gamma` result on a small in-memory world.

Two settlements and two underlyings. AAA (programme) has a listed surface flat at 30%,
FLEX calls written outright and a FLEX conversion; BBB (control) has the same surface and
only a FLEX conversion, so its pair-netted FLEX gamma is zero. FLEX marks are European
Black-Scholes prices at 30%, so gamma from the marks matches gamma from the surface.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.hidden_gamma_result import GammaInputs, hidden_gamma_result
from hidden_options.measure.implied import RATE
from hidden_options.measure.pricing import black_scholes
from hidden_options.publish.latex import render_macros
from hidden_options.publish.results import Result, read_results, write_result

DAYS = (pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02"))
SPOT, VOL = 100.0, 0.3
EXPIRIES = (pd.Timestamp("2026-10-16"), pd.Timestamp("2026-12-18"))
DOMAIN = frozenset(
    (m, d)
    for m in (
        "<0.70",
        "0.70-0.80",
        "0.80-0.90",
        "0.90-0.95",
        "0.95-1.00",
        "1.00-1.05",
        "1.05-1.10",
        "1.10-1.20",
        "1.20-1.30",
        ">=1.30",
    )
    for d in ("<=7", "8-30", "31-90", "91-365", ">365")
)


def chains() -> pd.DataFrame:
    rows = []
    for day in DAYS:
        for symbol in ("AAA", "BBB"):
            for expiry in EXPIRIES:
                for right, strike in (("P", 80.0), ("P", 95.0), ("C", 105.0), ("C", 120.0)):
                    rows.append(
                        {
                            "date": day,
                            "symbol": symbol,
                            "root": symbol,
                            "expiry": expiry,
                            "right": right,
                            "strike": strike,
                            "open_interest": 1000,
                            "bid": 1.0,
                            "ask": 1.1,
                            "theo": 1.05,
                            "underlying_price": SPOT,
                            "iv": VOL,
                        }
                    )
    return pd.DataFrame(rows)


def mark(day: pd.Timestamp, expiry: pd.Timestamp, strike: float, right: str) -> float:
    years = (expiry - day).days / 365
    price = black_scholes(SPOT, strike, years, VOL, rate=RATE, carry=0.0, is_call=right == "C")
    return float(np.asarray(price).item())


def panel() -> pd.DataFrame:
    lines = [
        ("1AAA", "C", 110.0, 5000),  # written calls, unpaired
        ("1AAA", "C", 100.0, 2000),  # a conversion at 100
        ("1AAA", "P", 100.0, 2000),
        ("1BBB", "C", 100.0, 3000),  # BBB: only a conversion
        ("1BBB", "P", 100.0, 3000),
    ]
    rows = [
        {
            "report_date": day,
            "kind": "equity",
            "class_name": root,
            "root": root,
            "underlying": root[1:],
            "right": right,
            "expiry": EXPIRIES[0],
            "strike": strike,
            "mark_price": mark(day, EXPIRIES[0], strike, right),
            "open_interest": oi,
            "exercise_style": "european",
        }
        for day in DAYS
        for root, right, strike, oi in lines
    ]
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def result() -> Result:
    inputs = GammaInputs(
        chains=chains(),
        panel=panel(),
        groups={"AAA": "programme", "BBB": "control"},
        domain=DOMAIN,
    )
    return hidden_gamma_result(inputs)


def test_named_with_valid_macros(result):
    assert result.name == "hidden_gamma"
    assert "GammaMedianGross" in render_macros({"hidden_gamma": result})


def test_values_survive_a_round_trip_through_json(result, tmp_path):
    write_result(result, tmp_path)
    again = read_results(tmp_path)["hidden_gamma"]
    assert json.dumps(again.values, sort_keys=True) == json.dumps(result.values, sort_keys=True)


def test_a_conversion_alone_has_no_netted_gamma(result):
    bbb = result.values["underlyings"]["BBB"]
    assert bbb["share_gross"] > 0
    assert bbb["share_netted"] == 0.0
    assert bbb["share_netted_both"] == 0.0


def test_netting_never_raises_a_share(result):
    for figures in result.values["underlyings"].values():
        assert figures["share_netted"] <= figures["share_gross"]


def test_gamma_from_the_marks_matches_the_surface_it_was_priced_at(result):
    marks = result.values["marks"]
    assert marks["oi_share"] == pytest.approx(1.0)
    assert marks["gamma_ratio"] == pytest.approx(1.0, rel=1e-4)


def test_groups_and_sample_are_recorded(result):
    dist = result.values["distribution"]["share_gross"]
    assert dist["group_counts"] == {"programme": 1, "control": 1, "other": 0}
    assert result.inputs["settlements"] == 2
    assert result.inputs["underlyings"] == 2


def test_table_reads_the_result_macros(result):
    from hidden_options.measure.hidden_gamma_table import hidden_gamma_table

    text = hidden_gamma_table({"hidden_gamma": result})
    assert "\\label{tab:gamma}" in text
    assert result.macros["GammaMedianGross"] in text
    with pytest.raises(KeyError):
        hidden_gamma_table({})


def test_names_above_a_tenth_netted():
    from hidden_options.measure.hidden_gamma_macros import _names

    found = _names(
        {
            "AAA": {"share_netted": 0.12, "share_netted_both": 0.30},
            "BBB": {"share_netted": 0.40, "share_netted_both": 0.05},
            "CCC": {"share_netted": 0.01, "share_netted_both": 0.01},
        }
    )
    assert found == {"GammaTenNettedNames": "BBB and AAA", "GammaTenBothNames": "AAA"}
