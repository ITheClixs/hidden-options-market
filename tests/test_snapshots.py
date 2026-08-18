"""Tests for capture deduplication.

A source with a publication lag returns the same content to consecutive captures.
Concatenating partitions then double-counts one settlement, which is how a panel
acquires spurious observations that look like real days.
"""

from __future__ import annotations

import pandas as pd
import pytest

from absorb.measure.snapshots import deduplicate, distinct_snapshots, frame_fingerprint


def _write(tmp_path, name, frame):
    path = tmp_path / name
    frame.to_parquet(path, index=False)
    return path


@pytest.fixture
def frame():
    return pd.DataFrame({"symbol": ["A", "B"], "oi": [10, 20]})


class TestFingerprint:
    def test_identical_frames_match(self, frame):
        assert frame_fingerprint(frame) == frame_fingerprint(frame.copy())

    def test_row_order_does_not_matter(self, frame):
        assert frame_fingerprint(frame) == frame_fingerprint(frame.iloc[::-1])

    def test_a_changed_value_changes_the_hash(self, frame):
        other = frame.copy()
        other.loc[0, "oi"] = 11
        assert frame_fingerprint(frame) != frame_fingerprint(other)

    def test_empty_frame_is_handled(self):
        assert len(frame_fingerprint(pd.DataFrame())) == 64


class TestDistinctSnapshots:
    def test_identical_captures_group_together(self, tmp_path, frame):
        """The real case: two captures of one settlement, byte-identical."""
        a = _write(tmp_path, "2026-08-16.parquet", frame)
        b = _write(tmp_path, "2026-08-17.parquet", frame)
        groups = distinct_snapshots([a, b])
        assert len(groups) == 1
        assert len(next(iter(groups.values()))) == 2

    def test_different_captures_stay_separate(self, tmp_path, frame):
        a = _write(tmp_path, "a.parquet", frame)
        changed = frame.copy()
        changed.loc[0, "oi"] = 99
        b = _write(tmp_path, "b.parquet", changed)
        assert len(distinct_snapshots([a, b])) == 2

    def test_unreadable_files_are_skipped_not_fatal(self, tmp_path, frame):
        good = _write(tmp_path, "good.parquet", frame)
        bad = tmp_path / "bad.parquet"
        bad.write_text("not parquet")
        assert len(distinct_snapshots([good, bad])) == 1


class TestDeduplicate:
    def test_keeps_one_per_distinct_content(self, tmp_path, frame):
        a = _write(tmp_path, "2026-08-16.parquet", frame)
        b = _write(tmp_path, "2026-08-17.parquet", frame)
        assert deduplicate([a, b]) == [a]

    def test_keeps_the_earliest_capture(self, tmp_path, frame):
        """Earliest is closest to the settlement it describes."""
        b = _write(tmp_path, "2026-08-17.parquet", frame)
        a = _write(tmp_path, "2026-08-16.parquet", frame)
        assert deduplicate([b, a]) == [a]

    def test_distinct_content_is_all_retained(self, tmp_path, frame):
        a = _write(tmp_path, "a.parquet", frame)
        changed = frame.copy()
        changed.loc[1, "oi"] = 77
        b = _write(tmp_path, "b.parquet", changed)
        assert len(deduplicate([a, b])) == 2
