"""Result `hidden_share`: how much of each underlying's option market is FLEX (M2).

Two universes, as the design sets them.

* The census: OCC's series search for every optionable symbol with listed weeklies,
  captured once. It gives the distribution across hundreds of underlyings on one date.
* The daily universe: the symbols the collector follows, on every settlement a daily
  capture shows. The series-search captures cover the equity and ETF names; the three
  index products, which the collector does not search, come from the Cboe chain. A
  headline count is a count of underlyings whose share clears a threshold on every one
  of these dates, among those observed on all.

Around the shares sit the checks that make them usable: the settlement each capture
shows, the FLEX open interest of the search against the FLEX report's, adjusted
deliverables kept apart, what leaving out expiring series does where the full book is
known, and the FLEX share of option value where listed quotes exist.
`hidden_share_macros` formats what the paper and README print.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.config import (
    ACCEPT_CI_RUNS_ENV,
    CI_CAPTURES_DIR,
    LOCAL_ONLY_ENV,
    PANEL_END,
    RAW_DIR,
    load_universe,
)
from hidden_options.measure.flex_panel import panel_through
from hidden_options.measure.hidden_share import (
    LISTED_INDEX_ROOTS,
    hidden_share,
    reconcile_flex_sources,
    stable_symbols,
)
from hidden_options.measure.hidden_share_checks import (
    adjusted_summary,
    coverage,
    expiry_check,
    index_full_book,
    reconciliation_summary,
    records,
)
from hidden_options.measure.hidden_share_data import (
    CaptureDate,
    chain_open_interest,
    check_ci_runs,
    ci_roots,
    date_capture,
    date_captures,
    expiring_series,
    index_rows,
    load_captures,
    load_census,
    load_chains,
    load_reports,
    priced_chains,
    switch_on,
    trading_calendar,
)
from hidden_options.measure.hidden_share_macros import hidden_share_macros
from hidden_options.measure.hidden_share_value import value_summary
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import RESULTS_DIR, Result, now_iso

NAME = "hidden_share"
THRESHOLDS = (0.10, 0.25, 0.50)
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
LARGEST = 5
PROGRAMME, CONTROL = "programme", "control"


@dataclass(frozen=True)
class HiddenInputs:
    """Everything the result is computed from, as the loaders return it.

    `universe` maps each followed symbol (no `_` prefix) to its group: `programme` for
    the underlyings chosen for the option-income programmes on them, `control` for the
    liquid names chosen as controls. `ci_runs` names the CI captures read beside the
    local ones, by run date; `local_only` marks inputs read without them.
    """

    census: pd.DataFrame
    captures: pd.DataFrame
    chains: pd.DataFrame
    reports: pd.DataFrame
    universe: Mapping[str, str]
    ci_runs: Sequence[str] = ()
    local_only: bool = False


@dataclass(frozen=True)
class CensusView:
    """The census on the settlement it shows, with the index products beside it."""

    dated: CaptureDate
    share: pd.DataFrame
    indices: pd.DataFrame

    @property
    def ordinary(self) -> pd.DataFrame:
        return self.share[~self.share["adjusted"]]


def census_view(inputs: HiddenInputs, chain_oi: pd.DataFrame | None = None) -> CensusView:
    """Date the census by its listed side and compute its shares, indices included."""
    chain_oi = chain_open_interest(inputs.chains) if chain_oi is None else chain_oi
    dated = date_capture(inputs.census, chain_oi)
    share = hidden_share(inputs.census.assign(date=dated.date))
    indices = _index_share(chain_oi, inputs.reports, pd.DatetimeIndex([dated.date]))
    return CensusView(dated, share, indices)


def freeze(inputs: HiddenInputs, end: pd.Timestamp) -> HiddenInputs:
    """`inputs` with the reports and the chain readings of settlements after `end` left out.

    The series-search captures are cut where they are dated (`date_captures`).
    """
    chains = inputs.chains[inputs.chains["oi_date"] <= end]
    return replace(inputs, chains=chains, reports=panel_through(inputs.reports, end))


def hidden_share_result(inputs: HiddenInputs) -> Result:
    """The `hidden_share` result from loaded inputs, up to the frozen PANEL_END.

    The listed side of every settlement up to the panel end comes from the chains read
    after it, which may be a later day's; a chain's own settlement is its `oi_date`.
    """
    end = pd.Timestamp(PANEL_END)
    # A capture is dated against every chain reading, so a later settlement is known as such.
    daily_rows, log = date_captures(inputs.captures, chain_open_interest(inputs.chains), end)
    inputs = freeze(inputs, end)
    chain_oi = chain_open_interest(inputs.chains)
    census = census_view(inputs, chain_oi)
    dates = pd.DatetimeIndex(sorted(daily_rows["date"].unique()))
    calendar = pd.DatetimeIndex(sorted(inputs.reports["report_date"].unique()))
    span = calendar[(calendar >= dates[0]) & (calendar <= dates[-1])]

    search = hidden_share(daily_rows)
    indices = _index_share(chain_oi, inputs.reports, dates)
    whole = _index_share(chain_oi, inputs.reports, dates, expiring_series(inputs.chains))
    daily = pd.concat([search[~search["adjusted"]], indices], ignore_index=True)
    daily = daily[daily["symbol"].isin(set(inputs.universe))]

    equity = inputs.reports[inputs.reports["kind"] == "equity"]
    values: dict[str, Any] = {
        "census": _census(census, inputs.census, equity),
        "census_indices": records(census.indices),
        "daily": _daily(daily, dates, log, inputs.universe, span),
        "reconciliation": {
            "census": reconciliation_summary(reconcile_flex_sources(census.share, equity)),
            "daily": reconciliation_summary(reconcile_flex_sources(search, equity)),
        },
        "adjusted": adjusted_summary(census.share, search),
        "expiry_check": expiry_check(daily_rows, search),
        "index_full_book": index_full_book(whole[whole["symbol"].isin(set(inputs.universe))]),
        "value": value_summary(
            priced_chains(inputs.chains), inputs.reports, dates, inputs.universe
        ),
    }
    run_inputs = {
        "sources": {
            "census": "data/raw/occ_census",
            "daily": "data/raw/occ_open_interest, data/ci_captures/*/raw/occ_open_interest",
            "chains": "data/raw/cboe_chain, data/ci_captures/*/raw/cboe_chain",
            "flex": "data/raw/occ_flex",
        },
        "ci_runs": list(inputs.ci_runs),
        "local_only": inputs.local_only,
        "panel_end": formats.iso_date(end),
        "census_rows": len(inputs.census),
        "capture_rows": int(log["rows"].sum()),
        "chain_rows": len(inputs.chains),
        "report_rows": len(inputs.reports),
        "universe": dict(sorted(inputs.universe.items())),
    }
    return Result(NAME, values, hidden_share_macros(values), run_inputs, now_iso())


@ANALYSES.register(NAME)
def hidden_share_analysis() -> Result:
    """M2 on the census, the daily captures and the chains on disk, up to PANEL_END."""
    return hidden_share_result(load_inputs())


def load_inputs(
    raw: Path | None = None,
    ci: Path | None = None,
    *,
    local_only: bool | None = None,
    accept_ci_runs: bool | None = None,
) -> HiddenInputs:
    """Read every input from `raw` (RAW_DIR by default) and the CI captures under `ci`
    (CI_CAPTURES_DIR by default), the FLEX report from the first chain settlement to
    PANEL_END.

    The census and the FLEX report are local only. Series-search captures and chains
    are read from the local root first and then from each CI run. The CI runs must be
    there and must be the runs the committed result was computed with, or the daily
    numbers would change quietly; either raises CICapturesError. `local_only` skips the
    CI captures and marks the inputs; `accept_ci_runs` accepts a different set of runs.
    Left as None, each is read from its environment variable (LOCAL_ONLY_ENV,
    ACCEPT_CI_RUNS_ENV), which `hidden-options results` sets from its flags.
    """
    raw = RAW_DIR if raw is None else raw
    local_only = switch_on(LOCAL_ONLY_ENV) if local_only is None else local_only
    accept = switch_on(ACCEPT_CI_RUNS_ENV) if accept_ci_runs is None else accept_ci_runs
    runs = [] if local_only else ci_roots(CI_CAPTURES_DIR if ci is None else ci)
    if not local_only and not accept:
        check_ci_runs([run.parent.name for run in runs], NAME, RESULTS_DIR)
    roots = [raw, *runs]
    end = pd.Timestamp(PANEL_END)
    calendar = trading_calendar(raw, end)
    chains = load_chains(roots, calendar)
    universe = load_universe()
    groups = {
        **{s: PROGRAMME for s in (*universe.treated_single_name, *universe.treated_index_and_etf)},
        **{s: CONTROL for s in universe.control_single_name},
    }
    return HiddenInputs(
        census=load_census(raw),
        captures=load_captures(roots),
        chains=chains,
        reports=load_reports(raw, pd.Timestamp(chains["oi_date"].min()), end),
        universe={symbol.lstrip("_"): group for symbol, group in groups.items()},
        ci_runs=[run.parent.name for run in runs],
        local_only=local_only,
    )


def _index_share(
    chain_oi: pd.DataFrame,
    reports: pd.DataFrame,
    dates: pd.DatetimeIndex,
    expiring: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """The index products' shares on `dates`, the listed side from the chain.

    With `expiring`, the series expiring on each date count too (see `index_rows`).
    """
    on_dates = chain_oi[chain_oi["date"].isin(dates)]
    if expiring is not None:
        expiring = expiring[expiring["date"].isin(dates)]
    return hidden_share(index_rows(on_dates, _on(reports, dates), expiring))


def _on(reports: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return reports[reports["report_date"].isin(dates)]


def _census(view: CensusView, raw: pd.DataFrame, equity: pd.DataFrame) -> dict[str, Any]:
    """The census distribution over ordinary underlyings; adjusted classes go elsewhere."""
    ordinary = view.ordinary
    shares = ordinary["flex_share"]
    report = equity[equity["report_date"] == view.dated.date]
    in_census = report["underlying"].isin(set(view.share["symbol"]))
    top = ordinary.iloc[int(np.argmax(shares.to_numpy()))]
    flex, listed = int(ordinary["flex_oi"].sum()), int(ordinary["listed_oi"].sum())
    return {
        "date": formats.iso_date(view.dated.date),
        "support": view.dated.support,
        "compared": view.dated.compared,
        "symbols": int(raw["symbol"].nunique()),
        "underlyings": len(ordinary),
        "only_adjusted": sorted(set(raw["symbol"]) - set(ordinary["symbol"])),
        "with_flex": int((ordinary["flex_oi"] > 0).sum()),
        "quantiles": {_key(q): float(shares.quantile(q)) for q in QUANTILES},
        "mean": float(shares.mean()),
        "max": {"symbol": str(top["symbol"]), "share": float(top["flex_share"])},
        "at_least": {_key(t): int((shares >= t).sum()) for t in THRESHOLDS},
        "half_or_more": records(ordinary[shares >= 0.5].sort_values("flex_share", ascending=False)),
        "largest": records(ordinary.sort_values("flex_oi", ascending=False).head(LARGEST)),
        "flex_oi": flex,
        "listed_oi": listed,
        "aggregate_share": flex / (flex + listed),
        "report_flex_oi": int(report["open_interest"].sum()),
        "report_coverage": float(
            report.loc[in_census, "open_interest"].sum() / report["open_interest"].sum()
        ),
    }


def _daily(
    daily: pd.DataFrame,
    dates: pd.DatetimeIndex,
    log: pd.DataFrame,
    universe: Mapping[str, str],
    span: pd.DatetimeIndex,
) -> dict[str, Any]:
    """Shares on every settlement covered, and who clears each threshold on all of them."""
    seen = daily.groupby("symbol")["date"].nunique()
    complete = sorted(seen[seen == len(dates)].index)
    full = daily[daily["symbol"].isin(complete)]
    by_name = daily.groupby("symbol")["flex_share"].agg(["min", "median", "max"])
    search = daily[~daily["symbol"].isin(set(LISTED_INDEX_ROOTS.values()))]
    totals = search.groupby("date")[["flex_oi", "listed_oi"]].sum()
    aggregate = totals["flex_oi"] / totals.sum(axis=1)
    stable = {_key(t): stable_symbols(full, t) for t in THRESHOLDS}
    kept = log[log["dated"] & ~log["mixed"]]
    covered = coverage(log, span)
    return {
        "dates": len(dates),
        "first_date": formats.iso_date(dates[0]),
        "last_date": formats.iso_date(dates[-1]),
        "span": covered.pop("span"),
        "missing_dates": covered.pop("missing_dates"),
        "captures": len(log),
        "captures_by_root": covered.pop("captures_by_root"),
        "duplicate_captures": int(kept["duplicate"].sum()),
        "min_support": int(kept["support"].min()),
        "compared": int(kept["compared"].max()),
        "coverage": covered,
        "universe": len(universe),
        "universe_by_group": _by_group(sorted(universe), universe),
        "search_symbols": int(search["symbol"].nunique()),
        "not_in_search": sorted(set(universe) - set(search["symbol"])),
        "complete": len(complete),
        "complete_by_group": _by_group(complete, universe),
        "incomplete": {str(s): int(n) for s, n in seen[seen < len(dates)].items()},
        "missing": sorted(set(universe) - set(seen.index)),
        "stable": {
            key: {"count": len(names), "symbols": names, "by_group": _by_group(names, universe)}
            for key, names in stable.items()
        },
        "median_of_medians": float(by_name.loc[complete, "median"].median()),
        "aggregate": {"min": float(aggregate.min()), "max": float(aggregate.max())},
        "names": {
            str(symbol): {
                "min": float(row["min"]),
                "median": float(row["median"]),
                "max": float(row["max"]),
                "dates": int(seen.loc[str(symbol)]),
            }
            for symbol, row in by_name.sort_values("median", ascending=False).iterrows()
        },
    }


def _by_group(names: Sequence[str], universe: Mapping[str, str]) -> dict[str, int]:
    groups = [universe[name] for name in names]
    return {group: groups.count(group) for group in (PROGRAMME, CONTROL)}


def _key(fraction: float) -> str:
    """`0.25` -> `"25"`: thresholds and quantiles keyed by their percentage."""
    return str(round(fraction * 100))
