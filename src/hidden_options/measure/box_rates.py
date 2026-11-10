"""Box spreads in Cboe's FLEX execution reports, and the rates they trade at.

Specification: `docs/log/2026-11-10-box-rates-spec.md`. A box traded as one order appears
as four legs with one timestamp: a call and a put at each of two strikes. Its net price,
(C1 - P1) - (C2 - P2) with 1 the lower strike, is what the lender pays for the distance
between the strikes at expiry, whichever side each party took. The rate that discounts
one to the other is set beside the Treasury curve of the trade date and beside the rate
in OCC's marks for the same four series.

The reports give no buyer or seller, so nothing here says who lent.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hidden_options.collect.cboe_flex_trades import EXECUTION_COLUMNS

CONTRACT_MULTIPLIER = 100
DAYS_PER_YEAR = 365.0
MIN_DAYS = 7
RATE_RANGE = (-0.05, 0.25)
SIMPLE_UP_TO_YEARS = 0.5
MATURITY_YEARS = {
    "1 Mo": 1 / 12,
    "1.5 Month": 1.5 / 12,
    "2 Mo": 2 / 12,
    "3 Mo": 3 / 12,
    "4 Mo": 4 / 12,
    "6 Mo": 6 / 12,
    "1 Yr": 1.0,
    "2 Yr": 2.0,
    "3 Yr": 3.0,
    "5 Yr": 5.0,
    "7 Yr": 7.0,
    "10 Yr": 10.0,
    "20 Yr": 20.0,
    "30 Yr": 30.0,
}
GROUP = ["time", "root", "expiry", "size"]
BOX_COLUMNS = (
    "trade_date",
    "time",
    "root",
    "underlying",
    "expiry",
    "lower",
    "upper",
    "size",
    "price",
    "face",
    "days",
    "rate",
)


def executions(rows: pd.DataFrame) -> pd.DataFrame:
    """The distinct rows of the reports with `executions`: a row seen m times is m/2
    executions, rounded up, since each is reported from both sides."""
    seen = rows.groupby(list(EXECUTION_COLUMNS), dropna=False, sort=False).size()
    found = seen.rename("seen").reset_index()
    found["executions"] = (found["seen"] + 1) // 2
    return found.drop(columns="seen")


def box_trades(found: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Box packages among `found` (the output of `executions`), and how many groups with
    two or more strikes carrying both rights could not be read as one box.

    A box is a group with one timestamp, root, expiry and size that consists of exactly
    four spread legs, a call and a put at each of two strikes, each executed equally
    often. A box executed k times at one instant has k times the size.
    """
    legs = found[found["spread"] & found["root"].notna() & found["right"].isin(["C", "P"])]
    legs = legs.assign(is_call=legs["right"] == "C")
    strikes = legs.groupby([*GROUP, "strike"], sort=False).agg(
        calls=("is_call", "sum"), rows=("is_call", "size")
    )
    strikes["puts"] = strikes["rows"] - strikes["calls"]
    strikes["paired"] = (strikes["calls"] >= 1) & (strikes["puts"] >= 1)
    strikes["clean"] = (strikes["calls"] == 1) & (strikes["puts"] == 1)
    groups = strikes.groupby(level=GROUP, sort=False).agg(
        paired=("paired", "sum"), clean=("clean", "sum"), rows=("rows", "sum")
    )
    even = legs.groupby(GROUP, sort=False)["executions"].nunique() == 1
    is_box = (groups["paired"] == 2) & (groups["clean"] == 2) & (groups["rows"] == 4) & even
    unresolved = int(((groups["paired"] >= 2) & ~is_box).sum())
    chosen = legs.merge(is_box[is_box].rename("box").reset_index()[GROUP], on=GROUP)
    if chosen.empty:
        return pd.DataFrame(columns=list(BOX_COLUMNS)), unresolved

    lower = chosen.groupby(GROUP, sort=False)["strike"].transform("min")
    sign = np.where(chosen["is_call"] == (chosen["strike"] == lower), 1.0, -1.0)
    boxes = (
        chosen.assign(signed=sign * chosen["price"])
        .groupby(GROUP, sort=False)
        .agg(
            trade_date=("trade_date", "first"),
            lower=("strike", "min"),
            upper=("strike", "max"),
            price=("signed", "sum"),
            executions=("executions", "first"),
        )
        .reset_index()
    )
    boxes["size"] = boxes["size"] * boxes["executions"]
    width = boxes["upper"] - boxes["lower"]
    boxes["face"] = width * CONTRACT_MULTIPLIER * boxes["size"]
    boxes["days"] = (boxes["expiry"] - boxes["trade_date"]).dt.days
    boxes["rate"] = _rate(boxes["price"], width, boxes["days"])
    boxes["underlying"] = boxes["root"].astype(str).str.replace(r"^\d", "", regex=True)
    return boxes[list(BOX_COLUMNS)].reset_index(drop=True), unresolved


def _rate(price: pd.Series, width: pd.Series, days: pd.Series) -> np.ndarray:
    """The continuously compounded rate that discounts `width` to `price` over `days`."""
    usable = (price > 0) & (days > 0) & (width > 0)
    ratio = np.where(usable, price / width.where(width > 0, 1.0), 1.0)
    years = np.where(usable, days / DAYS_PER_YEAR, 1.0)
    rate: np.ndarray = np.where(usable, -np.log(ratio) / years, np.nan)
    return rate


