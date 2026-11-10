"""Product rules and dealer sides, checked against what fund issuers disclose.

Specification: `docs/log/2026-11-10-holders-spec.md`. Issuer holdings carry signed option
quantities. A fund's FLEX lines are matched to OCC's report of the same date on root,
expiry, right and strike, and then:

* the anatomy rules (`measure.anatomy`) are scored on lines whose role is known from the
  fund's own file: its *true stock leg*, a long call struck at no more than 5% of its
  price plus its strike, and its *true package legs*, its other FLEX lines beside one;
* the side each package leg is held on is set against the design of a defined-outcome
  fund: long the highest put, short the other puts, short every other call;
* the dealer, who holds the opposite of the fund, is given the gamma of each matched leg.

One issuer's funds on one date say nothing about other issuers or other dates.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hidden_options.measure.anatomy import STOCK_LEG_MAX_SHARE
from hidden_options.measure.hidden_gamma import dollar_gamma

CONTRACT_MULTIPLIER = 100
KEY = ["root", "expiry", "right", "strike"]
HOME = ["fund", "root", "expiry"]
FULL_SHARE = 0.95
LEG_TYPES = ("upper_put", "lower_put", "call")


def flex_lines(holdings: pd.DataFrame) -> pd.DataFrame:
    """The option lines whose root begins with a digit, with the root named `root`."""
    lines = holdings.rename(columns={"option_root": "root"})
    flex = lines["root"].astype(str).str.match(r"^\d")
    return lines[flex & (lines["contracts"] != 0)].reset_index(drop=True)


def with_roles(lines: pd.DataFrame) -> pd.DataFrame:
    """`lines` with `role`: `stock_leg`, `package_leg` or `other`, from the fund's file."""
    reach = lines["price"] + lines["strike"]
    stock = (
        (lines["right"] == "C")
        & (lines["contracts"] > 0)
        & (lines["strike"] <= STOCK_LEG_MAX_SHARE * reach)
    )
    homes = lines.loc[stock, HOME].drop_duplicates().assign(home=True)
    beside = lines[HOME].merge(homes, on=HOME, how="left")["home"].fillna(False)
    role = np.where(
        stock, "stock_leg", np.where(beside.to_numpy(dtype=bool), "package_leg", "other")
    )
    return lines.assign(role=role)


def match(lines: pd.DataFrame, series: pd.DataFrame) -> pd.DataFrame:
    """`lines` with the report's `open_interest`, `mark_price`, `underlying` and anatomy
    `category` for the same series, missing where the report has none."""
    columns = [*KEY, "open_interest", "mark_price", "underlying", "category"]
    return lines.merge(series[columns], on=KEY, how="left")


def matching(found: pd.DataFrame) -> dict[str, Any]:
    """How many fund lines the report holds, and the funds' share of each series found."""
    size = found["contracts"].abs()
    present = found["open_interest"].notna()
    per_series = (
        found[present]
        .assign(size=size[present])
        .groupby(KEY)
        .agg(held=("size", "sum"), open_interest=("open_interest", "first"))
    )
    share = per_series["held"] / per_series["open_interest"]
    return {
        "lines": len(found),
        "funds": int(found["fund"].nunique()),
        "found_lines_share": float(present.mean()) if len(found) else 0.0,
        "found_contracts_share": _share(size[present].sum(), size.sum()),
        "series": len(per_series),
        "median_share_of_open_interest": float(share.median()) if len(share) else 0.0,
        "series_at_least_95": float((share >= FULL_SHARE).mean()) if len(share) else 0.0,
        "held_share_of_their_open_interest": _share(
            per_series["held"].sum(), per_series["open_interest"].sum()
        ),
    }


def rule_recall(found: pd.DataFrame) -> dict[str, float]:
    """Of true stock legs and true package legs found in the report, by contracts, the
    share the anatomy rules put in the category of the same name."""
    present = found[found["open_interest"].notna()]
    size = present["contracts"].abs()
    out = {}
    for role in ("stock_leg", "package_leg"):
        of_role = present["role"] == role
        agreed = of_role & (present["category"] == role)
        out[role] = _share(size[agreed].sum(), size[of_role].sum())
    return out


def category_shares(found: pd.DataFrame, series: pd.DataFrame) -> dict[str, float]:
    """Of the report's open interest in stock-leg calls and in package legs, the share in
    series these funds hold."""
    held = found.loc[found["open_interest"].notna(), KEY].drop_duplicates().assign(held=True)
    flagged = series.merge(held, on=KEY, how="left")
    inside = flagged["held"].fillna(False).to_numpy(dtype=bool)
    out = {}
    for category in ("stock_leg", "package_leg"):
        of_category = (flagged["category"] == category).to_numpy()
        interest = flagged["open_interest"].to_numpy(float)
        out[category] = _share(interest[of_category & inside].sum(), interest[of_category].sum())
    return out


