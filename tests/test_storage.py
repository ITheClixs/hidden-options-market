"""Tests for the atomic parquet writer shared by every collector.

Several collectors treat a file on disk as proof the data is held, so the property that
matters is that a crash never leaves a truncated file at the destination.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hidden_options.collect.storage import write_frame

FRAME = pd.DataFrame({"symbol": ["AAL", "AAPL"], "open_interest": [1, 2]})


def test_writes_a_readable_parquet_and_creates_missing_directories(tmp_path):
    destination = tmp_path / "a" / "b" / "frame.parquet"
    write_frame(FRAME, destination)
    pd.testing.assert_frame_equal(pd.read_parquet(destination), FRAME)


def test_leaves_no_staging_file_behind(tmp_path):
    write_frame(FRAME, tmp_path / "frame.parquet")
    assert [p.name for p in tmp_path.iterdir()] == ["frame.parquet"]


def test_replaces_an_existing_file(tmp_path):
    destination = tmp_path / "frame.parquet"
    destination.write_bytes(b"old")
    write_frame(FRAME, destination)
    assert len(pd.read_parquet(destination)) == 2


def test_a_failed_write_keeps_the_previous_file_and_leaves_no_partial(tmp_path, monkeypatch):
    destination = tmp_path / "frame.parquet"
    write_frame(FRAME, destination)
    before = destination.read_bytes()

    def dies_midway(self, path, *args, **kwargs):
        Path(path).write_bytes(b"PAR1 truncated")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", dies_midway)
    with pytest.raises(OSError, match="disk full"):
        write_frame(FRAME.assign(open_interest=[9, 9]), destination)

    assert destination.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["frame.parquet"]
