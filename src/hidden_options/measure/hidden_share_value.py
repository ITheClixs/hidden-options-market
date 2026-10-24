"""The FLEX share of option value, as result values.

Listed series are valued at their mid quote, or at Cboe's theoretical value where the
quote is one-sided or crossed; FLEX series at the report's mark. The aggregate is taken
only on dates when every followed name is priced, so it does not move with which names
happen to have quotes. On the last of those dates the FLEX value is taken apart: how
much of it is intrinsic at that day's spot, how much sits in deep in-the-money lines,
and how much in lines paired with the opposite right at the same strike.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.measure.hidden_share import (
    DEEP_INTRINSIC,
    flex_series,
    value_composition,
    value_share,
)
from hidden_options.publish import formats

VALUE_LEADERS = 10


def value_summary(
    priced: pd.DataFrame,
    reports: pd.DataFrame,
    dates: pd.DatetimeIndex,
    universe: Mapping[str, str],
) -> dict[str, Any]:
    """FLEX mark value as a share of option value, on the daily universe's dates."""
    chains = priced[priced["date"].isin(dates) & priced["symbol"].isin(set(universe))]
    shares = value_share(chains, reports[reports["report_date"].isin(dates)])
    usable = shares[shares["usable"]]
    priced_names = usable.groupby("date")["symbol"].nunique()
    complete = priced_names[priced_names == len(universe)].index
    totals = (
        usable[usable["date"].isin(complete)]
        .groupby("date")[["flex_value", "listed_value", "flex_oi", "listed_oi"]]
        .sum()
    )
    value = totals["flex_value"] / (totals["flex_value"] + totals["listed_value"])
    oi = totals["flex_oi"] / (totals["flex_oi"] + totals["listed_oi"])
    per_name = usable.groupby("symbol")[["value_share", "oi_share"]].median()
    last_date = pd.Timestamp(usable["date"].max())
    last = usable[usable["date"] == last_date].sort_values("value_share", ascending=False)
    series = flex_series(reports, pd.DatetimeIndex([last_date]))
    series = series[series["symbol"].isin(set(last["symbol"]))]
    return {
        "symbol_dates": len(shares),
        "usable": len(usable),
        "dates": int(usable["date"].nunique()),
        "complete_dates": len(complete),
        "names": int(per_name.shape[0]),
        "theo_share": float(
            (usable["theo_share"] * usable["listed_oi"]).sum() / usable["listed_oi"].sum()
        ),
        "aggregate": _spread(value),
        "aggregate_oi": _spread(oi),
        "median_name": float(per_name["value_share"].median()),
        "median_name_oi": float(per_name["oi_share"].median()),
        "above_oi_share": int((per_name["value_share"] > per_name["oi_share"]).sum()),
        "last_date": formats.iso_date(last_date),
        "leaders": [
            {
                "symbol": str(row["symbol"]),
                "value_share": float(row["value_share"]),
                "oi_share": float(row["oi_share"]),
            }
            for row in last.head(VALUE_LEADERS).to_dict("records")
        ],
        "largest_line": _largest_line(series, last, last_date),
        "composition": _composition(series, chains, last_date),
    }


def _composition(series: pd.DataFrame, chains: pd.DataFrame, on: pd.Timestamp) -> dict[str, Any]:
    """What the FLEX value of the last date is made of, at the spot quoted with its prices."""
    quoted = chains[(chains["date"] == on) & chains["underlying_price"].notna()]
    spots = quoted.groupby("symbol")["underlying_price"].median()
    parts = value_composition(series, {str(s): float(p) for s, p in spots.items()})
    return {"date": formats.iso_date(on), "deep_threshold": DEEP_INTRINSIC, **parts}


def _largest_line(series: pd.DataFrame, last: pd.DataFrame, on: pd.Timestamp) -> dict[str, Any]:
    """The single FLEX series worth most on `on`, beside its underlying's listed value."""
    line = series.iloc[int(np.argmax(series["flex_value"].to_numpy()))]
    opposite = series[
        (series["root"] == line["root"])
        & (series["expiry"] == line["expiry"])
        & (series["strike"] == line["strike"])
        & (series["right"] != line["right"])
    ]
    listed = last.loc[last["symbol"] == line["symbol"], "listed_value"]
    return {
        "date": formats.iso_date(on),
        "symbol": str(line["symbol"]),
        "root": str(line["root"]),
        "right": str(line["right"]),
        "expiry": formats.iso_date(pd.Timestamp(line["expiry"])),
        "strike": float(line["strike"]),
        "mark": float(line["mark_price"]),
        "open_interest": int(line["open_interest"]),
        "value": float(line["flex_value"]),
        "opposite_open_interest": int(opposite["open_interest"].sum()),
        "listed_value": float(listed.iloc[0]),
    }


def _spread(series: pd.Series) -> dict[str, float]:
    return {
        "median": float(series.median()),
        "min": float(series.min()),
        "max": float(series.max()),
    }


__all__ = ["VALUE_LEADERS", "value_summary"]
