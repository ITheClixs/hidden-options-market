"""Result `implied_validation`: volatilities backed out of OCC's marks, checked against the
listed chain (M5).

Every FLEX row on a report date with a chain reading after the close is inverted at the
constant rate, each with a status. Where a row has a listed twin (`compare_with_listed`)
its volatility is set against Cboe's, and the agreement is summarised overall, by
moneyness and days to expiry, by how the class heading gave the exercise style, and at
two other rates. The buckets where the two agree are the validated domain later results
may use. `implied_macros` formats what the paper prints.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.config import PANEL_END
from hidden_options.measure.implied import (
    CARRY,
    DAYS_PER_YEAR,
    DTE_LABELS,
    MAX_MEDIAN_DIFF,
    MIN_MATCHED,
    MONEYNESS_LABELS,
    PREFIX_STYLES,
    RATE,
    SIGMA_BOUNDS,
    InversionStatus,
    bucketed,
    compare_with_listed,
    implied_vols_frame,
    product_prefix,
    validated_domain,
)
from hidden_options.measure.implied_data import (
    RESULT_NAME,
    SPOT_AGREEMENT,
    STYLE_GROUPS,
    ImpliedInputs,
    close_readings,
    equity_closes,
    load_inputs,
    overlap_dates,
    reading_agreement,
    spot_table,
    style_groups,
    usable_listed,
    with_spots,
)
from hidden_options.measure.implied_macros import implied_macros
from hidden_options.measure.pricing import TREE_STEPS
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = RESULT_NAME
# Two vol points: the agreement the share "within" counts.
WITHIN = 0.02
SENSITIVITY_RATES = (0.03, 0.05)
# A call struck below this share of spot is deep in the money.
DEEP_MONEYNESS = 0.9
# The underlyings with the most marks below the model's floor are named.
BELOW_NAMED = 5
STATUSES = tuple(status.value for status in InversionStatus)
# The FLEX columns a row is inverted from, kept through the comparison.
FLEX_COLUMNS = (
    "report_date",
    "kind",
    "class_name",
    "root",
    "underlying",
    "right",
    "expiry",
    "strike",
    "mark_price",
    "open_interest",
    "exercise_style",
    "spot",
)


def implied_validation_result(inputs: ImpliedInputs) -> Result:
    """The `implied_validation` result from loaded inputs, up to the frozen PANEL_END."""
    report_dates = pd.to_datetime(inputs.panel["report_date"])
    panel = inputs.panel[report_dates <= pd.Timestamp(PANEL_END)]
    readings = close_readings(inputs.chains)
    closes = equity_closes(inputs.bars)
    agreement = reading_agreement(readings, closes)
    listed = usable_listed(readings, agreement)
    dates = overlap_dates(panel, readings)
    in_window = pd.to_datetime(panel["report_date"]).isin(dates)
    window = panel[in_window].reset_index(drop=True)
    spots = spot_table(readings, closes)
    rows = invert(with_spots(window, spots), RATE)
    validation = compare_with_listed(rows, listed)
    domain = validated_domain(validation, max_median_diff=MAX_MEDIAN_DIFF, min_matched=MIN_MATCHED)
    values: dict[str, Any] = {
        "settings": _settings(),
        "window": {
            "first_date": formats.iso_date(dates[0]),
            "last_date": formats.iso_date(dates[-1]),
            "dates": len(dates),
            "rows": len(rows),
            "panel_end": formats.iso_date(pd.Timestamp(PANEL_END)),
        },
        "spots": _spots(rows, spots, agreement),
        "coverage": _coverage(rows),
        "styles": _styles(panel, rows),
        "validation": _validation(validation),
        "domain": _domain(domain, validation, rows),
        "rates": {f"{rate:.2f}": _at_rate(validation, listed, rate) for rate in SENSITIVITY_RATES},
    }
    run_inputs = {
        "sources": {
            "flex": "data/raw/occ_flex",
            "chains": "data/raw/cboe_chain, data/ci_captures/*/raw/cboe_chain",
            "bars": "data/flex_underlying_bars.parquet",
        },
        "ci_runs": list(inputs.ci_runs),
        "local_only": inputs.local_only,
        "panel_end": formats.iso_date(pd.Timestamp(PANEL_END)),
        "panel_rows": len(panel),
        "chain_rows": len(inputs.chains),
        "bar_rows": len(inputs.bars),
    }
    return Result(NAME, values, implied_macros(values), run_inputs, now_iso())


@ANALYSES.register(NAME)
def implied_validation_analysis() -> Result:
    """M5 on the panel, chains and bars on disk."""
    return implied_validation_result(load_inputs())


def invert(frame: pd.DataFrame, rate: float) -> pd.DataFrame:
    """`frame` inverted at `rate`, with its buckets and style group."""
    inverted = bucketed(implied_vols_frame(frame, rate=rate, carry=CARRY))
    return inverted.assign(group=style_groups(frame))


def gap_stats(diff: pd.Series) -> dict[str, Any]:
    """How far FLEX volatilities sit from listed ones: count, median |gap|, share within
    two vol points, median signed gap. A group with nothing in it has None for each."""
    gaps = diff[np.isfinite(diff.to_numpy(dtype=float))].astype(float)
    if gaps.empty:
        return {"n": 0, "median_abs": None, "within": None, "median_diff": None}
    return {
        "n": len(gaps),
        "median_abs": float(gaps.abs().median()),
        "within": float((gaps.abs() <= WITHIN).mean()),
        "median_diff": float(gaps.median()),
    }


def _settings() -> dict[str, Any]:
    return {
        "rate": RATE,
        "carry": CARRY,
        "sensitivity_rates": list(SENSITIVITY_RATES),
        "prefix_styles": dict(PREFIX_STYLES),
        "sigma_bounds": list(SIGMA_BOUNDS),
        "tree_steps": TREE_STEPS,
        "days_per_year": DAYS_PER_YEAR,
        "within": WITHIN,
        "max_median_diff": MAX_MEDIAN_DIFF,
        "min_matched": MIN_MATCHED,
        "spot_agreement": SPOT_AGREEMENT,
        "deep_moneyness": DEEP_MONEYNESS,
    }


def _spots(rows: pd.DataFrame, spots: pd.DataFrame, agreement: pd.DataFrame) -> dict[str, Any]:
    """Which underlying-dates of the window have a spot, from where, and the chain check."""
    pairs = rows[["report_date", "underlying"]].drop_duplicates()
    pairs = pairs.assign(date=pd.to_datetime(pairs["report_date"]).astype("datetime64[ns]"))
    found = pairs.merge(spots, on=["date", "underlying"], how="inner")
    in_window = agreement[agreement["date"].isin(set(pairs["date"]))]
    return {
        "pairs": len(pairs),
        "with_spot": len(found),
        "by_source": _counts(found["source"]),
        "agreement": {
            "readings": len(in_window),
            "set_aside": int((~in_window["agrees"]).sum()),
            "median_abs_rel": float(in_window["rel_diff"].abs().median()),
        },
    }


def _coverage(rows: pd.DataFrame) -> dict[str, Any]:
    """Every row's status, overall and by kind, and what the rows without a volatility are."""
    status = rows["iv_status"]
    below = rows[status == InversionStatus.BELOW_INTRINSIC.value]
    deep = (below["right"] == "C") & (below["moneyness"] < DEEP_MONEYNESS)
    no_spot = rows.loc[status == InversionStatus.NO_SPOT.value, "underlying"]
    return {
        "rows": len(rows),
        "by_status": _counts(status, STATUSES),
        "by_kind": {
            str(kind): _counts(group["iv_status"], STATUSES)
            for kind, group in rows.groupby("kind", sort=True)
        },
        "below_intrinsic": _below(below, deep),
        "no_spot_underlyings": sorted(set(no_spot.astype(str))),
    }


