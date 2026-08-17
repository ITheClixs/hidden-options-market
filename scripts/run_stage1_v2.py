#!/usr/bin/env python
"""Stage 1, revised. Fixes the two measurement weaknesses identified in the first run.

What changed
------------
1. **Dose is time-varying.** The first run applied each fund's current net assets
   across five years of history. Dose now steps with the N-PORT reported series and is
   undefined before a fund's first report rather than back-filled.

2. **Dose enters continuously.** Tercile splits threw away information and left the
   top bucket with about eight names and an MDE of 11.7%. A single interaction
   coefficient uses the whole cross-section and is the direct mechanism test.

3. **The roll weekday is scanned, not assumed.** The first run assumed Friday without
   verification. Every weekday is estimated and all five are reported. This is a
   five-way search, so a single nominally significant day is not evidence; the
   multiplicity is stated rather than hidden.

Specification:

    log(dollar volume)_it = a_i + d_t
                          + b1 post_it
                          + b2 (post_it x day_t)
                          + b3 (post_it x day_t x log_dose_it)
                          + b4 (post_it x log_dose_it)
                          + b5 (day_t x ever_treated_i)
                          + g  |return|_it + e_it

b3 is the estimand: does the day-of-week volume footprint scale with programme size?
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.collect.http import build_session  # noqa: E402
from absorb.collect.nport import as_of_series  # noqa: E402
from absorb.config import RAW_DIR, load_programmes, load_universe  # noqa: E402
from absorb.measure.panel import fit  # noqa: E402
from run_stage1 import daily_bars, fund_launch_dates  # noqa: E402

WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}


def attach_dose(panel: pd.DataFrame, reports: pd.DataFrame, launches: pd.DataFrame) -> pd.DataFrame:
    """Add a time-varying dose: reported net assets over trailing dollar ADV."""
    fund_by_symbol = dict(zip(launches["symbol"], launches["fund"], strict=True))

    net_assets = pd.Series(np.nan, index=panel.index)
    for symbol, group in panel.groupby("symbol"):
        fund = fund_by_symbol.get(symbol)
        if fund:
            net_assets.loc[group.index] = as_of_series(reports, group["date"], fund)

    out = panel.copy()
    out["net_assets"] = net_assets
    out["dose"] = out["net_assets"] / out["adv"]
    # Centred so the level coefficient is read at mean dose rather than at dose = 1.
    out["log_dose"] = np.log(out["dose"].where(out["dose"] > 0))
    out["log_dose"] = (out["log_dose"] - out["log_dose"].mean()).fillna(0.0)
    return out


def run_for_day(panel: pd.DataFrame, label: str, weekday: int) -> None:
    frame = panel.copy()
    day = (frame["date"].dt.weekday == weekday).astype(float)
    frame["post_day"] = frame["post"] * day
    frame["post_day_dose"] = frame["post_day"] * frame["log_dose"]
    frame["post_dose"] = frame["post"] * frame["log_dose"]
    frame["day_treated"] = day * frame["ever_treated"]

    regressors = ["post", "post_day", "post_day_dose", "post_dose", "day_treated", "abs_ret"]
    try:
        result = fit(frame, "log_dv", regressors)
    except ValueError as exc:
        print(f"  {label:5s} SKIPPED ({exc})")
        return

    level, dose = result["post_day"], result["post_day_dose"]
    print(
        f"  {label:5s} level b={level.coefficient:+.4f} (t={level.t_stat:+5.2f})   "
        f"dose-response b={dose.coefficient:+.4f} (t={dose.t_stat:+5.2f}, "
        f"MDE80={dose.mde80:.4f})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback", default="5y")
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    reports_path = args.root / "nport" / "net_assets.parquet"
    if not reports_path.exists():
        print(f"missing {reports_path}; run scripts/fetch_nport.py first", file=sys.stderr)
        return 1
    reports = pd.read_parquet(reports_path)

    session = build_session()
    programmes = [p for p in load_programmes() if not p.underlying.startswith("_")]
    universe = load_universe()

    launches = fund_launch_dates(session, programmes)
    launches = launches.sort_values("launch").drop_duplicates("symbol", keep="first")
    treated = sorted(set(launches["symbol"]))
    controls = [s for s in universe.control_single_name if s not in treated]

    bars = daily_bars(session, treated + controls, args.lookback)

    from run_stage1 import build_panel  # noqa: PLC0415

    panel = build_panel(bars, launches, pd.DataFrame(columns=["symbol", "net_assets"]))
    panel = attach_dose(panel, reports, launches)

    covered = panel[(panel["post"] == 1) & panel["dose"].notna()]
    print(
        f"panel {len(panel):,} obs | {panel.symbol.nunique()} names | "
        f"{panel.date.nunique():,} dates\n"
        f"treated post-launch obs with a dose: {len(covered):,} "
        f"across {covered.symbol.nunique()} names\n"
        f"dose (net assets / ADV) p25/p50/p75: "
        f"{covered.dose.quantile([0.25, 0.5, 0.75]).round(2).tolist()}"
    )

    print("\n--- WEEKDAY SCAN (5 tests; treat any single hit with suspicion) ---")
    for label, weekday in WEEKDAYS.items():
        run_for_day(panel, label, weekday)

    print("\n--- FALSIFICATION: dose permuted across treated names ---")
    rng = np.random.default_rng(0)
    shuffled = panel.copy()
    per_name = shuffled.groupby("symbol")["log_dose"].mean()
    treated_names = [s for s in per_name.index if s in set(treated)]
    permuted = dict(
        zip(treated_names, rng.permutation(per_name.loc[treated_names].to_numpy()), strict=True)
    )
    shuffled["log_dose"] = shuffled["symbol"].map(permuted).fillna(0.0)
    run_for_day(shuffled, "Fri", 4)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
