"""Tests for F9 (FLEX gamma share, gross against netted) and F10 (pinning on placebo dates)."""

from __future__ import annotations

import matplotlib as mpl
import pytest
from matplotlib.colors import to_hex

from hidden_options.figures import convexity as figures
from hidden_options.figures.style import PALETTE, apply_style
from hidden_options.publish.results import Result, write_result

UNDERLYINGS = {
    "AAA": {"group": "programme", "share_gross": 0.30, "share_netted": 0.01},
    "BBB": {"group": "programme", "share_gross": 0.20, "share_netted": 0.02},
    "CCC": {"group": "control", "share_gross": 0.05, "share_netted": 0.03},
    "SPY": {"group": "index", "share_gross": 0.18, "share_netted": 0.12},
}
INDEX = {
    "SPY": {"share_gross": 0.18, "share_netted": 0.12},
    "NDX": {"share_gross": 0.20, "share_netted": 0.15},
    "SPX": {"share_gross": 0.10, "share_netted": 0.05},
}
NULL = {
    "offsets": [
        {"offset": k, "mean": 0.01 * (k % 3 - 1), "std_error": 0.03} for k in (-12, -10, 10, 12)
    ],
    "centre": 0.0,
}
H1 = {"mean": -0.029, "std_error": 0.028}


@pytest.fixture
def styled():
    with mpl.rc_context():
        apply_style()
        yield


def _colours(ax) -> list[str]:
    found = []
    for collection in ax.collections:
        found.extend(to_hex(c) for c in collection.get_facecolor())
    for line in ax.get_lines():
        found.append(to_hex(line.get_color()))
    return found


class TestGammaShareFigure:
    def test_one_point_per_market_index_products_marked(self, styled):
        points = figures.gamma_points(UNDERLYINGS, INDEX)
        # Index rows come from `index`, never twice.
        assert sorted(p["name"] for p in points) == ["AAA", "BBB", "CCC", "NDX", "SPX", "SPY"]
        assert {p["name"]: p["group"] for p in points}["NDX"] == "index"

        fig = figures.fig_gamma_share(points, labelled=("SPY", "NDX"))
        (ax,) = fig.axes
        assert PALETTE["accent"] in _colours(ax)
        assert {t.get_text() for t in ax.texts} >= {"SPY", "NDX"}
        assert ax.get_xlim()[0] == 0.0 and ax.get_ylim()[0] == 0.0

    def test_build_reads_the_result(self, tmp_path, styled):
        write_result(
            Result(
                "hidden_gamma",
                {"underlyings": UNDERLYINGS, "index": INDEX},
                {},
                {},
                "2026-11-09T00:00:00+00:00",
            ),
            tmp_path / "results",
        )
        figures.build_gamma_share(tmp_path / "results", tmp_path)
        assert (tmp_path / "paper" / "figures" / "gamma_share.pdf").exists()


class TestPinningNullFigure:
    def test_placebo_offsets_with_the_expiry_in_accent(self, styled):
        fig = figures.fig_pinning_null(NULL, H1)
        (ax,) = fig.axes
        xs = sorted(
            x for line in ax.get_lines() for x in line.get_xdata() if len(line.get_xdata()) == 1
        )
        assert 0 in xs  # the real expiry
        assert {-12, -10, 10, 12} <= set(xs)
        assert PALETTE["accent"] in _colours(ax)

    def test_build_reads_the_result(self, tmp_path, styled):
        write_result(
            Result(
                "pinning",
                {"empirical_null": NULL, "h1": H1},
                {},
                {},
                "2026-11-09T00:00:00+00:00",
            ),
            tmp_path / "results",
        )
        figures.build_pinning_null(tmp_path / "results", tmp_path)
        assert (tmp_path / "paper" / "figures" / "pinning_null.pdf").exists()

    def test_missing_result_says_what_to_run(self, tmp_path):
        (tmp_path / "results").mkdir()
        with pytest.raises(FileNotFoundError, match="pinning"):
            figures.build_pinning_null(tmp_path / "results", tmp_path)