def _below(below: pd.DataFrame, deep: pd.Series) -> dict[str, Any]:
    """Marks below the floor: how many, how many on deep in-the-money calls, and on whom."""
    per = below.groupby(below["underlying"].astype(str)).size().sort_index()
    top = per.sort_values(ascending=False, kind="stable").head(BELOW_NAMED)
    return {
        "rows": len(below),
        "deep_calls": int(deep.sum()),
        "top": [{"symbol": str(name), "rows": int(n)} for name, n in top.items()],
        "top_share": _share(top.sum(), len(below)),
    }


def _styles(panel: pd.DataFrame, rows: pd.DataFrame) -> dict[str, Any]:
    """Where the equity exercise style comes from, over the panel and the window, and how
    well the product symbol's prefix agrees with the headings that name a style."""
    equity = panel[panel["kind"] == "equity"]
    groups = style_groups(equity)
    named = groups.isin(["strict", "clipped"])
    expected = product_prefix(equity["root"]).map(dict(PREFIX_STYLES))
    style = equity["exercise_style"].astype(object)
    known = expected.notna()
    return {
        "panel": _group_shares(groups),
        "window": _group_shares(rows.loc[rows["kind"] == "equity", "group"]),
        "prefix_agreement": {
            "checked": int(named.sum()),
            "agree": int((named & known & (style == expected)).sum()),
            "contradict": int((named & known & (style != expected)).sum()),
            "other": int((named & ~known).sum()),
        },
    }


