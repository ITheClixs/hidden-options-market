"""Tests for the historical FLEX backfill.

The backfill is the same capture as the nightly collector run over an arbitrary span, so
the properties that matter are the ones that make a long unattended walk safe to repeat:
a date already held is never fetched or rewritten, one bad request never ends the walk,
and a report is only ever filed under the activity date it states.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from flex_stub import FlexStub, flex_report
from hidden_options.collect import backfill, occ_flex
from hidden_options.collect.backfill import BackfillSummary, backfill_flex
from hidden_options.collect.http import FetchError

BOTH = ("equity", "index")


def _put(root, day: str, kind: str, payload: bytes = b"already on disk"):
    target = root / f"occ_flex/date={day}/{kind}.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def _files(root) -> set[str]:
    return {str(p.relative_to(root)) for p in (root / "occ_flex").rglob("*.parquet")}


class TestBackfillFlex:
    def test_a_date_already_on_disk_is_skipped(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        held = _put(tmp_path, "2026-08-13", "equity")

        summary = backfill_flex(date(2026, 8, 13), date(2026, 8, 14), tmp_path, BOTH, session="s")

        assert (date(2026, 8, 13), "equity") not in stub.calls
        assert sorted(stub.calls) == [
            (date(2026, 8, 13), "index"),
            (date(2026, 8, 14), "equity"),
            (date(2026, 8, 14), "index"),
        ]
        assert held.read_bytes() == b"already on disk"
        assert summary.skipped == 1
        assert summary.saved == 3

    def test_rerunning_a_finished_backfill_fetches_nothing(self, tmp_path, monkeypatch):
        FlexStub(monkeypatch)
        backfill_flex(date(2026, 8, 12), date(2026, 8, 14), tmp_path, BOTH, session="s")

        stub = FlexStub(monkeypatch)
        again = backfill_flex(date(2026, 8, 12), date(2026, 8, 14), tmp_path, BOTH, session="s")

        assert stub.calls == []
        assert (again.saved, again.skipped, again.absent, again.failed) == (0, 6, 0, 0)

    def test_covers_every_weekday_in_the_span_inclusive_and_no_weekend(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        # Saturday 8 Aug through Monday 17 Aug: Mon-Fri 10-14, then Mon 17.
        summary = backfill_flex(date(2026, 8, 8), date(2026, 8, 17), tmp_path, BOTH, session="s")

        requested = {day for day, _ in stub.calls}
        assert requested == {date(2026, 8, d) for d in (10, 11, 12, 13, 14, 17)}
        assert summary.saved == 12

    def test_walks_from_the_newest_date_back(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        backfill_flex(date(2026, 8, 12), date(2026, 8, 14), tmp_path, BOTH, session="s")

        days = [day for day, _ in stub.calls]
        assert days == sorted(days, reverse=True)

    def test_only_the_requested_kinds_are_fetched(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        backfill_flex(date(2026, 8, 13), date(2026, 8, 14), tmp_path, ("equity",), session="s")

        assert {kind for _, kind in stub.calls} == {"equity"}
        assert _files(tmp_path) == {
            "occ_flex/date=2026-08-13/equity.parquet",
            "occ_flex/date=2026-08-14/equity.parquet",
        }

    def test_an_unpublished_date_is_absent_not_failed_and_writes_nothing(
        self, tmp_path, monkeypatch
    ):
        FlexStub(monkeypatch, {date(2026, 8, 14): None})
        summary = backfill_flex(date(2026, 8, 13), date(2026, 8, 14), tmp_path, BOTH, session="s")

        assert (summary.absent, summary.failed, summary.saved) == (2, 0, 2)
        assert not (tmp_path / "occ_flex/date=2026-08-14").exists()

    def test_one_failing_request_does_not_end_the_walk(self, tmp_path, monkeypatch):
        FlexStub(
            monkeypatch,
            {
                date(2026, 8, 14): FetchError("upstream 503"),
                date(2026, 8, 13): occ_flex.FlexReportError("no series rows parsed"),
            },
        )
        summary = backfill_flex(date(2026, 8, 12), date(2026, 8, 14), tmp_path, BOTH, session="s")

        assert summary.failed == 4
        assert summary.saved == 2
        assert _files(tmp_path) == {
            "occ_flex/date=2026-08-12/equity.parquet",
            "occ_flex/date=2026-08-12/index.parquet",
        }

    def test_an_unreadable_report_counts_as_failed_not_absent(self, tmp_path, monkeypatch):
        """With a hardened fetch, a layout change is a FlexReportError, which is never
        absence: it has to surface as a failure or a moved layout looks like a quiet day."""
        FlexStub(monkeypatch, {date(2026, 8, 14): occ_flex.FlexReportError("layout moved")})
        summary = backfill_flex(
            date(2026, 8, 14), date(2026, 8, 14), tmp_path, ("equity",), session="s"
        )

        assert (summary.failed, summary.absent) == (1, 0)
        assert "layout moved" in summary.outcomes[0].detail

    def test_never_files_the_previous_settlement_under_the_requested_date(
        self, tmp_path, monkeypatch
    ):
        FlexStub(monkeypatch, {date(2026, 8, 14): date(2026, 8, 13)})
        summary = backfill_flex(
            date(2026, 8, 14), date(2026, 8, 14), tmp_path, ("equity",), session="s"
        )

        assert not (tmp_path / "occ_flex/date=2026-08-14").exists()
        stored = pd.read_parquet(tmp_path / "occ_flex/date=2026-08-13/equity.parquet")
        assert set(stored["report_date"]) == {date(2026, 8, 13)}
        assert summary.absent == 1

    def test_writes_go_through_the_staging_file(self, tmp_path, monkeypatch):
        """A file on disk is proof the date is held, so a crash must not leave a stub."""
        FlexStub(monkeypatch)

        def dies_midway(self, path, *args, **kwargs):
            Path(path).write_bytes(b"PAR1 truncated")
            raise OSError("disk full")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", dies_midway)
        summary = backfill_flex(
            date(2026, 8, 14), date(2026, 8, 14), tmp_path, ("equity",), session="s"
        )

        assert summary.failed == 1
        assert not list((tmp_path / "occ_flex").rglob("*.parquet*"))

    def test_logs_a_warning_when_class_totals_do_not_reconcile(self, tmp_path, monkeypatch, caplog):
        """A report whose rows disagree with its own totals is a parse problem, and the
        only place that is visible during a long backfill is the log."""
        unreconciled = dataclasses.replace(
            flex_report(date(2026, 8, 14), "equity"),
            class_totals_checked=5,
            class_totals_matched=4,
        )
        monkeypatch.setattr(occ_flex, "fetch_report", lambda *_a, **_k: unreconciled)

        with caplog.at_level(logging.WARNING):
            summary = backfill_flex(
                date(2026, 8, 14), date(2026, 8, 14), tmp_path, ("equity",), session="s"
            )

        assert any("4/5" in r.getMessage() for r in caplog.records)
        assert summary.saved == 1

    def test_builds_its_own_session_when_none_is_given(self, tmp_path, monkeypatch):
        seen = []
        FlexStub(monkeypatch)
        monkeypatch.setattr(backfill, "build_session", lambda: seen.append("built") or "built")
        backfill_flex(date(2026, 8, 14), date(2026, 8, 14), tmp_path, ("equity",))
        assert seen == ["built"]

    def test_a_span_that_ends_before_it_starts_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="before"):
            backfill_flex(date(2026, 8, 14), date(2026, 8, 13), tmp_path, BOTH, session="s")

    def test_an_unknown_kind_is_rejected_before_any_request(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        with pytest.raises(ValueError, match="kind"):
            backfill_flex(date(2026, 8, 14), date(2026, 8, 14), tmp_path, ("futures",), session="s")
        assert stub.calls == []


class TestBackfillSummary:
    def test_describe_states_every_count(self, tmp_path, monkeypatch):
        FlexStub(monkeypatch, {date(2026, 8, 14): None})
        _put(tmp_path, "2026-08-13", "equity")
        summary = backfill_flex(date(2026, 8, 13), date(2026, 8, 14), tmp_path, BOTH, session="s")

        assert isinstance(summary, BackfillSummary)
        assert summary.describe() == "saved=1 absent=2 skipped=1 failed=0"
