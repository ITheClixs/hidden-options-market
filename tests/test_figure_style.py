"""Figure style tests.

Every figure in the paper and README is drawn through one style module, so these tests
pin what a reader would notice if it drifted: the palette stays legible in greyscale
print, the text is the paper's serif at the paper's size, a figure keeps the width it
was designed at, and regenerating a figure does not change its bytes.
"""

from __future__ import annotations

import logging
import math
import re
import struct
import warnings
from io import BytesIO
from pathlib import Path

import matplotlib as mpl
import numpy as np
import pytest
from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import Rectangle

from hidden_options.config import PROJECT_ROOT
from hidden_options.figures import style
from hidden_options.figures.style import (
    PALETTE,
    SEQ,
    TEXT_WIDTH_IN,
    apply_style,
    label_line_end,
    new_figure,
    save,
    seq_cmap,
)

HEX = re.compile(r"#[0-9a-f]{6}")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """WCAG relative luminance of a `#rrggbb` colour."""
    r, g, b = (_linear(int(colour[i : i + 2], 16) / 255) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def lightness(colour: str) -> float:
    """CIE L*, the grey a greyscale print gives the colour (0 black, 100 white)."""
    y = luminance(colour)
    return 116 * y ** (1 / 3) - 16 if y > 0.008856 else 903.3 * y


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture
def styled():
    """The house style, undone afterwards so no other test sees it."""
    with mpl.rc_context():
        apply_style()
        yield


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(PNG_SIGNATURE)
    return struct.unpack(">II", data[16:24])  # type: ignore[return-value]


class TestPalette:
    def test_palette_hex_and_distinct(self):
        colours = [*PALETTE.values(), *SEQ]
        assert all(HEX.fullmatch(c) for c in colours)
        assert len(set(colours)) == len(colours)
        assert {"ink", "muted", "accent", "faint"} <= set(PALETTE)

    def test_palette_cannot_be_edited_by_a_figure(self):
        with pytest.raises(TypeError):
            PALETTE["ink"] = "#ff0000"  # type: ignore[index]

    def test_three_voices_stay_apart_in_greyscale_print(self):
        ink, accent, muted = (lightness(PALETTE[k]) for k in ("ink", "accent", "muted"))
        assert ink + 15 <= accent
        assert accent + 15 <= muted

    def test_marks_clear_three_to_one_on_the_surface(self):
        for key in ("ink", "accent", "muted"):
            assert contrast(PALETTE[key], PALETTE["surface"]) >= 3.0, key

    def test_faint_recedes_behind_every_mark(self):
        faint = lightness(PALETTE["faint"])
        assert faint > lightness(PALETTE["muted"]) + 15
        assert faint < lightness(PALETTE["surface"])

    def test_ramp_darkens_evenly_so_it_reads_in_greyscale(self):
        grey = [lightness(c) for c in SEQ]
        steps = np.diff(grey)
        assert (steps < -8).all()
        assert steps.max() - steps.min() < 6

    def test_cmap_runs_from_first_to_last_step(self):
        cmap = seq_cmap()
        assert mpl.colors.to_hex(cmap(0.0)) == SEQ[0]
        assert mpl.colors.to_hex(cmap(1.0)) == SEQ[-1]
        grey = [luminance(mpl.colors.to_hex(cmap(x))) for x in np.linspace(0, 1, 50)]
        assert all(a > b for a, b in zip(grey, grey[1:], strict=False))


class TestApplyStyle:
    def test_matches_the_paper_body(self, styled):
        rc = mpl.rcParams
        assert rc["font.size"] == 8.5
        assert rc["text.usetex"] is False
        assert rc["mathtext.fontset"] == "cm"
        assert rc["font.family"][0] == "serif"
        assert rc["axes.spines.top"] is False
        assert rc["axes.spines.right"] is False
        assert rc["pdf.fonttype"] == 42
        assert rc["savefig.dpi"] == 200
        assert rc["savefig.bbox"] != "tight"

    def test_is_idempotent(self, styled):
        before = dict(mpl.rcParams)
        apply_style()
        assert dict(mpl.rcParams) == before

    def test_a_serif_font_resolves_without_a_system_tex(self, styled):
        found = font_manager.findfont(
            font_manager.FontProperties(family=mpl.rcParams["font.family"]),
            fallback_to_default=False,
        )
        assert Path(found).exists()

    def test_uncoloured_marks_are_ink_not_matplotlib_blue(self, styled):
        fig = new_figure()
        (line,) = fig.subplots().plot([0, 1], [0, 1])
        assert mpl.colors.to_hex(line.get_color()) == PALETTE["ink"]

    def test_no_glyph_goes_missing_in_plain_or_math_text(self, tmp_path, styled, caplog):
        """cmr10 has no en dash, times sign or true minus. matplotlib reports a missing
        glyph as a warning or as a log record, and a figure must produce neither."""
        caplog.set_level(logging.WARNING)
        fig = new_figure()
        ax = fig.subplots()
        ax.plot([-2, 2], [-3e6, 4e6])
        ax.set_xlabel("Gross open interest, m contracts (log scale)")
        ax.text(0, 0, "naive – exposure × 2, −3.1% of \\$596bn ≈ 0")
        ax.set_ylabel("Coefficient on next-day $|r|$ (× 10$^{-3}$, −)")
        with warnings.catch_warnings():
            warnings.filterwarnings("error", message="Glyph .* missing from")
            save(fig, "demo", readme=True, root=tmp_path)
        assert [r.getMessage() for r in caplog.records] == []


class TestFigureSize:
    def test_text_width_is_the_papers(self):
        """The paper sets margin=1.1in on letter paper; a figure drawn wider is scaled
        down by LaTeX and its 8.5 pt type with it."""
        tex = (PROJECT_ROOT / "paper" / "hidden_options_market.tex").read_text()
        found = re.search(r"\\usepackage\[margin=([\d.]+)in\]\{geometry\}", tex)
        assert found, "the preamble no longer sets margin=<n>in through geometry"
        assert math.isclose(TEXT_WIDTH_IN, 8.5 - 2 * float(found.group(1)))

    def test_new_figure_takes_a_share_of_the_text_width(self, styled):
        full = new_figure()
        half = new_figure(0.5, aspect=1.0)
        assert full.get_size_inches()[0] == pytest.approx(TEXT_WIDTH_IN)
        assert half.get_size_inches() == pytest.approx([TEXT_WIDTH_IN / 2] * 2)

    def test_new_figure_rejects_a_share_outside_the_page(self):
        for share in (0, -0.5, 1.2):
            with pytest.raises(ValueError, match="share"):
                new_figure(share)

    def test_new_figure_rejects_a_flat_aspect(self):
        with pytest.raises(ValueError, match="Aspect"):
            new_figure(aspect=0)


class TestDateAxis:
    """A daily series over the panel window, drawn by plain `ax.plot` on a date axis."""

    DAYS = np.arange("2025-07-23", "2026-08-18", dtype="datetime64[D]")

    def drawn_labels(self, share: float):
        fig = new_figure(share, aspect=0.8)
        ax = fig.subplots()
        ax.plot(self.DAYS, np.arange(len(self.DAYS)))
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        renderer = canvas.get_renderer()
        texts = [*ax.xaxis.get_ticklabels(), ax.xaxis.get_offset_text()]
        return [
            (t.get_text(), t.get_window_extent(renderer))
            for t in texts
            if t.get_visible() and t.get_text()
        ]

    @pytest.mark.parametrize("share", [1.0, 0.5, 0.45])
    def test_tick_labels_do_not_collide_at_any_figure_width(self, styled, share):
        labels = self.drawn_labels(share)
        assert len(labels) >= 3
        for i, (first, box) in enumerate(labels):
            for second, other in labels[i + 1 :]:
                assert not box.overlaps(other), f"{first!r} runs into {second!r}"


class TestOutlineMarks:
    """Marks that are only an outline must stay visible; filled ones carry none."""

    def test_unfilled_arrow_has_a_line(self, styled):
        ax = new_figure().subplots()
        note = ax.annotate("", xy=(1, 1), xytext=(0, 0), arrowprops={"arrowstyle": "-"})
        assert note.arrow_patch.get_linewidth() > 0

    def test_step_histogram_has_a_line(self, styled):
        ax = new_figure().subplots()
        _, _, patches = ax.hist(np.linspace(0, 1, 50), histtype="step")
        assert patches[0].get_linewidth() > 0

    def test_unfilled_rectangle_and_stairs_have_a_line(self, styled):
        ax = new_figure().subplots()
        box = ax.add_patch(Rectangle((0, 0), 1, 1, fill=False))
        (stairs,) = [ax.stairs([1, 2, 1], [0, 1, 2, 3])]
        assert box.get_linewidth() > 0
        assert stairs.get_linewidth() > 0

    def test_filled_marks_get_no_outline(self, styled):
        ax = new_figure().subplots()
        bars = ax.bar([0, 1], [1, 2])
        _, _, hist = ax.hist(np.linspace(0, 1, 50))
        band = ax.fill_between([0, 1], [0, 0], [1, 2])
        for mark in (*bars, *hist, band):
            edge = mpl.colors.to_rgba_array(mark.get_edgecolor())
            assert len(edge) == 0 or edge[:, 3].max() == 0


class TestSave:
    def test_save_writes_pdf_and_png(self, tmp_path, styled):
        fig = new_figure()
        fig.subplots().plot([0, 1], [0, 1])

        written = save(fig, "demo", readme=True, root=tmp_path)

        pdf, png = tmp_path / "paper/figures/demo.pdf", tmp_path / "docs/figures/demo.png"
        assert written == [pdf, png]
        assert pdf.read_bytes().startswith(b"%PDF")
        width, height = fig.get_size_inches()
        assert png_size(png.read_bytes()) == (round(width * 200), round(height * 200))

    def test_paper_only_is_the_default(self, tmp_path, styled):
        fig = new_figure()
        fig.subplots().plot([0, 1], [0, 1])

        assert save(fig, "demo", root=tmp_path) == [tmp_path / "paper/figures/demo.pdf"]
        assert not (tmp_path / "docs").exists()

    def test_readme_only(self, tmp_path, styled):
        fig = new_figure()
        fig.subplots().plot([0, 1], [0, 1])

        written = save(fig, "demo", paper=False, readme=True, root=tmp_path)
        assert written == [tmp_path / "docs/figures/demo.png"]
        assert not (tmp_path / "paper").exists()

    def test_png_is_opaque_so_it_reads_on_a_dark_page(self, tmp_path, styled):
        fig = new_figure()
        fig.subplots().plot([0, 1], [0, 1])
        (png,) = save(fig, "demo", paper=False, readme=True, root=tmp_path)

        corner = mpl.image.imread(png)[0, 0]
        assert corner.tolist() == [1.0, 1.0, 1.0, 1.0]

    def test_pdf_bytes_do_not_change_between_runs(self, tmp_path, styled):
        """A regenerated figure must not churn in git: no creation date, stable fonts."""

        def render(root: Path) -> bytes:
            fig = new_figure()
            ax = fig.subplots()
            ax.plot([0, 1, 2], [3, 1, 2])
            ax.set_xlabel("Report date")
            (pdf,) = save(fig, "demo", root=root)
            return pdf.read_bytes()

        first = render(tmp_path / "a")
        assert b"/CreationDate" not in first
        assert render(tmp_path / "b") == first

    def test_saving_a_pdf_is_quiet(self, tmp_path, styled, caplog):
        """The bundled Computer Modern font carries a zero timestamp that fontTools
        complains about on every save; a build that runs seven figures should not."""
        caplog.set_level(logging.WARNING)
        fig = new_figure()
        fig.subplots().set_xlabel("Report date")
        save(fig, "demo", root=tmp_path)
        assert [r.getMessage() for r in caplog.records] == []

    @pytest.mark.parametrize("stem", ["", "../escape", "a/b", "demo.pdf", "two words"])
    def test_stem_cannot_leave_the_figures_folder(self, tmp_path, stem, styled):
        fig = new_figure()
        with pytest.raises(ValueError, match="Figure name"):
            save(fig, stem, root=tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_asking_for_no_output_is_an_error(self, tmp_path, styled):
        with pytest.raises(ValueError, match="nothing to write"):
            save(new_figure(), "demo", paper=False, readme=False, root=tmp_path)

    def test_defaults_to_the_project_folders(self):
        assert style.PAPER_FIGURES.as_posix() == "paper/figures"
        assert style.README_FIGURES.as_posix() == "docs/figures"


class TestLabelLineEnd:
    def test_label_sits_right_of_the_point_in_ink(self, styled):
        ax = new_figure().subplots()
        ax.plot([0, 1], [0, 1])
        label_line_end(ax, 1, 1, "Open interest")

        (label,) = ax.texts
        assert label.get_text() == "Open interest"
        assert label.xy == (1, 1)
        assert label.get_horizontalalignment() == "left"
        assert label.get_verticalalignment() == "center"
        assert mpl.colors.to_hex(label.get_color()) == PALETTE["ink"]
        assert label.get_annotation_clip() is False

    def test_label_beyond_the_axes_still_fits_on_the_page(self, tmp_path, styled):
        """Constrained layout must make room for it, or it is cut off at the edge."""
        fig = new_figure()
        ax = fig.subplots()
        ax.plot([0, 1], [0, 1])
        label_line_end(ax, 1, 1, "A label that runs well past the end of the line")
        fig.savefig(BytesIO(), format="png", dpi=fig.dpi)

        assert ax.texts[0].get_window_extent().x1 <= fig.bbox.x1
        assert ax.get_position().x1 < 0.9

    def test_accepts_a_date_on_a_time_axis(self, styled):
        ax = new_figure().subplots()
        days = np.array(["2026-01-01", "2026-06-30"], dtype="datetime64[D]")
        ax.plot(days, [1, 2])
        label_line_end(ax, days[-1], 2, "end")
        assert ax.texts[0].get_text() == "end"
