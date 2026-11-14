"""Tests for the `anatomy` result: the product split over the panel and its macros."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.anatomy import CATEGORIES
from hidden_options.measure.anatomy_macros import anatomy_macros
from hidden_options.measure.anatomy_result import anatomy_result, gamma_by_category

D1 = pd.Timestamp("2026-10-21")
D2 = pd.Timestamp("2026-10-22")
E = pd.Timestamp("2026-12-18")


def day(date, *, box=500, stock=1800):
    """A report date with one SPY box, one fund package and one lone put."""
    rows = [
        ("2SPY", "SPY", "C", 100.0, 660.0, box),
        ("2SPY", "SPY", "P", 100.0, 0.01, box),
        ("2SPY", "SPY", "C", 1200.0, 0.01, box),
        ("2SPY", "SPY", "P", 1200.0, 430.0, box),
        ("4SPY", "SPY", "C", 6.81, 755.0, stock),
        ("4SPY", "SPY", "P", 680.59, 3.7, stock),
        ("4SPY", "SPY", "C", 780.98, 10.4, stock),
        ("2SPX", "SPX", "C", 5877.01, 1829.8, 20),
        ("2SPX", "SPX", "P", 5877.01, 12.3, 20),
        ("4SPY", "SPY", "P", 650.0, 2.5, 777),
    ]
    return pd.DataFrame(
        [
            {
                "report_date": date,
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


GAMMA = pd.DataFrame(
    [
        {"date": D2, "root": "4SPY", "expiry": E, "right": "P", "strike": 680.59, "gross": 30.0},
        {"date": D2, "root": "4SPY", "expiry": E, "right": "C", "strike": 780.98, "gross": 50.0},
        {"date": D2, "root": "4SPY", "expiry": E, "right": "P", "strike": 650.0, "gross": 20.0},
    ]
)


@pytest.fixture
def result():
    return anatomy_result([day(D1, box=250, stock=900), day(D2)], GAMMA, chance_every=1)


def test_first_and_last_dates_carry_the_split(result):
    values = result.values
    assert values["dates"] == 2
    assert (values["first"]["date"], values["last"]["date"]) == ("2026-10-21", "2026-10-22")
    last = values["last"]["split"]
    assert set(last) == set(CATEGORIES)
    assert last["box"]["open_interest"] == 2000
    assert last["stock_leg"]["value"] == pytest.approx(755.0 * 1800 * 100)
    assert last["package_leg"]["series"] == 2
    assert last["pair"]["series"] == 2
    assert last["other"]["open_interest"] == 777


def test_box_face_grows_with_the_count(result):
    boxes = result.values["boxes"]
    assert boxes["last"]["face"] == pytest.approx(1100 * 100 * 500)
    assert boxes["first"]["face"] == pytest.approx(1100 * 100 * 250)
    assert boxes["growth"] == pytest.approx(2.0)


def test_daily_rows_cover_every_date(result):
    daily = result.values["daily"]
    assert [row["date"] for row in daily] == ["2026-10-21", "2026-10-22"]
    assert daily[1]["box_face"] == pytest.approx(1100 * 100 * 500)
    assert daily[1]["value"]["stock_leg"] == pytest.approx(755.0 * 1800 * 100)
    assert daily[1]["pair_notional"] == pytest.approx(20 * 100 * (5877.01 + 1829.8 - 12.3))


def test_stock_legs_by_underlying_on_the_last_date(result):
    stock = result.values["stock_legs"]
    assert stock["last_by_underlying"]["SPY"] == pytest.approx(755.0 * 1800 * 100)
    assert stock["growth"] == pytest.approx(2.0)
    assert stock["underlyings"] == 1


def test_chance_benchmark_is_recorded(result):
    chance = result.values["chance"]
    assert chance["dates"] == 2
    assert 0.0 <= chance["box_face_share"] <= 1.0
    assert chance["box_face_share_pairs_kept"] >= 0.0
    assert result.values["boxes"]["last"]["unambiguous_face"] == pytest.approx(1100 * 100 * 500)


def test_gamma_by_category(result):
    gamma = result.values["gamma"]
    assert gamma["share"]["package_leg"] == pytest.approx(0.8)
    assert gamma["share"]["other"] == pytest.approx(0.2)
    assert gamma["matched_share"] == pytest.approx(1.0)


def test_gamma_join_counts_unmatched_rows():
    series = pd.DataFrame(
        {
            "root": ["4SPY"],
            "expiry": [E],
            "right": ["P"],
            "strike": [650.0],
            "category": ["other"],
        }
    )
    rows = GAMMA[["root", "expiry", "right", "strike", "gross"]]
    sums, matched = gamma_by_category(rows, series)
    assert sums["other"] == pytest.approx(20.0)
    assert matched == pytest.approx(20.0)


def test_macros_cover_the_headline_figures(result):
    macros = anatomy_macros(result.values)
    assert macros["AnatBoxFace"] == "\\$0.1bn"
    assert macros["AnatBoxGrowth"] == "2.0"
    assert macros["AnatDates"] == "2"
    for stem in ("Box", "Stock", "Package", "Pair", "Other"):
        assert f"Anat{stem}ValueShare" in macros
        assert f"Anat{stem}OIShare" in macros
        assert f"AnatGamma{stem}" in macros
    assert result.macros == macros


def test_table_prints_the_macro_strings(result):
    from hidden_options.measure.anatomy_table import anatomy_table

    table = anatomy_table({"anatomy": result})
    assert "Box spreads" in table
    assert result.macros["AnatStockValue"] in table
    assert "tab:anatomy" in table


def test_peak_composition(result):
    (box,) = result.values["boxes"]["peak_largest"]
    assert box["root"] == "2SPY" and box["count"] == 500


def test_peak_macros(result):
    macros = anatomy_macros(result.values)
    assert macros["AnatBoxPeakFirstUnderlying"] == "SPY"
    assert macros["AnatChanceBoxPairsKept"].endswith("\\%")
    assert macros["AnatBoxUnambiguousFace"] == "\\$0.1bn"
