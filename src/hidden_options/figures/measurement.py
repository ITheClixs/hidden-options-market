"""Figures for the measurement results. F3: how much of each options market is FLEX.

F3 sets each underlying's FLEX open interest against its listed open interest on the
census date, both on log scales. A line of constant FLEX share is a straight line of
slope one there, so the 10% and 50% lines are drawn and named where they run, and a
point's distance above or below them reads as its share. The accent marks the
underlyings where FLEX is at least half the market; the largest names, the index
products and the accented ones carry their tickers, placed so that no two labels touch.

The builder recomputes the census from the raw captures and refuses to draw against a
`hidden_share` result from another census, since the figure and the text beside it
would then disagree.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from matplotlib import patheffects
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.text import Annotation, Text
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
from matplotlib.transforms import Bbox

from hidden_options.config import PROJECT_ROOT, RAW_DIR
from hidden_options.figures.style import PALETTE, apply_style, new_figure, save
from hidden_options.measure.hidden_share_result import census_view, load_inputs
from hidden_options.publish.registry import FIGURES
from hidden_options.publish.results import RESULTS_DIR, read_results

RESULT = "hidden_share"
ISO_SHARES = (0.10, 0.50)
HALF = 0.5
# The underlyings with the most FLEX open interest are named, besides the accented ones.
LARGEST_NAMED = 6
_PAD_PT = 1.5
# Label positions tried around a point, nearest ring first, as (radius, (dx, dy)) in
# points. Beyond the first ring a hairline leads back to the point.
_NEAR_RADIUS = 5
_DIRECTIONS = (
    (1, 0.5),
    (1, -0.5),
    (-1, 0.5),
    (-1, -0.5),
    (0, 1),
    (0, -1),
    (1, 0),
    (-1, 0),
    (0.7, 0.7),
    (-0.7, 0.7),
    (0.7, -0.7),
    (-0.7, -0.7),
)
_CANDIDATES = tuple(
    (radius, (dx * radius, dy * radius))
    for radius in (_NEAR_RADIUS, 12, 20, 30, 42)
    for dx, dy in _DIRECTIONS
)
# Where along its visible run, as a fraction of the run in log terms, an iso-share line
# may be named; tried in this order.
ISO_PLACES = tuple(round(0.9 - 0.05 * step, 2) for step in range(16))
# Added to a position's cost when its label would not sit clearly nearer its own point.
_AMBIGUOUS = 1e3
# How much nearer its own point than any other named point a label without a leader
# must sit, in points.
AMBIGUITY_MARGIN_PT = 6.0
# Half the side of the square kept clear around a named point, in points.
_MARKER_PT = 3.0
_UNITS = ((1e6, "m"), (1e3, "k"))
# Factor by which the axes reach past the outermost points on a log scale.
LIMIT_PAD = 1.8
# A ring in the page colour around label text, so a label stays legible over the dots.
_HALO = (patheffects.withStroke(linewidth=2.2, foreground=PALETTE["surface"]),)


def contracts(value: float, _position: Any = None) -> str:
    """A count of contracts as a log axis labels it: `10`, `1k`, `10m`."""
    for scale, unit in _UNITS:
        if value >= scale:
            return f"{value / scale:g}{unit}"
    return f"{value:g}"


def fig_hidden_share(share: pd.DataFrame, indices: pd.DataFrame | None) -> Figure:
    """F3 from census shares and, if given, index products on the same date.

    Both frames hold `symbol`, `flex_oi`, `listed_oi` and `flex_share`. An underlying
    with no FLEX or no listed open interest has no place on log axes and is not drawn.
    """
    frame = _drawable(share)
    index = _drawable(indices) if indices is not None else frame.iloc[:0]
    both = pd.concat([frame, index], ignore_index=True)

    fig = new_figure(1.0, aspect=0.62)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.set_xscale("log")
    ax.set_yscale("log")
    limits = _limits(both)
    ax.set_xlim(*limits[0])
    ax.set_ylim(*limits[1])
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_locator(LogLocator(base=10))
        axis.set_major_formatter(FuncFormatter(contracts))
        axis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("Listed open interest, contracts")
    ax.set_ylabel("FLEX open interest, contracts")

    for target in ISO_SHARES:
        xs = np.geomspace(*limits[0], 64)
        ax.plot(
            xs,
            xs * _ratio(target),
            color=PALETTE["faint"],
            lw=0.9,
            zorder=1,
            label=f"iso {target:.0%}",
        )

    largest = frame.nlargest(LARGEST_NAMED, "flex_oi")
    accented = both[both["flex_share"] >= HALF]
    context = frame[~frame["symbol"].isin(set(largest["symbol"]) | set(accented["symbol"]))]
    named = largest[largest["flex_share"] < HALF]
    ax.scatter(
        context["listed_oi"], context["flex_oi"], s=6, color=PALETTE["muted"], lw=0, zorder=2
    )
    ax.scatter(named["listed_oi"], named["flex_oi"], s=11, color=PALETTE["ink"], lw=0, zorder=3)
    if not index.empty:
        ax.scatter(
            index["listed_oi"],
            index["flex_oi"],
            s=30,
            marker="s",
            facecolors="none",
            edgecolors=PALETTE["ink"],
            linewidths=0.8,
            zorder=4,
        )
    ax.scatter(
        accented["listed_oi"], accented["flex_oi"], s=13, color=PALETTE["accent"], lw=0, zorder=5
    )

    fig.draw_without_rendering()
    order = pd.concat([accented, index, named]).drop_duplicates("symbol")
    markers = _marker_boxes(fig, ax, order)
    required = set(accented["symbol"]) | set(index["symbol"])
    placed = _place_labels(fig, ax, order, markers, required)
    dots = ax.transData.transform(both[["listed_oi", "flex_oi"]].to_numpy(dtype=float))
    _iso_labels(ax, limits, [*markers, *placed], dots)
    return fig


@FIGURES.register(RESULT)
def build_hidden_share(
    raw: Path = RAW_DIR, results: Path = RESULTS_DIR, root: Path = PROJECT_ROOT
) -> None:
    """F3, for the paper and as the README's lead figure."""
    expected = _census_values(results)
    view = census_view(load_inputs(raw))
    found = (f"{view.dated.date:%Y-%m-%d}", len(view.ordinary))
    if found != (expected["date"], expected["underlyings"]):
        raise ValueError(
            f"The census on disk ({found[0]}, {found[1]} underlyings) is not the one "
            f"results/{RESULT}.json was computed on ({expected['date']}, "
            f"{expected['underlyings']} underlyings); run `hidden-options results --only {RESULT}`"
        )
    apply_style()
    save(fig_hidden_share(view.ordinary, view.indices), RESULT, paper=True, readme=True, root=root)


