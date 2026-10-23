"""Distinguish captures from settlements.

OCC publishes settlement open interest overnight, so a capture taken during or shortly
after a session reports the *previous* settlement. Two consecutive captures can
therefore be byte-identical, and were: captures on 2026-08-16 and 2026-08-17 both
returned Friday 2026-08-14's settlement, differing in not a single contract.

Partitioning by capture date silently mislabels such data and double-counts it in any
panel built by concatenating partitions. This module keys captures by payload content
so that duplicates collapse to one observation.

The lesson generalises to any snapshot source with a publication lag: the date a file
was fetched is not the date its contents describe.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


def frame_fingerprint(frame: pd.DataFrame) -> str:
    """Content hash of a frame, stable under row order."""
    if frame.empty:
        return hashlib.sha256(b"").hexdigest()
    ordered = frame.sort_values(list(frame.columns)).reset_index(drop=True)
    return hashlib.sha256(
        pd.util.hash_pandas_object(ordered, index=False).values.tobytes()
    ).hexdigest()


def distinct_snapshots(paths: list[Path]) -> dict[str, list[Path]]:
    """Group capture files by content, newest path last within each group.

    Returns a mapping from content hash to the captures carrying it. A group with more
    than one member indicates repeated captures of one settlement, which must be
    counted once.
    """
    groups: dict[str, list[Path]] = {}
    for path in sorted(paths):
        try:
            digest = frame_fingerprint(pd.read_parquet(path))
        except Exception:  # noqa: BLE001 - an unreadable capture is skipped, not fatal
            continue
        groups.setdefault(digest, []).append(path)
    return groups


def deduplicate(paths: list[Path]) -> list[Path]:
    """One representative capture per distinct content, earliest kept.

    The earliest capture of a given settlement is kept because it is closest to the
    settlement it describes.
    """
    return sorted(group[0] for group in distinct_snapshots(paths).values())


__all__ = ["deduplicate", "distinct_snapshots", "frame_fingerprint"]
