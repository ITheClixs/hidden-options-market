"""Result `identification`: the off-grid strike rule scored on the census (M3).

The census is OCC's series search for every symbol with listed weekly options, captured
once and dated by its listed side as the hidden-share result dates it, with the same
loaders. The rule is scored on the census lines `identification.scored_series` keeps,
and the result says how many lines were left out and why, so the series count can be
traced back to what the search returned. Beside the score sit what explains it: where
FLEX and listed strikes sit on the grid, the listed series the rule flags, and the
largest FLEX series on a whole-dollar strike as an example. `identification_macros`
formats what the paper and README print.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from hidden_options.config import PANEL_END, RAW_DIR
from hidden_options.measure.hidden_share import is_adjusted_product
from hidden_options.measure.hidden_share_data import (
    CaptureDate,
    chain_open_interest,
    date_capture,
    load_census,
    load_chains,
    trading_calendar,
)
from hidden_options.measure.identification import (
    GROUPS,
    MEASURES,
    grid_shares,
    score_strike_rule,
    scored_series,
)
from hidden_options.measure.identification_macros import identification_macros
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import RESULTS_DIR, Result, now_iso, read_results

NAME = "identification"
CENSUS_RESULT = "hidden_share"
# The underlyings with the most flagged listed series are named in the text.
FLAGGED_NAMED = 3


def identification_result(census: pd.DataFrame, dated: CaptureDate) -> Result:
    """The `identification` result from the census rows and the settlement they show."""
    series = scored_series(census)
    ordinary = census[~census["product_symbol"].astype(str).map(is_adjusted_product)]
    shares = grid_shares(series)
    values: dict[str, Any] = {
        "census": _counts(census, series, dated),
        "rule": score_strike_rule(series).as_dict(),
        "rule_open_interest": score_strike_rule(series, weight="open_interest").as_dict(),
        "rule_with_empty": score_strike_rule(ordinary).as_dict(),
        "grid": {
            group: {
                measure: {str(k): float(v) for k, v in shares[f"{group}_{measure}"].items()}
                for measure in MEASURES
            }
            for group in GROUPS
        },
        "listed_flagged": _listed_flagged(series),
        "largest_whole_dollar": _largest_whole_dollar(series),
    }
    run_inputs = {
        "sources": {
            "census": "data/raw/occ_census",
            "chains": "data/raw/cboe_chain (to date the census)",
        },
        "census_rows": len(census),
    }
    return Result(NAME, values, identification_macros(values), run_inputs, now_iso())


@ANALYSES.register(NAME)
def identification_analysis() -> Result:
    """M3 on the census on disk, refused if it is not the census `hidden_share` describes."""
    census, dated = load_dated_census()
    _check_census(dated, RESULTS_DIR)
    return identification_result(census, dated)


def load_dated_census(raw: Path | None = None) -> tuple[pd.DataFrame, CaptureDate]:
    """The census rows and the settlement their listed side shows.

    Dated as `hidden_share_result.census_view` dates it, from the local Cboe chains: the
    census needs no CI capture, and the local chains date it on their own. Only settlements
    up to PANEL_END count.
    """
    raw = RAW_DIR if raw is None else raw
    end = pd.Timestamp(PANEL_END)
    census = load_census(raw)
    chain_oi = chain_open_interest(load_chains(raw, trading_calendar(raw, end)))
    chain_oi = chain_oi[chain_oi["date"] <= end]
    return census, date_capture(census, chain_oi)


def _check_census(dated: CaptureDate, results: Path) -> None:
    """Refuse a census dated otherwise than the committed `hidden_share` census.

    The paper names the census date once, from `hidden_share`, for both results.
    """
    stored = read_results(results).get(CENSUS_RESULT)
    if stored is None:
        return
    expected = stored.values["census"]["date"]
    if formats.iso_date(dated.date) != expected:
        raise ValueError(
            f"The census on disk shows the {formats.iso_date(dated.date)} settlement, but "
            f"results/{CENSUS_RESULT}.json describes the census of {expected}; run "
            f"`hidden-options results --only {CENSUS_RESULT}` first"
        )


def _counts(census: pd.DataFrame, series: pd.DataFrame, dated: CaptureDate) -> dict[str, Any]:
    """How many lines the search returned, how many were left out and why, how many scored."""
    adjusted = int(census["product_symbol"].astype(str).map(is_adjusted_product).sum())
    flex = int(series["flex"].sum())
    return {
        "date": formats.iso_date(dated.date),
        "support": dated.support,
        "compared": dated.compared,
        "symbols": int(census["symbol"].nunique()),
        "rows": len(census),
        "adjusted": adjusted,
        "empty": len(census) - adjusted - len(series),
        "series": len(series),
        "flex": flex,
        "listed": len(series) - flex,
        "flex_underlyings": int(series.loc[series["flex"], "symbol"].nunique()),
    }


def _listed_flagged(series: pd.DataFrame) -> dict[str, Any]:
    """The listed series off the grid: on how many underlyings, and the most-flagged ones."""
    flagged = series[~series["flex"] & (series["grid"] == "off_grid")]
    # Alphabetical first, so names with equal counts come out in a fixed order.
    per = flagged.groupby(flagged["symbol"].astype(str)).size().sort_index()
    top = per.sort_values(ascending=False, kind="stable").head(FLAGGED_NAMED)
    return {
        "underlyings": len(per),
        "top": [{"symbol": str(name), "series": int(n)} for name, n in top.items()],
        "top_share": float(top.sum() / len(flagged)) if len(flagged) else 0.0,
    }


def _largest_whole_dollar(series: pd.DataFrame) -> dict[str, Any]:
    """The FLEX series with the most open interest on a whole-dollar strike."""
    candidates = series[series["flex"] & (series["grid"] == "dollar")]
    if candidates.empty:
        raise ValueError("No FLEX series sits on a whole-dollar strike in the census")
    order = candidates.sort_values(
        ["open_interest", "product_symbol", "expiry", "strike"],
        ascending=[False, True, True, True],
    )
    line = order.iloc[0]
    return {
        "symbol": str(line["symbol"]),
        "product_symbol": str(line["product_symbol"]),
        "expiry": formats.iso_date(pd.Timestamp(line["expiry"])),
        "strike": float(line["strike"]),
        "open_interest": int(line["open_interest"]),
    }
