"""Tests for the market figures: what they draw and that their numbers come from results."""

from __future__ import annotations

import matplotlib as mpl
import pandas as pd
import pytest
from matplotlib.colors import LogNorm, to_hex

from hidden_options.figures import market as figures
from hidden_options.figures.style import PALETTE, apply_style
from hidden_options.measure import market_result as results_module
from hidden_options.measure.market import (
    expiry_cohorts,
    market_daily,
    monthly_expiries,
)
from hidden_options.publish.results import write_result
from market_stub import synthetic_market

PANEL = synthetic_market()


@pytest.fixture
def styled():
    with mpl.rc_context():
        apply_style()
        yield


@pytest.fixture(scope="module")
def result():
    return results_module.market_result(PANEL)


def _colours(ax) -> list[str]:
    lines = [to_hex(line.get_color()) for line in ax.get_lines()]
    texts = [to_hex(text.get_color()) for text in ax.texts]
    return lines + texts


class TestGrowthFigure:
    def draw(self):
        daily = market_daily(PANEL)
        expiries = monthly_expiries(pd.DatetimeIndex(daily["report_date"]))
        return figures.fig_growth(daily, pd.Timestamp("2025-05-01"), expiries)

    def test_two_panels_share_the_date_axis(self, styled):
        fig = self.draw()
        top, bottom = fig.axes

        assert top.get_shared_x_axes().joined(top, bottom)
        # No second y-axis anywhere: two measures get two panels.
        assert len(fig.axes) == 2

    def test_accent_marks_only_the_break(self, styled):
        fig = self.draw()
        accent = [c for ax in fig.axes for c in _colours(ax) if c == PALETTE["accent"]]
        labels = [t.get_text() for ax in fig.axes for t in ax.texts]

        assert accent  # the break line and its label
        assert any("May 2025" in label for label in labels)

    def test_every_monthly_expiry_is_marked(self, styled):
        daily = market_daily(PANEL)
        expiries = monthly_expiries(pd.DatetimeIndex(daily["report_date"]))
        fig = figures.fig_growth(daily, pd.Timestamp("2025-05-01"), expiries)
        faint = [
            line for line in fig.axes[0].get_lines() if to_hex(line.get_color()) == PALETTE["faint"]
        ]

        assert len(faint) == len(expiries)


class TestCohortFigure:
    def test_heat_map_on_the_sequential_ramp(self, styled):
        fig = figures.fig_cohorts(expiry_cohorts(PANEL))
        mesh = fig.axes[0].collections[0]

        assert mesh.get_cmap().name == "hidden_options_seq"
        assert isinstance(mesh.norm, LogNorm)
        # The heat map and its colour bar.
        assert len(fig.axes) == 2

    def test_far_expiries_are_cut_at_the_horizon(self, styled):
        cohorts = expiry_cohorts(PANEL)
        far = pd.Timestamp("2029-01-01")
        cohorts.loc[far] = 0
        cohorts.loc[far, cohorts.columns[0]] = 5

        fig = figures.fig_cohorts(cohorts)
        top = mpl.dates.num2date(fig.axes[0].get_ylim()[1]).replace(tzinfo=None)

        assert top < far


class TestConcentrationFigure:
    def test_marks_are_labelled_from_the_given_shares(self, styled):
        cumulative = pd.Series([0.5, 0.8, 1.0], index=[1, 2, 3])
        fig = figures.fig_concentration(cumulative, {2: 0.8})
        labels = [t.get_text() for t in fig.axes[0].texts]

        assert labels == ["top 2: 80%"]


class TestBuilders:
    @pytest.fixture
    def project(self, tmp_path, monkeypatch, result):
        write_result(result, tmp_path / "results")
        monkeypatch.setattr(figures, "load_panel", lambda root: PANEL)
        figures.cached_panel.cache_clear()
        yield tmp_path
        figures.cached_panel.cache_clear()

    @pytest.mark.parametrize(
        ("build", "outputs"),
        [
            (figures.build_growth, ["paper/figures/growth.pdf", "docs/figures/growth.png"]),
            (figures.build_cohorts, ["paper/figures/cohorts.pdf"]),
            (figures.build_concentration, ["paper/figures/concentration.pdf"]),
        ],
    )
    def test_builders_write_their_files(self, project, build, outputs):
        with mpl.rc_context():
            build(raw=project, results=project / "results", root=project)

        for output in outputs:
            assert (project / output).is_file()

    def test_builder_without_a_result_says_what_to_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(figures, "load_panel", lambda root: PANEL)
        with pytest.raises(FileNotFoundError, match="results --only market"):
            figures.build_growth(raw=tmp_path, results=tmp_path / "results", root=tmp_path)

    def test_break_label_is_read_from_the_result(self, project, monkeypatch, result):
        drawn = {}
        original = figures.fig_growth

        def spy(daily, break_date, expiries):
            drawn["break"] = break_date
            return original(daily, break_date, expiries)

        monkeypatch.setattr(figures, "fig_growth", spy)
        with mpl.rc_context():
            figures.build_growth(raw=project, results=project / "results", root=project)

        assert drawn["break"] == pd.Timestamp(result.values["growth"]["break_date"])


def test_figures_register_under_their_stems():
    from hidden_options.publish import registry

    assert "hidden_options.figures.market" in registry.REGISTRATION_MODULES
    assert "hidden_options.measure.market_result" in registry.REGISTRATION_MODULES
    assert results_module.market.__name__ == "market"


def test_builder_refuses_a_result_from_another_panel(tmp_path, monkeypatch, result):
    write_result(result, tmp_path / "results")
    shorter = PANEL[PANEL["report_date"] < "2025-12-01"]
    monkeypatch.setattr(figures, "load_panel", lambda root: shorter)
    figures.cached_panel.cache_clear()
    try:
        with pytest.raises(ValueError, match="results --only market"):
            figures.build_cohorts(raw=tmp_path, results=tmp_path / "results", root=tmp_path)
    finally:
        figures.cached_panel.cache_clear()
