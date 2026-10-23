"""One look for every figure in the paper and the README.

The figures sit in a LaTeX `article` set in Computer Modern, so the text here is
Computer Modern too, at 8.5 pt against the body's 11 pt, and a figure is drawn at the
width it is printed (`new_figure`) so that size survives. Colour is spent only on
encoding. Three voices carry identity -- ink for the thing measured, the accent for the
one thing to notice, muted for context -- and they differ in lightness as well as hue,
so a greyscale print keeps them apart. A sequential ramp carries magnitude. Hairline
grey does the gridlines and reference lines.

Direct labels (`label_line_end`) stand in for legends, and a figure never carries a
second y-axis: two measures get two panels.

Typical use:

    apply_style()
    fig = new_figure()
    ax = fig.subplots()
    ax.plot(dates, values)
    label_line_end(ax, dates[-1], values[-1], "Open interest")
    save(fig, "growth", readme=True)

One limit of matplotlib's mathtext applies: in a string that contains `$...$`, the plain
text around the formula is drawn from Computer Modern alone, so an en dash, an arrow or an
accented letter there is missing. Write such a symbol as math (`$\\approx$`) or keep it
out of the mixed string.

The module imports matplotlib's `Figure` rather than pyplot, so it needs no display and
leaves no figures registered behind it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

import matplotlib as mpl
from cycler import cycler
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure

from hidden_options.config import PROJECT_ROOT
from hidden_options.publish.results import NAME_PATTERN

# Neutrals are true greys, so nothing in the figure tints the white page.
#
# ink     #1a1a1a  17.4:1 on white  primary marks and all text
# accent  #b0331a   6.3:1           deep vermilion, the one thing to notice
# muted   #949494   3.0:1           context marks, tick marks, axis lines
# faint   #d9d9d9   1.4:1           gridlines and reference lines, behind everything
#
# CIE L* of the three voices is 9, 41 and 61, so each pair is 20 or more apart in a
# greyscale print. Under simulated protanopia and deuteranopia the closest pair is
# vermilion against muted at 17.7 in OKLab (x100), against a target of 8.
PALETTE: Mapping[str, str] = MappingProxyType(
    {
        "ink": "#1a1a1a",
        "accent": "#b0331a",
        "muted": "#949494",
        "faint": "#d9d9d9",
        "surface": "#ffffff",
    }
)

# The sequential ramp for magnitude, one blue from light to dark. Seven steps at equal
# lightness spacing (OKLCH L 0.905 to 0.338, about 11 in CIE L* each) give a monotone
# greyscale. The lightest step is allowed to recede toward the surface: it stands for
# "near zero". Marks that must stand clear of the page (discrete ordered bins, not a
# continuous map) should start at SEQ[2], the first step past 2:1 contrast.
SEQ: tuple[str, ...] = (
    "#cde2fb",
    "#9ec5f4",
    "#6da7ec",
    "#3987e5",
    "#256abf",
    "#184f95",
    "#0d366b",
)

# \textwidth of the paper: letter paper less the 1.1in margins set in the preamble.
# tests/test_figure_style.py reads the .tex and fails if the two disagree.
TEXT_WIDTH_IN = 6.3

PAPER_FIGURES = Path("paper/figures")
README_FIGURES = Path("docs/figures")
PNG_DPI = 200

_FONT_SIZE = 8.5
_LABEL_GAP_PT = 4.0

# Computer Modern ships inside matplotlib as `cmr10`, so the paper's face is available
# anywhere without a TeX install, and a figure regenerates the same on any machine.
# `cmr10` has no en dash, multiplication sign or true minus; those glyphs fall through
# the family list to STIX, then to DejaVu Serif, rather than going missing.
_FALLBACK_FONTS = ["STIXGeneral", "DejaVu Serif"]

# Keyed loosely because recent matplotlib stubs type rcParams keys as a closed set of
# literals that a Mapping[str, ...] cannot satisfy. A misspelt key still raises a KeyError
# the first time `apply_style` runs, which every figure test does.
_RC: Mapping[Any, Any] = MappingProxyType(
    {
        "font.family": ["serif", *_FALLBACK_FONTS],
        "font.serif": ["cmr10", *_FALLBACK_FONTS],
        "font.size": _FONT_SIZE,
        "mathtext.fontset": "cm",
        "text.usetex": False,
        "text.color": PALETTE["ink"],
        # Tick labels go through mathtext so the minus sign and exponents are Computer
        # Modern as well, which cmr10 alone cannot draw.
        "axes.formatter.use_mathtext": True,
        "axes.facecolor": PALETTE["surface"],
        "axes.edgecolor": PALETTE["muted"],
        "axes.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.labelsize": _FONT_SIZE,
        "axes.labelcolor": PALETTE["ink"],
        "axes.titlesize": _FONT_SIZE,
        "axes.titleweight": "normal",
        "axes.titlelocation": "left",
        "axes.axisbelow": True,
        "axes.grid": False,
        "axes.prop_cycle": cycler(color=[PALETTE["ink"], PALETTE["accent"], PALETTE["muted"]]),
        "grid.color": PALETTE["faint"],
        "grid.linewidth": 0.5,
        "xtick.color": PALETTE["muted"],
        "ytick.color": PALETTE["muted"],
        "xtick.labelcolor": PALETTE["ink"],
        "ytick.labelcolor": PALETTE["ink"],
        "xtick.labelsize": 8.0,
        "ytick.labelsize": 8.0,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.minor.size": 1.8,
        "ytick.minor.size": 1.8,
        "xtick.minor.width": 0.5,
        "ytick.minor.width": 0.5,
        "lines.linewidth": 1.1,
        "lines.markersize": 4.0,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        # Bars and bands are filled marks; an outline would add ink that is not data.
        "patch.linewidth": 0.0,
        "legend.frameon": False,
        "legend.fontsize": _FONT_SIZE,
        "figure.facecolor": PALETTE["surface"],
        "figure.constrained_layout.use": True,
        "savefig.facecolor": PALETTE["surface"],
        "savefig.dpi": PNG_DPI,
        # `tight` would change the printed size a figure was designed at.
        "savefig.bbox": "standard",
        # Vector output with real, embedded text rather than Type 3 glyph outlines.
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

# Dropping the creation date is what keeps a regenerated PDF byte-identical.
_PDF_METADATA: Mapping[str, str | None] = MappingProxyType({"CreationDate": None})


@contextmanager
def _quiet_font_timestamps() -> Iterator[None]:
    """Hold back fontTools' note about the zero timestamp in matplotlib's `cmr10`.

    Embedding the font in a PDF reads its `head` table, and fontTools logs a warning for
    each timestamp, four lines per figure, none of which the author can act on.
    """
    logger = logging.getLogger("fontTools.ttLib.tables._h_e_a_d")
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous)


def apply_style() -> None:
    """Install the house style in matplotlib's rcParams. Safe to call more than once."""
    mpl.rcParams.update(_RC)


