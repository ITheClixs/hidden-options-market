"""Tests for F7: the coefficients, their placebo and the permutation distribution."""

from __future__ import annotations

import matplotlib as mpl
import numpy as np
import pytest
from matplotlib.colors import to_hex
from matplotlib.patches import Rectangle

from hidden_options.figures import predictive as figures
from hidden_options.figures.style import PALETTE, apply_style
from hidden_options.publish.results import Result, write_result


def _row(key: str, coefficient: float, half: float, *, placebo: bool = False) -> dict:
    return {
        "key": key,
        "predictor": key,
        "outcome": "abs_ret_next",
        "coefficient": coefficient,
        "ci_low": coefficient - half,
        "ci_high": coefficient + half,
        "t_stat": coefficient / (half / 2),
        "placebo": placebo,
        "permutation_p": 0.4,
    }


ROWS = [
    _row("innovation", -0.00004, 0.00011),
    _row("change", -0.00006, 0.00021),
    _row("near_share", -0.00013, 0.00076),
    _row("put_share", 0.00006, 0.00051),
    {**_row("innovation_squared", 0.000006, 0.00002), "outcome": "sq_ret_next"},
    _row("placebo", 0.0001, 0.00011, placebo=True),
]
PERMUTATION = {
    "observed": -0.00004,
    "p_value": 0.43,
    "n_perm": 400,
    "null": list(np.random.default_rng(0).normal(0, 0.00005, 400)),
}


@pytest.fixture
def styled():
    with mpl.rc_context():
        apply_style()
        yield


def _accent_artists(fig) -> list:
    found = []
    for ax in fig.axes:
        for artist in [*ax.get_lines(), *ax.collections, *ax.texts]:
            colours = []
            if hasattr(artist, "get_color"):
                colour = artist.get_color()
                colours = [colour] if isinstance(colour, str) else list(colour)
            if any(to_hex(c) == PALETTE["accent"] for c in colours):
                found.append(artist)
    return found


class TestNullFigure:
    def test_shuffled_draws_above_coefficients_on_one_scale(self, styled):
        fig = figures.fig_null(figures.figure_rows(ROWS), PERMUTATION)
        top, bottom = fig.axes
        assert len(fig.axes) == 2
        assert top.get_shared_x_axes().joined(top, bottom)

    def test_only_log_point_predictors_share_the_scale(self, styled):
        """The share predictors are in other units; they stay in the table."""
        rows = figures.figure_rows(ROWS)
        assert [row["key"] for row in rows] == ["innovation", "change", "placebo"]

    def test_histogram_is_faint_and_in_units_of_ten_to_the_minus_four(self, styled):
        fig = figures.fig_null(figures.figure_rows(ROWS), PERMUTATION)
        bars = [p for p in fig.axes[0].patches if isinstance(p, Rectangle)]
        assert len(bars) >= 10
        assert {to_hex(bar.get_facecolor()) for bar in bars} == {PALETTE["faint"]}
        right = max(bar.get_x() + bar.get_width() for bar in bars)
        assert 0.5 < right < 5  # draws of about 0.5e-4 drawn as about 0.5, not 5e-5

    def test_estimate_is_marked_in_the_distribution_with_its_p_value(self, styled):
        fig = figures.fig_null(figures.figure_rows(ROWS), PERMUTATION)
        top = fig.axes[0]
        marks = [line for line in top.get_lines() if to_hex(line.get_color()) == PALETTE["ink"]]
        assert any(np.allclose(line.get_xdata(), -0.4) for line in marks)
        assert any("0.43" in text.get_text() for text in top.texts)

    def test_accent_marks_the_placebo_and_nothing_else(self, styled):
        fig = figures.fig_null(figures.figure_rows(ROWS), PERMUTATION)
        accent = _accent_artists(fig)
        assert accent
        bottom = fig.axes[1]
        placebo_y = len(figures.figure_rows(ROWS)) - 1
        for artist in accent:
            assert artist.axes is bottom
            if hasattr(artist, "get_ydata"):
                assert np.allclose(artist.get_ydata(), placebo_y)

    def test_intervals_come_from_the_estimates(self, styled):
        fig = figures.fig_null(figures.figure_rows(ROWS), PERMUTATION)
        bottom = fig.axes[1]
        spans = sorted(
            tuple(np.round(line.get_xdata(), 6))
            for line in bottom.get_lines()
            if len(line.get_xdata()) == 2 and line.get_ydata()[0] == line.get_ydata()[1]
        )
        assert (-1.5, 0.7) in spans  # the innovation's interval, times 10^4
        labels = [tick.get_text() for tick in bottom.get_yticklabels()]
        assert labels[0] == "Inventory innovation" and labels[-1].startswith("Placebo")


class TestBuilder:
    def _result(self) -> Result:
        values = {"rows": ROWS, "permutation": PERMUTATION}
        return Result("predictive", values, {}, {}, "2026-10-24T00:00:00+00:00")

    def test_writes_the_paper_pdf_and_the_readme_png(self, tmp_path):
        write_result(self._result(), tmp_path / "results")
        with mpl.rc_context():
            figures.build_placebo(results=tmp_path / "results", root=tmp_path)
        assert (tmp_path / "paper/figures/placebo.pdf").is_file()
        assert (tmp_path / "docs/figures/placebo.png").is_file()

    def test_without_a_result_it_says_what_to_run(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="results --only predictive"):
            figures.build_placebo(results=tmp_path / "results", root=tmp_path)


def test_registered_with_the_figures_only():
    from hidden_options.publish import registry

    assert "hidden_options.figures.predictive" in registry.FIGURE_MODULES
    assert "hidden_options.figures.predictive" not in registry.REGISTRATION_MODULES
    registry.load_figure_registrations()
    assert "placebo" in registry.FIGURES.select()