def continuous_curve(row: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """One date's par yields (in percent) as maturities in years and continuously
    compounded rates: a simple yield up to six months, a semiannual one from one year.
    Missing maturities are left out."""
    years, rates = [], []
    for label, maturity in MATURITY_YEARS.items():
        if label not in row.index or pd.isna(row[label]):
            continue
        quoted = float(row[label]) / 100
        years.append(maturity)
        if maturity <= SIMPLE_UP_TO_YEARS:
            rates.append(np.log(1 + quoted * maturity) / maturity)
        else:
            rates.append(2 * np.log(1 + quoted / 2))
    return np.asarray(years), np.asarray(rates)


def benchmark_rates(curve: pd.DataFrame, trade_dates: pd.Series, days: np.ndarray) -> np.ndarray:
    """The Treasury rate at each trade's maturity, from the curve of its date or the last
    one before it: linear in maturity between published points and flat outside them."""
    curve = curve.sort_values("date").reset_index(drop=True)
    published = curve["date"].to_numpy()
    wanted = pd.to_datetime(trade_dates).to_numpy()
    place = np.searchsorted(published, wanted, side="right") - 1
    years = np.asarray(days, dtype=float) / DAYS_PER_YEAR
    out = np.full(len(wanted), np.nan)
    for index in np.unique(place[place >= 0]):
        nodes, rates = continuous_curve(curve.iloc[int(index)])
        if len(nodes) == 0:
            continue
        chosen = place == index
        out[chosen] = np.interp(years[chosen], nodes, rates)
    return out


def rate_sample(trades: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Box trades with at least MIN_DAYS to expiry, a positive price and a rate inside
    RATE_RANGE, and how many trades each condition dropped, in that order."""
    short = trades["days"] < MIN_DAYS
    no_price = ~short & ~((trades["price"] > 0) & trades["rate"].notna())
    low, high = RATE_RANGE
    wild = ~short & ~no_price & ~trades["rate"].between(low, high)
    dropped = {
        "short": int(short.sum()),
        "out_of_range": int(wild.sum()),
        "no_price": int(no_price.sum()),
    }
    return trades[~short & ~no_price & ~wild].reset_index(drop=True), dropped


def spread_summary(trades: pd.DataFrame) -> dict[str, Any]:
    """The spread's face-weighted mean with a standard error clustered by trade date, and
    its median and quartiles across trades."""
    if trades.empty:
        return {"trades": 0, "face": 0.0, "dates": 0, **dict.fromkeys(_STATISTICS)}
    spread = trades["spread"].to_numpy(float)
    face = trades["face"].to_numpy(float)
    mean = float(np.average(spread, weights=face))
    dates = trades["trade_date"].nunique()
    return {
        "trades": len(trades),
        "face": float(face.sum()),
        "dates": int(dates),
        "mean": mean,
        "std_error": _clustered_error(spread, face, trades["trade_date"], mean),
        "median": float(np.median(spread)),
        "q25": float(np.quantile(spread, 0.25)),
        "q75": float(np.quantile(spread, 0.75)),
    }


_STATISTICS = ("mean", "std_error", "median", "q25", "q75")


def _clustered_error(
    spread: np.ndarray, face: np.ndarray, dates: pd.Series, mean: float
) -> float | None:
    """The standard error of a weighted mean when trades of one date move together."""
    scores = pd.Series(face * (spread - mean)).groupby(dates.to_numpy()).sum().to_numpy()
    clusters = len(scores)
    if clusters < 2:
        return None
    variance = (scores**2).sum() / face.sum() ** 2 * clusters / (clusters - 1)
    return float(np.sqrt(variance))


def mark_rates(trades: pd.DataFrame, report: pd.DataFrame) -> np.ndarray:
    """The rate in OCC's marks for each traded box on its trade date, missing where the
    report of that date lacks one of the four series."""
    marks = report.rename(columns={"report_date": "trade_date"})[
        ["trade_date", "root", "expiry", "right", "strike", "mark_price"]
    ]

    def leg(side: str, right: str) -> np.ndarray:
        wanted = trades[["trade_date", "root", "expiry", side]].rename(columns={side: "strike"})
        found = wanted.assign(right=right).merge(
            marks, on=["trade_date", "root", "expiry", "right", "strike"], how="left"
        )
        return found["mark_price"].to_numpy(float)

    value = (leg("lower", "C") - leg("lower", "P")) - (leg("upper", "C") - leg("upper", "P"))
    width = (trades["upper"] - trades["lower"]).to_numpy(float)
    days = trades["days"].to_numpy(float)
    usable = np.isfinite(value) & (value > 0) & (days > 0)
    out = np.full(len(trades), np.nan)
    out[usable] = -np.log(value[usable] / width[usable]) / (days[usable] / DAYS_PER_YEAR)
    return out


__all__ = [
    "BOX_COLUMNS",
    "MATURITY_YEARS",
    "MIN_DAYS",
    "benchmark_rates",
    "box_trades",
    "continuous_curve",
    "executions",
    "mark_rates",
    "rate_sample",
    "spread_summary",
]
