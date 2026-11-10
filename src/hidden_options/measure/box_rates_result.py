"""Result `box_rates`: the rate at which box spreads trade in Cboe's FLEX reports.

Specification: `docs/log/2026-11-10-box-rates-spec.md`. The inputs are the daily
execution reports up to PANEL_END, the Treasury par yield curve, OCC's FLEX report of
each trade date for the marks, and the boxes the `anatomy` rules find in open interest
on the last report date.
"""

from __future__ import annotations

import glob
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.collect.treasury import SNAPSHOT as CURVE_SNAPSHOT
from hidden_options.config import PANEL_END, RAW_DIR
from hidden_options.measure.anatomy import MATURITY_LABELS, UNDERLYING_GROUPS, classify
from hidden_options.measure.anatomy_result import REPORT_COLUMNS
from hidden_options.measure.box_rates import (
    MIN_DAYS,
    benchmark_rates,
    box_trades,
    executions,
    mark_rates,
    rate_sample,
    spread_summary,
)
from hidden_options.measure.box_rates_macros import box_rates_macros
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "box_rates"
HEADLINE_MAX_DAYS = 365
MATURITY_EDGES = (30, 91, 365, 730)
BOX_KEY = ["root", "expiry", "lower", "upper"]


def box_rates_result(
    days: Iterable[pd.DataFrame],
    curve: pd.DataFrame,
    read_report: Callable[[pd.Timestamp], pd.DataFrame | None],
    last_boxes: pd.DataFrame,
) -> Result:
    """The figures the specification lists.

    `days` yields one trade date's published rows at a time. `read_report` returns OCC's
    FLEX report of a date, or None. `last_boxes` holds the boxes found in open interest
    on the last report date, with their `face`.
    """
    found, files, executed, unresolved = [], 0, 0, 0
    for day in days:
        files += 1
        rows = executions(day)
        executed += int(rows.loc[rows["root"].notna(), "executions"].sum())
        boxes, left = box_trades(rows)
        unresolved += left
        if not boxes.empty:  # an empty frame would turn the dates of the rest into objects
            found.append(boxes)
    if not files:
        raise ValueError("No execution reports to read")
    if not found:
        raise ValueError("No box trade in the execution reports")
    trades = pd.concat(found, ignore_index=True)
    kept, dropped = rate_sample(trades)
    benchmark = benchmark_rates(curve, kept["trade_date"], kept["days"].to_numpy())
    kept = kept.assign(benchmark=benchmark, spread=kept["rate"] - benchmark)
    sample = kept[kept["benchmark"].notna()].reset_index(drop=True)
    headline = sample[sample["days"] <= HEADLINE_MAX_DAYS]
    bucket = np.searchsorted(MATURITY_EDGES, sample["days"].to_numpy(), side="left")
    group = np.where(
        headline["underlying"].isin(UNDERLYING_GROUPS[:2]), headline["underlying"], "other"
    )

    values: dict[str, Any] = {
        "sample": {
            "files": files,
            "first_date": _iso(trades["trade_date"].min()),
            "last_date": _iso(trades["trade_date"].max()),
            "executions": executed,
            "box_trades": len(trades),
            "box_face": float(trades["face"].sum()),
            "unresolved": unresolved,
            "dropped": dropped,
            "no_benchmark": int(len(kept) - len(sample)),
            "rate_trades": len(sample),
            "rate_face": float(sample["face"].sum()),
        },
        "headline": {**spread_summary(headline), **_levels(headline)},
        "by_maturity": {
            label: spread_summary(sample[bucket == place])
            for place, label in enumerate(MATURITY_LABELS)
        },
        "by_underlying": {
            name: spread_summary(headline[group == name]) for name in UNDERLYING_GROUPS
        },
        "monthly": _monthly(headline, trades),
        "marks": _marks(sample, read_report),
        "open_interest": _seen_trading(last_boxes, trades),
    }
    run_inputs = {
        "first_date": values["sample"]["first_date"],
        "last_date": values["sample"]["last_date"],
        "files": files,
        "min_days": MIN_DAYS,
        "headline_max_days": HEADLINE_MAX_DAYS,
    }
    return Result(NAME, values, box_rates_macros(values), run_inputs, now_iso())


def _levels(trades: pd.DataFrame) -> dict[str, float | None]:
    """The face-weighted traded rate and benchmark rate behind the mean spread."""
    if trades.empty:
        return {"rate": None, "benchmark": None}
    face = trades["face"].to_numpy(float)
    return {
        "rate": float(np.average(trades["rate"].to_numpy(float), weights=face)),
        "benchmark": float(np.average(trades["benchmark"].to_numpy(float), weights=face)),
    }


