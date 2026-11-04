"""Tests for F5 and F6: the anatomy of a structure, and the ratio across underlyings."""

from __future__ import annotations

import matplotlib as mpl
import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_hex
from matplotlib.patches import Rectangle

from hidden_options.figures import measurement as figures
from hidden_options.figures.style import PALETTE, apply_style
from hidden_options.measure.positions_macros import usd
from hidden_options.publish import registry
from hidden_options.publish.results import write_result
from positions_stub import inputs


@pytest.fixture
def styled():
    with mpl.rc_context():
        apply_style()
        yield


@pytest.fixture(scope="module")
def result():
    from hidden_options.measure.positions_result import positions_result

    return positions_result(inputs())


def ratios(n=200, seed=3):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "symbol": [f"N{i}" for i in range(n)],
            "ratio": np.minimum(10 ** rng.normal(0.5, 0.8, n), 900.0),
            "gross_ratio": 10 ** rng.normal(0.1, 0.5, n),
        }
    )


class TestAnatomy:
    def test_two_payoffs_over_two_bars(self, styled, result):
        fig = figures.fig_anatomy(result.values["cases"])
        assert len(fig.axes) == 4

    def test_payoff_panels_peak_at_the_maximum_value(self, styled, result):
        cases = result.values["cases"]
        fig = figures.fig_anatomy(cases)
        butterfly = fig.axes[0].get_lines()[-2].get_ydata()
        wing = 100_000 * 100 * 40.0
        assert float(np.max(butterfly)) == pytest.approx(wing / 1e9, rel=0.01)
        collar = fig.axes[1].get_lines()[-2].get_ydata()
        assert float(np.max(collar)) == pytest.approx(cases["collar"]["max_value"] / 1e9, rel=0.01)

    def test_bars_state_both_totals(self, styled, result):
        cases = result.values["cases"]
        fig = figures.fig_anatomy(cases)
        text = [t.get_text() for t in fig.axes[2].texts]
        assert usd(cases["butterfly"]["strike_notional"]) in text
        assert usd(cases["butterfly"]["max_value"]) in text

    def test_maxima_say_their_scope_and_the_deep_call_is_named(self, styled, result):
        fig = figures.fig_anatomy(result.values["cases"])
        assert any("Maximum, one expiry" in t.get_text() for t in fig.axes[0].texts)
        labels = [t.get_text() for t in fig.axes[2].get_yticklabels()]
        assert any("3 expiries" in label for label in labels)
        assert any("call struck at" in t.get_text() for t in fig.axes[1].texts)
        assert fig.axes[1].get_xlim()[0] < 0


class TestRatioDistribution:
    def test_reference_at_one_is_the_only_accent(self, styled):
        fig = figures.fig_ratio_distribution(ratios())
        ax = fig.axes[0]
        accents = [line for line in ax.get_lines() if to_hex(line.get_color()) == PALETTE["accent"]]
        assert len(accents) == 1
        assert list(accents[0].get_xdata()) == [0.0, 0.0]

    def test_the_unnetted_series_is_filled(self, styled):
        frame = ratios()
        fig = figures.fig_ratio_distribution(frame)
        filled = sum(bar.get_height() for bar in fig.axes[0].patches if isinstance(bar, Rectangle))
        edges = np.linspace(-1, 3, 21)
        assert filled == np.histogram(np.log10(frame["gross_ratio"]), bins=edges)[0].sum()

    def test_each_underlying_is_counted_once(self, styled):
        frame = ratios()
        fig = figures.fig_ratio_distribution(frame)
        filled = [bar.get_height() for bar in fig.axes[0].patches if isinstance(bar, Rectangle)]
        assert sum(filled) == len(frame)

    def test_names_the_shares_either_side_of_one(self, styled):
        frame = ratios()
        fig = figures.fig_ratio_distribution(frame)
        text = " ".join(t.get_text() for t in fig.axes[0].texts)
        below = (frame["gross_ratio"] < 1).mean() * 100
        assert f"{below:.0f}%" in text

    def test_underlyings_past_the_axis_are_counted_in_a_note(self, styled):
        frame = ratios()
        wild = pd.DataFrame({"symbol": ["FAR"], "ratio": [39_148.0], "gross_ratio": [39_148.0]})
        fig = figures.fig_ratio_distribution(pd.concat([frame, wild], ignore_index=True))
        text = " ".join(t.get_text() for t in fig.axes[0].texts)
        assert "1 underlying beyond the axis" in text
        assert "39,148" in text
        assert fig.axes[0].get_xticks()[-1] == 3

    def test_both_histograms_are_named(self, styled):
        fig = figures.fig_ratio_distribution(ratios())
        text = " ".join(t.get_text() for t in fig.axes[0].texts)
        assert "no netting" in text
        assert "netted, every leg long" in text


class TestBuilders:
    def test_both_are_registered_and_write_their_pdfs(self, result, tmp_path):
        registry.load_figure_registrations()
        assert {"anatomy", "notional_ratio"} <= set(registry.FIGURES.select())
        write_result(result, tmp_path)
        figures.build_anatomy(tmp_path, tmp_path)
        figures.build_notional_ratio(tmp_path, tmp_path)
        assert (tmp_path / "paper/figures/anatomy.pdf").exists()
        assert (tmp_path / "paper/figures/notional_ratio.pdf").exists()

    def test_a_missing_case_is_refused(self, result, tmp_path):
        from dataclasses import replace

        values = {**result.values, "cases": {"butterfly": None, "collar": None}}
        write_result(replace(result, values=values), tmp_path)
        with pytest.raises(ValueError, match="worked case"):
            figures.build_anatomy(tmp_path, tmp_path)
