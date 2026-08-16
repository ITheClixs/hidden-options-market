"""Runner and config tests.

The behaviour that matters most is isolation: because the upstream endpoints are
snapshots with no history, one failing symbol must never cost the whole capture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from absorb.collect import cboe, runner
from absorb.collect.http import FetchError
from absorb.config import Universe, load_universe

AS_OF = datetime(2026, 8, 16, 21, 5, tzinfo=UTC)


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
