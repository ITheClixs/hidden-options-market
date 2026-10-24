"""The checks around the hidden share, as result values.

* Coverage: which settlements the local and CI captures hold, which they share, whether
  their readings agree, and which captures were set aside and why.
* The two FLEX sources, the series search against the FLEX report. A median relative
  difference above MAX_MEDIAN_REL_DIFF stops the analysis: the shares would rest on a
  FLEX count the report does not confirm.
* Adjusted-deliverable classes, counted and listed apart from their parents.
* The index counting rule: what leaving out series that expire on the date does where the
  full book is known (equities), and the index shares with those series added back.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hidden_options.measure.hidden_share import hidden_share
from hidden_options.publish import formats

MAX_MEDIAN_REL_DIFF = 0.01
# A share moved by more than this when expiring series are left out is counted.
EXPIRY_MOVE = 0.01
LOCAL_SOURCE = 0


def coverage(log: pd.DataFrame, span: pd.DatetimeIndex) -> dict[str, Any]:
    """What the captures in `log` cover of the settlements in `span`, by root."""
    kept = log[log["dated"] & ~log["mixed"]]
    local_rows = kept[kept["source"] == LOCAL_SOURCE]
    ci_rows = kept[kept["source"] != LOCAL_SOURCE]
    local, ci = set(local_rows["date"]), set(ci_rows["date"])
    covered = local | ci
    set_aside = log[~log["dated"] | log["mixed"]]
    return {
        "span": len(span),
        "missing_dates": [formats.iso_date(day) for day in span if day not in covered],
        "captures_by_root": {
            "local": int((log["source"] == LOCAL_SOURCE).sum()),
            "ci": int((log["source"] != LOCAL_SOURCE).sum()),
        },
        "local": len(local),
        "ci": len(ci),
        "ci_only": [formats.iso_date(day) for day in sorted(ci - local)],
        "both": len(local & ci),
        "cross_root_symbols": int(ci_rows[ci_rows["date"].isin(local)]["symbols_compared"].sum()),
        "set_aside": [
            {
                "capture": formats.iso_date(row["capture"]),
                "root": "local" if row["source"] == LOCAL_SOURCE else "ci",
                "reason": str(row["reason"]),
            }
            for row in set_aside.to_dict("records")
        ],
    }


def reconciliation_summary(reconciled: pd.DataFrame) -> dict[str, Any]:
    """The two FLEX sources over every symbol-date where either has FLEX.

    Raises ValueError when the median relative difference exceeds MAX_MEDIAN_REL_DIFF.
    """
    either = reconciled[(reconciled["flex_oi_search"] > 0) | (reconciled["flex_oi_report"] > 0)]
    median = float(either["rel_diff"].median())
    if median > MAX_MEDIAN_REL_DIFF:
        raise ValueError(
            f"The series search and the FLEX report differ by a median {median:.2%} over "
            f"{len(either)} symbol-dates, above the 1% the shares can rest on"
        )
    return {
        "symbol_dates": len(either),
        "agreeing": int((either["rel_diff"] == 0).sum()),
        "median_rel_diff": median,
        "max_rel_diff": float(either["rel_diff"].max()),
        "flex_oi_search": int(either["flex_oi_search"].sum()),
        "flex_oi_report": int(either["flex_oi_report"].sum()),
    }


def adjusted_summary(census: pd.DataFrame, search: pd.DataFrame) -> dict[str, Any]:
    """Adjusted-deliverable classes: counted and listed, never folded into their parents."""
    on_census = census[census["adjusted"]]
    with_flex = on_census[on_census["flex_oi"] > 0].sort_values("flex_oi", ascending=False)
    daily = search[search["adjusted"] & (search["flex_oi"] > 0)]
    by_name = daily.groupby("symbol")["flex_share"].agg(["min", "max", "size"])
    return {
        "census": len(on_census),
        "census_with_flex": len(with_flex),
        "census_flex": records(with_flex),
        "census_flex_oi": int(on_census["flex_oi"].sum()),
        "census_flex_share": float(on_census["flex_oi"].sum() / census["flex_oi"].sum()),
        "daily_with_flex": {
            str(s): {"min": float(r["min"]), "max": float(r["max"]), "dates": int(r["size"])}
            for s, r in by_name.iterrows()
        },
    }


def expiry_check(daily_rows: pd.DataFrame, search: pd.DataFrame) -> dict[str, Any]:
    """How far an equity share moves when series expiring on the date are left out.

    The index shares are computed that way because the chain no longer lists those
    series; this says what the same rule does where the full book is known.
    """
    later = daily_rows[pd.to_datetime(daily_rows["expiry"]) > daily_rows["date"]]
    both = search.merge(
        hidden_share(later), on=["date", "symbol", "adjusted"], suffixes=("", "_later")
    )
    both = both[~both["adjusted"]]
    gap = (both["flex_share"] - both["flex_share_later"]).abs()
    return {
        "name_dates": len(both),
        "moved": int((gap > EXPIRY_MOVE).sum()),
        "max_abs_diff": float(gap.max()),
        "median_abs_diff": float(gap.median()),
    }


def index_full_book(whole: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Each index product's lowest share with the series expiring on the date counted too.

    `whole` is `hidden_share` output for index rows built with the expiring series. The
    lowest share is reported with its date and whether that date is a standard monthly
    expiry (a third Friday).
    """
    summary = {}
    for symbol, rows in whole.groupby("symbol"):
        low = rows.iloc[int(np.argmin(rows["flex_share"].to_numpy()))]
        day = pd.Timestamp(low["date"])
        summary[str(symbol)] = {
            "min": float(low["flex_share"]),
            "min_date": formats.iso_date(day),
            "min_on_monthly_expiry": bool(day.weekday() == 4 and 15 <= day.day <= 21),
            "dates": int(rows["date"].nunique()),
        }
    return summary


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Share rows as plain records: symbol, FLEX and listed open interest, share."""
    return [
        {
            "symbol": str(row["symbol"]),
            "flex_oi": int(row["flex_oi"]),
            "listed_oi": int(row["listed_oi"]),
            "share": float(row["flex_share"]),
        }
        for row in frame.to_dict("records")
    ]


__all__ = [
    "EXPIRY_MOVE",
    "MAX_MEDIAN_REL_DIFF",
    "adjusted_summary",
    "coverage",
    "expiry_check",
    "index_full_book",
    "reconciliation_summary",
    "records",
]
