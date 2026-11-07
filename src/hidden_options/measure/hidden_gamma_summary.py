"""Summaries of the hidden-gamma frames, as the specification lists them.

Every function here takes the frames `hidden_gamma` builds and returns plain numbers, so
the result module only loads data and calls these. See
`docs/log/2026-11-07-hidden-gamma-spec.md` for what each figure is.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

RULES = ("share_gross", "share_netted", "share_netted_both")
THRESHOLDS = (0.05, 0.10, 0.25)
DAY_EDGES = (0, 7, 30, 90)
DAY_LABELS = ("<=7", "8-30", "31-90", ">90")
MONEYNESS_EDGES = (0.8, 0.95, 1.05, 1.2)
MONEYNESS_LABELS = ("<0.80", "0.80-0.95", "0.95-1.05", "1.05-1.20", ">=1.20")
OTHER = "other"


def per_underlying(shares: pd.DataFrame, groups: Mapping[str, str]) -> pd.DataFrame:
    """Each underlying's median share over its settlements, under each rule, with its group."""
    medians = shares.groupby("symbol")[[*RULES, "listed_gross"]].median()
    medians["settlements"] = shares.groupby("symbol").size()
    medians["group"] = [groups.get(str(symbol), OTHER) for symbol in medians.index]
    return medians.sort_index()


def distribution(medians: pd.DataFrame, groups: Sequence[str]) -> dict[str, Any]:
    """Across underlyings, per rule: quartiles, counts at the thresholds, group medians."""
    out: dict[str, Any] = {}
    for rule in RULES:
        values = medians[rule]
        out[rule] = {
            "median": float(values.median()),
            "q25": float(values.quantile(0.25)),
            "q75": float(values.quantile(0.75)),
            "at_least": {f"{t:.2f}": int((values >= t).sum()) for t in THRESHOLDS},
            "by_group": {
                group: _median_or_none(values[medians["group"] == group]) for group in groups
            },
            "group_counts": {group: int((medians["group"] == group).sum()) for group in groups},
        }
    return out


def pooled(shares: pd.DataFrame) -> dict[str, float]:
    """Each rule's share of the sum over every underlying-settlement, so large books weigh."""
    flex_gross, flex_netted = shares["flex_gross"].sum(), shares["flex_netted"].sum()
    listed_gross, listed_netted = shares["listed_gross"].sum(), shares["listed_netted"].sum()
    return {
        "share_gross": float(flex_gross / (flex_gross + listed_gross)),
        "share_netted": float(flex_netted / (flex_netted + listed_gross)),
        "share_netted_both": float(flex_netted / (flex_netted + listed_netted)),
    }


def where(flex: pd.DataFrame) -> dict[str, dict[str, dict[str, float]]]:
    """Share of FLEX dollar gamma, gross and netted, by days to expiry and by moneyness."""
    days = pd.cut(flex["days"], [*DAY_EDGES, np.inf], labels=list(DAY_LABELS))
    moneyness = pd.cut(
        flex["moneyness"],
        [0.0, *MONEYNESS_EDGES, np.inf],
        labels=list(MONEYNESS_LABELS),
        right=False,
    )
    return {"days": _split(flex, days), "moneyness": _split(flex, moneyness)}


def signed_view(shares: pd.DataFrame) -> dict[str, float]:
    """Under the vendor convention: how often adding FLEX flips the listed sign, and the
    median size of the FLEX term relative to the listed figure."""
    listed = shares["listed_signed"]
    total = listed + shares["flex_signed"]
    usable = listed != 0
    flips = np.sign(total[usable]) != np.sign(listed[usable])
    relative = (shares["flex_signed"][usable] / listed[usable]).abs()
    return {
        "flip_share": float(flips.mean()) if usable.any() else float("nan"),
        "median_relative": float(relative.median()) if usable.any() else float("nan"),
        "underlying_days": int(usable.sum()),
    }


def mark_check(flex: pd.DataFrame, mark_sigma: pd.Series, gamma_at: pd.Series) -> dict[str, Any]:
    """Gamma from the FLEX marks against gamma from the listed surface, on the series
    whose mark volatility is validated.

    `mark_sigma` is NaN outside the validated domain; `gamma_at` is the gross dollar gamma
    of each series recomputed at its mark volatility, aligned with `flex`.
    """
    ok = mark_sigma.notna() & gamma_at.notna()
    total_oi = flex["open_interest"].sum()
    surface, marks = flex.loc[ok, "gross"].sum(), gamma_at[ok].sum()
    gaps = (mark_sigma[ok] - flex.loc[ok, "sigma"]).abs()
    return {
        "oi_share": float(flex.loc[ok, "open_interest"].sum() / total_oi) if total_oi else 0.0,
        "gamma_ratio": float(marks / surface) if surface else float("nan"),
        "median_vol_gap": float(gaps.median()) if ok.any() else float("nan"),
        "series": int(ok.sum()),
    }


def _split(flex: pd.DataFrame, labels: pd.Series) -> dict[str, dict[str, float]]:
    sums = flex.groupby(labels, observed=False)[["gross", "netted"]].sum()
    totals = sums.sum()
    return {
        str(label): {
            rule: float(sums.loc[label, rule] / totals[rule]) if totals[rule] else 0.0
            for rule in ("gross", "netted")
        }
        for label in sums.index
    }


def _median_or_none(values: pd.Series) -> float | None:
    return float(values.median()) if len(values) else None


__all__ = [
    "DAY_LABELS",
    "MONEYNESS_LABELS",
    "RULES",
    "THRESHOLDS",
    "distribution",
    "mark_check",
    "per_underlying",
    "pooled",
    "signed_view",
    "where",
]