def design_agreement(found: pd.DataFrame) -> dict[str, float]:
    """Of true package legs, by contracts, the share held on the side the design of a
    defined-outcome fund predicts: long the highest put of the fund's root and expiry,
    short its other puts, short its calls. Reported in all and by leg type."""
    legs = found[found["role"] == "package_leg"]
    puts = legs["right"] == "P"
    top = legs["strike"].where(puts).groupby([legs[c] for c in HOME]).transform("max")
    upper = puts & (legs["strike"] == top)
    leg_type = np.where(upper, "upper_put", np.where(puts, "lower_put", "call"))
    predicted = np.where(upper, 1.0, -1.0)
    agrees = np.sign(legs["contracts"].to_numpy(float)) == predicted
    size = legs["contracts"].abs().to_numpy(float)
    out = {"all": _share(size[agrees].sum(), size.sum())}
    for name in LEG_TYPES:
        chosen = leg_type == name
        out[name] = _share(size[agrees & chosen].sum(), size[chosen].sum())
    out["contracts"] = float(size.sum())
    return out


def spots_from_stock_legs(series: pd.DataFrame) -> dict[str, float]:
    """Each underlying's spot as the mark plus the strike of its stock-leg call nearest to
    expiry. Such a call is worth spot less the strike and the dividends to expiry, so the
    nearest one is the closest to spot."""
    legs = series[series["category"] == "stock_leg"].sort_values("expiry")
    nearest = legs.groupby("underlying").first()
    return {str(name): float(row["mark_price"] + row["strike"]) for name, row in nearest.iterrows()}


def dealer_gamma(found: pd.DataFrame, gamma: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Dollar gamma of the matched legs seen from the dealer, per underlying and in `all`.

    `gamma` holds each report series' `gamma` per unit, `spot`, `open_interest` and
    `underlying`. The dealer holds the opposite of the fund. The convention of gamma
    vendors, dealers long calls and short puts, is applied to the same legs beside it.
    """
    legs = found.merge(gamma[[*KEY, "gamma", "spot"]], on=KEY, how="inner")
    legs = legs[legs["gamma"].notna()]
    size = dollar_gamma(legs["gamma"], legs["contracts"].abs(), legs["spot"])
    dealer = -np.sign(legs["contracts"].to_numpy(float))
    convention = np.where(legs["right"] == "C", 1.0, -1.0)
    priced = gamma[gamma["gamma"].notna()]
    gross = pd.Series(
        dollar_gamma(priced["gamma"], priced["open_interest"], priced["spot"]),
        index=priced["underlying"].to_numpy(),
    )
    total = gross.groupby(level=0).sum()

    def summary(rows: np.ndarray, whole: float) -> dict[str, float]:
        held = size[rows]
        return {
            "dealer_long": float(held[dealer[rows] > 0].sum()),
            "dealer_short": float(held[dealer[rows] < 0].sum()),
            "net": float((held * dealer[rows]).sum()),
            "convention_net": float((held * convention[rows]).sum()),
            "convention_wrong_share": _share(
                held[dealer[rows] != convention[rows]].sum(), held.sum()
            ),
            "share_of_flex_gamma": _share(held.sum(), whole),
        }

    names = legs["underlying"].to_numpy()
    out = {
        str(name): summary(names == name, float(total.get(name, 0.0)))
        for name in sorted(set(names))
    }
    out["all"] = summary(
        np.ones(len(legs), dtype=bool), float(total.reindex(sorted(set(names))).sum())
    )
    return out


def box_positions(lines: pd.DataFrame) -> pd.DataFrame:
    """A fund's boxes: at one root and expiry, two strikes each held as a call and a put on
    opposite sides. Long the lower call is a box bought, which lends; the reverse borrows."""
    records = []
    for (fund, root, expiry), group in lines.groupby(HOME):
        strikes = sorted(group["strike"].unique())
        if len(strikes) != 2 or len(group) != 4:
            continue
        lower = group[(group["strike"] == strikes[0]) & (group["right"] == "C")]
        if lower.empty:
            continue
        contracts = float(lower["contracts"].iloc[0])
        records.append(
            {
                "fund": fund,
                "root": root,
                "expiry": expiry,
                "lower": strikes[0],
                "upper": strikes[1],
                "contracts": abs(contracts),
                "side": "lent" if contracts > 0 else "borrowed",
                "face": (strikes[1] - strikes[0]) * CONTRACT_MULTIPLIER * abs(contracts),
            }
        )
    columns = ["fund", "root", "expiry", "lower", "upper", "contracts", "side", "face"]
    return pd.DataFrame.from_records(records, columns=columns)


def _share(part: Any, whole: Any) -> float:
    """`part` over `whole` as a float, zero when there is nothing to divide by."""
    return float(part) / float(whole) if float(whole) else 0.0


__all__ = [
    "KEY",
    "box_positions",
    "category_shares",
    "dealer_gamma",
    "design_agreement",
    "flex_lines",
    "match",
    "matching",
    "rule_recall",
    "spots_from_stock_legs",
    "with_roles",
]
