"""How much option gamma a listed-only calculation leaves out.

The specification is `docs/log/2026-11-07-hidden-gamma-spec.md`; this module follows it.

Dealer-gamma figures in public use are built from listed chains, and FLEX series are not
in them. Both sides are priced here on one footing: Black-Scholes gamma from the listed
implied-volatility surface of the same underlying and session. A listed series uses its
own quoted volatility; a FLEX series reads the surface at its strike and expiry, linear in
log-moneyness within an expiry (flat beyond the outermost strikes) and linear in total
variance between the two listed expiries around it (flat in volatility beyond the first
and last). `interior` records whether a FLEX series was read inside the surface.

The chain's own `gamma` column is not used: it is rounded to four decimals, which sets
index-option gamma to zero.

Open interest does not say who is long, so these are gamma *notional* figures under two
attribution rules, never dealer positions:

* `gross` counts every contract;
* `netted` matches call and put open interest at each root, expiry and strike and counts
  only the excess, since a long call and a short put at one strike is a forward with no
  gamma. That is what conversions, reversals and boxes are; a straddle would be
  understated, so `netted` is a floor for conversion-like books, not a bound in general.

`signed` is the convention vendors use for listed chains, calls up and puts down, applied
to both sides and reported as that convention only.

Dollar gamma here is the change in dollar delta for a 1% move, Γ·n·100·S²·0.01, the unit
of published gamma-exposure figures. `implied.py` reports the P&L of a 1% move instead,
½·Γ·n·100·(0.01·S)², which is 1/200 of it. Shares are ratios and do not depend on which.
"""

from __future__ import annotations

from typing import cast

import numpy as np
import numpy.typing as npt
import pandas as pd

from hidden_options.measure.pricing import black_scholes_greeks

CONTRACT_MULTIPLIER = 100
# Dollar gamma is the change in dollar delta for a move of this fraction of spot.
MOVE = 0.01
DAYS_PER_YEAR = 365.0
# Quotes outside this band are not volatilities a surface should be built from.
MIN_IV = 0.01
MAX_IV = 5.0
# Total variance is kept above this when interpolating across a calendar inversion.
MIN_TOTAL_VARIANCE = 1e-10

KEYS = ["date", "symbol"]
LISTED_COLUMNS = ("date", "symbol", "listed_gross", "listed_netted", "listed_signed")
FLEX_COLUMNS = (
    "date",
    "symbol",
    "root",
    "expiry",
    "right",
    "strike",
    "open_interest",
    "netted_oi",
    "sigma",
    "interior",
    "days",
    "moneyness",
    "gross",
    "netted",
    "signed",
)
SHARE_COLUMNS = (
    "date",
    "symbol",
    "listed_gross",
    "listed_netted",
    "listed_signed",
    "flex_gross",
    "flex_netted",
    "flex_signed",
    "share_gross",
    "share_netted",
    "share_netted_both",
    "interior_oi_share",
)

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


def dollar_gamma(
    gamma: npt.ArrayLike, open_interest: npt.ArrayLike, spot: npt.ArrayLike
) -> FloatArray:
    """Change in dollar delta of `open_interest` contracts for a MOVE in the underlying."""
    g, n, s = (np.asarray(x, dtype=np.float64) for x in (gamma, open_interest, spot))
    return np.asarray(g * n * CONTRACT_MULTIPLIER * s * s * MOVE, dtype=np.float64)


def surface_points(chain: pd.DataFrame) -> pd.DataFrame:
    """The out-of-the-money quotes of one chain reading that a surface is built from.

    Calls struck above spot and puts struck below it, with a volatility in
    [MIN_IV, MAX_IV]. In-the-money quotes are noisier and carry the same information.
    """
    if chain.empty:
        return pd.DataFrame(columns=["expiry", "strike", "iv"])
    spot = chain["underlying_price"].astype(float)
    otm = ((chain["right"] == "C") & (chain["strike"] > spot)) | (
        (chain["right"] == "P") & (chain["strike"] < spot)
    )
    good = chain["iv"].between(MIN_IV, MAX_IV)
    points = chain.loc[otm & good, ["expiry", "strike", "iv"]]
    return points.sort_values(["expiry", "strike"]).reset_index(drop=True)


def surface_vol(
    points: pd.DataFrame, spot: float, as_of: pd.Timestamp, series: pd.DataFrame
) -> tuple[FloatArray, BoolArray]:
    """Volatility of the surface `points` at each series' strike and expiry.

    Returns the volatilities (NaN with no surface) and whether each was read inside the
    surface, in both strike and expiry.
    """
    n = len(series)
    if points.empty or n == 0:
        return np.full(n, np.nan), np.zeros(n, dtype=bool)

    slices = _slices(points, spot, as_of)
    taus = np.array([tau for tau, _, _ in slices])
    target_tau = _years(series["expiry"], as_of)
    target_x = np.log(series["strike"].to_numpy(dtype=float) / spot)
    sigma = np.empty(n)
    interior = np.empty(n, dtype=bool)
    for i, (tau, x) in enumerate(zip(target_tau, target_x, strict=True)):
        sigma[i], interior[i] = _read(slices, taus, tau, x)
    return sigma, interior


