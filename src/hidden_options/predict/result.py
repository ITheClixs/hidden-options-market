"""Result `predictive` and its two tables: the predictive null on the full panel (P1).

Everything the paper's predictive section and the README's null section print is
computed here: the six table rows with a permutation p-value each, the main predictor's
permutation distribution, longer horizons, the restriction to large inventory changes,
the open-to-close timing check, and the main row and placebo with the panel loaded from
later start dates.

Index underlyings are left out. Bars are fetched only for the equity report's tickers,
and a bare index symbol (SPX, NDX) names another security on the bar provider, or none;
the index itself is a different symbol there. Equity underlyings whose symbols the
provider does not serve have no bars and drop out at the join. The result names them and
counts them by reason: OCC's adjusted-deliverable roots (GME1) and share-class spellings
(BRKB), whose stocks still trade under other symbols, and other tickers, which include
delisted and renamed names. Only that last group tilts the sample towards names still
trading.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.collect.bars import (
    MIN_ACTIVITY_DATES,
    MISSING_BAR_REASONS,
    flex_underlyings,
    missing_bar_reason,
)
from hidden_options.config import BARS_PATH, RAW_DIR
from hidden_options.measure.flex_panel import daily_inventory, load_panel
from hidden_options.predict.inference import N_PERM, SEED, permutation_test
from hidden_options.predict.macros import predictive_macros
from hidden_options.predict.panel import CONTROLS, build_predictive_panel
from hidden_options.predict.regressions import (
    MAIN_OUTCOME,
    MAIN_PREDICTOR,
    TABLE_SPECS,
    TOP_SHARE,
    PredictiveRow,
    horizon_rows,
    run_predictive,
    timing_row,
    top_decile_row,
    window_robustness,
)
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "predictive"

# Keys for the six table rows, in TABLE_SPECS order.
ROW_KEYS = ("innovation", "change", "near_share", "put_share", "innovation_squared", "placebo")

# Later starts for the window check: the start of the window the paper used before the
# panel was extended back, and the start of the sample its table was estimated on.
LATER_STARTS = ("2025-07-23", "2025-09-09")

# Null draws are stored for the figure, rounded far below anything it can show.
_NULL_DIGITS = 10

logger = logging.getLogger(__name__)


def predictive_result(
    flex_panel: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    n_perm: int = N_PERM,
    seed: int = SEED,
    later_starts: Sequence[str] = LATER_STARTS,
) -> Result:
    """The `predictive` result for an assembled FLEX panel and the underlyings' bars."""
    started = time.perf_counter()
    kinds = flex_panel.groupby("kind")["underlying"].unique()
    equity = set(kinds.get("equity", []))
    daily = daily_inventory(flex_panel)
    daily = daily[daily["underlying"].isin(equity)]
    panel = build_predictive_panel(daily, bars)

    rows = run_predictive(panel)
    permutations = {
        key: permutation_test(panel, row.outcome, row.predictor, CONTROLS, n_perm=n_perm, seed=seed)
        for key, row in zip(ROW_KEYS, rows, strict=True)
    }
    main_null = permutations["innovation"]
    decile, cut = top_decile_row(panel)
    first = f"{daily['report_date'].min():%Y-%m-%d}"
    windows = window_robustness(daily, bars, [first, *later_starts])

    values: dict[str, Any] = {
        "sample": _sample(panel, rows[0], flex_panel, kinds, bars),
        "controls": list(CONTROLS),
        "rows": [
            {"key": key, **asdict(row), "permutation_p": permutations[key].p_value}
            for key, row in zip(ROW_KEYS, rows, strict=True)
        ],
        "permutation": {
            "predictor": MAIN_PREDICTOR,
            "outcome": MAIN_OUTCOME,
            "n_perm": n_perm,
            "seed": seed,
            "observed": main_null.observed,
            "p_value": main_null.p_value,
            "null_mean": float(main_null.null.mean()),
            "null_sd": float(main_null.null.std(ddof=1)),
            "null_low": float(np.quantile(main_null.null, 0.025)),
            "null_high": float(np.quantile(main_null.null, 0.975)),
            "null": [round(float(x), _NULL_DIGITS) for x in main_null.null],
        },
        "horizons": [
            {"days": int(row.outcome.split("_")[-1].rstrip("d")), **asdict(row)}
            for row in horizon_rows(panel)
        ],
        "top_decile": {**asdict(decile), "share": TOP_SHARE, "threshold": cut},
        "timing": asdict(timing_row(panel)),
        "windows": [
            {"start": start, "main": asdict(main), "placebo": asdict(placebo)}
            for start, main, placebo in zip(
                [first, *later_starts], windows[::2], windows[1::2], strict=True
            )
        ],
    }
    values["max_abs_t"] = _max_abs_t(values)
    inputs = {
        "source": "data/raw/occ_flex",
        "bars": "data/flex_underlying_bars.parquet",
        "first_date": first,
        "last_date": f"{daily['report_date'].max():%Y-%m-%d}",
        "dates": int(daily["report_date"].nunique()),
        "bar_symbols": int(bars["symbol"].nunique()),
        "bar_rows": len(bars),
    }
    logger.info(
        "predictive: %d underlying-days, %d permutations per row, %.0f s",
        len(panel),
        n_perm,
        time.perf_counter() - started,
    )
    return Result(NAME, values, predictive_macros(values), inputs, now_iso())