def _monthly(headline: pd.DataFrame, trades: pd.DataFrame) -> list[dict[str, Any]]:
    """Each calendar month's spread on the headline sample and the face of every box
    traded in it."""
    traded = trades.groupby(trades["trade_date"].dt.strftime("%Y-%m"))["face"].sum()
    months = headline["trade_date"].dt.strftime("%Y-%m")
    rows = []
    for month in sorted(traded.index):
        summary = spread_summary(headline[months == month])
        rows.append(
            {
                "month": str(month),
                "traded_face": float(traded[month]),
                "trades": summary["trades"],
                "mean": summary["mean"],
                "median": summary["median"],
            }
        )
    return rows


def _marks(
    sample: pd.DataFrame, read_report: Callable[[pd.Timestamp], pd.DataFrame | None]
) -> dict[str, Any]:
    """The rate in OCC's marks less the traded rate, on trades whose four series are in
    the report of the trade date."""
    gaps, weights = [], []
    for date, trades in sample.groupby("trade_date"):
        report = read_report(pd.Timestamp(str(date)))
        if report is None:
            continue
        implied = mark_rates(trades.reset_index(drop=True), report)
        usable = np.isfinite(implied)
        gaps.append(implied[usable] - trades["rate"].to_numpy(float)[usable])
        weights.append(trades["face"].to_numpy(float)[usable])
    gap = np.concatenate(gaps) if gaps else np.array([])
    weight = np.concatenate(weights) if weights else np.array([])
    if len(gap) == 0:
        return {"matched": 0, "matched_share": 0.0, "mean": None, "median": None}
    return {
        "matched": len(gap),
        "matched_share": float(len(gap) / len(sample)),
        "mean": float(np.average(gap, weights=weight)),
        "median": float(np.median(gap)),
    }


def _seen_trading(last_boxes: pd.DataFrame, trades: pd.DataFrame) -> dict[str, float]:
    """The share of open-interest box face at strikes that traded as a box package."""
    face = float(last_boxes["face"].sum())
    traded = trades[BOX_KEY].drop_duplicates().assign(traded=True)
    seen = last_boxes.merge(traded, on=BOX_KEY, how="left")["traded"].fillna(False)
    inside = float(last_boxes["face"].to_numpy(float)[seen.to_numpy(dtype=bool)].sum())
    return {"face": face, "traded_face_share": inside / face if face else 0.0}


def _iso(day: Any) -> str | None:
    return None if pd.isna(day) else f"{pd.Timestamp(day):%Y-%m-%d}"


def trade_days(raw: Path, until: pd.Timestamp) -> Iterator[pd.DataFrame]:
    """Each stored execution report up to `until`, in date order."""
    for path in sorted(glob.glob(str(raw / "cboe_flex_trades/date=*/executions.parquet"))):
        if pd.Timestamp(path.split("date=")[1][:10]) <= until:
            yield pd.read_parquet(path)


def read_report_day(raw: Path, day: pd.Timestamp) -> pd.DataFrame | None:
    """OCC's FLEX report of `day`, equity and index together, or None if it is not held."""
    files = sorted(glob.glob(str(raw / f"occ_flex/date={day:%Y-%m-%d}/*.parquet")))
    if not files:
        return None
    report = pd.concat(
        [pd.read_parquet(path, columns=list(REPORT_COLUMNS)) for path in files],
        ignore_index=True,
    )
    report["report_date"] = pd.to_datetime(report["report_date"])
    report["expiry"] = pd.to_datetime(report["expiry"])
    return report


def last_report_day(raw: Path, until: pd.Timestamp) -> pd.DataFrame:
    """The latest FLEX report held that is dated on or before `until`."""
    dates = sorted(
        pd.Timestamp(folder.split("date=")[1][:10])
        for folder in glob.glob(str(raw / "occ_flex/date=*"))
    )
    held = [day for day in dates if day <= until]
    report = read_report_day(raw, held[-1]) if held else None
    if report is None:
        raise FileNotFoundError(f"No FLEX reports under {raw}/occ_flex up to {until:%Y-%m-%d}")
    return report


@ANALYSES.register(NAME)
def box_rates_analysis() -> Result:
    """Box rates on every execution report on disk up to PANEL_END."""
    end = pd.Timestamp(PANEL_END)
    last = last_report_day(RAW_DIR, end)
    return box_rates_result(
        trade_days(RAW_DIR, end),
        pd.read_parquet(RAW_DIR / CURVE_SNAPSHOT),
        lambda day: read_report_day(RAW_DIR, day),
        classify(last).boxes,
    )


__all__ = [
    "NAME",
    "box_rates_analysis",
    "box_rates_result",
    "last_report_day",
    "read_report_day",
    "trade_days",
]
