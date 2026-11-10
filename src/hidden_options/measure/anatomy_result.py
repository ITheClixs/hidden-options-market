"""Result `anatomy`: what the FLEX market is made of, on every report date.

Specification: `docs/log/2026-11-10-anatomy-spec.md`. Each date's report is split by
`measure.anatomy.classify`; this module adds the dates up, runs the chance benchmark on
every twentieth date, and divides gross FLEX dollar gamma among the categories on the
domain of the `hidden_gamma` result.
"""

from __future__ import annotations

import glob
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.config import PANEL_END, RAW_DIR
from hidden_options.measure.anatomy import (
    CATEGORIES,
    SERIES,
    Anatomy,
    box_lending,
    classify,
    colocated_other_share,
    pair_notional,
    shuffled,
    split,
    stock_leg_value,
)
from hidden_options.measure.anatomy_macros import anatomy_macros
from hidden_options.measure.hidden_gamma import flex_gamma
from hidden_options.measure.hidden_gamma_result import load_inputs as load_gamma_inputs
from hidden_options.measure.hidden_share import flex_series
from hidden_options.measure.implied import RATE
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "anatomy"
SEED = 20261110
CHANCE_EVERY = 20
TOP_UNDERLYINGS = 8
REPORT_COLUMNS = (
    "report_date",
    "kind",
    "root",
    "underlying",
    "right",
    "expiry",
    "strike",
    "mark_price",
    "open_interest",
)
GAMMA_COLUMNS = ("date", *SERIES, "gross")


def anatomy_result(
    days: Iterable[pd.DataFrame],
    gamma: pd.DataFrame,
    *,
    seed: int = SEED,
    chance_every: int = CHANCE_EVERY,
) -> Result:
    """The figures the specification lists.

    `days` yields one report date's rows at a time, in date order. `gamma` holds gross
    dollar gamma per FLEX series and date (GAMMA_COLUMNS) on the `hidden_gamma` domain.
    """
    rng = np.random.default_rng(seed)
    gamma_days = {pd.Timestamp(str(day)): rows for day, rows in gamma.groupby("date")}
    daily: list[dict[str, Any]] = []
    ends: dict[str, tuple[pd.Timestamp, Anatomy]] = {}
    chance = {"dates": 0, "box_face": 0.0, "box_face_actual": 0.0}
    chance.update({f"{name}_oi": 0.0 for name in ("package_leg", "pair")})
    chance.update({f"{name}_oi_actual": 0.0 for name in ("package_leg", "pair")})
    gamma_sums = dict.fromkeys(CATEGORIES, 0.0)
    gamma_total = gamma_matched = 0.0

    for place, day in enumerate(days):
        date = pd.Timestamp(day["report_date"].iloc[0])
        found = classify(day)
        daily.append(_daily(found, date))
        ends.setdefault("first", (date, found))
        ends["last"] = (date, found)
        if place % chance_every == 0:
            _add_chance(chance, day, found, rng)
        if date in gamma_days:
            sums, matched = gamma_by_category(gamma_days[date], found.series)
            for name, amount in sums.items():
                gamma_sums[name] += amount
            gamma_matched += matched
            gamma_total += float(gamma_days[date]["gross"].sum())
    if not daily:
        raise ValueError("No report dates to split")

    first, last = _end(*ends["first"]), _end(*ends["last"])
    stock_first = first["split"]["stock_leg"]["value"]
    by_underlying = stock_leg_value(ends["last"][1].series)
    values: dict[str, Any] = {
        "dates": len(daily),
        "first": first,
        "last": last,
        "mean_share": _mean_shares(daily),
        "daily": daily,
        "boxes": {
            "first": first["lending"],
            "last": last["lending"],
            "growth": _ratio(last["lending"]["face"], first["lending"]["face"]),
            "peak": max(daily, key=lambda row: row["box_face"])["box_face"],
            "peak_date": max(daily, key=lambda row: row["box_face"])["date"],
        },
        "stock_legs": {
            "first_value": stock_first,
            "last_value": last["split"]["stock_leg"]["value"],
            "growth": _ratio(last["split"]["stock_leg"]["value"], stock_first),
            "underlyings": len(by_underlying),
            "last_by_underlying": {
                str(name): float(value)
                for name, value in by_underlying.head(TOP_UNDERLYINGS).items()
            },
        },
        "pairs": {
            "first_notional": daily[0]["pair_notional"],
            "last_notional": daily[-1]["pair_notional"],
        },
        "chance": {
            "dates": int(chance["dates"]),
            "box_face_share": _ratio(chance["box_face"], chance["box_face_actual"]),
            "package_oi_share": _ratio(chance["package_leg_oi"], chance["package_leg_oi_actual"]),
            "pair_oi_share": _ratio(chance["pair_oi"], chance["pair_oi_actual"]),
        },
        "gamma": {
            "share": {name: _ratio(gamma_sums[name], gamma_total) for name in CATEGORIES},
            "matched_share": _ratio(gamma_matched, gamma_total),
            "dates": len(gamma_days),
        },
    }
    run_inputs = {
        "first_date": first["date"],
        "last_date": last["date"],
        "dates": len(daily),
        "seed": seed,
        "chance_every": chance_every,
    }
    return Result(NAME, values, anatomy_macros(values), run_inputs, now_iso())


