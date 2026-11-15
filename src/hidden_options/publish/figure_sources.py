"""Which results each committed figure was drawn from, and whether they have changed since.

A figure is an image, so the drift check cannot re-render it without the raw data some
builders read. What it can check is provenance: when `hidden-options figures` builds a
figure, it records a hash of the values of every result the builder looked up
(`results.recording_reads`) under the figure's name in SOURCES. The drift check then
recomputes those hashes from `results/`. A figure whose results have changed since it was
built, or a committed figure with no record, is reported as drift.

Nothing here imports matplotlib, so the check still runs on a bare checkout.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from hidden_options.publish.results import Result, values_digest

SOURCES = "paper/figures/sources.json"
FIGURES_DIR = "paper/figures"

_SAVERS: list[set[str]] = []


@contextmanager
def recording_saves() -> Iterator[set[str]]:
    """Collect the stems of the figures saved while the block runs."""
    stems: set[str] = set()
    _SAVERS.append(stems)
    try:
        yield stems
    finally:
        _SAVERS.remove(stems)


def note_saved(stem: str) -> None:
    """Called by the figure style's `save` for every figure written."""
    for stems in _SAVERS:
        stems.add(stem)


def record(
    root: Path, stems: Iterable[str], names: Iterable[str], results: Mapping[str, Result]
) -> None:
    """Record, for each figure in `stems`, the digest of each result in `names`."""
    path = root / SOURCES
    stored = _load(path)
    digests = {name: values_digest(results[name]) for name in sorted(names) if name in results}
    for stem in stems:
        stored[stem] = digests
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(sorted(stored.items())), indent=2, sort_keys=True)
    path.write_text(f"{text}\n", encoding="utf-8")


def stale(root: Path, results: Mapping[str, Result]) -> list[str]:
    """Committed figures with no record, or drawn from results whose values have changed."""
    stored = _load(root / SOURCES)
    drifted = []
    for figure in sorted((root / FIGURES_DIR).glob("*.pdf")):
        record_of = stored.get(figure.stem)
        current = {
            name: values_digest(results[name]) for name in (record_of or {}) if name in results
        }
        if record_of is None or current != record_of:
            drifted.append(figure.relative_to(root).as_posix())
    return drifted


def _load(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    loaded: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


__all__ = ["SOURCES", "note_saved", "record", "recording_saves", "stale"]
