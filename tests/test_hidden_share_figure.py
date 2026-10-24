"""Tests for F3: FLEX against listed open interest per underlying, on the census date."""

from __future__ import annotations

import itertools

import matplotlib as mpl
import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_hex

from hidden_options.figures import measurement as figures
from hidden_options.figures.style import PALETTE, apply_style
from hidden_options.publish import registry


@pytest.fixture
def styled():
    with mpl.rc_context():
        apply_style()
        yield


def shares(rows):
    """rows: (symbol, flex_oi, listed_oi)"""
    frame = pd.DataFrame(rows, columns=["symbol", "flex_oi", "listed_oi"])
    frame["flex_share"] = frame["flex_oi"] / (frame["flex_oi"] + frame["listed_oi"])
    return frame


def crowd(n=300, seed=7):
    rng = np.random.default_rng(seed)
    listed = np.round(10 ** rng.uniform(3, 7, n))
    flex = np.round(listed * rng.uniform(0.0, 0.4, n))
    rows = [(f"N{i:03d}", f, li) for i, (f, li) in enumerate(zip(flex, listed, strict=True))]
    rows += [
        ("BIG", 5_000_000, 20_000_000),
        ("HALF", 400_000, 100_000),
        ("TIE", 1_300_000, 1_280_000),
    ]
    return shares(rows)


INDICES = shares([("SPX", 3_500_000, 24_000_000), ("RUT", 850_000, 710_000)])


def draw():
    return figures.fig_hidden_share(crowd(), INDICES)


def _texts(fig):
    return [t for t in fig.axes[0].texts if t.get_visible()]


class TestHiddenShareFigure:
    def test_log_log_axes(self, styled):
        ax = draw().axes[0]
        assert (ax.get_xscale(), ax.get_yscale()) == ("log", "log")
        assert "Listed" in ax.get_xlabel()
        assert "FLEX" in ax.get_ylabel()

    def test_iso_share_lines_are_labelled_directly(self, styled):
        fig = draw()
        labels = [t.get_text() for t in _texts(fig)]
        assert any(label.startswith("10%") for label in labels)
        assert any(label.startswith("50%") for label in labels)
        # The 50% line is FLEX equal to listed.
        line = next(ln for ln in fig.axes[0].get_lines() if ln.get_label() == "iso 50%")
        x, y = line.get_data()
        assert np.allclose(np.asarray(y), np.asarray(x))

    def test_accent_marks_only_the_names_at_half_or_more(self, styled):
        fig = draw()
        accented = [
            coll
            for coll in fig.axes[0].collections
            if any(to_hex(c) == PALETTE["accent"] for c in coll.get_facecolors())
        ]
        assert len(accented) == 1
        offsets = accented[0].get_offsets()
        frame = pd.concat([crowd(), INDICES])
        expected = frame[frame["flex_share"] >= 0.5]
        assert len(offsets) == len(expected)

    def test_largest_names_and_indices_are_labelled(self, styled):
        labels = [t.get_text() for t in _texts(draw())]
        assert {"BIG", "HALF", "TIE", "SPX", "RUT"} <= set(labels)
        assert len(labels) == len(set(labels))

    def test_labels_do_not_collide(self, styled):
        fig = draw()
        renderer = fig.canvas.get_renderer()
        # A slanted label is covered by a strip of boxes along it, not by its bounding box.
        shapes = [figures.label_boxes(t, renderer) for t in _texts(fig)]
        for one, other in itertools.combinations(shapes, 2):
            assert not any(a.overlaps(b) for a in one for b in other)
        frame = fig.axes[0].get_window_extent(renderer)
        for box in (box for shape in shapes for box in shape):
            assert frame.x0 <= box.x0 and box.x1 <= frame.x1
            assert frame.y0 <= box.y0 and box.y1 <= frame.y1

    def test_a_level_label_is_its_own_box_and_a_slanted_one_a_strip(self, styled):
        fig = draw()
        renderer = fig.canvas.get_renderer()
        texts = _texts(fig)
        level = next(t for t in texts if t.get_rotation() == 0)
        slanted = next(t for t in texts if t.get_rotation() != 0)
        (box,) = figures.label_boxes(level, renderer)
        assert box.extents.tolist() == level.get_window_extent(renderer).extents.tolist()
        strip = figures.label_boxes(slanted, renderer, pieces=5)
        assert len(strip) == 5
        whole = slanted.get_window_extent(renderer)
        assert sum(b.width * b.height for b in strip) < whole.width * whole.height

    def test_names_without_flex_are_not_drawn(self, styled):
        fig = figures.fig_hidden_share(shares([("A", 0, 100), ("B", 10, 90)]), None)
        drawn = sum(len(c.get_offsets()) for c in fig.axes[0].collections)
        assert drawn == 1

    def test_tick_labels_are_readable(self):
        assert figures.contracts(1_000) == "1k"
        assert figures.contracts(10_000_000) == "10m"
        assert figures.contracts(10) == "10"


def test_registered_only_for_the_figures_command():
    assert "hidden_options.figures.measurement" in registry.FIGURE_MODULES
    assert "hidden_options.figures.measurement" not in registry.REGISTRATION_MODULES


def test_builder_refuses_a_result_from_another_census(monkeypatch, tmp_path):
    from types import SimpleNamespace

    view = SimpleNamespace(
        dated=SimpleNamespace(date=pd.Timestamp("2026-08-14")),
        ordinary=crowd(),
        indices=INDICES,
    )
    monkeypatch.setattr(figures, "load_inputs", lambda raw: None)
    monkeypatch.setattr(figures, "census_view", lambda inputs: view)
    monkeypatch.setattr(
        figures,
        "_census_values",
        lambda results: {"date": "2026-08-17", "underlyings": len(view.ordinary)},
    )
    with pytest.raises(ValueError, match="2026-08-17"):
        figures.build_hidden_share(raw=tmp_path, results=tmp_path, root=tmp_path)


def test_builder_writes_paper_and_readme_figures(monkeypatch, tmp_path):
    from types import SimpleNamespace

    view = SimpleNamespace(
        dated=SimpleNamespace(date=pd.Timestamp("2026-08-14")),
        ordinary=crowd(),
        indices=INDICES,
    )
    monkeypatch.setattr(figures, "load_inputs", lambda raw: None)
    monkeypatch.setattr(figures, "census_view", lambda inputs: view)
    monkeypatch.setattr(
        figures,
        "_census_values",
        lambda results: {"date": "2026-08-14", "underlyings": len(view.ordinary)},
    )
    with mpl.rc_context():
        figures.build_hidden_share(raw=tmp_path, results=tmp_path, root=tmp_path)
    assert (tmp_path / "paper/figures/hidden_share.pdf").is_file()
    assert (tmp_path / "docs/figures/hidden_share.png").is_file()


def test_missing_result_is_named(tmp_path):
    with pytest.raises(FileNotFoundError, match="hidden_share"):
        figures._census_values(tmp_path)
