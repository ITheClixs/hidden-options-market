"""CLI tests.

Exit codes are the contract with the scheduler: 0 means a usable capture happened,
non-zero means a human should look. Getting that backwards would either hide a dead
collector or generate noise every time one symbol hiccups.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from hidden_options import cli
from hidden_options.collect.backfill import BackfillSummary
from hidden_options.collect.bars import BarsRefresh
from hidden_options.collect.lock import single_instance
from hidden_options.collect.runner import SymbolOutcome


@pytest.fixture
def stub_run(monkeypatch):
    """Replace the collection pass with a scripted set of outcomes."""
    captured: dict[str, object] = {}

    def _install(outcomes: tuple[SymbolOutcome, ...]):
        def fake(universe, programmes=(), *, root=None, as_of=None, sources=(), **kwargs):
            captured["universe"] = universe
            captured["programmes"] = programmes
            captured["sources"] = sources
            captured["root"] = root
            return outcomes

        monkeypatch.setattr(cli, "run_daily_collection", fake)
        return captured

    return _install


class TestExitCodes:
    def test_success_returns_zero(self, stub_run, tmp_path):
        stub_run((SymbolOutcome("cboe_chain", "MSTR", "ok", rows=10),))
        assert cli.main(["collect", "--root", str(tmp_path)]) == 0

    def test_partial_failure_still_returns_zero(self, stub_run, tmp_path):
        """A run that captured most symbols is a good run; the manifest records gaps."""
        stub_run(
            (
                SymbolOutcome("cboe_chain", "MSTR", "ok", rows=10),
                SymbolOutcome("cboe_chain", "NVDA", "error", detail="FetchError: 503"),
            )
        )
        assert cli.main(["collect", "--root", str(tmp_path)]) == 0

    def test_unpublished_reports_are_not_failures(self, stub_run, tmp_path, caplog):
        """FLEX for the day just ended is normally not out yet; that is not worth a warning."""
        stub_run(
            (
                SymbolOutcome("cboe_chain", "MSTR", "ok", rows=10),
                SymbolOutcome("flex", "equity:2026-08-14", "absent", detail="no report"),
            )
        )
        with caplog.at_level("INFO"):
            assert cli.main(["collect", "--root", str(tmp_path)]) == 0
        assert not [r for r in caplog.records if r.levelname == "WARNING"]

    def test_only_absent_reports_still_returns_one(self, stub_run, tmp_path):
        """Nothing captured is nothing captured, whatever the reason."""
        stub_run((SymbolOutcome("flex", "equity:2026-08-14", "absent"),))
        assert cli.main(["collect", "--root", str(tmp_path)]) == 1

    def test_total_failure_returns_one(self, stub_run, tmp_path):
        stub_run((SymbolOutcome("cboe_chain", "MSTR", "error", detail="down"),))
        assert cli.main(["collect", "--root", str(tmp_path)]) == 1

    def test_bad_universe_path_returns_two(self, tmp_path):
        code = cli.main(
            ["collect", "--universe", str(tmp_path / "missing.json"), "--root", str(tmp_path)]
        )
        assert code == 2

    def test_malformed_config_returns_two(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{")
        assert cli.main(["collect", "--universe", str(bad), "--root", str(tmp_path)]) == 2


class TestArgumentHandling:
    def test_defaults_to_every_source(self, stub_run, tmp_path):
        captured = stub_run((SymbolOutcome("cboe_chain", "MSTR", "ok", rows=1),))
        cli.main(["collect", "--root", str(tmp_path)])
        assert captured["sources"] == ("holdings", "cboe", "occ", "bars", "flex")

    def test_flex_alone_can_be_selected(self, stub_run, tmp_path):
        captured = stub_run((SymbolOutcome("flex", "equity:2026-08-14", "ok", rows=1),))
        cli.main(["collect", "--root", str(tmp_path), "--sources", "flex"])
        assert captured["sources"] == ("flex",)

    def test_flex_is_listed_in_the_help_text(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["collect", "--help"])
        assert "flex" in capsys.readouterr().out

    def test_source_subset_is_honoured(self, stub_run, tmp_path):
        captured = stub_run((SymbolOutcome("occ_oi", "MSTR", "ok", rows=1),))
        cli.main(["collect", "--root", str(tmp_path), "--sources", "occ"])
        assert captured["sources"] == ("occ",)

    def test_programmes_not_loaded_when_holdings_disabled(self, stub_run, tmp_path):
        """Avoids failing a chain-only run because the fund registry is absent."""
        captured = stub_run((SymbolOutcome("cboe_chain", "MSTR", "ok", rows=1),))
        cli.main(["collect", "--root", str(tmp_path), "--sources", "cboe"])
        assert captured["programmes"] == ()

    def test_programmes_loaded_when_holdings_enabled(self, stub_run, tmp_path):
        captured = stub_run((SymbolOutcome("fund_holdings", "MSTY", "ok", rows=1),))
        cli.main(["collect", "--root", str(tmp_path), "--sources", "holdings"])
        assert len(captured["programmes"]) > 10

    def test_custom_fund_registry_is_used(self, stub_run, tmp_path):
        registry = tmp_path / "funds.json"
        registry.write_text(
            json.dumps(
                {
                    "issuers": {
                        "test": {"url_template": "https://x/{ticker}", "funds": {"AAA": "BBB"}}
                    }
                }
            )
        )
        captured = stub_run((SymbolOutcome("fund_holdings", "AAA", "ok", rows=1),))
        cli.main(
            ["collect", "--root", str(tmp_path), "--sources", "holdings", "--funds", str(registry)]
        )
        assert [p.fund for p in captured["programmes"]] == ["AAA"]

    def test_verbose_flag_is_accepted(self, stub_run, tmp_path):
        stub_run((SymbolOutcome("cboe_chain", "MSTR", "ok", rows=1),))
        assert cli.main(["collect", "--root", str(tmp_path), "--verbose"]) == 0


@pytest.fixture
def stub_backfill(monkeypatch):
    """Replace the backfill walk with a scripted summary, recording how it was called."""
    calls: list[dict[str, object]] = []

    def _install(*outcomes: SymbolOutcome, skipped: int = 0):
        def fake(start, end, root, kinds, **kwargs):
            calls.append({"start": start, "end": end, "root": root, "kinds": kinds})
            return BackfillSummary(skipped=skipped, outcomes=tuple(outcomes))

        monkeypatch.setattr(cli, "backfill_flex", fake)
        return calls

    return _install


class TestBackfillFlex:
    def test_success_returns_zero_and_passes_the_span_through(self, stub_backfill, tmp_path):
        calls = stub_backfill(SymbolOutcome("flex", "equity:2026-08-14", "ok", rows=1))
        code = cli.main(
            [
                "backfill-flex",
                "--start",
                "2026-08-10",
                "--end",
                "2026-08-14",
                "--root",
                str(tmp_path),
            ]
        )
        assert code == 0
        assert calls == [
            {
                "start": date(2026, 8, 10),
                "end": date(2026, 8, 14),
                "root": tmp_path,
                "kinds": ("equity", "index"),
            }
        ]

    def test_end_defaults_to_today(self, stub_backfill, tmp_path):
        calls = stub_backfill()
        cli.main(["backfill-flex", "--start", "2026-08-10", "--root", str(tmp_path)])
        assert calls[0]["end"] == date.today()

    def test_kinds_can_be_restricted(self, stub_backfill, tmp_path):
        calls = stub_backfill()
        cli.main(
            ["backfill-flex", "--start", "2026-08-10", "--kinds", "equity", "--root", str(tmp_path)]
        )
        assert calls[0]["kinds"] == ("equity",)

    def test_start_is_required(self, stub_backfill, tmp_path):
        stub_backfill()
        with pytest.raises(SystemExit) as raised:
            cli.main(["backfill-flex", "--root", str(tmp_path)])
        assert raised.value.code == 2

    def test_a_malformed_date_is_a_usage_error(self, stub_backfill, tmp_path):
        stub_backfill()
        with pytest.raises(SystemExit) as raised:
            cli.main(["backfill-flex", "--start", "last tuesday", "--root", str(tmp_path)])
        assert raised.value.code == 2

    def test_nothing_new_to_fetch_is_still_success(self, stub_backfill, tmp_path):
        """Re-running a finished backfill saves nothing; that is the point of it."""
        stub_backfill(skipped=94)
        assert cli.main(["backfill-flex", "--start", "2026-08-10", "--root", str(tmp_path)]) == 0

    def test_unpublished_dates_are_not_failures(self, stub_backfill, tmp_path, caplog):
        stub_backfill(
            SymbolOutcome("flex", "equity:2026-08-14", "ok", rows=1),
            SymbolOutcome("flex", "equity:2026-08-17", "absent"),
        )
        with caplog.at_level("INFO"):
            assert (
                cli.main(["backfill-flex", "--start", "2026-08-10", "--root", str(tmp_path)]) == 0
            )
        assert not [r for r in caplog.records if r.levelname == "WARNING"]

    def test_any_failed_request_returns_one(self, stub_backfill, tmp_path):
        """A backfill that silently skipped dates would leave a hole nobody looks for."""
        stub_backfill(
            SymbolOutcome("flex", "equity:2026-08-14", "ok", rows=1),
            SymbolOutcome("flex", "equity:2026-08-13", "error", detail="FetchError: 503"),
        )
        assert cli.main(["backfill-flex", "--start", "2026-08-10", "--root", str(tmp_path)]) == 1

    def test_a_span_that_ends_before_it_starts_returns_two(self, tmp_path):
        code = cli.main(
            [
                "backfill-flex",
                "--start",
                "2026-08-14",
                "--end",
                "2026-08-10",
                "--root",
                str(tmp_path),
            ]
        )
        assert code == 2

    def test_declines_while_a_collector_holds_the_lock(self, stub_backfill, tmp_path):
        """The nightly collector and a backfill write the same partitions."""
        calls = stub_backfill()
        with single_instance(tmp_path / ".collector.lock"):
            code = cli.main(["backfill-flex", "--start", "2026-08-10", "--root", str(tmp_path)])
        assert code == 3
        assert calls == []


def _refresh_summary(out: Path, **overrides: object) -> BarsRefresh:
    fields: dict[str, object] = {
        "path": out,
        "requested": ("AAL", "AAPL", "BRKB"),
        "refreshed": ("AAL", "AAPL"),
        "failed": {"BRKB": "FetchError: 404 (resource absent)"},
        "dropped": ("NDX",),
        "history_start": pd.Timestamp("2024-10-07"),
        "late_starts": ("AAPL",),
        "rows": 1000,
    }
    fields.update(overrides)
    return BarsRefresh(**fields)  # type: ignore[arg-type]


@pytest.fixture
def stub_refresh(monkeypatch):
    """Replace the panel load and the bar refresh, recording how they were called."""
    calls: dict[str, object] = {}

    def _install(outcome: BarsRefresh | Exception | None = None, *, panel_error=None):
        def fake_load(root):
            calls["raw"] = root
            if panel_error is not None:
                raise panel_error
            return "panel"

        def fake_refresh(panel, out, **kwargs):
            calls["panel"] = panel
            calls["out"] = out
            if isinstance(outcome, Exception):
                raise outcome
            return outcome or _refresh_summary(out)

        monkeypatch.setattr(cli, "load_panel", fake_load)
        monkeypatch.setattr(cli, "refresh_flex_underlying_bars", fake_refresh)
        return calls

    return _install


class TestRefreshBars:
    def test_refreshes_from_the_panel_into_the_bars_file(self, stub_refresh, tmp_path, capsys):
        calls = stub_refresh()
        out = tmp_path / "bars.parquet"
        code = cli.main(["refresh-bars", "--raw", str(tmp_path / "raw"), "--out", str(out)])

        assert code == 0
        assert calls == {"raw": tmp_path / "raw", "panel": "panel", "out": out}
        printed = capsys.readouterr().out
        assert "2 of 3" in printed
        assert "BRKB" in printed and "404" in printed
        assert "NDX" in printed

    def test_defaults_to_the_data_directory(self, stub_refresh):
        calls = stub_refresh()
        assert cli.main(["refresh-bars"]) == 0
        assert calls["raw"] == cli.RAW_DIR
        assert calls["out"] == cli.BARS_PATH

    def test_nothing_refreshed_returns_one(self, stub_refresh, tmp_path, capsys):
        stub_refresh(RuntimeError("no symbol could be refreshed (3 failed)"))
        assert cli.main(["refresh-bars", "--out", str(tmp_path / "b.parquet")]) == 1
        assert "no symbol" in capsys.readouterr().err

    def test_no_panel_returns_two(self, stub_refresh, tmp_path, capsys):
        stub_refresh(panel_error=FileNotFoundError("no FLEX reports found under raw/occ_flex"))
        assert cli.main(["refresh-bars", "--out", str(tmp_path / "b.parquet")]) == 2
        assert "no FLEX reports" in capsys.readouterr().err

    def test_a_bars_file_of_another_shape_returns_two(self, stub_refresh, tmp_path):
        stub_refresh(ValueError("b.parquet has columns ['px'], expected [...]"))
        assert cli.main(["refresh-bars", "--out", str(tmp_path / "b.parquet")]) == 2
