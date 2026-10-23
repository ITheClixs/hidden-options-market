"""Naming tests.

The project was renamed from its working title to match the paper. A stale name left in
a tracked file points readers at an import path or command that no longer exists, so
the check is a plain case-insensitive search of everything git tracks.
"""

from __future__ import annotations

import subprocess

import pytest

from hidden_options import cli
from hidden_options.collect.runner import SymbolOutcome

# The alias entry point lives in pyproject.toml; docs/ holds historical write-ups.
ALLOWED = ("pyproject.toml", "docs/")
OLD_NAME = "absorb"


def test_no_stale_project_name_in_tracked_files():
    hits = subprocess.run(
        ["git", "grep", "-nIi", OLD_NAME, "--", ".", ":!tests/test_naming.py"],
        capture_output=True,
        text=True,
    ).stdout
    offenders = [line for line in hits.splitlines() if not line.startswith(ALLOWED)]
    assert offenders == []


def test_alias_delegates_to_collect_subcommand(monkeypatch):
    calls: list[list[str] | None] = []

    def fake_main(argv=None):
        calls.append(argv)
        return 7

    monkeypatch.setattr(cli, "main", fake_main)
    assert cli.collect_alias(["--sources", "x"]) == 7
    assert calls == [["collect", "--sources", "x"]]


def test_alias_matches_subcommand_exit_code(monkeypatch, tmp_path):
    """Both entry points must give the scheduler the same exit code for the same run."""

    def fake(universe, programmes=(), *, root=None, as_of=None, sources=(), **kwargs):
        return (SymbolOutcome("cboe_chain", "MSTR", "ok", rows=1),)

    monkeypatch.setattr(cli, "run_daily_collection", fake)
    argv = ["--sources", "cboe", "--root", str(tmp_path)]
    assert cli.collect_alias(argv) == cli.main(["collect", *argv]) == 0


def test_main_requires_a_subcommand():
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