def _census_values(results: Path) -> Mapping[str, Any]:
    found = read_results(results)
    if RESULT not in found:
        raise FileNotFoundError(
            f"No {RESULT!r} result in {results}; run `hidden-options results --only {RESULT}`"
        )
    census: Mapping[str, Any] = found[RESULT].values["census"]
    return census


def _drawable(frame: pd.DataFrame) -> pd.DataFrame:
    keep = (frame["flex_oi"] > 0) & (frame["listed_oi"] > 0)
    return frame.loc[keep, ["symbol", "flex_oi", "listed_oi", "flex_share"]].reset_index(drop=True)


def _ratio(share: float) -> float:
    """FLEX over listed open interest at a given FLEX share."""
    return share / (1 - share)


def _limits(frame: pd.DataFrame) -> tuple[tuple[float, float], tuple[float, float]]:
    """The points' range on each axis, widened by LIMIT_PAD each way so no mark sits on an edge."""

    def padded(values: pd.Series, top: float) -> tuple[float, float]:
        return float(values.min()) / LIMIT_PAD, float(values.max()) * top

    # The largest names sit at the top; the extra headroom there is room for their labels.
    return padded(frame["listed_oi"], LIMIT_PAD), padded(frame["flex_oi"], LIMIT_PAD**2)


def _iso_labels(
    ax: Axes,
    limits: tuple[tuple[float, float], tuple[float, float]],
    avoid: list[Bbox],
    dots: np.ndarray,
) -> None:
    """Name each iso-share line where its label touches no other label and fewest dots.

    Every place along the visible run of the line is tried; a place that collides with
    a label or a named mark is taken only if all do, and among the rest the one covering
    the fewest points wins, the upper one on a tie. The label lies along the line, just
    above it.
    """
    renderer = _renderer(ax.figure)
    frame = ax.get_window_extent(renderer)
    for target in ISO_SHARES:
        ratio = _ratio(target)
        low = max(limits[0][0], limits[1][0] / ratio)
        high = min(limits[0][1], limits[1][1] / ratio)
        best: tuple[tuple[float, int], Annotation] | None = None
        for fraction in ISO_PLACES:
            label = _iso_label(ax, target, low * (high / low) ** fraction)
            boxes = label_boxes(label, renderer)
            clash = sum(_overlap(box, avoid) + _outside(box, frame) for box in boxes)
            cost = (clash, _covered(boxes, dots))
            if best is not None and cost >= best[0]:
                label.remove()
                continue
            if best is not None:
                best[1].remove()
            best = (cost, label)
        assert best is not None
        avoid.extend(label_boxes(best[1], renderer))


