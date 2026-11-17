#!/usr/bin/env python
"""A five-minute demonstration on live public data: no private captures needed.

It fetches one day of OCC's FLEX open-interest report (equity and index classes) and one
day of Cboe's FLEX execution reports, then runs the project's own code on them:

1. the product split of the hidden book (boxes, fund stock legs, package legs, pairs);
2. the largest box spreads in open interest, and the largest fund stock legs;
3. the box trades of the day in Cboe's reports, priced against the Treasury curve.

Nothing is written to the repository's data directory. By default the latest weekday that
both OCC and Cboe serve is used; `--date` picks another. Run it with `make demo`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import pandas as pd

from hidden_options.collect.cboe_flex_trades import TradeReportError, parse_executions, report_url
from hidden_options.collect.http import FetchError, build_session, fetch
from hidden_options.collect.occ_flex import FlexReportError, fetch_report
from hidden_options.collect.treasury import PARAMS as CURVE_PARAMS
from hidden_options.collect.treasury import URL as CURVE_URL
from hidden_options.collect.treasury import parse_curve
from hidden_options.measure.anatomy import CATEGORIES, classify, split, stock_leg_value
from hidden_options.measure.box_rates import (
    benchmark_rates,
    box_trades,
    executions,
    rate_sample,
)

LABELS = {
    "box": "Box legs",
    "stock_leg": "Stock-leg calls",
    "package_leg": "Package legs",
    "pair": "Same-strike pairs",
    "other": "Other (options)",
}
LOOKBACK_DAYS = 10


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    session = build_session()

    day, report = _report(session, args.date)
    print(f"\nOCC FLEX open-interest report of {day:%d %B %Y}")
    found = classify(report)
    _print_split(found.series)
    _print_boxes(found.boxes)
    _print_stock_legs(found.series)
    _print_trades(session, day)
    return 0


def _report(session, wanted: date | None) -> tuple[date, pd.DataFrame]:
    """The report of `wanted`, or of the latest weekday OCC serves, equity and index."""
    candidates = (
        [wanted] if wanted else [date.today() - timedelta(days=k) for k in range(1, LOOKBACK_DAYS)]
    )
    for day in candidates:
        if day.weekday() >= 5:
            continue
        try:
            parts = [fetch_report(session, day, kind).frame for kind in ("equity", "index")]
        except (FlexReportError, FetchError):
            continue
        frame = pd.concat(parts, ignore_index=True)
        frame["report_date"] = pd.to_datetime(frame["report_date"])
        frame["expiry"] = pd.to_datetime(frame["expiry"])
        return pd.Timestamp(frame["report_date"].iloc[0]).date(), frame
    raise SystemExit("OCC served no FLEX report for the dates tried")


def _print_split(series: pd.DataFrame) -> None:
    parts = split(series)
    value = sum(part["value"] for part in parts.values())
    held = sum(part["open_interest"] for part in parts.values())
    print(
        f"\n{'Category':<20}{'Series':>9}{'Open interest':>15}{'Mark value':>13}{'Value share':>13}"
    )
    for name in CATEGORIES:
        part = parts[name]
        print(
            f"{LABELS[name]:<20}{part['series']:>9,}{part['open_interest'] / held:>15.1%}"
            f"{part['value'] / 1e9:>11.1f}bn{part['value'] / value:>13.1%}"
        )
    print(f"{'All':<20}{len(series):>9,}{1:>15.1%}{value / 1e9:>11.1f}bn")


def _print_boxes(boxes: pd.DataFrame) -> None:
    face = boxes["face"].sum() / 1e9
    print(f"\nBox positions by contract counts: {len(boxes):,}, face ${face:.1f}bn")
    top = boxes.sort_values("face", ascending=False).head(5)
    for row in top.itertuples():
        print(
            f"  {row.root:<6} {pd.Timestamp(row.expiry):%Y-%m-%d}  {row.lower:>10,.2f} / "
            f"{row.upper:>10,.2f}  x{row.count:>7,}  face ${row.face / 1e9:6.2f}bn"
        )


def _print_stock_legs(series: pd.DataFrame) -> None:
    value = stock_leg_value(series)
    print(f"\nStock held through deep FLEX calls: ${value.sum() / 1e9:.1f}bn, largest:")
    for name, amount in value.head(5).items():
        print(f"  {name:<6} ${amount / 1e9:6.2f}bn")


def _print_trades(session, day: date) -> None:
    try:
        payload = fetch(session, report_url(day)).content
        rows = parse_executions(payload)
    except (FetchError, TradeReportError) as exc:
        print(f"\nCboe FLEX trades of {day}: not available ({exc})")
        return
    trades, _ = box_trades(executions(rows))
    count = len(rows) // 2  # each execution is reported from both sides
    print(f"\nCboe FLEX executions of {day:%d %B %Y}: {count:,} trades, {len(trades)} box trades")
    if trades.empty:
        return
    kept, _ = rate_sample(trades)
    if kept.empty:
        return
    params = {**CURVE_PARAMS, "field_tdr_date_value": str(day.year)}
    curve = parse_curve(fetch(session, CURVE_URL.format(year=day.year), params=params).content)
    bench = benchmark_rates(curve, kept["trade_date"], kept["settle_days"].to_numpy())
    kept = kept.assign(spread=(kept["rate"] - bench) * 1e4)
    for row in kept.sort_values("face", ascending=False).head(8).itertuples():
        print(
            f"  {row.root:<6} to {pd.Timestamp(row.expiry):%Y-%m-%d}  face ${row.face / 1e6:9,.1f}m"
            f"  rate {row.rate:6.2%}  over Treasuries {row.spread:+6.1f}bp"
        )
    print(f"  median spread over Treasuries: {kept['spread'].median():+.1f}bp")


if __name__ == "__main__":
    sys.exit(main())
