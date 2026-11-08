"""Whose book is the netted FLEX remainder in the programme names?

The signed gamma test (`docs/log/2026-11-08-programme-gamma-spec.md`) assumes that what
pair-netting leaves of FLEX open interest in the programme names is the funds' written
calls, so that the dealer opposite is long its gamma. The funds whose daily holdings the
collector keeps let that be checked, after the test was run:

- `fund_legs`: which of the funds' option legs are FLEX (a root with a leading digit) and
  which are listed, by side;
- `programme_book`: on the dates the holdings cover, how much of the netted FLEX open
  interest in those names is the funds' own netted FLEX book, and how much of it is calls.
"""

from __future__ import annotations

from collections.abc import Set
from typing import Any

import pandas as pd

from hidden_options.measure.hidden_gamma import pair_netted

SERIES = ["root", "expiry", "strike"]


def _with_underlying(holdings: pd.DataFrame) -> pd.DataFrame:
    return holdings.assign(
        flex=holdings["option_root"].astype(str).str.match(r"^\d"),
        underlying=holdings["option_root"].astype(str).str.replace(r"^\d+", "", regex=True),
    )


def fund_legs(holdings: pd.DataFrame, names: Set[str]) -> dict[str, Any]:
    """FLEX shares of the funds' contracts in `names`: written calls and short puts, and the
    share of FLEX short puts with a FLEX long call at the same strike (synthetic stock)."""
    legs = _with_underlying(holdings)
    legs = legs[legs["underlying"].isin(names)]
    size = legs["contracts"].abs()
    written = (legs["right"] == "C") & (legs["contracts"] < 0)
    short_put = (legs["right"] == "P") & (legs["contracts"] < 0)
    flex_put = legs[short_put & legs["flex"]]
    long_call = legs[(legs["right"] == "C") & (legs["contracts"] > 0) & legs["flex"]]
    keys = ["fund", "as_of", "option_root", "expiry", "strike"]
    paired = flex_put.merge(long_call[keys].drop_duplicates(), on=keys, how="inner")
    return {
        "written_call_flex_share": _share(size[written & legs["flex"]].sum(), size[written].sum()),
        "short_put_flex_share": _share(size[short_put & legs["flex"]].sum(), size[short_put].sum()),
        "short_puts_paired": _share(
            paired["contracts"].abs().sum(), flex_put["contracts"].abs().sum()
        ),
        "funds": int(legs["fund"].nunique()),
        "capture_dates": int(legs["as_of"].nunique()),
    }


def programme_book(
    holdings: pd.DataFrame, reports: pd.DataFrame, names: Set[str]
) -> dict[str, Any]:
    """On the holdings' dates, the funds' netted FLEX contracts as a share of the report's
    netted FLEX open interest in `names`, and the call share of the latter. Both books are
    pair-netted the same way; the fund share is capped at one per name and date."""
    legs = _with_underlying(holdings)
    legs = legs[legs["flex"] & legs["underlying"].isin(names)]
    dates = set(pd.to_datetime(legs["as_of"]))
    book = reports[
        reports["underlying"].isin(names)
        & pd.to_datetime(reports["report_date"]).isin(dates)
        & (reports["expiry"] > reports["report_date"])
    ].rename(columns={"report_date": "date"})
    netted = pair_netted(book)
    totals = (
        netted.assign(call=netted["netted_oi"].where(netted["right"] == "C", 0))
        .groupby(["date", "underlying"])[["netted_oi", "call"]]
        .sum()
    )
    fund = (
        legs.assign(
            date=legs["as_of"], root=legs["option_root"], open_interest=legs["contracts"].abs()
        )
        .groupby(["date", "underlying", *SERIES, "right"], as_index=False)["open_interest"]
        .sum()
    )
    fund_net = pair_netted(pd.DataFrame(fund)).groupby(["date", "underlying"])["netted_oi"].sum()
    joined = totals.join(fund_net.rename("fund"), how="left").fillna({"fund": 0})
    covered = joined[["fund", "netted_oi"]].min(axis=1)
    return {
        "netted_call_share": _share(joined["call"].sum(), joined["netted_oi"].sum()),
        "fund_share": _share(covered.sum(), joined["netted_oi"].sum()),
        "names": int(joined.index.get_level_values("underlying").nunique()),
        "dates": int(joined.index.get_level_values("date").nunique()),
    }


def _share(part: float, whole: float) -> float:
    return float(part / whole) if whole else 0.0


__all__ = ["fund_legs", "programme_book"]
