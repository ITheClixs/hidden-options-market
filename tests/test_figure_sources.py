"""Tests for the record of which results each figure was drawn from."""

from __future__ import annotations

import json

from hidden_options.publish.figure_sources import (
    SOURCES,
    note_saved,
    record,
    recording_saves,
    stale,
)
from hidden_options.publish.results import Result, read_results, recording_reads, write_result

STAMP = "2026-11-15T00:00:00+00:00"


def results(tmp_path, p_value):
    write_result(Result("predictive", {"p": p_value}, {}, {}, STAMP), tmp_path / "results")
    write_result(Result("market", {"n": 1}, {}, {}, STAMP), tmp_path / "results")
    return read_results(tmp_path / "results")


def test_reads_and_saves_are_recorded_only_inside_the_block(tmp_path):
    results(tmp_path, 0.42)
    with recording_reads() as reads, recording_saves() as stems:
        found = read_results(tmp_path / "results")
        _ = found["predictive"]
        note_saved("placebo")
    assert reads == {"predictive"}
    assert stems == {"placebo"}
    plain = read_results(tmp_path / "results")
    assert type(plain) is dict  # no recording outside the block


def test_a_figure_drawn_from_changed_results_is_stale(tmp_path):
    found = results(tmp_path, 0.42)
    (tmp_path / "paper" / "figures").mkdir(parents=True)
    (tmp_path / "paper" / "figures" / "placebo.pdf").write_bytes(b"%PDF")
    record(tmp_path, {"placebo"}, {"predictive"}, found)
    assert stale(tmp_path, found) == []
    assert set(json.loads((tmp_path / SOURCES).read_text())["placebo"]) == {"predictive"}

    changed = results(tmp_path, 0.45)
    assert stale(tmp_path, changed) == ["paper/figures/placebo.pdf"]


def test_a_figure_with_no_record_is_stale(tmp_path):
    found = results(tmp_path, 0.42)
    (tmp_path / "paper" / "figures").mkdir(parents=True)
    (tmp_path / "paper" / "figures" / "growth.pdf").write_bytes(b"%PDF")
    assert stale(tmp_path, found) == ["paper/figures/growth.pdf"]


def test_an_unrelated_result_does_not_make_a_figure_stale(tmp_path):
    found = results(tmp_path, 0.42)
    (tmp_path / "paper" / "figures").mkdir(parents=True)
    (tmp_path / "paper" / "figures" / "placebo.pdf").write_bytes(b"%PDF")
    record(tmp_path, {"placebo"}, {"predictive"}, found)
    write_result(Result("market", {"n": 2}, {}, {}, STAMP), tmp_path / "results")
    assert stale(tmp_path, read_results(tmp_path / "results")) == []