def _covered(boxes: Sequence[Bbox], dots: np.ndarray) -> int:
    """How many of `dots` (display coordinates) fall inside any of `boxes`."""
    inside = np.zeros(len(dots), dtype=bool)
    for box in boxes:
        inside |= (
            (dots[:, 0] >= box.x0)
            & (dots[:, 0] <= box.x1)
            & (dots[:, 1] >= box.y0)
            & (dots[:, 1] <= box.y1)
        )
    return int(inside.sum())


def _iso_label(ax: Axes, target: float, x: float) -> Annotation:
    ratio = _ratio(target)
    start, end = ax.transData.transform([(x / 10, x / 10 * ratio), (x, x * ratio)])
    angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
    label = ax.annotate(
        f"{target:.0%} FLEX",
        xy=(x, x * ratio),
        xytext=(0, 2.0),
        textcoords="offset points",
        ha="right",
        va="bottom",
        rotation=angle,
        rotation_mode="anchor",
        color=PALETTE["ink"],
        path_effects=_HALO,
    )
    label.set_in_layout(False)
    return label


def label_boxes(text: Text, renderer: Any, pieces: int = 8) -> list[Bbox]:
    """Boxes that cover a label tightly, with its leader line if it has one.

    A level label is its own box. The axis-aligned box of a slanted label would cover
    the empty triangles above and below it, so a slanted label is cut along its length
    into `pieces` and each piece boxed on its own. A leader is covered the same way,
    by thin boxes along the segment from the text to its point.
    """
    if isinstance(text, Annotation):
        text.update_positions(renderer)
    angle = text.get_rotation() % 360
    if angle == 0:
        boxes = [Text.get_window_extent(text, renderer)]
    else:
        boxes = _slanted_boxes(text, renderer, angle, pieces)
    if isinstance(text, Annotation) and text.arrow_patch is not None:
        boxes += _leader_boxes(text, boxes[0], pieces)
    return boxes


def _slanted_boxes(text: Text, renderer: Any, angle: float, pieces: int) -> list[Bbox]:
    text.set_rotation(0)
    level = Text.get_window_extent(text, renderer)
    text.set_rotation(angle)
    # The anchor is the bottom right corner of the level text (ha right, va bottom).
    anchor = np.array([level.x1, level.y0])
    along = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
    up = np.array([-along[1], along[0]])
    boxes = []
    for piece in range(pieces):
        near, far = level.width * piece / pieces, level.width * (piece + 1) / pieces
        corners = [anchor - s * along + t * up for s in (near, far) for t in (0.0, level.height)]
        boxes.append(Bbox.from_extents(*np.min(corners, axis=0), *np.max(corners, axis=0)))
    return boxes


