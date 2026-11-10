"""Tests for F11 (value by product) and F12 (box lending and its traded spread)."""

from __future__ import annotations

import matplotlib as mpl
import pytest

from hidden_options.figures import products as figures
from hidden_options.figures.style import apply_style
from hidden_options.measure.anatomy import CATEGORIES
from hidden_options.publish.results import Result, write_result

DAILY = [
    {
        "date": f"2026-10-{day:02d}",
        "value": {name: (place + 1) * 1e9 * day for place, name in enumerate(CATEGORIES)},
        "box_face": 2e9 * day,
        "box_neighbour_face": 1.5e9 * day,
    }
    for day in (20, 21, 22)
]
MONTHLY = [
    {"month": "2026-09", "median": 0.0040, "mean": 0.0041, "trades": 5, "traded_face": 1e9},
    {"month": "2026-10", "median": None, "mean": None, "trades": 0, "traded_face": 2e9},
]


@pytest.fixture
def styled():
    with mpl.rc_context():
        apply_style()
        yield


def test_split_stacks_every_category_and_names_each(styled):
    fig = figures.fig_product_split(DAILY)
    (ax,) = fig.axes
    assert len(ax.collections) == len(CATEGORIES)
    labels = {text.get_text() for text in ax.texts}
    assert labels == {label for _, label, _ in figures.LAYERS}
    assert {name for name, _, _ in figures.LAYERS} == set(CATEGORIES)


def test_lending_has_two_panels_and_skips_months_without_trades(styled):
    fig = figures.fig_box_lending(DAILY, MONTHLY)
    top, bottom = fig.axes
    assert len(top.get_lines()) == 2
    spread = [line for line in bottom.get_lines() if len(line.get_xdata()) == 1]
    assert len(spread) == 1  # only the month with a median


def test_builders_read_the_results(tmp_path, styled):
    stamp = "2026-11-10T00:00:00+00:00"
    write_result(Result("anatomy", {"daily": DAILY}, {}, {}, stamp), tmp_path / "results")
    write_result(Result("box_rates", {"monthly": MONTHLY}, {}, {}, stamp), tmp_path / "results")
    figures.build_product_split(tmp_path / "results", tmp_path)
    figures.build_box_lending(tmp_path / "results", tmp_path)
    for stem in ("product_split", "box_lending"):
        assert (tmp_path / "paper" / "figures" / f"{stem}.pdf").exists()


def test_a_missing_result_says_what_to_run(tmp_path):
    (tmp_path / "results").mkdir()
    with pytest.raises(FileNotFoundError, match="anatomy"):
        figures.build_product_split(tmp_path / "results", tmp_path)
