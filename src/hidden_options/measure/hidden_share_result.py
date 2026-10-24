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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.config import RAW_DIR, load_universe
from hidden_options.measure.hidden_share import (
    LISTED_INDEX_ROOTS,
    flex_series,
    hidden_share,
    reconcile_flex_sources,
    stable_symbols,
    value_share,
)
from hidden_options.measure.hidden_share_data import (
    CaptureDate,
    chain_open_interest,
    date_capture,
    date_captures,
    index_rows,
    load_captures,
    load_census,
    load_chains,
    load_reports,
    priced_chains,
    trading_calendar,
)
from hidden_options.measure.hidden_share_macros import hidden_share_macros
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "hidden_share"
THRESHOLDS = (0.10, 0.25, 0.50)
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
LARGEST = 5
VALUE_LEADERS = 10
# A share moved by more than this when expiring series are left out is counted.
EXPIRY_MOVE = 0.01
PROGRAMME, CONTROL = "programme", "control"


@dataclass(frozen=True)
class HiddenInputs:
    """Everything the result is computed from, as the loaders return it.

    `universe` maps each followed symbol (no `_` prefix) to its group: `programme` for
    the underlyings chosen for the option-income programmes on them, `control` for the
    liquid names chosen as controls.
    """

    census: pd.DataFrame
    captures: pd.DataFrame
    chains: pd.DataFrame
    reports: pd.DataFrame
    universe: Mapping[str, str]


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


def hidden_share_result(inputs: HiddenInputs) -> Result:
    """The `hidden_share` result from loaded inputs."""
    chain_oi = chain_open_interest(inputs.chains)
    census = census_view(inputs, chain_oi)
    daily_rows, log = date_captures(inputs.captures, chain_oi)
    dates = pd.DatetimeIndex(sorted(daily_rows["date"].unique()))

    search = hidden_share(daily_rows)
    indices = _index_share(chain_oi, inputs.reports, dates)
    daily = pd.concat([search[~search["adjusted"]], indices], ignore_index=True)
    daily = daily[daily["symbol"].isin(set(inputs.universe))]

    equity = inputs.reports[inputs.reports["kind"] == "equity"]
    values: dict[str, Any] = {
        "census": _census(census, inputs.census, equity),
        "census_indices": _records(census.indices),
        "daily": _daily(daily, dates, log, inputs.universe),
        "reconciliation": {
            "census": _reconciliation(reconcile_flex_sources(census.share, equity)),
            "daily": _reconciliation(reconcile_flex_sources(search, equity)),
        },
        "adjusted": _adjusted(census.share, search),
        "expiry_check": _expiry_check(daily_rows, search),
        "value": _value(priced_chains(inputs.chains), inputs.reports, dates, inputs.universe),
    }
    run_inputs = {
        "sources": {
            "census": "data/raw/occ_census",
            "daily": "data/raw/occ_open_interest",
            "chains": "data/raw/cboe_chain",
            "flex": "data/raw/occ_flex",
        },
        "census_rows": len(inputs.census),
        "capture_rows": len(inputs.captures),
        "chain_rows": len(inputs.chains),
        "report_rows": len(inputs.reports),
        "universe": dict(sorted(inputs.universe.items())),
    }
    return Result(NAME, values, hidden_share_macros(values), run_inputs, now_iso())


@ANALYSES.register(NAME)
def hidden_share_analysis() -> Result:
    """M2 on the census, the daily captures and the chains on disk."""
    return hidden_share_result(load_inputs())


def load_inputs(raw: Path | None = None) -> HiddenInputs:
    """Read every input from `raw` (RAW_DIR by default), the FLEX report from the first
    chain settlement on."""
    raw = RAW_DIR if raw is None else raw
    calendar = trading_calendar(raw)
    chains = load_chains(raw, calendar)
    universe = load_universe()
    groups = {
        **{s: PROGRAMME for s in (*universe.treated_single_name, *universe.treated_index_and_etf)},
        **{s: CONTROL for s in universe.control_single_name},
    }
    return HiddenInputs(
        census=load_census(raw),
        captures=load_captures(raw),
        chains=chains,
        reports=load_reports(raw, pd.Timestamp(chains["oi_date"].min())),
        universe={symbol.lstrip("_"): group for symbol, group in groups.items()},
    )