def _leader_boxes(label: Annotation, box: Bbox, pieces: int) -> list[Bbox]:
    """Thin boxes along the leader, from the label's centre to its point, outside the label."""
    assert label.axes is not None
    point = label.axes.transData.transform(label.xy)
    centre = np.array([(box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2])
    steps = np.linspace(0.0, 1.0, pieces + 1)
    ends = [centre + step * (point - centre) for step in steps]
    boxes = []
    for start, end in zip(ends[:-1], ends[1:], strict=True):
        piece = Bbox.from_extents(*np.minimum(start, end), *np.maximum(start, end)).padded(0.5)
        if not box.containsx(piece.x0) or not box.containsy(piece.y0):
            boxes.append(piece)
    return boxes


def _place_labels(
    fig: Figure, ax: Axes, points: pd.DataFrame, markers: list[Bbox], required: set[str]
) -> list[Bbox]:
    """Name each point at the first nearby position that touches no other label or mark.

    Positions next to the point come first; further out, a hairline leads back to it.
    `markers` are the named points' marks, in the order of `points`; a label must clear
    every mark but its own, which its hairline reaches by design. A label without a
    hairline must sit nearer its own point than any other named point by
    AMBIGUITY_MARGIN_PT, or it could read as that one's. A label is kept inside the axes.
    Should every position fail, a `required` label takes the one failing least, and any
    other label is left off: a large name without its ticker is better than a wrong one.
    Returns the boxes of the labels placed.
    """
    renderer = _renderer(fig)
    frame = ax.get_window_extent(renderer)
    pad = _PAD_PT * fig.dpi / 72
    margin = AMBIGUITY_MARGIN_PT * fig.dpi / 72
    centres = ax.transData.transform(points[["listed_oi", "flex_oi"]].to_numpy(dtype=float))
    placed: list[Bbox] = []
    for position, row in enumerate(points.itertuples()):
        others = np.delete(centres, position, axis=0)
        obstacles = [*placed, *markers[:position], *markers[position + 1 :]]
        best: tuple[float, Annotation] | None = None
        for radius, (dx, dy) in _CANDIDATES:
            far = radius > _NEAR_RADIUS
            label = _label(ax, row, dx, dy, far=far)
            boxes = label_boxes(label, renderer)
            cost = sum(_overlap(box.padded(pad), obstacles) + _outside(box, frame) for box in boxes)
            if not far and _nearer_to_another(boxes[0], centres[position], others, margin):
                cost += _AMBIGUOUS
            if best is not None and cost >= best[0]:
                label.remove()
                continue
            if best is not None:
                best[1].remove()
            best = (cost, label)
            if cost == 0:
                break
        assert best is not None
        if best[0] > 0 and row.symbol not in required:
            best[1].remove()
            continue
        placed.extend(label_boxes(best[1], renderer))
    return placed


def _nearer_to_another(box: Bbox, own: np.ndarray, others: np.ndarray, margin: float) -> bool:
    """True unless every point in `others` is at least `margin` farther from `box` than `own`."""
    if len(others) == 0:
        return False
    return bool(_distance(box, others).min() < _distance(box, own[None, :])[0] + margin)


def _distance(box: Bbox, points: np.ndarray) -> np.ndarray:
    """Distance from each point to the nearest edge of `box`; zero inside it."""
    dx = np.maximum(np.maximum(box.x0 - points[:, 0], points[:, 0] - box.x1), 0.0)
    dy = np.maximum(np.maximum(box.y0 - points[:, 1], points[:, 1] - box.y1), 0.0)
    return np.asarray(np.hypot(dx, dy), dtype=float)


def _renderer(fig: Any) -> Any:
    return fig.canvas.get_renderer()


def _marker_boxes(fig: Figure, ax: Axes, points: pd.DataFrame) -> list[Bbox]:
    """A small square around each named point, so no label sits on a named mark."""
    half = _MARKER_PT * fig.dpi / 72
    centres = ax.transData.transform(points[["listed_oi", "flex_oi"]].to_numpy(dtype=float))
    return [Bbox.from_extents(x - half, y - half, x + half, y + half) for x, y in centres]


def _label(ax: Axes, row: Any, dx: float, dy: float, *, far: bool) -> Annotation:
    arrow = {"arrowstyle": "-", "color": PALETTE["muted"], "lw": 0.5, "shrinkA": 0, "shrinkB": 2}
    label = ax.annotate(
        row.symbol,
        xy=(row.listed_oi, row.flex_oi),
        xytext=(dx, dy),
        textcoords="offset points",
        ha="left" if dx > 0 else "right" if dx < 0 else "center",
        va="bottom" if dy > 0 else "top" if dy < 0 else "center",
        color=PALETTE["ink"],
        arrowprops=arrow if far else None,
        path_effects=_HALO,
    )
    label.set_in_layout(False)
    return label


def _overlap(box: Bbox, others: Sequence[Bbox]) -> float:
    """Total area `box` shares with `others`."""
    area = 0.0
    for other in others:
        width = min(box.x1, other.x1) - max(box.x0, other.x0)
        height = min(box.y1, other.y1) - max(box.y0, other.y0)
        if width > 0 and height > 0:
            area += width * height
    return area


def _outside(box: Bbox, frame: Bbox) -> float:
    """How far `box` reaches past `frame`, weighted so that leaving the axes is never cheap."""
    reach = max(0.0, frame.x0 - box.x0, box.x1 - frame.x1, frame.y0 - box.y0, box.y1 - frame.y1)
    return float(reach) * 1e4
