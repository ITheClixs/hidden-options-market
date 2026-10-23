"""Runner and config tests.

The behaviour that matters most is isolation: because the upstream endpoints are
snapshots with no history, one failing symbol must never cost the whole capture.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from hidden_options.collect import cboe, occ_flex, runner
from hidden_options.collect.http import FetchError
from hidden_options.config import Universe, load_universe

AS_OF = datetime(2026, 8, 16, 21, 5, tzinfo=UTC)
FRIDAY = datetime(2026, 8, 14, 23, 30, tzinfo=UTC)


@pytest.fixture
def universe() -> Universe:
    return Universe(
        treated_single_name=("MSTR", "NVDA"),
        treated_index_and_etf=("_SPX",),
        control_single_name=("ADBE", "MSTR"),
    )


class TestUniverse:
    def test_all_symbols_deduplicates_and_orders_treated_first(self, universe):
        assert universe.all_symbols == ("MSTR", "NVDA", "_SPX", "ADBE")

    def test_occ_symbols_exclude_index_pseudo_symbols(self, universe):
        assert "_SPX" not in universe.occ_symbols
        assert "MSTR" in universe.occ_symbols

    def test_shipped_config_loads(self):
        loaded = load_universe()
        assert len(loaded.all_symbols) > 50
        assert "MSTR" in loaded.treated_single_name

    def test_missing_config_raises_actionable_error(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_universe(tmp_path / "absent.json")

    def test_malformed_config_raises_actionable_error(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_universe(bad)

    def test_config_missing_keys_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"treated_underlyings": {}}))
        with pytest.raises(ValueError, match="missing required keys"):
            load_universe(bad)


def _stub_snapshot(symbol: str) -> cboe.ChainSnapshot:
    frame = pd.DataFrame({"symbol": [symbol], "contract": [f"{symbol}260814C00030000"]})
    return cboe.ChainSnapshot(
        symbol=symbol, quote_timestamp="t", frame=frame, payload_sha256="d" * 64
    )


class TestCollectCboeChains:
    def test_writes_one_partition_per_symbol(self, universe, tmp_path, monkeypatch):
        monkeypatch.setattr(cboe, "fetch_chain", lambda _s, symbol: _stub_snapshot(symbol))
        outcomes = runner.collect_cboe_chains(universe, AS_OF, tmp_path)

        assert [o.status for o in outcomes] == ["ok"] * 4
        written = sorted(p.name for p in (tmp_path / "cboe_chain" / "date=2026-08-16").iterdir())
        assert written == [
            "equity_ADBE.parquet",
            "equity_MSTR.parquet",
            "equity_NVDA.parquet",
            "index_SPX.parquet",
        ]

    def test_one_failing_symbol_does_not_abort_the_run(self, universe, tmp_path, monkeypatch):
        def flaky(_session, symbol):
            if symbol == "NVDA":
                raise FetchError("upstream 503")
            return _stub_snapshot(symbol)

        monkeypatch.setattr(cboe, "fetch_chain", flaky)
        outcomes = runner.collect_cboe_chains(universe, AS_OF, tmp_path)

        by_symbol = {o.symbol: o for o in outcomes}
        assert by_symbol["NVDA"].status == "error"
        assert "upstream 503" in by_symbol["NVDA"].detail
        assert by_symbol["MSTR"].status == "ok"
        assert len(list((tmp_path / "cboe_chain" / "date=2026-08-16").iterdir())) == 3

    def test_parse_failure_is_recorded_not_raised(self, universe, tmp_path, monkeypatch):
        def always_bad(_session, _symbol):
            raise cboe.ChainParseError("layout changed")

        monkeypatch.setattr(cboe, "fetch_chain", always_bad)
        outcomes = runner.collect_cboe_chains(universe, AS_OF, tmp_path)
        assert all(o.status == "error" for o in outcomes)
        assert all("ChainParseError" in o.detail for o in outcomes)


class TestManifest:
    def test_records_counts_and_every_outcome(self, tmp_path):
        outcomes = (
            runner.SymbolOutcome("cboe_chain", "MSTR", "ok", rows=3210, sha256="a" * 64),
            runner.SymbolOutcome("cboe_chain", "NVDA", "error", detail="FetchError: 503"),
        )
        path = runner.write_manifest(outcomes, AS_OF, tmp_path)
        manifest = json.loads(path.read_text())

        assert manifest["n_attempted"] == 2
        assert manifest["n_ok"] == 1
        assert manifest["n_failed"] == 1
        assert manifest["total_rows"] == 3210
        assert len(manifest["outcomes"]) == 2

    def test_manifest_written_even_when_everything_fails(self, universe, tmp_path, monkeypatch):
        monkeypatch.setattr(
            cboe, "fetch_chain", lambda *_: (_ for _ in ()).throw(FetchError("down"))
        )
        runner.run_daily_collection(universe, root=tmp_path, as_of=AS_OF, sources=("cboe",))
        assert list((tmp_path / "manifests").iterdir())


class TestSweepUp:
    """A missed capture is unrecoverable, so failures get one retry after the burst."""

    def test_successful_retry_supersedes_the_failure(self, universe, tmp_path, monkeypatch):
        attempts: dict[str, int] = {}

        def flaky_once(_session, symbol):
            attempts[symbol] = attempts.get(symbol, 0) + 1
            if symbol == "NVDA" and attempts[symbol] == 1:
                raise FetchError("throttled")
            return _stub_snapshot(symbol)

        monkeypatch.setattr(cboe, "fetch_chain", flaky_once)
        outcomes = runner.run_daily_collection(
            universe, root=tmp_path, as_of=AS_OF, sources=("cboe",)
        )

        by_symbol = {o.symbol: o for o in outcomes}
        assert by_symbol["NVDA"].status == "ok"
        assert attempts["NVDA"] == 2
        assert len([o for o in outcomes if o.symbol == "NVDA"]) == 1

    def test_persistent_failure_stays_failed(self, universe, tmp_path, monkeypatch):
        monkeypatch.setattr(
            cboe, "fetch_chain", lambda *_: (_ for _ in ()).throw(FetchError("gone"))
        )
        outcomes = runner.run_daily_collection(
            universe, root=tmp_path, as_of=AS_OF, sources=("cboe",)
        )
        assert all(o.status == "error" for o in outcomes)

    def test_sweep_can_be_disabled(self, universe, tmp_path, monkeypatch):
        attempts: dict[str, int] = {}

        def always_fail(_session, symbol):
            attempts[symbol] = attempts.get(symbol, 0) + 1
            raise FetchError("down")

        monkeypatch.setattr(cboe, "fetch_chain", always_fail)
        runner.run_daily_collection(
            universe, root=tmp_path, as_of=AS_OF, sources=("cboe",), sweep_up=False
        )
        assert all(count == 1 for count in attempts.values())


def _flex_report(report_date: date, kind: str) -> occ_flex.FlexReport:
    frame = pd.DataFrame(
        {
            "report_date": [report_date],
            "kind": [kind],
            "root": ["1AAL"],
            "open_interest": [100],
        }
    )
    return occ_flex.FlexReport(
        report_date=report_date,
        kind=kind,
        frame=frame,
        payload_sha256="f" * 64,
        class_totals_checked=1,
        class_totals_matched=1,
    )


class FlexStub:
    """Stands in for OCC: records every request and answers from a script.

    ``answers`` maps a requested date to the report date OCC answers with, or to
    ``None`` for "no report available". Unlisted dates answer with their own report.
    """

    def __init__(self, monkeypatch, answers=None):
        self.calls: list[tuple[date, str]] = []
        self.answers = answers or {}
        monkeypatch.setattr(occ_flex, "fetch_report", self._fetch)

    def _fetch(self, _session, requested, kind="equity"):
        self.calls.append((requested, kind))
        answer = self.answers.get(requested, requested)
        if answer is None:
            raise occ_flex.FlexReportAbsent(f"{kind} {requested}: no report available")
        if isinstance(answer, Exception):
            raise answer
        return _flex_report(answer, kind)


def _flex_files(root) -> set[str]:
    return {str(p.relative_to(root)) for p in (root / "occ_flex").rglob("*.parquet")}


class TestCollectOccFlex:
    """The FLEX report is published overnight and keeps ~20 months of history, so unlike
    the snapshot sources a missed day is recoverable. A lookback window re-asks for any
    date still missing instead of treating one empty answer as final."""

    def test_writes_missing_dates_only(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        for day in ("2026-08-10", "2026-08-11"):
            for kind in ("equity", "index"):
                target = tmp_path / f"occ_flex/date={day}/{kind}.parquet"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"already on disk")

        outcomes = runner.collect_occ_flex(AS_OF, tmp_path)

        # 2026-08-09 .. 08-16 holds five weekdays; two are on disk, three are fetched.
        assert sorted(stub.calls) == sorted(
            (date(2026, 8, d), kind) for d in (12, 13, 14) for kind in ("equity", "index")
        )
        assert len(_flex_files(tmp_path)) == 10
        assert (tmp_path / "occ_flex/date=2026-08-10/equity.parquet").read_bytes() == (
            b"already on disk"
        )
        assert {o.status for o in outcomes} == {"ok"}
        assert {o.symbol for o in outcomes} == {
            f"{kind}:2026-08-{d}" for d in (12, 13, 14) for kind in ("equity", "index")
        }
        assert {o.source for o in outcomes} == {"flex"}

    def test_each_kind_is_skipped_independently(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        have = tmp_path / "occ_flex/date=2026-08-14/equity.parquet"
        have.parent.mkdir(parents=True)
        have.write_bytes(b"x")

        runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)

        assert stub.calls == [(date(2026, 8, 14), "index")]

    def test_weekends_are_never_requested(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        runner.collect_occ_flex(AS_OF, tmp_path, lookback_days=30)
        assert all(day.weekday() < 5 for day, _ in stub.calls)

    def test_lookback_bounds_the_window(self, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=2)
        assert {day for day, _ in stub.calls} == {
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
        }

    def test_outcome_rows_and_hash_come_from_the_report(self, tmp_path, monkeypatch):
        FlexStub(monkeypatch)
        (outcome,) = [
            o
            for o in runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)
            if o.symbol == "equity:2026-08-14"
        ]
        assert (outcome.rows, outcome.sha256) == (1, "f" * 64)

    def test_unpublished_report_is_absent_not_an_error(self, tmp_path, monkeypatch):
        FlexStub(monkeypatch, {date(2026, 8, 14): None})
        outcomes = runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)

        assert {o.status for o in outcomes} == {"absent"}
        assert "no report available" in outcomes[0].detail
        assert not (tmp_path / "occ_flex").exists()

    def test_absent_dates_are_asked_for_again_on_the_next_run(self, tmp_path, monkeypatch):
        """The window is what catches up a report that was not out yet."""
        FlexStub(monkeypatch, {date(2026, 8, 14): None})
        runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)

        stub = FlexStub(monkeypatch)
        later = datetime(2026, 8, 15, 23, 30, tzinfo=UTC)
        outcomes = runner.collect_occ_flex(later, tmp_path, lookback_days=1)

        assert sorted(stub.calls) == [(date(2026, 8, 14), "equity"), (date(2026, 8, 14), "index")]
        assert {o.status for o in outcomes} == {"ok"}

    def test_never_files_previous_settlement_under_today(self, tmp_path, monkeypatch):
        """OCC answering a request for D with the report for D-1 must not put D-1's data
        at date=D: that would enter one settlement twice as two stable days."""
        FlexStub(monkeypatch, {date(2026, 8, 14): date(2026, 8, 13)})
        outcomes = runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)

        assert not (tmp_path / "occ_flex/date=2026-08-14").exists()
        assert _flex_files(tmp_path) == {
            "occ_flex/date=2026-08-13/equity.parquet",
            "occ_flex/date=2026-08-13/index.parquet",
        }
        by_symbol = {o.symbol: o for o in outcomes}
        assert by_symbol["equity:2026-08-14"].status == "absent"
        assert "2026-08-13" in by_symbol["equity:2026-08-14"].detail
        assert by_symbol["equity:2026-08-13"].status == "ok"
        stored = pd.read_parquet(tmp_path / "occ_flex/date=2026-08-13/equity.parquet")
        assert set(stored["report_date"]) == {date(2026, 8, 13)}

    def test_previous_settlement_already_on_disk_is_left_alone(self, tmp_path, monkeypatch):
        FlexStub(monkeypatch, {date(2026, 8, 14): date(2026, 8, 13)})
        have = tmp_path / "occ_flex/date=2026-08-13/equity.parquet"
        have.parent.mkdir(parents=True)
        have.write_bytes(b"original")

        outcomes = runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)

        assert have.read_bytes() == b"original"
        assert not (tmp_path / "occ_flex/date=2026-08-14").exists()
        assert {o.symbol: o.status for o in outcomes}["equity:2026-08-14"] == "absent"
        assert "equity:2026-08-13" not in {o.symbol for o in outcomes}

    def test_unreadable_report_is_an_error_not_absent(self, tmp_path, monkeypatch):
        """A layout change must be loud: otherwise every report would look unpublished."""
        broken = occ_flex.FlexReportError("equity 2026-08-14: no series rows parsed")
        FlexStub(monkeypatch, {date(2026, 8, 14): broken})
        outcomes = runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)

        assert {o.status for o in outcomes} == {"error"}
        assert "no series rows parsed" in outcomes[0].detail

    def test_one_failing_request_does_not_stop_the_others(self, tmp_path, monkeypatch):
        FlexStub(monkeypatch, {date(2026, 8, 13): FetchError("upstream 503")})
        outcomes = runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=1)

        statuses = {o.symbol: o.status for o in outcomes}
        assert statuses["equity:2026-08-13"] == "error"
        assert statuses["equity:2026-08-14"] == "ok"
        assert statuses["index:2026-08-14"] == "ok"

    def test_failed_write_leaves_nothing_that_would_be_skipped(self, tmp_path, monkeypatch):
        """A file on disk is taken as proof the date is held, so a half-written parquet
        would never be repaired."""
        FlexStub(monkeypatch)

        def dies_midway(self, path, *args, **kwargs):
            Path(path).write_bytes(b"PAR1 truncated")
            raise OSError("disk full")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", dies_midway)
        outcomes = runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)

        assert {o.status for o in outcomes} == {"write_error"}
        assert not list((tmp_path / "occ_flex").rglob("*.parquet*"))

    def test_builds_its_own_session_when_none_is_given(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(runner, "build_session", lambda: "built")
        monkeypatch.setattr(
            occ_flex, "fetch_report", lambda s, d, k: seen.append(s) or _flex_report(d, k)
        )
        runner.collect_occ_flex(FRIDAY, tmp_path, lookback_days=0)
        runner.collect_occ_flex(FRIDAY, tmp_path / "other", lookback_days=0, session="mine")
        assert set(seen) == {"built", "mine"}


class TestFlexInDailyRun:
    def test_flex_is_a_selectable_source(self, universe, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        outcomes = runner.run_daily_collection(
            universe, root=tmp_path, as_of=FRIDAY, sources=("flex",)
        )
        assert {o.source for o in outcomes} == {"flex"}
        assert stub.calls

    def test_flex_is_not_collected_when_not_selected(self, universe, tmp_path, monkeypatch):
        stub = FlexStub(monkeypatch)
        monkeypatch.setattr(cboe, "fetch_chain", lambda _s, symbol: _stub_snapshot(symbol))
        runner.run_daily_collection(universe, root=tmp_path, as_of=FRIDAY, sources=("cboe",))
        assert stub.calls == []

    def test_sweep_does_not_retry_absent_reports(self, universe, tmp_path, monkeypatch):
        """An unpublished report is not a failure; asking again within the same run
        cannot change the answer and would only add load on OCC."""
        stub = FlexStub(monkeypatch, {date(2026, 8, 14): None})
        outcomes = runner.run_daily_collection(
            universe, root=tmp_path, as_of=FRIDAY, sources=("flex",), sweep_up=True
        )

        today = [o for o in outcomes if o.symbol.endswith("2026-08-14")]
        assert {o.status for o in today} == {"absent"}
        assert [c for c in stub.calls if c[0] == date(2026, 8, 14)] == [
            (date(2026, 8, 14), "equity"),
            (date(2026, 8, 14), "index"),
        ]

    def test_sweep_still_retries_real_failures_alongside_absent_reports(
        self, universe, tmp_path, monkeypatch
    ):
        stub = FlexStub(monkeypatch, {date(2026, 8, 14): None})
        attempts: dict[str, int] = {}

        def flaky_once(_session, symbol):
            attempts[symbol] = attempts.get(symbol, 0) + 1
            if symbol == "NVDA" and attempts[symbol] == 1:
                raise FetchError("throttled")
            return _stub_snapshot(symbol)

        monkeypatch.setattr(cboe, "fetch_chain", flaky_once)
        outcomes = runner.run_daily_collection(
            universe, root=tmp_path, as_of=FRIDAY, sources=("cboe", "flex")
        )

        by_key = {(o.source, o.symbol): o.status for o in outcomes}
        assert by_key[("cboe_chain", "NVDA")] == "ok"
        assert attempts["NVDA"] == 2
        assert by_key[("flex", "equity:2026-08-14")] == "absent"
        assert stub.calls.count((date(2026, 8, 14), "equity")) == 1

    def test_absent_outcomes_are_recorded_in_the_manifest(self, universe, tmp_path, monkeypatch):
        FlexStub(monkeypatch, {date(2026, 8, 14): None})
        runner.run_daily_collection(universe, root=tmp_path, as_of=FRIDAY, sources=("flex",))

        (manifest_path,) = (tmp_path / "manifests").iterdir()
        recorded = json.loads(manifest_path.read_text())["outcomes"]
        assert {"equity:2026-08-14", "index:2026-08-14"} <= {
            o["symbol"] for o in recorded if o["status"] == "absent"
        }
