"""Tests for refreshing the daily bars that sit under the FLEX panel.

The file this writes feeds every regression, so the failures that matter are quiet ones:
an in-progress session stored as if it had closed, a symbol Yahoo refuses taking down the
whole refresh, and a rewrite that drops or rescales history it did not mean to touch.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from hidden_options.collect import bars
from hidden_options.collect.bars import (
    BAR_COLUMNS,
    HISTORY_SESSIONS,
    BarParseError,
    BarSnapshot,
    flex_underlyings,
    history_start,
    lookback_since,
    refresh_flex_underlying_bars,
    settled_daily_bars,
)
from hidden_options.collect.http import FetchError


def _panel(rows: dict[tuple[str, str], int]) -> pd.DataFrame:
    """A FLEX panel with ``n`` distinct activity dates for each (kind, underlying)."""
    frames = []
    for (kind, underlying), n_dates in rows.items():
        dates = pd.bdate_range("2025-01-02", periods=n_dates)
        frames.append(pd.DataFrame({"kind": kind, "underlying": underlying, "report_date": dates}))
    return pd.concat(frames, ignore_index=True)


def _bars(symbol: str, days: list[str], close: float = 10.0) -> pd.DataFrame:
    """Daily bars stamped at the 13:30 UTC open, the way the provider stamps them."""
    stamps = pd.to_datetime([f"{d} 13:30" for d in days], utc=True)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": stamps,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000,
        },
        columns=list(BAR_COLUMNS),
    )


class FakeYahoo:
    """Stands in for the chart endpoint: serves scripted frames, records every request."""

    def __init__(self, monkeypatch, served: dict[str, pd.DataFrame | Exception]):
        self.served = served
        self.requests: list[tuple[str, str, str | None]] = []
        monkeypatch.setattr(bars, "fetch_bars", self._fetch)

    def _fetch(self, _session, symbol, *, interval="5m", lookback=None):
        self.requests.append((symbol, interval, lookback))
        answer = self.served[symbol]
        if isinstance(answer, Exception):
            raise answer
        return BarSnapshot(symbol, interval, answer, "f" * 64)


AFTER_CLOSE = datetime(2026, 10, 23, 22, 0, tzinfo=UTC)


class TestFlexUnderlyings:
    def test_keeps_underlyings_with_enough_distinct_dates(self):
        panel = _panel({("equity", "AAL"): 45, ("equity", "AAPL"): 39, ("equity", "ZZZ"): 40})
        assert flex_underlyings(panel) == ["AAL", "ZZZ"]

    def test_threshold_is_inclusive_and_adjustable(self):
        panel = _panel({("equity", "AAL"): 10})
        assert flex_underlyings(panel, min_dates=10) == ["AAL"]
        assert flex_underlyings(panel, min_dates=11) == []

    def test_index_underlyings_are_out_of_scope(self):
        panel = _panel({("equity", "AAL"): 50, ("index", "SPX"): 50, ("index", "AAL"): 50})
        assert flex_underlyings(panel) == ["AAL"]

    def test_counts_dates_not_series_rows(self):
        """A name with thousands of series on three dates is still three dates."""
        dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
        panel = pd.DataFrame(
            {
                "kind": "equity",
                "underlying": "AAL",
                "report_date": list(dates) * 100,
            }
        )
        assert flex_underlyings(panel, min_dates=4) == []
        assert flex_underlyings(panel, min_dates=3) == ["AAL"]

    def test_a_panel_without_the_needed_columns_is_rejected(self):
        with pytest.raises(ValueError, match="report_date"):
            flex_underlyings(pd.DataFrame({"kind": ["equity"], "underlying": ["AAL"]}))


class TestHistoryLookback:
    def test_history_starts_forty_sessions_before_the_first_activity_date(self):
        panel = _panel({("equity", "AAL"): 45, ("index", "SPX"): 45})
        assert HISTORY_SESSIONS == 40
        assert history_start(panel) == pd.Timestamp("2024-11-07")

    def test_sessions_are_counted_as_weekdays(self):
        """1 January is a holiday but a weekday; counting it only reaches further back."""
        panel = _panel({("equity", "AAL"): 5})
        assert history_start(panel, sessions=1) == pd.Timestamp("2025-01-01")

    def test_an_empty_panel_has_no_history_to_reach(self):
        with pytest.raises(ValueError, match="empty"):
            history_start(_panel({("equity", "AAL"): 0}))

    def test_lookback_counts_calendar_days_to_the_new_york_date(self):
        """Yahoo reads an `Nd` range on daily bars as N sessions; a calendar-day count is
        the larger number, so it reaches the start under either reading."""
        assert lookback_since(pd.Timestamp("2024-11-07"), AFTER_CLOSE) == "715d"
        # 02:00 UTC on the 24th is still the 23rd in New York.
        late = datetime(2026, 10, 24, 2, 0, tzinfo=UTC)
        assert lookback_since(pd.Timestamp("2024-11-07"), late) == "715d"

    def test_lookback_is_at_least_one_day(self):
        assert lookback_since(pd.Timestamp("2026-10-23"), AFTER_CLOSE) == "1d"


class TestSettledDailyBars:
    FRAME = _bars("AAL", ["2026-10-21", "2026-10-22", "2026-10-23"])

    def test_drops_a_session_still_in_progress(self):
        """Used as a next-day outcome, a half-finished session reads as a quiet day."""
        morning = datetime(2026, 10, 23, 13, 35, tzinfo=UTC)  # 09:35 in New York
        kept = settled_daily_bars(self.FRAME, morning)
        assert list(kept["timestamp"].dt.date) == [date(2026, 10, 21), date(2026, 10, 22)]

    def test_keeps_the_session_once_it_has_closed(self):
        kept = settled_daily_bars(self.FRAME, AFTER_CLOSE)
        assert len(kept) == 3

    def test_keeps_everything_before_today(self):
        weekend = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)
        assert len(settled_daily_bars(self.FRAME, weekend)) == 3

    def test_the_session_date_is_the_new_york_date_not_the_utc_one(self):
        # 03:00 UTC on the 24th is 23:00 on the 23rd in New York: the 23rd has closed.
        late = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)
        assert len(settled_daily_bars(self.FRAME, late)) == 3


class TestRefresh:
    PANEL = _panel({("equity", "AAL"): 45, ("equity", "AAPL"): 45, ("equity", "FEW"): 5})

    def _refresh(self, out, **kwargs):
        return refresh_flex_underlying_bars(self.PANEL, out, session="s", now=AFTER_CLOSE, **kwargs)

    def test_fetches_daily_bars_for_each_qualifying_underlying_only(self, tmp_path, monkeypatch):
        yahoo = FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )
        self._refresh(tmp_path / "bars.parquet")
        assert [request[:2] for request in sorted(yahoo.requests)] == [
            ("AAL", "1d"),
            ("AAPL", "1d"),
        ]

    def test_default_lookback_reaches_the_history_the_panel_needs(self, tmp_path, monkeypatch):
        """The panel starts 2025-01-02, so the bars must start forty sessions earlier."""
        yahoo = FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )
        summary = self._refresh(tmp_path / "bars.parquet")
        assert summary.history_start == pd.Timestamp("2024-11-07")
        assert {lookback for *_, lookback in yahoo.requests} == {"715d"}

    def test_lookback_is_passed_through(self, tmp_path, monkeypatch):
        yahoo = FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )
        self._refresh(tmp_path / "bars.parquet", lookback="5y")
        assert {lookback for *_, lookback in yahoo.requests} == {"5y"}

    def test_returns_the_path_it_wrote_with_the_expected_columns(self, tmp_path, monkeypatch):
        FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )
        out = tmp_path / "bars.parquet"
        assert self._refresh(out).path == out
        written = pd.read_parquet(out)
        assert list(written.columns) == list(BAR_COLUMNS)
        assert str(written["timestamp"].dtype) == "datetime64[ms, UTC]"
        assert str(written["volume"].dtype) == "float64"
        assert written["symbol"].is_monotonic_increasing

    def test_a_symbol_the_provider_refuses_is_recorded_not_fatal(
        self, tmp_path, monkeypatch, caplog
    ):
        FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": FetchError("404 (resource absent)")},
        )
        out = tmp_path / "bars.parquet"
        with caplog.at_level(logging.WARNING):
            self._refresh(out)

        assert set(pd.read_parquet(out)["symbol"]) == {"AAL"}
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "AAPL" in message and "FetchError" in message

    def test_an_unparseable_answer_is_recorded_like_any_other_failure(
        self, tmp_path, monkeypatch, caplog
    ):
        FakeYahoo(
            monkeypatch,
            {"AAL": BarParseError("AAL: no bars"), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )
        with caplog.at_level(logging.WARNING):
            self._refresh(tmp_path / "bars.parquet")
        assert "AAL" in " ".join(r.getMessage() for r in caplog.records)

    def test_when_nothing_could_be_fetched_it_raises_and_leaves_the_file_alone(
        self, tmp_path, monkeypatch
    ):
        FakeYahoo(monkeypatch, {"AAL": FetchError("down"), "AAPL": FetchError("down")})
        out = tmp_path / "bars.parquet"
        _bars("AAL", ["2026-08-18"]).to_parquet(out, index=False)
        before = out.read_bytes()

        with pytest.raises(RuntimeError, match="no symbol"):
            self._refresh(out)
        assert out.read_bytes() == before

    def test_a_panel_with_no_qualifying_underlying_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="underlying"):
            refresh_flex_underlying_bars(
                _panel({("equity", "FEW"): 5}), tmp_path / "bars.parquet", session="s"
            )

    def test_replaces_a_refreshed_symbols_rows_wholesale(self, tmp_path, monkeypatch):
        """After a split the provider restates the whole history. Splicing new rows onto
        old ones would put a price jump in the series that is not a return."""
        out = tmp_path / "bars.parquet"
        _bars("AAL", ["2026-08-17", "2026-08-18"], close=100.0).to_parquet(out, index=False)
        FakeYahoo(
            monkeypatch,
            {
                "AAL": _bars("AAL", ["2026-08-18", "2026-10-22"], close=50.0),
                "AAPL": _bars("AAPL", ["2026-10-22"]),
            },
        )
        summary = self._refresh(out)

        aal = pd.read_parquet(out).query("symbol == 'AAL'")
        assert list(aal["timestamp"].dt.strftime("%Y-%m-%d")) == ["2026-08-18", "2026-10-22"]
        assert set(aal["close"]) == {50.0}
        # The 08-17 row predates the fetched window and is lost, so it is reported.
        assert dict(summary.discarded_history) == {"AAL": 1}
        assert dict(summary.kept_history) == {}

    def test_a_stub_keeps_the_held_history_before_it(self, tmp_path, monkeypatch):
        """A delisted name can come back as one bar. The held history before it cannot be
        fetched again, and where the overlapping close agrees it is the same series."""
        out = tmp_path / "bars.parquet"
        _bars("AAL", ["2026-08-13", "2026-08-14", "2026-08-17"]).to_parquet(out, index=False)
        stub = _bars("AAL", ["2026-08-17"]).assign(
            timestamp=pd.Timestamp("2026-08-17 20:00:03", tz="UTC")
        )
        FakeYahoo(monkeypatch, {"AAL": stub, "AAPL": _bars("AAPL", ["2026-10-22"])})
        summary = self._refresh(out)

        aal = pd.read_parquet(out).query("symbol == 'AAL'")
        assert list(aal["timestamp"].dt.strftime("%Y-%m-%d %H:%M")) == [
            "2026-08-13 13:30",
            "2026-08-14 13:30",
            "2026-08-17 20:00",  # the overlapping session comes from the fetch
        ]
        assert dict(summary.kept_history) == {"AAL": 2}
        assert dict(summary.discarded_history) == {}

    def test_a_small_restatement_still_counts_as_the_same_series(self, tmp_path, monkeypatch):
        out = tmp_path / "bars.parquet"
        _bars("AAL", ["2026-08-14", "2026-08-17"], close=100.0).to_parquet(out, index=False)
        FakeYahoo(
            monkeypatch,
            {
                "AAL": _bars("AAL", ["2026-08-17", "2026-10-22"], close=100.2),
                "AAPL": _bars("AAPL", ["2026-10-22"]),
            },
        )
        summary = self._refresh(out)
        assert dict(summary.kept_history) == {"AAL": 1}

    def test_held_history_with_no_overlap_to_check_is_discarded_and_named(
        self, tmp_path, monkeypatch, caplog
    ):
        """Without a shared session there is no way to rule out a split in the gap."""
        out = tmp_path / "bars.parquet"
        _bars("AAL", ["2026-08-13", "2026-08-14"]).to_parquet(out, index=False)
        FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )
        with caplog.at_level(logging.WARNING):
            summary = self._refresh(out)

        assert set(pd.read_parquet(out).query("symbol == 'AAL'")["timestamp"].dt.month) == {10}
        assert dict(summary.discarded_history) == {"AAL": 2}
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "AAL" in message and "discarded" in message

    def test_a_qualifying_symbol_that_failed_keeps_its_rows(self, tmp_path, monkeypatch):
        out = tmp_path / "bars.parquet"
        _bars("AAPL", ["2026-08-18"], close=1.0).to_parquet(out, index=False)
        FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": FetchError("404")},
        )
        self._refresh(out)

        written = pd.read_parquet(out)
        assert set(written["symbol"]) == {"AAL", "AAPL"}
        # AAPL failed, so its previous rows are the best data there is.
        assert list(written.query("symbol == 'AAPL'")["close"]) == [1.0]

    def test_symbols_outside_the_qualifying_set_are_dropped(self, tmp_path, monkeypatch):
        """A series nobody asks for any more (an index under an equity ticker, a name
        that fell below the date threshold) would otherwise sit in the file for good."""
        out = tmp_path / "bars.parquet"
        pd.concat([_bars("NDX", ["2026-08-14"]), _bars("FEW", ["2026-08-14"])]).to_parquet(
            out, index=False
        )
        FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )
        summary = self._refresh(out)

        assert set(pd.read_parquet(out)["symbol"]) == {"AAL", "AAPL"}
        assert summary.dropped == ("FEW", "NDX")

    def test_the_summary_names_each_failed_symbol_and_why(self, tmp_path, monkeypatch):
        FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": FetchError("404 (resource absent)")},
        )
        summary = self._refresh(tmp_path / "bars.parquet")

        assert summary.requested == ("AAL", "AAPL")
        assert summary.refreshed == ("AAL",)
        assert dict(summary.failed) == {"AAPL": "FetchError: 404 (resource absent)"}
        assert summary.rows == 1
        assert "1 of 2" in summary.describe()

    def test_warns_when_fetched_history_starts_after_the_needed_session(
        self, tmp_path, monkeypatch, caplog
    ):
        FakeYahoo(
            monkeypatch,
            {
                "AAL": _bars("AAL", ["2024-11-07", "2026-10-22"]),
                "AAPL": _bars("AAPL", ["2025-06-02", "2026-10-22"]),
            },
        )
        with caplog.at_level(logging.WARNING):
            summary = self._refresh(tmp_path / "bars.parquet")

        assert summary.late_starts == ("AAPL",)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "AAPL" in message and "2024-11-07" in message

    def test_no_warning_when_every_history_reaches_back_far_enough(
        self, tmp_path, monkeypatch, caplog
    ):
        FakeYahoo(
            monkeypatch,
            {
                "AAL": _bars("AAL", ["2024-11-07", "2026-10-22"]),
                "AAPL": _bars("AAPL", ["2024-11-01", "2026-10-22"]),
            },
        )
        with caplog.at_level(logging.WARNING):
            summary = self._refresh(tmp_path / "bars.parquet")
        assert summary.late_starts == ()
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_never_stores_the_session_in_progress(self, tmp_path, monkeypatch):
        FakeYahoo(
            monkeypatch,
            {
                "AAL": _bars("AAL", ["2026-10-22", "2026-10-23"]),
                "AAPL": _bars("AAPL", ["2026-10-22", "2026-10-23"]),
            },
        )
        out = tmp_path / "bars.parquet"
        morning = datetime(2026, 10, 23, 13, 35, tzinfo=UTC)
        refresh_flex_underlying_bars(self.PANEL, out, session="s", now=morning)
        assert set(pd.read_parquet(out)["timestamp"].dt.strftime("%Y-%m-%d")) == {"2026-10-22"}

    def test_a_failed_write_keeps_the_previous_file(self, tmp_path, monkeypatch):
        out = tmp_path / "bars.parquet"
        _bars("OLD", ["2026-08-18"]).to_parquet(out, index=False)
        before = out.read_bytes()
        FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )

        def dies_midway(self, path, *args, **kwargs):
            open(path, "wb").close()
            raise OSError("disk full")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", dies_midway)
        with pytest.raises(OSError, match="disk full"):
            self._refresh(out)
        assert out.read_bytes() == before
        assert [p.name for p in tmp_path.iterdir()] == ["bars.parquet"]

    def test_an_existing_file_with_other_columns_is_not_overwritten(self, tmp_path, monkeypatch):
        out = tmp_path / "bars.parquet"
        pd.DataFrame({"symbol": ["OLD"], "px": [1.0]}).to_parquet(out, index=False)
        FakeYahoo(
            monkeypatch,
            {"AAL": _bars("AAL", ["2026-10-22"]), "AAPL": _bars("AAPL", ["2026-10-22"])},
        )
        with pytest.raises(ValueError, match="columns"):
            self._refresh(out)