def seq_cmap() -> LinearSegmentedColormap:
    """The sequential ramp as a colormap, `SEQ[0]` at 0 and `SEQ[-1]` at 1."""
    return LinearSegmentedColormap.from_list("hidden_options_seq", list(SEQ))


def new_figure(share: float = 1.0, *, aspect: float = 0.6) -> Figure:
    """A figure `share` of the text width wide and `aspect` times as tall as it is wide.

    Include it in the paper at the same share of `\\textwidth` and its type prints at the
    size the style sets. The figure is not registered with pyplot, so there is nothing
    to close, and it lays itself out with constrained layout.
    """
    if not 0 < share <= 1:
        raise ValueError(f"A figure's share of the text width must be in (0, 1], got {share}")
    if aspect <= 0:
        raise ValueError(f"Aspect (height over width) must be positive, got {aspect}")
    width = TEXT_WIDTH_IN * share
    return Figure(figsize=(width, width * aspect), layout="constrained")


def label_line_end(ax: Axes, x: Any, y: float, text: str) -> None:
    """Name a line where it ends, in place of a legend.

    The label sits just right of the data point (x, y), in ink: the text never wears the
    series colour, the line beside it carries that. It may run past the axes; the
    figure's constrained layout makes room. `x` may be a number or a date.
    """
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(_LABEL_GAP_PT, 0.0),
        textcoords="offset points",
        ha="left",
        va="center",
        color=PALETTE["ink"],
        annotation_clip=False,
    )


def save(
    fig: Figure,
    stem: str,
    *,
    paper: bool = True,
    readme: bool = False,
    root: Path = PROJECT_ROOT,
) -> list[Path]:
    """Write `fig` as `paper/figures/<stem>.pdf` and, if asked, `docs/figures/<stem>.png`.

    The PDF is vector and carries no creation date, so regenerating an unchanged figure
    leaves it byte-identical in git. The PNG is 200 dpi on an opaque white page so it
    reads on a dark README theme. Both land under `root`, which tests point elsewhere.
    Returns the paths written, PDF first. The figure is left open for the caller.
    """
    if not NAME_PATTERN.fullmatch(stem):
        raise ValueError(f"Figure name {stem!r} must be letters, digits, _ or -")
    if not (paper or readme):
        raise ValueError(
            f"Figure {stem!r}: nothing to write; ask for the paper, the README or both"
        )

    written: list[Path] = []
    if paper:
        pdf = root / PAPER_FIGURES / f"{stem}.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        with _quiet_font_timestamps():
            fig.savefig(
                pdf, format="pdf", facecolor=PALETTE["surface"], metadata=dict(_PDF_METADATA)
            )
        written.append(pdf)
    if readme:
        png = root / README_FIGURES / f"{stem}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(png, format="png", dpi=PNG_DPI, facecolor=PALETTE["surface"])
        written.append(png)
    return written
