"""CLI tests.

Exit codes are the contract with the scheduler: 0 means a usable capture happened,
non-zero means a human should look. Getting that backwards would either hide a dead
collector or generate noise every time one symbol hiccups.
"""

from __future__ import annotations

import json

import pytest

from absorb import cli
from absorb.collect.runner import SymbolOutcome


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
        assert cli.main(["--root", str(tmp_path)]) == 0

    def test_partial_failure_still_returns_zero(self, stub_run, tmp_path):
        """A run that captured most symbols is a good run; the manifest records gaps."""
        stub_run(
            (
                SymbolOutcome("cboe_chain", "MSTR", "ok", rows=10),
                SymbolOutcome("cboe_chain", "NVDA", "error", detail="FetchError: 503"),
            )
        )
        assert cli.main(["--root", str(tmp_path)]) == 0

    def test_total_failure_returns_one(self, stub_run, tmp_path):
        stub_run((SymbolOutcome("cboe_chain", "MSTR", "error", detail="down"),))
        assert cli.main(["--root", str(tmp_path)]) == 1

    def test_bad_universe_path_returns_two(self, tmp_path):
        code = cli.main(["--universe", str(tmp_path / "missing.json"), "--root", str(tmp_path)])
        assert code == 2

    def test_malformed_config_returns_two(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{")
        assert cli.main(["--universe", str(bad), "--root", str(tmp_path)]) == 2


class TestArgumentHandling:
    def test_defaults_to_all_three_sources(self, stub_run, tmp_path):
        captured = stub_run((SymbolOutcome("cboe_chain", "MSTR", "ok", rows=1),))
        cli.main(["--root", str(tmp_path)])
        assert captured["sources"] == ("holdings", "cboe", "occ")

    def test_source_subset_is_honoured(self, stub_run, tmp_path):
        captured = stub_run((SymbolOutcome("occ_oi", "MSTR", "ok", rows=1),))
        cli.main(["--root", str(tmp_path), "--sources", "occ"])
        assert captured["sources"] == ("occ",)

    def test_programmes_not_loaded_when_holdings_disabled(self, stub_run, tmp_path):
        """Avoids failing a chain-only run because the fund registry is absent."""
        captured = stub_run((SymbolOutcome("cboe_chain", "MSTR", "ok", rows=1),))
        cli.main(["--root", str(tmp_path), "--sources", "cboe"])
        assert captured["programmes"] == ()

    def test_programmes_loaded_when_holdings_enabled(self, stub_run, tmp_path):
        captured = stub_run((SymbolOutcome("fund_holdings", "MSTY", "ok", rows=1),))
        cli.main(["--root", str(tmp_path), "--sources", "holdings"])
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
        cli.main(["--root", str(tmp_path), "--sources", "holdings", "--funds", str(registry)])
        assert [p.fund for p in captured["programmes"]] == ["AAA"]

    def test_verbose_flag_is_accepted(self, stub_run, tmp_path):
        stub_run((SymbolOutcome("cboe_chain", "MSTR", "ok", rows=1),))
        assert cli.main(["--root", str(tmp_path), "--verbose"]) == 0