def _index_share(
    chain_oi: pd.DataFrame, reports: pd.DataFrame, dates: pd.DatetimeIndex
) -> pd.DataFrame:
    """The index products' shares on `dates`, the listed side from the chain."""
    on_dates = chain_oi[chain_oi["date"].isin(dates)]
    return hidden_share(index_rows(on_dates, _on(reports, dates)))


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
        "half_or_more": _records(
            ordinary[shares >= 0.5].sort_values("flex_share", ascending=False)
        ),
        "largest": _records(ordinary.sort_values("flex_oi", ascending=False).head(LARGEST)),
        "flex_oi": flex,
        "listed_oi": listed,
        "aggregate_share": flex / (flex + listed),
        "report_flex_oi": int(report["open_interest"].sum()),
        "report_coverage": float(
            report.loc[in_census, "open_interest"].sum() / report["open_interest"].sum()
        ),
    }


def _daily(
    daily: pd.DataFrame, dates: pd.DatetimeIndex, log: pd.DataFrame, universe: Mapping[str, str]
) -> dict[str, Any]:
    """Shares on every settlement, and who clears each threshold on all of them."""
    seen = daily.groupby("symbol")["date"].nunique()
    complete = sorted(seen[seen == len(dates)].index)
    full = daily[daily["symbol"].isin(complete)]
    by_name = daily.groupby("symbol")["flex_share"].agg(["min", "median", "max"])
    search = daily[~daily["symbol"].isin(set(LISTED_INDEX_ROOTS.values()))]
    totals = search.groupby("date")[["flex_oi", "listed_oi"]].sum()
    aggregate = totals["flex_oi"] / totals.sum(axis=1)
    stable = {_key(t): stable_symbols(full, t) for t in THRESHOLDS}
    return {
        "dates": len(dates),
        "first_date": formats.iso_date(dates[0]),
        "last_date": formats.iso_date(dates[-1]),
        "captures": len(log),
        "duplicate_captures": int(log["duplicate"].sum()),
        "min_support": int(log["support"].min()),
        "compared": int(log["compared"].max()),
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


def _reconciliation(reconciled: pd.DataFrame) -> dict[str, Any]:
    """The two FLEX sources side by side, over every symbol-date where either has FLEX."""
    either = reconciled[(reconciled["flex_oi_search"] > 0) | (reconciled["flex_oi_report"] > 0)]
    return {
        "symbol_dates": len(either),
        "agreeing": int((either["rel_diff"] == 0).sum()),
        "median_rel_diff": float(either["rel_diff"].median()),
        "max_rel_diff": float(either["rel_diff"].max()),
        "flex_oi_search": int(either["flex_oi_search"].sum()),
        "flex_oi_report": int(either["flex_oi_report"].sum()),
    }


def _adjusted(census: pd.DataFrame, search: pd.DataFrame) -> dict[str, Any]:
    """Adjusted-deliverable classes: counted and listed, never folded into their parents."""
    on_census = census[census["adjusted"]]
    with_flex = on_census[on_census["flex_oi"] > 0].sort_values("flex_oi", ascending=False)
    daily = search[search["adjusted"] & (search["flex_oi"] > 0)]
    by_name = daily.groupby("symbol")["flex_share"].agg(["min", "max", "size"])
    return {
        "census": len(on_census),
        "census_with_flex": len(with_flex),
        "census_flex": _records(with_flex),
        "census_flex_oi": int(on_census["flex_oi"].sum()),
        "census_flex_share": float(on_census["flex_oi"].sum() / census["flex_oi"].sum()),
        "daily_with_flex": {
            str(s): {"min": float(r["min"]), "max": float(r["max"]), "dates": int(r["size"])}
            for s, r in by_name.iterrows()
        },
    }


def _expiry_check(daily_rows: pd.DataFrame, search: pd.DataFrame) -> dict[str, Any]:
    """How far an equity share moves when series expiring on the date are left out.

    The index shares are computed that way because the chain no longer lists those
    series; this says what the same rule does where the full book is known.
    """
    later = daily_rows[pd.to_datetime(daily_rows["expiry"]) > daily_rows["date"]]
    both = search.merge(
        hidden_share(later), on=["date", "symbol", "adjusted"], suffixes=("", "_later")
    )
    both = both[~both["adjusted"]]
    gap = (both["flex_share"] - both["flex_share_later"]).abs()
    return {
        "name_dates": len(both),
        "moved": int((gap > EXPIRY_MOVE).sum()),
        "max_abs_diff": float(gap.max()),
        "median_abs_diff": float(gap.median()),
    }


def _value(
    priced: pd.DataFrame,
    reports: pd.DataFrame,
    dates: pd.DatetimeIndex,
    universe: Mapping[str, str],
) -> dict[str, Any]:
    """FLEX mark value as a share of option value, on the daily universe's dates.

    The aggregate is taken only on dates when every followed name is priced, so it does
    not move with which names happen to have quotes.
    """
    chains = priced[priced["date"].isin(dates) & priced["symbol"].isin(set(universe))]
    shares = value_share(chains, _on(reports, dates))
    usable = shares[shares["usable"]]
    priced_names = usable.groupby("date")["symbol"].nunique()
    complete = priced_names[priced_names == len(universe)].index
    totals = (
        usable[usable["date"].isin(complete)]
        .groupby("date")[["flex_value", "listed_value", "flex_oi", "listed_oi"]]
        .sum()
    )
    value = totals["flex_value"] / (totals["flex_value"] + totals["listed_value"])
    oi = totals["flex_oi"] / (totals["flex_oi"] + totals["listed_oi"])
    per_name = usable.groupby("symbol")[["value_share", "oi_share"]].median()
    last_date = pd.Timestamp(usable["date"].max())
    last = usable[usable["date"] == last_date].sort_values("value_share", ascending=False)
    return {
        "symbol_dates": len(shares),
        "usable": len(usable),
        "dates": int(usable["date"].nunique()),
        "complete_dates": len(complete),
        "names": int(per_name.shape[0]),
        "theo_share": float(
            (usable["theo_share"] * usable["listed_oi"]).sum() / usable["listed_oi"].sum()
        ),
        "aggregate": _spread(value),
        "aggregate_oi": _spread(oi),
        "median_name": float(per_name["value_share"].median()),
        "median_name_oi": float(per_name["oi_share"].median()),
        "above_oi_share": int((per_name["value_share"] > per_name["oi_share"]).sum()),
        "last_date": formats.iso_date(last_date),
        "leaders": [
            {
                "symbol": str(row["symbol"]),
                "value_share": float(row["value_share"]),
                "oi_share": float(row["oi_share"]),
            }
            for row in last.head(VALUE_LEADERS).to_dict("records")
        ],
        "largest_line": _largest_line(reports, last, last_date, universe),
    }


def _largest_line(
    reports: pd.DataFrame, last: pd.DataFrame, on: pd.Timestamp, universe: Mapping[str, str]
) -> dict[str, Any]:
    """The single FLEX series worth most on `on`, beside its underlying's listed value."""
    series = flex_series(reports, pd.DatetimeIndex([on]))
    series = series[series["symbol"].isin(set(last["symbol"]))]
    line = series.iloc[int(np.argmax(series["flex_value"].to_numpy()))]
    opposite = series[
        (series["root"] == line["root"])
        & (series["expiry"] == line["expiry"])
        & (series["strike"] == line["strike"])
        & (series["right"] != line["right"])
    ]
    listed = last.loc[last["symbol"] == line["symbol"], "listed_value"]
    return {
        "date": formats.iso_date(on),
        "symbol": str(line["symbol"]),
        "root": str(line["root"]),
        "right": str(line["right"]),
        "expiry": formats.iso_date(pd.Timestamp(line["expiry"])),
        "strike": float(line["strike"]),
        "mark": float(line["mark_price"]),
        "open_interest": int(line["open_interest"]),
        "value": float(line["flex_value"]),
        "opposite_open_interest": int(opposite["open_interest"].sum()),
        "listed_value": float(listed.iloc[0]),
    }


def _by_group(names: Sequence[str], universe: Mapping[str, str]) -> dict[str, int]:
    groups = [universe[name] for name in names]
    return {group: groups.count(group) for group in (PROGRAMME, CONTROL)}


def _spread(series: pd.Series) -> dict[str, float]:
    return {
        "median": float(series.median()),
        "min": float(series.min()),
        "max": float(series.max()),
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "symbol": str(row["symbol"]),
            "flex_oi": int(row["flex_oi"]),
            "listed_oi": int(row["listed_oi"]),
            "share": float(row["flex_share"]),
        }
        for row in frame.to_dict("records")
    ]


def _key(fraction: float) -> str:
    """`0.25` -> `"25"`: thresholds and quantiles keyed by their percentage."""
    return str(round(fraction * 100))
