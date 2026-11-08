"""Result `gamma_predictive`: does hidden dollar gamma predict next-day volatility?

Specification: `docs/log/2026-11-08-gamma-predictive-spec.md`, followed here line for line.
The base panel (sample, controls, outcomes, publication lag) is the `predictive`
result's. Gamma at each activity date comes from a walk over every report, priced as the
`positions` result prices it: each series at the volatility its own mark inverts to,
kept inside the validated cells, after same-strike pairs are netted.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.config import BARS_PATH, PANEL_END, RAW_DIR
from hidden_options.measure.flex_panel import daily_inventory, load_panel, panel_through
from hidden_options.measure.hidden_gamma import pair_netted
from hidden_options.measure.implied import RATE
from hidden_options.measure.panel import fit
from hidden_options.measure.positions_data import PositionsInputs
from hidden_options.measure.positions_data import load_inputs as load_position_inputs
from hidden_options.measure.positions_result import priced_rows
from hidden_options.predict.gamma_macros import gamma_predictive_macros
from hidden_options.predict.gamma_panel import (
    RAW_PREDICTORS,
    aggregate_gamma,
    gamma_predictors,
    range_outcome,
    standardise,
)
from hidden_options.predict.inference import N_PERM, SEED, holm, permutation_test
from hidden_options.predict.panel import CONTROLS, bars_through, build_predictive_panel
from hidden_options.predict.regressions import PredictiveRow
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "gamma_predictive"
PRIMARY, OUTCOME = "x_net", "abs_ret_next"
INTERACTION = "x_net_top"
ALPHA = 0.05
TOP_TERCILE = 2 / 3
# A null is "bounded" when the MDE per standard deviation is below this share of mean |r|.
BOUNDED_SHARE = 0.02
SECONDARY = (
    ("x_gross", OUTCOME),
    ("x_signed", OUTCOME),
    (PRIMARY, "oc_abs_next"),
    (PRIMARY, "range_next"),
    ("x_net_lead", OUTCOME),
)

logger = logging.getLogger(__name__)


def walk_gamma(inputs: PositionsInputs) -> pd.DataFrame:
    """`aggregate_gamma` on every report date, each priced at its own date's spots."""
    spots = inputs.spots.assign(date=pd.to_datetime(inputs.spots["date"]))
    by_day = dict(iter(spots.groupby("date", sort=False)))
    frames = []
    for day in inputs.dates:
        rows = inputs.read_day(day).reset_index(drop=True)
        rows = rows.assign(
            expiry=pd.to_datetime(rows["expiry"]).astype("datetime64[ns]"),
            report_date=pd.to_datetime(rows["report_date"]).astype("datetime64[ns]"),
        )
        rows = rows[rows["expiry"] > rows["report_date"]].reset_index(drop=True)
        today = by_day.get(day)
        spot = {} if today is None else dict(zip(today["underlying"], today["spot"], strict=True))
        netted = pair_netted(rows.assign(date=rows["report_date"]))["netted_oi"].to_numpy()
        priced = priced_rows(rows, spot, RATE, inputs.domain)
        frames.append(aggregate_gamma(priced.assign(date=priced["report_date"], netted_oi=netted)))
    return pd.concat(frames, ignore_index=True)