def pair_netted(series: pd.DataFrame) -> pd.DataFrame:
    """`series` with `netted_oi`: each line's open interest less the opposite right's.

    Lines pair within root, expiry and strike. A new frame is returned.
    """
    out = series.copy()
    line = ["date", "root", "expiry", "strike"]
    calls = out["open_interest"].where(out["right"] == "C", 0)
    puts = out["open_interest"].where(out["right"] == "P", 0)
    call_total = calls.groupby([out[c] for c in line]).transform("sum")
    put_total = puts.groupby([out[c] for c in line]).transform("sum")
    own = np.where(out["right"] == "C", call_total, put_total)
    other = np.where(out["right"] == "C", put_total, call_total)
    share: FloatArray = out["open_interest"].to_numpy(dtype=float) / np.where(own > 0, own, 1)
    out["netted_oi"] = (np.clip(own - other, 0, None) * share).round().astype(int)
    return out


def listed_gamma(chains: pd.DataFrame, *, rate: float) -> pd.DataFrame:
    """Listed dollar gamma per date and symbol: gross, pair-netted, and vendor-signed.

    `chains` holds priced listed series (`date`, `symbol`, `root`, `expiry`, `right`,
    `strike`, `iv`, `open_interest`, `underlying_price`). Series expiring on or before
    their date and series without a usable volatility are out. Listed pairs net by the
    rule FLEX pairs net by, so the two sides are treated alike.
    """
    live = chains[(chains["expiry"] > chains["date"]) & chains["iv"].between(MIN_IV, MAX_IV)]
    live = pair_netted(live[live["open_interest"] > 0])
    if live.empty:
        return pd.DataFrame(columns=list(LISTED_COLUMNS))
    spot = live["underlying_price"].to_numpy(dtype=float)
    gamma = _gamma(spot, live["strike"], _years(live["expiry"], live["date"]), live["iv"], rate)
    dollars = dollar_gamma(gamma, live["open_interest"], spot)
    frame = live[KEYS].assign(
        listed_gross=dollars,
        listed_netted=dollar_gamma(gamma, live["netted_oi"], spot),
        listed_signed=np.where(live["right"] == "C", dollars, -dollars),
    )
    columns = ["listed_gross", "listed_netted", "listed_signed"]
    return frame.groupby(KEYS, as_index=False)[columns].sum()


def flex_gamma(series: pd.DataFrame, chains: pd.DataFrame, *, rate: float) -> pd.DataFrame:
    """Dollar gamma of each live FLEX series, priced on its underlying's listed surface.

    `series` holds FLEX rows (`date`, `symbol`, `root`, `expiry`, `right`, `strike`,
    `open_interest`); `chains` the listed rows of the same dates. A series expiring on or
    before its date, or whose symbol has no surface on its date, is out.
    """
    live = pair_netted(series[series["expiry"] > series["date"]])
    frames = []
    readings = {key: frame for key, frame in chains.groupby(KEYS, sort=False)}
    for key, group in live.groupby(KEYS, sort=True):
        reading = readings.get(key)
        if reading is None or reading.empty:
            continue
        day = pd.Timestamp(cast(str, key[0]))
        spot = float(reading["underlying_price"].iloc[0])
        sigma, interior = surface_vol(surface_points(reading), spot, day, group)
        frames.append(_priced(group, spot, sigma, interior, day, rate))
    if not frames:
        return pd.DataFrame(columns=list(FLEX_COLUMNS))
    return pd.concat(frames, ignore_index=True)[list(FLEX_COLUMNS)]