@ANALYSES.register(NAME)
def predictive() -> Result:
    """P1 on every FLEX report on disk and the refreshed bars."""
    return predictive_result(load_panel(RAW_DIR), pd.read_parquet(BARS_PATH))


def _sample(
    panel: pd.DataFrame,
    main: PredictiveRow,
    flex_panel: pd.DataFrame,
    kinds: pd.Series,
    bars: pd.DataFrame,
) -> dict[str, Any]:
    """The main row's estimation sample, what was left out of it, and the scale its
    coefficients are read against."""
    used = panel.dropna(subset=[MAIN_PREDICTOR, MAIN_OUTCOME, *CONTROLS])
    qualifying = flex_underlyings(flex_panel)
    without_bars = sorted(set(qualifying) - set(bars["symbol"]))
    reasons = [missing_bar_reason(symbol) for symbol in without_bars]
    return {
        "qualifying_underlyings": len(qualifying),
        "qualifying_min_dates": MIN_ACTIVITY_DATES,
        "without_bars": without_bars,
        "without_bars_by_reason": {reason: reasons.count(reason) for reason in MISSING_BAR_REASONS},
        "underlying_days": main.n_obs,
        "underlyings": main.n_underlyings,
        "dates": main.n_dates,
        "first_date": f"{used['date'].min():%Y-%m-%d}",
        "last_date": f"{used['date'].max():%Y-%m-%d}",
        "equity_underlyings": int(len(kinds.get("equity", []))),
        "index_underlyings": int(len(kinds.get("index", []))),
        "mean_abs_ret": float(used[MAIN_OUTCOME].mean()),
        "median_abs_ret": float(used[MAIN_OUTCOME].median()),
        "panel_rows": len(panel),
        "report_dates": int(flex_panel["report_date"].nunique()),
    }


def _max_abs_t(values: Mapping[str, Any]) -> float:
    """The largest |t| among the genuine (non-placebo) estimates the result reports."""
    genuine = [row for row in values["rows"] if not row["placebo"]]
    genuine += values["horizons"]
    genuine += [values["top_decile"], values["timing"]]
    genuine += [window["main"] for window in values["windows"]]
    return max(abs(float(row["t_stat"])) for row in genuine)


__all__ = ["LATER_STARTS", "NAME", "ROW_KEYS", "TABLE_SPECS", "predictive_result"]
