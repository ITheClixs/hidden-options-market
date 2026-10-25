"""Tests for F4: where FLEX and listed strikes sit on the listing grid."""

from __future__ import annotations

import itertools

import matplotlib as mpl
import pandas as pd
import pytest
from matplotlib.colors import to_hex

from hidden_options.figures import measurement as figures
from hidden_options.figures.style import PALETTE, apply_style
from hidden_options.measure.identification import GRID_POSITIONS, grid_shares, scored_series
from hidden_options.measure.identification_result import identification_result
from hidden_options.publish import registry
from hidden_options.publish.results import write_result
from identification_stub import DATED, census

SERIES = scored_series(census())


@pytest.fixture
def styled():
    with mpl.rc_context():
        apply_style()
        yield


def _bars(ax, colour):
    return [p for p in ax.patches if to_hex(p.get_facecolor()) == PALETTE[colour]]


def _texts(fig):
    return [t for ax in fig.axes for t in ax.texts if t.get_visible() and t.get_text()]


class TestGridFigure:
    def test_two_panels_series_and_open_interest(self, styled):
        fig = figures.fig_grid(SERIES)
        assert len(fig.axes) == 2
        titles = [ax.get_title(loc="left").lower() for ax in fig.axes]
        assert "series" in titles[0] and "open interest" in titles[1]

    def test_bars_are_the_shares_flex_in_ink_listed_in_muted(self, styled):
        fig = figures.fig_grid(SERIES)
        shares = grid_shares(SERIES)
        for ax, measure in zip(fig.axes, ("series", "open_interest"), strict=True):
            flex = sorted(_bars(ax, "ink"), key=lambda p: -p.get_y())
            listed = sorted(_bars(ax, "muted"), key=lambda p: -p.get_y())
            assert [p.get_width() for p in flex] == pytest.approx(
                shares[f"flex_{measure}"].tolist()
            )
            assert [p.get_width() for p in listed] == pytest.approx(
                shares[f"listed_{measure}"].tolist()
            )

    def test_whole_dollar_row_on_top_and_off_grid_at_the_bottom(self, styled):
        ax = figures.fig_grid(SERIES).axes[0]
        ticks = sorted(ax.get_yticklabels(), key=lambda t: -t.get_position()[1])
        labels = [t.get_text() for t in ticks]
        assert labels == [figures.GRID_LABELS[p] for p in GRID_POSITIONS]

    def test_every_bar_carries_its_share_and_the_groups_are_named(self, styled):
        fig = figures.fig_grid(SERIES)
        texts = [t.get_text() for t in _texts(fig)]
        assert any(t.startswith("40%") for t in texts)
        assert any("FLEX" in t for t in texts)
        assert any("listed" in t.lower() for t in texts)
        # Eight bars a panel, each labelled, plus the note on the rule's row.
        assert len([t for t in texts if "%" in t]) == 16

    def test_accent_is_not_spent_on_this_figure_more_than_once(self, styled):
        fig = figures.fig_grid(SERIES)
        accented = [p for ax in fig.axes for p in _bars(ax, "accent")]
        assert len(accented) <= 1

    def test_labels_do_not_collide_or_leave_the_figure(self, styled):
        fig = figures.fig_grid(SERIES)
        fig.draw_without_rendering()
        renderer = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(renderer) for t in _texts(fig)]
        for one, other in itertools.combinations(boxes, 2):
            assert not one.overlaps(other)
        page = fig.bbox
        for box in boxes:
            assert page.x0 <= box.x0 and box.x1 <= page.x1

    def test_share_labels_are_readable(self):
        assert figures.share_label(0.4907) == "49%"
        assert figures.share_label(0.0331) == "3.3%"
        assert figures.share_label(0.000356) == "0.04%"
        assert figures.share_label(0.00999) == "1.0%"
        assert figures.share_label(0.0) == "0%"


def test_registered_only_for_the_figures_command():
    registry.load_figure_registrations()
    assert "strike_grid" in registry.FIGURES.select()


def _point_at(monkeypatch, frame=None):
    monkeypatch.setattr(
        figures, "load_dated_census", lambda raw: (census() if frame is None else frame, DATED)
    )


def test_builder_writes_the_paper_figure_only(monkeypatch, tmp_path):
    write_result(identification_result(census(), DATED), tmp_path)
    _point_at(monkeypatch)
    with mpl.rc_context():
        figures.build_strike_grid(raw=tmp_path, results=tmp_path, root=tmp_path)
    assert (tmp_path / "paper/figures/strike_grid.pdf").is_file()
    assert not (tmp_path / "docs/figures/strike_grid.png").exists()


def test_builder_refuses_a_result_from_another_census(monkeypatch, tmp_path):
    write_result(identification_result(census(), DATED), tmp_path)
    smaller = census().iloc[:-1]
    _point_at(monkeypatch, smaller)
    with pytest.raises(ValueError, match="identification"):
        figures.build_strike_grid(raw=tmp_path, results=tmp_path, root=tmp_path)


def test_builder_names_a_missing_result(monkeypatch, tmp_path):
    _point_at(monkeypatch)
    with pytest.raises(FileNotFoundError, match="identification"):
        figures.build_strike_grid(raw=tmp_path, results=tmp_path, root=tmp_path)


def test_census_frame_is_not_changed_by_scoring():
    frame = census()
    before = frame.copy()
    scored_series(frame)
    pd.testing.assert_frame_equal(frame, before)