def gamma_by_category(rows: pd.DataFrame, series: pd.DataFrame) -> tuple[dict[str, float], float]:
    """Gross gamma of `rows` summed by the category of the same series in `series`, and
    the gamma of the rows that found one."""
    joined = rows.merge(series[[*SERIES, "category"]], on=SERIES, how="left")
    sums = joined.groupby("category")["gross"].sum()
    by_name = {name: float(sums.get(name, 0.0)) for name in CATEGORIES}
    return by_name, float(joined.loc[joined["category"].notna(), "gross"].sum())


def _daily(found: Anatomy, date: pd.Timestamp) -> dict[str, Any]:
    parts = split(found.series)
    return {
        "date": f"{date:%Y-%m-%d}",
        "open_interest": {name: parts[name]["open_interest"] for name in CATEGORIES},
        "value": {name: parts[name]["value"] for name in CATEGORIES},
        "box_face": float(found.boxes["face"].sum()),
        "box_value": float(found.boxes["value"].sum()),
        "box_neighbour_face": found.neighbour_face,
        "pair_notional": pair_notional(found.series),
        "colocated_other_share": colocated_other_share(found.series),
    }


def _end(date: pd.Timestamp, found: Anatomy) -> dict[str, Any]:
    return {
        "date": f"{date:%Y-%m-%d}",
        "split": split(found.series),
        "lending": box_lending(found, date),
        "colocated_other_share": colocated_other_share(found.series),
    }


def _mean_shares(daily: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Each category's share of open interest and of value, averaged over dates."""
    out: dict[str, dict[str, float]] = {}
    for measure in ("open_interest", "value"):
        table = pd.DataFrame([row[measure] for row in daily], dtype=float)
        shares = table.div(table.sum(axis=1), axis=0).mean()
        out[measure] = {name: float(shares[name]) for name in CATEGORIES}
    return out


def _add_chance(
    chance: dict[str, float], day: pd.DataFrame, found: Anatomy, rng: np.random.Generator
) -> None:
    dealt = classify(shuffled(day, rng))
    actual, random = split(found.series), split(dealt.series)
    chance["dates"] += 1
    chance["box_face"] += float(dealt.boxes["face"].sum())
    chance["box_face_actual"] += float(found.boxes["face"].sum())
    for name in ("package_leg", "pair"):
        chance[f"{name}_oi"] += random[name]["open_interest"]
        chance[f"{name}_oi_actual"] += actual[name]["open_interest"]


def _ratio(part: float, whole: float) -> float:
    return float(part / whole) if whole else 0.0


def report_days(raw: Path, until: pd.Timestamp) -> Iterator[pd.DataFrame]:
    """Each report date's rows, equity and index together, in date order up to `until`."""
    folders = sorted(glob.glob(str(raw / "occ_flex/date=*")))
    for folder in folders:
        if pd.Timestamp(folder.split("date=")[1][:10]) > until:
            continue
        files = sorted(glob.glob(f"{folder}/*.parquet"))
        if not files:
            continue
        day = pd.concat(
            [pd.read_parquet(path, columns=list(REPORT_COLUMNS)) for path in files],
            ignore_index=True,
        )
        day["report_date"] = pd.to_datetime(day["report_date"])
        day["expiry"] = pd.to_datetime(day["expiry"])
        yield day


def domain_gamma() -> pd.DataFrame:
    """Gross dollar gamma of each FLEX series on the `hidden_gamma` domain."""
    inputs = load_gamma_inputs()
    dates = pd.DatetimeIndex(sorted(inputs.chains["date"].unique()))
    series = flex_series(inputs.panel, dates)
    series = series[series["symbol"].isin(set(inputs.chains["symbol"]))]
    priced = flex_gamma(series, inputs.chains, rate=RATE)
    return pd.DataFrame(priced[list(GAMMA_COLUMNS)])


@ANALYSES.register(NAME)
def anatomy_analysis() -> Result:
    """The split on every report on disk up to PANEL_END."""
    return anatomy_result(report_days(RAW_DIR, pd.Timestamp(PANEL_END)), domain_gamma())


__all__ = [
    "NAME",
    "anatomy_analysis",
    "anatomy_result",
    "domain_gamma",
    "gamma_by_category",
    "report_days",
]