def _group_shares(groups: pd.Series) -> dict[str, Any]:
    counts = _counts(groups, STYLE_GROUPS[:4])
    total = sum(counts.values())
    unread = counts["prefix"] + counts["fallback"]
    return {
        "equity_rows": total,
        "by_group": counts,
        "unread_share": unread / total if total else None,
    }


def _validation(validation: pd.DataFrame) -> dict[str, Any]:
    """Matched rows and their gaps, overall and by every split the paper reports."""
    series = validation[["root", "expiry", "right", "strike"]].drop_duplicates()
    diff = validation["diff"]
    return {
        "matched": len(validation),
        "matched_series": len(series),
        "by_status": _counts(validation["iv_status"]),
        "compared": int(np.isfinite(diff.to_numpy(dtype=float)).sum()),
        "overall": gap_stats(diff),
        "by_kind": _split(validation, ["kind"], [["equity", "index"]]),
        "by_right": _split(validation, ["right"], [["C", "P"]]),
        "by_moneyness": _split(validation, ["moneyness_bucket"], [MONEYNESS_LABELS]),
        "by_dte": _split(validation, ["dte_bucket"], [DTE_LABELS]),
        "by_bucket": _split(
            validation, ["moneyness_bucket", "dte_bucket"], [MONEYNESS_LABELS, DTE_LABELS]
        ),
        "by_group": _split(validation, ["group"], [STYLE_GROUPS]),
        "by_group_right": _split(validation, ["group", "right"], [STYLE_GROUPS, ["C", "P"]]),
    }


def _split(
    frame: pd.DataFrame, columns: Sequence[str], levels: Sequence[Iterable[str]]
) -> dict[str, dict[str, Any]]:
    """`gap_stats` for every combination of `levels`, keyed `a|b`; empty ones included."""
    grouped = {
        key if isinstance(key, tuple) else (key,): group["diff"]
        for key, group in frame.groupby(list(columns), sort=False)
    }
    empty = pd.Series(dtype=float)
    keys = pd.MultiIndex.from_product([list(level) for level in levels])
    return {"|".join(map(str, key)): gap_stats(grouped.get(tuple(key), empty)) for key in keys}


def _domain(
    domain: frozenset[tuple[str, str]], validation: pd.DataFrame, rows: pd.DataFrame
) -> dict[str, Any]:
    """The validated buckets, and how much of the comparison and of the book they hold."""
    compared = validation[np.isfinite(validation["diff"].to_numpy(dtype=float))]
    ok = rows["iv_status"] == InversionStatus.OK.value
    oi = rows["open_interest"].astype(float)
    return {
        "cells": len(domain),
        "of_cells": len(MONEYNESS_LABELS) * len(DTE_LABELS),
        "buckets": [list(cell) for cell in sorted(domain)],
        "failing_short": sum((m, DTE_LABELS[0]) not in domain for m in MONEYNESS_LABELS),
        "compared_share": _share(_in(compared, domain).sum(), len(compared)),
        "ok_open_interest": _share(oi[ok].sum(), oi.sum()),
        "usable_open_interest": _share(oi[ok & _in(rows, domain)].sum(), oi.sum()),
    }


def _at_rate(validation: pd.DataFrame, listed: pd.DataFrame, rate: float) -> dict[str, Any]:
    """The matched rows inverted again at `rate` and compared again."""
    again = compare_with_listed(invert(validation[list(FLEX_COLUMNS)], rate), listed)
    domain = validated_domain(again, max_median_diff=MAX_MEDIAN_DIFF, min_matched=MIN_MATCHED)
    return {
        "rate": rate,
        "overall": gap_stats(again["diff"]),
        "by_right": _split(again, ["right"], [["C", "P"]]),
        "domain_cells": len(domain),
    }


def _in(frame: pd.DataFrame, domain: frozenset[tuple[str, str]]) -> pd.Series:
    pairs = zip(frame["moneyness_bucket"], frame["dte_bucket"], strict=True)
    cells = pd.Series(list(pairs), index=frame.index, dtype=object)
    return cells.isin(domain)


def _counts(values: pd.Series, keys: Iterable[str] | None = None) -> dict[str, int]:
    counts = values.astype(str).value_counts()
    names = sorted(counts.index) if keys is None else list(keys)
    return {str(name): int(counts.get(name, 0)) for name in names}


def _share(part: float, whole: float) -> float | None:
    return float(part / whole) if whole else None
