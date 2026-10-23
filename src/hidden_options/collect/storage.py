"""Atomic parquet writes shared by every collector.

Several collectors take a file's existence as proof that its data is held (the FLEX
collector skips a date whose file is present), so a crash mid-write must never leave a
truncated file at the destination.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_frame(frame: pd.DataFrame, destination: Path) -> None:
    """Write via a staging file so a crash never leaves a truncated parquet in place.

    Most sources overwrite their file the next day, but the FLEX collector treats an
    existing file as proof the date is held, so a half-written one would never be redone.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + ".partial")
    try:
        frame.to_parquet(staging, index=False, compression="zstd")
        staging.replace(destination)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


__all__ = ["write_frame"]
