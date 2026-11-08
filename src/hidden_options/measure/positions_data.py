"""Inputs to the `positions` result: reports read a date at a time, spots and holdings.

Spots follow `implied_data`: an equity's is its close from the bars, an index's its level
in the chain read after the close, a mini product's a fixed fraction of that. The bars go
back past the panel's start and the chains only to August 2026, so index series have no
spot, and so no delta, before then. Fund holdings are read from the local collector and
any CI run that carries them.
"""

from __future__ import annotations

import glob
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from hidden_options.collect.splits import read_bars
from hidden_options.config import (
    ACCEPT_CI_RUNS_ENV,
    BARS_PATH,
    CI_CAPTURES_DIR,
    LOCAL_ONLY_ENV,
    PANEL_END,
    RAW_DIR,
)
from hidden_options.measure.hidden_share_data import (
    check_ci_runs,
    ci_roots,
    load_chains,
    switch_on,
    trading_calendar,
)
from hidden_options.measure.holdings_truth import load_fund_holdings, load_globalx_options
from hidden_options.measure.implied_data import (
    BAR_COLUMNS,
    PANEL_READ_COLUMNS,
    READING_COLUMNS,
    close_readings,
    earliest_readings,
    equity_closes,
    read_panel,
    spot_table,
)
from hidden_options.publish.results import RESULTS_DIR, read_results

RESULT_NAME = "positions"
DOMAIN_RESULT = "implied_validation"
_INDEX_CHAINS = "index_*.parquet"


@dataclass(frozen=True)
class PositionsInputs:
    """What the result is computed from.

    `read_day` gives the FLEX rows of one report date with their exercise style, so the
    panel is never held whole. `domain` is the validated (moneyness, days to expiry) cells
    of the `implied_validation` result. `ci_runs` names the CI captures read beside the
    local ones; `local_only` marks inputs read without them.
    """

    dates: Sequence[pd.Timestamp]
    read_day: Callable[[pd.Timestamp], pd.DataFrame]
    spots: pd.DataFrame
    holdings: pd.DataFrame
    globalx: pd.DataFrame
    domain: frozenset[tuple[str, str]]
    ci_runs: Sequence[str] = ()
    local_only: bool = False


def load_inputs(
    raw: Path | None = None,
    ci: Path | None = None,
    bars_path: Path | None = None,
    results: Path | None = None,
    *,
    local_only: bool | None = None,
    accept_ci_runs: bool | None = None,
) -> PositionsInputs:
    """Everything on disk up to PANEL_END; CI runs are guarded as `implied_data` guards them."""
    raw = RAW_DIR if raw is None else raw
    results = RESULTS_DIR if results is None else results
    local_only = switch_on(LOCAL_ONLY_ENV) if local_only is None else local_only
    accept = switch_on(ACCEPT_CI_RUNS_ENV) if accept_ci_runs is None else accept_ci_runs
    runs = [] if local_only else ci_roots(CI_CAPTURES_DIR if ci is None else ci)
    names = [run.parent.name for run in runs]
    if not local_only and not accept:
        check_ci_runs(names, RESULT_NAME, results)
    end = pd.Timestamp(PANEL_END)
    bars = read_bars(BARS_PATH if bars_path is None else bars_path, BAR_COLUMNS)
    closes = equity_closes(bars)
    readings = earliest_readings(
        load_chains(
            [raw, *runs],
            trading_calendar(raw, end),
            extra=("iv",),
            keep=_file_readings,
            pattern=_INDEX_CHAINS,
        )
    )
    spots = spot_table(readings[readings["date"] <= end], closes[closes["date"] <= end])
    return PositionsInputs(
        dates=_report_dates(raw, end),
        read_day=lambda day: read_panel(raw, ("equity", "index"), PANEL_READ_COLUMNS, day, day),
        spots=spots,
        holdings=load_fund_holdings([raw, *runs]),
        globalx=load_globalx_options(raw),
        domain=load_domain(results),
        ci_runs=names,
        local_only=local_only,
    )


def load_domain(results: Path) -> frozenset[tuple[str, str]]:
    """The validated cells the `implied_validation` result holds."""
    stored = read_results(results).get(DOMAIN_RESULT)
    if stored is None:
        raise FileNotFoundError(f"No results/{DOMAIN_RESULT}.json under {results}")
    return frozenset((str(m), str(d)) for m, d in stored.values["domain"]["buckets"])


def _file_readings(chain: pd.DataFrame) -> pd.DataFrame:
    kept: pd.DataFrame = close_readings(chain)[list(READING_COLUMNS)]
    return kept


def _report_dates(raw: Path, end: pd.Timestamp) -> list[pd.Timestamp]:
    folders = glob.glob(str(raw / "occ_flex/date=*"))
    days = sorted(pd.Timestamp(folder.split("date=")[1][:10]) for folder in folders)
    return [day for day in days if day <= end]


__all__ = ["DOMAIN_RESULT", "RESULT_NAME", "PositionsInputs", "load_domain", "load_inputs"]
