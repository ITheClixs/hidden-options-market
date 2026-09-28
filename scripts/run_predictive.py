#!/usr/bin/env python
"""Does hidden inventory observable through clearing predict the visible market?

Design
------
FLEX positions are negotiated bilaterally and cleared. OCC reports the resulting open
interest for activity date T, published overnight and therefore available to an
observer on T+1. A dealer taking the other side of a FLEX trade hedges it in the
*listed* market, and the convexity it leaves behind persists for the life of the
position. If that is economically material, hidden inventory measured at T should
carry information about the underlying's behaviour from T+1 onwards.

Timing is the obvious way to get this wrong, so it is enforced rather than assumed:
every predictor is measured at T or earlier and every outcome strictly after T. The
one-day publication lag is respected by construction.

Specification, with underlying and date fixed effects and errors two-way clustered:

    y_{i,t+1} = a_i + d_t + b * flex_{i,t} + controls_{i,t} + e

Outcomes are next-day absolute return and next-day squared return, both standard
proxies for realised volatility at daily frequency. Predictors enter as innovations
relative to the underlying's own recent level, because the level of FLEX inventory is
dominated by persistent cross-sectional differences that the fixed effects absorb.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.measure.flex_panel import daily_inventory, load_panel  # noqa: E402
from absorb.measure.panel import fit  # noqa: E402


def build(
    root: Path, min_history: int = 40, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    panel = load_panel(root)
    if start or end:
        panel = panel[panel["report_date"].between(start or "1900-01-01", end or "2100-01-01")]
    inventory = daily_inventory(panel)

    bars = pd.read_parquet("data/flex_underlying_bars.parquet")
    bars["date"] = pd.to_datetime(bars["timestamp"]).dt.tz_localize(None).dt.normalize()
    bars = bars.sort_values(["symbol", "date"])
    bars["ret"] = bars.groupby("symbol")["close"].pct_change()
    bars["abs_ret"] = bars["ret"].abs()
    bars["dollar_volume"] = bars["close"] * bars["volume"]

    # Realised-volatility controls, all backward looking.
    grouped = bars.groupby("symbol")
    bars["rv5"] = grouped["abs_ret"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["rv22"] = grouped["abs_ret"].transform(lambda s: s.rolling(22).mean().shift(1))
    bars["log_dv"] = np.log(bars["dollar_volume"].where(bars["dollar_volume"] > 0))

    # Outcomes strictly after the predictor date.
    bars["abs_ret_next"] = grouped["abs_ret"].shift(-1)
    bars["sq_ret_next"] = grouped["ret"].shift(-1) ** 2

    panel = inventory.rename(columns={"report_date": "date", "underlying": "symbol"}).merge(
        bars[
            [
                "symbol",
                "date",
                "abs_ret",
                "rv5",
                "rv22",
                "log_dv",
                "abs_ret_next",
                "sq_ret_next",
            ]
        ],
        on=["symbol", "date"],
        how="inner",
    )

    panel = panel.sort_values(["symbol", "date"])
    counts = panel.groupby("symbol")["date"].transform("size")
    panel = panel[counts >= min_history].copy()

    grouped = panel.groupby("symbol", sort=False)
    panel["log_oi"] = np.log(panel["open_interest"].clip(lower=1))
    panel["d_log_oi"] = grouped["log_oi"].diff()
    # Innovation relative to the underlying's own trailing level.
    panel["oi_innov"] = panel["log_oi"] - grouped["log_oi"].transform(
        lambda s: s.rolling(20, min_periods=5).mean().shift(1)
    )
    panel["near_share"] = panel["near_dated_open_interest"] / panel["open_interest"].clip(lower=1)
    panel["d_near_share"] = grouped["near_share"].diff()
    panel["put_share"] = panel["put_open_interest"] / panel["open_interest"].clip(lower=1)

    return panel.dropna(subset=["abs_ret_next", "rv5", "rv22", "oi_innov", "d_log_oi", "log_dv"])


def report(panel: pd.DataFrame, outcome: str, predictors: list[str], label: str) -> None:
    controls = ["rv5", "rv22", "abs_ret", "log_dv"]
    try:
        result = fit(panel, outcome, [*predictors, *controls], entity="symbol", time="date")
    except ValueError as exc:
        print(f"  {label:34s} SKIPPED ({exc})")
        return
    for name in predictors:
        est = result[name]
        flag = "  <<<" if abs(est.t_stat) > 2.5 else ""
        print(
            f"  {label:24s} {name:14s} b={est.coefficient:+.5f} "
            f"t={est.t_stat:+5.2f} MDE80={est.mde80:.5f} N={est.n_obs:,}{flag}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/raw"))
    parser.add_argument("--start", help="first FLEX activity date to load (YYYY-MM-DD)")
    parser.add_argument("--end", help="last FLEX activity date to load (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    panel = build(args.root, start=args.start, end=args.end)
    print(
        f"panel {len(panel):,} underlying-days | {panel.symbol.nunique()} underlyings | "
        f"{panel.date.nunique()} dates | {panel.date.min().date()} to {panel.date.max().date()}\n"
    )

    print("PREDICTING NEXT-DAY ABSOLUTE RETURN")
    report(panel, "abs_ret_next", ["oi_innov"], "inventory innovation")
    report(panel, "abs_ret_next", ["d_log_oi"], "inventory change")
    report(panel, "abs_ret_next", ["d_near_share"], "near-dated share change")
    report(panel, "abs_ret_next", ["put_share"], "put share")

    print("\nPREDICTING NEXT-DAY SQUARED RETURN")
    report(panel, "sq_ret_next", ["oi_innov"], "inventory innovation")
    report(panel, "sq_ret_next", ["d_log_oi"], "inventory change")

    print("\nPLACEBO: predictor dated one day AFTER the outcome")
    lead = panel.copy()
    lead["oi_innov_lead"] = lead.groupby("symbol")["oi_innov"].shift(-2)
    lead = lead.dropna(subset=["oi_innov_lead"])
    report(lead, "abs_ret_next", ["oi_innov_lead"], "future inventory")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
