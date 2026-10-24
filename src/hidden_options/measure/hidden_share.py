"""How much of each underlying's option market is FLEX (M2).

OCC's series search lists, for one underlying, every series it clears: the listed
products and the FLEX ones, which carry the listed root behind a leading digit (`SPY`,
`1SPY`, `2SPY`, `4SPY`). The FLEX share of an underlying is its FLEX open interest over
all of its open interest. The FLEX report gives the same FLEX open interest a second
time, so the two sources can be checked against each other.

Three naming rules decide what counts as one underlying.

* A leading digit marks a FLEX product. Everything else is listed.
* A trailing digit marks an adjusted-deliverable class (`HON2`, `1HON2`): an option class
  renamed after a corporate action changed what one contract delivers. It is a separate
  underlying, kept apart from its parent rather than folded into it, on both sides.
* Index products are named by table, never by stripping characters. A FLEX index root
  maps to the index it settles on (`4SPX` to `SPX`), and a listed index root to the same
  (`SPXW` to `SPX`, `NDXP` to `NDX`). Mini and micro products (`XSP`, `XND`, `MRUT`) are
  products of their own with their own contract size, so they stay separate. A root the
  tables do not know stops the analysis rather than being guessed.

Value is measured where listed quotes exist: listed series at their mid quote, FLEX
series at the report's mark, both times open interest and the contract multiplier.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

import numpy as np
import pandas as pd

SHARE_COLUMNS = ("date", "symbol", "adjusted", "flex_oi", "listed_oi", "flex_share")
RECONCILE_COLUMNS = ("date", "symbol", "flex_oi_search", "flex_oi_report", "rel_diff")
VALUE_COLUMNS = (
    "date",
    "symbol",
    "listed_value",
    "flex_value",
    "value_share",
    "listed_oi",
    "flex_oi",
    "oi_share",
    "priced_share",
    "theo_share",
    "usable",
)

CONTRACT_MULTIPLIER = 100
# A symbol-date's listed value is used only when nearly all of its open interest has a
# quote from the session; otherwise a missing chain would pass for a small market.
MIN_PRICED_SHARE = 0.99

# Every FLEX index root in the panel, Dec 2024 to Oct 2026, and the index it settles on.
# The prefix is the settlement variant (2 AM-settled, 4 PM-settled; 1 and 3 appear on a
# handful of dates without open interest), so roots differing only in it share an index.
FLEX_INDEX_ROOTS: Mapping[str, str] = MappingProxyType(
    {
        "1RUT": "RUT",
        "2RUT": "RUT",
        "4RUT": "RUT",
        "1SPX": "SPX",
        "2SPX": "SPX",
        "3SPX": "SPX",
        "4SPX": "SPX",
        "2NDX": "NDX",
        "3NDX": "NDX",
        "4NDX": "NDX",
        "2DJX": "DJX",
        "4DJX": "DJX",
        "2XSP": "XSP",
        "4XSP": "XSP",
        "4XND": "XND",
        "4MRUT": "MRUT",
        "2CBTX": "CBTX",
        "4CBTX": "CBTX",
        "4MBTX": "MBTX",
        "4MXEA": "MXEA",
        "4MXEF": "MXEF",
        "4XDE": "XDE",
    }
)

# Listed index products in the Cboe chains and the index each settles on: the standard
# AM-settled monthly product and its PM-settled weekly sibling.
LISTED_INDEX_ROOTS: Mapping[str, str] = MappingProxyType(
    {
        "SPX": "SPX",
        "SPXW": "SPX",
        "NDX": "NDX",
        "NDXP": "NDX",
        "RUT": "RUT",
        "RUTW": "RUT",
    }
)

_FLEX_PREFIX = re.compile(r"^\d+")
_KINDS = ("equity", "index")


def is_flex_product(product_symbol: str) -> bool:
    """True for a FLEX product symbol, which OCC writes with a leading digit."""
    return bool(_FLEX_PREFIX.match(product_symbol))


def is_adjusted_product(product_symbol: str) -> bool:
    """True for an adjusted-deliverable class: a trailing digit once any FLEX prefix is off."""
    return _FLEX_PREFIX.sub("", product_symbol)[-1:].isdigit()


def listed_product(flex_root: str, kind: str = "equity") -> str:
    """The listed underlying a FLEX root belongs to.

    An equity root loses its leading digits (`1AAON` to `AAON`). An index root is looked
    up in FLEX_INDEX_ROOTS, and one the table does not know raises KeyError.
    """
    if kind not in _KINDS:
        raise ValueError(f"FLEX kind must be one of {_KINDS}, got {kind!r}")
    if not is_flex_product(flex_root):
        raise ValueError(f"{flex_root!r} is not a FLEX root: it has no leading digit")
    if kind == "equity":
        return _FLEX_PREFIX.sub("", flex_root)
    if flex_root not in FLEX_INDEX_ROOTS:
        raise KeyError(f"FLEX index root {flex_root!r} has no entry in FLEX_INDEX_ROOTS")
    return FLEX_INDEX_ROOTS[flex_root]


def listed_index(listed_root: str) -> str:
    """The index a listed index product settles on (`SPXW` to `SPX`); KeyError if unknown."""
    if listed_root not in LISTED_INDEX_ROOTS:
        raise KeyError(f"Listed index root {listed_root!r} has no entry in LISTED_INDEX_ROOTS")
    return LISTED_INDEX_ROOTS[listed_root]


def hidden_share(oi: pd.DataFrame) -> pd.DataFrame:
    """FLEX and listed open interest per underlying and date, and the FLEX share.

    `oi` holds OCC series rows (`date`, `symbol`, `product_symbol`, `call_open_interest`,
    `put_open_interest`). An ordinary product counts towards the symbol searched; an
    adjusted-deliverable product is its own underlying, named by its class without the
    FLEX prefix and flagged `adjusted`. An underlying with no open interest on a date has
    no share and no row.
    """
    products = oi["product_symbol"].astype(str)
    is_flex = products.map(is_flex_product).astype(bool)
    adjusted = products.map(is_adjusted_product).astype(bool)
    core = products.str.replace(_FLEX_PREFIX, "", regex=True)
    total = oi["call_open_interest"] + oi["put_open_interest"]

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(oi["date"]),
            "symbol": core.where(adjusted, oi["symbol"].astype(str)),
            "adjusted": adjusted,
            "flex_oi": total.where(is_flex, 0),
            "listed_oi": total.where(~is_flex, 0),
        }
    )
    share = frame.groupby(["date", "symbol", "adjusted"], as_index=False)[
        ["flex_oi", "listed_oi"]
    ].sum()
    market = share["flex_oi"] + share["listed_oi"]
    share = share[market > 0].copy()
    share["flex_share"] = share["flex_oi"] / (share["flex_oi"] + share["listed_oi"])
    return share.sort_values(["date", "symbol"]).reset_index(drop=True)[list(SHARE_COLUMNS)]


def stable_symbols(share: pd.DataFrame, threshold: float) -> list[str]:
    """Symbols whose FLEX share is at least `threshold` on every date in `share`.

    A symbol with no row on one of the dates is not confirmed on it and is left out.
    """
    if share.empty:
        return []
    dates = share["date"].nunique()
    above = share[share["flex_share"] >= threshold].groupby("symbol")["date"].nunique()
    return sorted(above[above == dates].index)


def stable_headline(share: pd.DataFrame, threshold: float) -> int:
    """How many symbols have a FLEX share of at least `threshold` on every date."""
    return len(stable_symbols(share, threshold))


def reconcile_flex_sources(share: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """FLEX open interest from the series search against the FLEX report, per symbol-date.

    `share` is `hidden_share` output from the series search; `daily` holds report rows or
    totals (`report_date`, `underlying`, `open_interest`), summed here per underlying and
    date. Every symbol-date of the search is kept, so FLEX the report lists for a symbol
    whose search shows none is a disagreement too. `rel_diff` is the absolute difference
    over the larger of the two, which is defined when one source is zero and is zero
    when both are.
    """
    report = (
        daily.groupby(["report_date", "underlying"])["open_interest"]
        .sum()
        .rename("flex_oi_report")
        .rename_axis(["date", "symbol"])
        .reset_index()
    )
    merged = share[["date", "symbol", "flex_oi"]].merge(report, on=["date", "symbol"], how="left")
    merged = merged.rename(columns={"flex_oi": "flex_oi_search"})
    merged["flex_oi_report"] = merged["flex_oi_report"].fillna(0)
    search, report_oi = merged["flex_oi_search"], merged["flex_oi_report"]
    larger = search.where(search >= report_oi, report_oi)
    gap = (search - report_oi).abs()
    merged["rel_diff"] = (gap / larger.where(larger > 0, 1)).where(larger > 0, 0.0)
    return merged[list(RECONCILE_COLUMNS)]


def quote_price(bid: pd.Series, ask: pd.Series, theo: pd.Series) -> tuple[pd.Series, pd.Series]:
    """The value of one listed contract, and whether it came from the model.

    A two-sided quote (a positive bid at or below the ask) is valued at its mid. Any other
    quote, with no bid, no ask or a bid above the ask, is valued at Cboe's theoretical
    value. A series with no quote at all stays missing.
    """
    two_sided = (bid > 0) & (ask >= bid)
    price = ((bid + ask) / 2).where(two_sided, theo)
    at_theo = ~two_sided & theo.notna()
    return price, at_theo


def value_share(chains: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """FLEX mark value as a share of all option value, per underlying and date.

    `chains` holds listed series priced on their date (`date`, `symbol`, `root`, `expiry`,
    `open_interest`, `bid`, `ask`, `theo`); `panel` holds FLEX report rows. Both sides
    count series expiring after the date only, since a chain read after a settlement no
    longer lists what expired on it. Adjusted-deliverable classes are left out on both
    sides. `usable` marks symbol-dates where at least MIN_PRICED_SHARE of listed open
    interest is priced.
    """
    listed = _listed_values(chains)
    flex = _flex_values(panel, listed["date"].unique())
    merged = listed.merge(flex, on=["date", "symbol"], how="left")
    merged[["flex_value", "flex_oi"]] = merged[["flex_value", "flex_oi"]].fillna(0.0)
    merged["value_share"] = merged["flex_value"] / (merged["flex_value"] + merged["listed_value"])
    merged["oi_share"] = merged["flex_oi"] / (merged["flex_oi"] + merged["listed_oi"])
    merged["priced_share"] = merged["priced_oi"] / merged["listed_oi"]
    merged["theo_share"] = merged["theo_oi"] / merged["listed_oi"]
    merged["usable"] = merged["priced_share"] >= MIN_PRICED_SHARE
    merged = merged.sort_values(["date", "symbol"]).reset_index(drop=True)
    return merged[list(VALUE_COLUMNS)]


def _listed_values(chains: pd.DataFrame) -> pd.DataFrame:
    roots = chains["root"].astype(str)
    owner = roots.map(lambda root: LISTED_INDEX_ROOTS.get(root, root))
    adjusted = roots.map(is_adjusted_product).astype(bool)
    stray = ~adjusted & (owner != chains["symbol"])
    if stray.any():
        bad = sorted(set(roots[stray]))
        raise ValueError(f"Listed roots {bad} do not belong to the chains they were read from")

    frame = chains[~adjusted & (chains["expiry"] > chains["date"])].copy()
    price, at_theo = quote_price(frame["bid"], frame["ask"], frame["theo"])
    oi = frame["open_interest"]
    frame["listed_value"] = (price * oi * CONTRACT_MULTIPLIER).fillna(0.0)
    frame["listed_oi"] = oi
    frame["priced_oi"] = oi.where(price.notna(), 0)
    frame["theo_oi"] = oi.where(at_theo, 0)
    columns = ["listed_value", "listed_oi", "priced_oi", "theo_oi"]
    listed = frame.groupby(["date", "symbol"], as_index=False)[columns].sum()
    return listed[listed["listed_oi"] > 0]


def flex_series(panel: pd.DataFrame, dates: np.ndarray | pd.DatetimeIndex) -> pd.DataFrame:
    """FLEX series on `dates` with the listed underlying they belong to and their value.

    Series expiring on or before their date and adjusted-deliverable classes are left
    out, as in `value_share`. An index root FLEX_INDEX_ROOTS does not know raises.
    """
    frame = panel[panel["report_date"].isin(dates) & (panel["expiry"] > panel["report_date"])]
    frame = frame[~frame["root"].astype(str).map(is_adjusted_product).astype(bool)]
    pairs = frame[["root", "kind"]].drop_duplicates()
    owners = {
        (root, kind): listed_product(root, kind)
        for root, kind in zip(pairs["root"], pairs["kind"], strict=True)
    }
    symbol = [owners[pair] for pair in zip(frame["root"], frame["kind"], strict=True)]
    series = frame[["root", "right", "expiry", "strike", "mark_price", "open_interest"]].copy()
    series.insert(0, "symbol", symbol)
    series.insert(0, "date", frame["report_date"])
    series["flex_value"] = series["mark_price"] * series["open_interest"] * CONTRACT_MULTIPLIER
    return series.reset_index(drop=True)


def _flex_values(panel: pd.DataFrame, dates: np.ndarray) -> pd.DataFrame:
    series = flex_series(panel, dates).rename(columns={"open_interest": "flex_oi"})
    return series.groupby(["date", "symbol"], as_index=False)[["flex_value", "flex_oi"]].sum()


__all__ = [
    "CONTRACT_MULTIPLIER",
    "FLEX_INDEX_ROOTS",
    "LISTED_INDEX_ROOTS",
    "MIN_PRICED_SHARE",
    "RECONCILE_COLUMNS",
    "SHARE_COLUMNS",
    "VALUE_COLUMNS",
    "flex_series",
    "hidden_share",
    "is_adjusted_product",
    "is_flex_product",
    "listed_index",
    "listed_product",
    "quote_price",
    "reconcile_flex_sources",
    "stable_headline",
    "stable_symbols",
    "value_share",
]