def gamma_panel(gamma: pd.DataFrame, flex_panel: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """The predictive panel with the gamma predictors, standardised on the main sample."""
    flex_panel = panel_through(flex_panel, PANEL_END)
    kinds = flex_panel.groupby("kind")["underlying"].unique()
    daily = daily_inventory(flex_panel)
    daily = daily[daily["underlying"].isin(set(kinds.get("equity", [])))]
    bars = bars_through(bars, pd.Timestamp(daily["available_at"].max()))
    panel = build_predictive_panel(daily, bars)
    panel = panel.merge(gamma_predictors(gamma, bars), on=["symbol", "date"], how="left")
    ranges = range_outcome(bars).rename(
        columns={"session": "available_at", "log_range": "range_next"}
    )
    panel = panel.merge(ranges, on=["symbol", "available_at"], how="left")
    sample = panel[[OUTCOME, *CONTROLS, "x_net_raw"]].notna().all(axis=1)
    for raw in RAW_PREDICTORS:
        panel[raw.removesuffix("_raw")] = standardise(panel[raw].where(sample))
    medians = panel[sample].groupby("symbol")["x_net_raw"].median()
    top = medians[medians >= medians.quantile(TOP_TERCILE)].index
    panel[INTERACTION] = panel[PRIMARY] * panel["symbol"].isin(top)
    return panel


def gamma_predictive_result(
    gamma: pd.DataFrame,
    flex_panel: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    n_perm: int = N_PERM,
    seed: int = SEED,
) -> Result:
    """The tests of record, the descriptive rows and the verdict the specification sets."""
    started = time.perf_counter()
    panel = gamma_panel(gamma, flex_panel, bars)
    h1 = _row(panel, PRIMARY, OUTCOME, [PRIMARY])
    h2 = _row(panel, INTERACTION, OUTCOME, [PRIMARY, INTERACTION])
    adjusted = holm({"h1": h1.p_value, "h2": h2.p_value})
    permutation = permutation_test(panel, OUTCOME, PRIMARY, CONTROLS, n_perm=n_perm, seed=seed)
    used = panel.dropna(subset=[OUTCOME, PRIMARY, *CONTROLS])
    mean_abs = float(used[OUTCOME].mean())
    values: dict[str, Any] = {
        "h1": {**asdict(h1), "holm_p": adjusted["h1"], "permutation_p": permutation.p_value},
        "h2": {**asdict(h2), "holm_p": adjusted["h2"]},
        "secondary": [asdict(_row(panel, x, y, [x])) for x, y in SECONDARY],
        "verdict": _verdict(h1, adjusted["h1"], mean_abs),
        "sample": _sample(panel, used, gamma, mean_abs),
        "settings": {
            "alpha": ALPHA,
            "bounded_share": BOUNDED_SHARE,
            "top_tercile": TOP_TERCILE,
            "n_perm": n_perm,
            "seed": seed,
        },
    }
    inputs = {
        "source": "data/raw/occ_flex",
        "bars": "data/flex_underlying_bars.parquet",
        "panel_end": f"{PANEL_END:%Y-%m-%d}",
        "first_date": f"{used['date'].min():%Y-%m-%d}",
        "last_date": f"{used['date'].max():%Y-%m-%d}",
    }
    logger.info("gamma_predictive: %d rows, %.0f s", len(used), time.perf_counter() - started)
    return Result(NAME, values, gamma_predictive_macros(values), inputs, now_iso())


@ANALYSES.register(NAME)
def gamma_predictive() -> Result:
    """The test on every FLEX report on disk up to PANEL_END and the refreshed bars."""
    gamma = walk_gamma(load_position_inputs())
    return gamma_predictive_result(gamma, load_panel(RAW_DIR), pd.read_parquet(BARS_PATH))


def _row(panel: pd.DataFrame, name: str, outcome: str, regressors: Sequence[str]) -> PredictiveRow:
    est = fit(panel, outcome, [*regressors, *CONTROLS], entity="symbol", time="date")
    return PredictiveRow.from_estimate(est[name], outcome, placebo=name.endswith("_lead"))


def _verdict(h1: PredictiveRow, holm_p: float, mean_abs: float) -> dict[str, Any]:
    mde_share = h1.mde80 / mean_abs
    if holm_p < ALPHA:
        kind = "finding"
    elif mde_share < BOUNDED_SHARE:
        kind = "bounded_null"
    else:
        kind = "inconclusive"
    return {"kind": kind, "mde_share": mde_share, "sign": float(np.sign(h1.coefficient))}


def _sample(
    panel: pd.DataFrame, used: pd.DataFrame, gamma: pd.DataFrame, mean_abs: float
) -> dict[str, Any]:
    in_panel = panel.dropna(subset=[OUTCOME, *CONTROLS])
    return {
        "underlying_days": len(used),
        "underlyings": int(used["symbol"].nunique()),
        "dates": int(used["date"].nunique()),
        "mean_abs_ret": mean_abs,
        "excluded_low_coverage": int((in_panel["coverage"] < 0.5).sum()),
        "base_underlying_days": len(in_panel),
        "median_coverage": float(used["coverage"].median()),
        "x_net_raw_median": float(used["x_net_raw"].median()),
        "x_net_raw_p90": float(used["x_net_raw"].quantile(0.9)),
        "x_net_sd": float(_winsorised_sd(used["x_net_raw"])),
        "gamma_dates": int(gamma["date"].nunique()),
    }


def _winsorised_sd(values: pd.Series) -> float:
    """The standard deviation one unit of the standardised predictor stands for."""
    low, high = values.quantile([0.01, 0.99])
    return float(values.clip(lower=low, upper=high).std(ddof=1))


__all__ = ["NAME", "gamma_panel", "gamma_predictive", "gamma_predictive_result", "walk_gamma"]