def gamma_shares(listed: pd.DataFrame, flex: pd.DataFrame) -> pd.DataFrame:
    """FLEX share of total dollar gamma per date and symbol, under each rule.

    Every listed date-symbol is kept; one with no FLEX has zero shares.
    `interior_oi_share` is the share of FLEX open interest priced inside the surface.
    """
    flex = flex.assign(interior_oi=flex["open_interest"].where(flex["interior"].astype(bool), 0))
    sums = flex.groupby(KEYS, as_index=False)[
        ["gross", "netted", "signed", "open_interest", "interior_oi"]
    ].sum()
    merged = listed.merge(sums, on=KEYS, how="left")
    filled = ["gross", "netted", "signed", "open_interest", "interior_oi"]
    merged[filled] = merged[filled].astype(float).fillna(0.0)
    merged = merged.rename(
        columns={"gross": "flex_gross", "netted": "flex_netted", "signed": "flex_signed"}
    )
    merged["share_gross"] = merged["flex_gross"] / (merged["flex_gross"] + merged["listed_gross"])
    merged["share_netted"] = merged["flex_netted"] / (
        merged["flex_netted"] + merged["listed_gross"]
    )
    both = merged["flex_netted"] + merged["listed_netted"]
    merged["share_netted_both"] = (merged["flex_netted"] / both.where(both > 0)).fillna(0.0)
    oi = merged["open_interest"]
    merged["interior_oi_share"] = (merged["interior_oi"] / oi.where(oi > 0)).fillna(0.0)
    return merged[list(SHARE_COLUMNS)].sort_values(KEYS).reset_index(drop=True)


def _priced(
    group: pd.DataFrame,
    spot: float,
    sigma: FloatArray,
    interior: BoolArray,
    day: pd.Timestamp,
    rate: float,
) -> pd.DataFrame:
    usable = np.isfinite(sigma)
    rows = group[usable].copy()
    years = _years(rows["expiry"], day)
    gamma = _gamma(np.full(len(rows), spot), rows["strike"], years, sigma[usable], rate)
    rows["sigma"] = sigma[usable]
    rows["interior"] = interior[usable]
    rows["days"] = (years * DAYS_PER_YEAR).round().astype(int)
    rows["moneyness"] = rows["strike"] / spot
    rows["gross"] = dollar_gamma(gamma, rows["open_interest"], spot)
    rows["netted"] = dollar_gamma(gamma, rows["netted_oi"], spot)
    rows["signed"] = np.where(rows["right"] == "C", rows["gross"], -rows["gross"])
    return rows


def _gamma(
    spot: npt.ArrayLike, strike: pd.Series, years: FloatArray, sigma: npt.ArrayLike, rate: float
) -> FloatArray:
    greeks = black_scholes_greeks(
        spot, strike.to_numpy(dtype=float), years, sigma, rate=rate, carry=0.0, is_call=True
    )
    return greeks.gamma


def _years(expiry: pd.Series, as_of: pd.Timestamp | pd.Series) -> FloatArray:
    days = (pd.to_datetime(expiry) - pd.to_datetime(as_of)).dt.days
    return np.asarray(days.to_numpy(dtype=float) / DAYS_PER_YEAR, dtype=np.float64)


def _slices(
    points: pd.DataFrame, spot: float, as_of: pd.Timestamp
) -> list[tuple[float, FloatArray, FloatArray]]:
    """(tau, log-moneyness, volatility) per listed expiry after `as_of`, by tau."""
    slices = []
    for expiry, group in points.groupby("expiry", sort=True):
        tau = (pd.Timestamp(cast(str, expiry)) - as_of).days / DAYS_PER_YEAR
        if tau <= 0:
            continue
        x = np.log(group["strike"].to_numpy(dtype=float) / spot)
        order = np.argsort(x)
        slices.append((tau, x[order], group["iv"].to_numpy(dtype=float)[order]))
    return slices


def _read(
    slices: list[tuple[float, FloatArray, FloatArray]], taus: FloatArray, tau: float, x: float
) -> tuple[float, bool]:
    if not slices:
        return float("nan"), False

    def at(index: int) -> tuple[float, bool]:
        _, xs, vols = slices[index]
        inside = bool(xs[0] <= x <= xs[-1])
        return float(np.interp(x, xs, vols)), inside

    if tau <= taus[0] or tau >= taus[-1] or len(slices) == 1:
        index = 0 if tau <= taus[0] else len(slices) - 1
        sigma, _ = at(index)
        exact = bool(np.isclose(tau, taus[index]))
        _, inside = at(index)
        return sigma, inside and exact

    upper = int(np.searchsorted(taus, tau))
    lower = upper - 1
    s_lo, in_lo = at(lower)
    s_hi, in_hi = at(upper)
    w_lo, w_hi = s_lo**2 * taus[lower], s_hi**2 * taus[upper]
    weight = (tau - taus[lower]) / (taus[upper] - taus[lower])
    total = max(w_lo + (w_hi - w_lo) * weight, MIN_TOTAL_VARIANCE)
    return float(np.sqrt(total / tau)), in_lo and in_hi


__all__ = [
    "CONTRACT_MULTIPLIER",
    "FLEX_COLUMNS",
    "LISTED_COLUMNS",
    "SHARE_COLUMNS",
    "dollar_gamma",
    "flex_gamma",
    "gamma_shares",
    "listed_gamma",
    "pair_netted",
    "surface_points",
    "surface_vol",
]
