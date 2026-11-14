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
from hidden_options.measure.anatomy import (
    MATURITY_LABELS,
    UNDERLYING_GROUPS,
    classify,
    new_lines,
)
from hidden_options.measure.anatomy_result import REPORT_COLUMNS, report_days
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
# Bands of trade size by face, for a diagnostic added after the first figures were seen.
SIZE_EDGES = (1e6, 1e7, 1e8, 1e9)
SIZE_LABELS = ("to_1m", "1m_10m", "10m_100m", "100m_1bn", "over_1bn")
BOX_KEY = ["root", "expiry", "lower", "upper"]
STRIKE_PAIR = ["root", "lower", "upper"]
TOP_DATES = 6


def box_rates_result(
    days: Iterable[pd.DataFrame],
    curve: pd.DataFrame,
    read_report: Callable[[pd.Timestamp], pd.DataFrame | None],
    last_boxes: pd.DataFrame,
    daily_boxes: Iterable[tuple[pd.Timestamp, pd.DataFrame]] = (),
    origins: pd.DataFrame | None = None,
) -> Result:
    """The figures the specification lists, and diagnostics added after they were seen.

    `days` yields one trade date's published rows at a time. `read_report` returns OCC's
    FLEX report of a date, or None. `last_boxes` holds the boxes found in open interest
    on the last report date, with their `face`. `daily_boxes` yields each report date
    with the boxes found in its open interest, for the series of confirmed box face.
    `origins` holds the date each line first had open interest (`anatomy.new_lines`).
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
        "by_size": _by_size(headline),
        "marks": _marks(sample, read_report),
        "open_interest": _seen_trading(last_boxes, trades),
        "diagnostics": {
            **_weight(headline),
            "by_quarter": _by_quarter(headline),
            "marks_headline": _marks(headline.reset_index(drop=True), read_report),
            "longest_largest": _largest(sample[bucket == len(MATURITY_LABELS) - 1]),
        },
        "confirmed": _confirmed(daily_boxes, trades),
        "origins": _origins(last_boxes, trades, origins),
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


def _by_size(headline: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """The spread by band of trade size. Not in the specification: added after the first
    figures showed one roll moving a month's face-weighted mean."""
    band = np.searchsorted(SIZE_EDGES, headline["face"].to_numpy(float), side="left")
    return {
        label: spread_summary(headline[band == place]) for place, label in enumerate(SIZE_LABELS)
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


def _seen_trading(last_boxes: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    """The share of open-interest box face at strikes that traded as a box package: in
    all (specified), and by underlying with the largest such box's part (added after)."""
    amounts = last_boxes["face"].to_numpy(float)
    face = float(amounts.sum())
    seen = _traded(last_boxes, trades, BOX_KEY)
    inside = float(amounts[seen].sum())
    group = np.where(
        last_boxes["underlying"].isin(UNDERLYING_GROUPS[:2]), last_boxes["underlying"], "other"
    )
    return {
        "face": face,
        "traded_face_share": inside / face if face else 0.0,
        "by_underlying": {
            name: _ratio(amounts[seen & (group == name)].sum(), amounts[group == name].sum())
            for name in UNDERLYING_GROUPS
        },
        "largest_share_of_traded": _ratio(amounts[seen].max() if seen.any() else 0.0, inside),
    }


def _traded(boxes: pd.DataFrame, trades: pd.DataFrame, key: list[str]) -> np.ndarray:
    """Which `boxes` share `key` with a box package in the trade files."""
    known = trades[key].drop_duplicates().assign(traded=True)
    return boxes.merge(known, on=key, how="left")["traded"].fillna(False).to_numpy(dtype=bool)


def _confirmed(
    daily_boxes: Iterable[tuple[pd.Timestamp, pd.DataFrame]], trades: pd.DataFrame
) -> dict[str, Any]:
    """On every report date, the open-interest box face that the trade files confirm.

    Added after the first figures. Two readings: the box's own root, expiry and strikes
    traded as a package at some time in the files (`exact`), or its root and strikes did
    at any expiry (`strike_pair`). The second reaches boxes that expired before the files
    begin, at the cost of trusting that a strike pair used for boxes stays one.
    """
    rows = []
    for date, boxes in daily_boxes:
        amounts = boxes["face"].to_numpy(float)
        rows.append(
            {
                "date": f"{date:%Y-%m-%d}",
                "face": float(amounts.sum()),
                "exact": float(amounts[_traded(boxes, trades, BOX_KEY)].sum()),
                "strike_pair": float(amounts[_traded(boxes, trades, STRIKE_PAIR)].sum()),
            }
        )
    if not rows:
        return {"daily": [], "first": None, "last": None, "growth": None}
    first, last = rows[0], rows[-1]
    return {
        "daily": rows,
        "first": first,
        "last": last,
        "growth": _ratio(last["strike_pair"], first["strike_pair"]),
    }


def _origins(
    boxes: pd.DataFrame, trades: pd.DataFrame, origins: pd.DataFrame | None
) -> dict[str, Any]:
    """Whether the two strikes of each box on the last date first had open interest on
    the same report date, as lines opened in one trade would. Lines already open on the
    first report date cannot be dated and are counted apart. Added after the first
    figures."""
    if origins is None or origins.empty or boxes.empty:
        return {"censored_share": None, "same_date_share": {}}
    start = origins["first_date"].min()
    dated = origins.set_index(["root", "expiry", "strike"])["first_date"]

    def first(side: str) -> np.ndarray:
        keys = pd.MultiIndex.from_frame(
            boxes[["root", "expiry", side]].rename(columns={side: "strike"})
        )
        return dated.reindex(keys).to_numpy()

    lower, upper = first("lower"), first("upper")
    face = boxes["face"].to_numpy(float)
    censored = (lower == start) | (upper == start)
    same = ~censored & (lower == upper)
    traded = _traded(boxes, trades, BOX_KEY)
    shares = {}
    for name, chosen in (
        ("all", np.ones(len(boxes), dtype=bool)),
        ("confirmed", traded),
        ("unconfirmed", ~traded),
    ):
        dateable = chosen & ~censored
        shares[name] = _ratio(face[same & chosen].sum(), face[dateable].sum())
    return {"censored_share": _ratio(face[censored].sum(), face.sum()), "same_date_share": shares}


def _weight(headline: pd.DataFrame) -> dict[str, Any]:
    """How much of the headline mean rests on a few dates, the mean without weights, and
    the range of the mean when one date at a time is left out. Added after the first
    figures."""
    empty: dict[str, Any] = {
        "top_dates": TOP_DATES,
        "top_dates_share": None,
        "effective_dates": None,
        "unweighted_mean": None,
        "leave_one_low": None,
        "leave_one_high": None,
    }
    if headline.empty:
        return empty
    weighted = headline.assign(moment=headline["spread"] * headline["face"])
    by_date = weighted.groupby("trade_date")[["face", "moment"]].sum()
    face = by_date["face"].to_numpy(dtype=np.float64)
    moment = by_date["moment"].to_numpy(dtype=np.float64)
    total_face, total_moment = float(face.sum()), float(moment.sum())
    out = {
        **empty,
        "top_dates_share": float(np.sort(face)[::-1][:TOP_DATES].sum()) / total_face,
        "effective_dates": total_face**2 / float(np.square(face).sum()),
        "unweighted_mean": float(headline["spread"].mean()),
    }
    if len(face) > 1:
        without = [(total_moment - m) / (total_face - f) for f, m in zip(face, moment, strict=True)]
        out["leave_one_low"] = float(min(without))
        out["leave_one_high"] = float(max(without))
    return out


def _largest(trades: pd.DataFrame) -> dict[str, Any] | None:
    """The largest trade by face in a bucket, with its spread. Added after the first
    figures, when one trade carried the mean of the longest bucket."""
    if trades.empty:
        return None
    top = trades.iloc[int(np.argmax(trades["face"].to_numpy(float)))]
    return {
        "face": float(top["face"]),
        "spread": float(top["spread"]),
        "expiry": f"{pd.Timestamp(top['expiry']):%Y-%m-%d}",
        "face_share": float(top["face"] / trades["face"].sum()),
    }


def _by_quarter(headline: pd.DataFrame) -> list[dict[str, Any]]:
    """The spread in each calendar quarter. Added after the first figures."""
    quarters = headline["trade_date"].dt.to_period("Q").astype(str)
    rows = []
    for quarter in sorted(quarters.unique()):
        summary = spread_summary(headline[quarters == quarter])
        rows.append(
            {
                "quarter": str(quarter),
                **{k: summary[k] for k in ("trades", "face", "mean", "median")},
            }
        )
    return rows


def _ratio(part: Any, whole: Any) -> float:
    return float(part) / float(whole) if float(whole) else 0.0


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
    daily, known = [], pd.DataFrame(columns=["root", "expiry", "strike", "first_date"])
    for day in report_days(RAW_DIR, end):
        date = pd.Timestamp(day["report_date"].iloc[0])
        daily.append((date, classify(day).boxes))
        known = new_lines(known, day, date)
    return box_rates_result(
        trade_days(RAW_DIR, end),
        pd.read_parquet(RAW_DIR / CURVE_SNAPSHOT),
        lambda day: read_report_day(RAW_DIR, day),
        daily[-1][1],
        daily,
        known,
    )


__all__ = [
    "NAME",
    "box_rates_analysis",
    "box_rates_result",
    "last_report_day",
    "read_report_day",
    "trade_days",
]
