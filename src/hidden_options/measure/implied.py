"""Implied volatility and greeks from OCC's FLEX marks (M5).

OCC marks every FLEX series it clears each night. Read against the underlying's price,
a mark gives back the volatility that prices it, and from that volatility the contract's
delta, gamma and vega. This module does both, and checks the volatilities against the
listed market where a FLEX series has a listed twin.

The model, one choice per input:

* European rows: Black-Scholes. American rows: a 200-step Cox-Ross-Rubinstein tree,
  except where early exercise never pays (see `pricing.early_exercise_matters`), where
  the closed form is exact.
* Rate RATE = 0.04, the constant `gamma_gap` already uses, and carry yield CARRY = 0: no
  dividends. Both are recorded with every result that uses them.
* Time: calendar days from the report date to expiry, over 365.
* Exercise style: the panel's, read from OCC's class heading; index rows are European
  (`flex_panel.load_panel`). Where an equity heading does not say, the FLEX product
  symbol's leading digit does (PREFIX_STYLES): wherever a heading names the style, 1
  goes with American and 2 and 4 with European. A row whose digit gives no answer is
  inverted as American. `style_source` says which of the three applied.
* Search: volatility between SIGMA_BOUNDS, 0.01% and 500%. One contract is solved with
  Brent's method; a frame is solved all at once by Newton steps kept inside a shrinking
  bracket, falling back to bisection when a step would leave it. The two agree to
  better than 1e-6 in volatility where the mark pins the volatility down.

Every row gets a status (InversionStatus); none is dropped. A row has a volatility only
when its status is OK.

Greeks are gross. Open interest is unsigned and summed over all holders, so a dollar
greek is that of the contracts outstanding held long; their writers hold the negative,
and the report does not say who is on which side. See GREEK_COLUMNS.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType
from typing import Literal

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from hidden_options.measure.hidden_share import CONTRACT_MULTIPLIER, listed_product
from hidden_options.measure.pricing import (
    BoolArray,
    FloatArray,
    binomial,
    binomial_greeks,
    black_scholes,
    black_scholes_greeks,
    black_scholes_vega,
    early_exercise_matters,
    lowest_tree_sigma,
)

RATE = 0.04
CARRY = 0.0
DAYS_PER_YEAR = 365
SIGMA_BOUNDS = (1e-4, 5.0)
# Convergence: the volatility bracket narrower than this, or the price within PRICE_TOL.
SIGMA_TOL = 1e-10
PRICE_TOL = 1e-9
# A mark this far outside what the model can price, at either end of the bracket, has no
# volatility. A hundredth of the report's 0.0001 price tick.
FLOOR_TOL = 1e-6
MAX_ITERATIONS = 100
STYLES = ("american", "european")
# The style each FLEX product-symbol prefix carries, as the marked class headings show it.
PREFIX_STYLES: Mapping[str, str] = MappingProxyType(
    {"1": "american", "2": "european", "4": "european"}
)
# The style of an equity row that neither its heading nor its prefix gives.
FALLBACK_STYLE = "american"
RIGHTS = ("C", "P")
# A one percent move in the underlying, for dollar gamma.
ONE_PERCENT = 0.01

# Strike over spot. Shared with the exposure profile, which bins by the same edges.
MONEYNESS_BINS = (0.7, 0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.3)
# Days to expiry: up to a week, a month, a quarter, a year, and beyond.
DTE_EDGES = (7, 30, 90, 365)
MONEYNESS_LABELS = (
    f"<{MONEYNESS_BINS[0]:.2f}",
    *(f"{low:.2f}-{high:.2f}" for low, high in pairwise(MONEYNESS_BINS)),
    f">={MONEYNESS_BINS[-1]:.2f}",
)
DTE_LABELS = (
    f"<={DTE_EDGES[0]}",
    *(f"{low + 1}-{high}" for low, high in pairwise(DTE_EDGES)),
    f">{DTE_EDGES[-1]}",
)
# A bucket is validated when FLEX and listed volatilities agree to within this median
# absolute gap, two vol points, over at least MIN_MATCHED matched series-days.
MAX_MEDIAN_DIFF = 0.02
MIN_MATCHED = 50

# The listed product a FLEX index series is the twin of: the AM-settled standard product
# for an AM-settled FLEX root (prefix 2), the PM-settled one for a PM-settled root (4).
INDEX_TWINS: Mapping[str, str] = MappingProxyType(
    {"2SPX": "SPX", "4SPX": "SPXW", "2NDX": "NDX", "4NDX": "NDXP", "2RUT": "RUT", "4RUT": "RUTW"}
)

GREEK_COLUMNS: Mapping[str, str] = MappingProxyType(
    {
        "delta": "Per contract: change in price per dollar of spot.",
        "gamma": "Per contract: change in delta per dollar of spot.",
        "vega": "Per contract: change in price for one vol point (0.01 of volatility).",
        "delta_dollars": (
            "Gross dollar delta of the open interest, delta x OI x 100 x spot: the exposure "
            "of the contracts outstanding held long. Their writers hold the negative, and "
            "the report does not say who holds which side."
        ),
        "gamma_dollars": (
            "Gross dollar gamma of the open interest, 1/2 x gamma x OI x 100 x spot^2 x "
            "0.01^2: what gamma alone adds to the long side's value on a one percent move."
        ),
        "vega_dollars": (
            "Gross dollar vega of the open interest, vega x OI x 100: the long side's change "
            "in value for one vol point."
        ),
    }
)

Model = Callable[[np.ndarray, FloatArray], FloatArray]


class InversionStatus(StrEnum):
    """What became of a row's inversion. Checked in this order; the first that applies wins.

    EXPIRED: the series expires on or before the report date, so it has no time value.
    ZERO_PRICE: the mark is zero, negative or missing.
    NO_SPOT: there is no price for the underlying on the date.
    BELOW_INTRINSIC: the mark is below the model's price at the bottom of the bracket,
        which is its intrinsic value: spot against strike now for an American row,
        against the discounted strike for a European one.
    NO_CONVERGENCE: no volatility in the bracket gives the mark (it is above the price at
        500%), or the search did not settle.
    OK: the row has a volatility.
    """

    OK = "ok"
    BELOW_INTRINSIC = "below_intrinsic"
    ZERO_PRICE = "zero_price"
    EXPIRED = "expired"
    NO_SPOT = "no_spot"
    NO_CONVERGENCE = "no_convergence"


def implied_vol(
    price: float,
    spot: float,
    strike: float,
    years: float,
    *,
    rate: float,
    carry: float,
    right: Literal["C", "P"],
    style: Literal["american", "european"],
) -> tuple[float, InversionStatus]:
    """The volatility that prices one contract at `price`, with Brent's method."""
    if right not in RIGHTS:
        raise ValueError(f"An option right is one of {RIGHTS}, got {right!r}")
    if style not in STYLES:
        raise ValueError(f"An exercise style is one of {STYLES}, got {style!r}")
    early = str(_precheck(np.array([price]), np.array([spot]), np.array([years]))[0])
    if early:
        return float("nan"), InversionStatus(early)
    is_call = np.array([right == "C"])
    on_tree = style == "american" and bool(
        early_exercise_matters(is_call, rate=rate, carry=carry)[0]
    )
    pricer = binomial if on_tree else black_scholes
    one = {"spot": [spot], "strike": [strike], "years": [years]}

    def gap(sigma: float) -> float:
        value = pricer(**one, sigma=[sigma], rate=rate, carry=carry, is_call=is_call)
        return float(value[0]) - price

    low = float(_floor(np.array([years]), on_tree, rate, carry)[0])
    high = SIGMA_BOUNDS[1]
    at_low, at_high = gap(low), gap(high)
    if at_low > FLOOR_TOL:
        return float("nan"), InversionStatus.BELOW_INTRINSIC
    if at_low >= -FLOOR_TOL:
        return low, InversionStatus.OK
    if at_high < -FLOOR_TOL:
        return float("nan"), InversionStatus.NO_CONVERGENCE
    if at_high <= FLOOR_TOL:
        return high, InversionStatus.OK
    root, info = brentq(
        gap, low, high, xtol=SIGMA_TOL, maxiter=MAX_ITERATIONS, full_output=True, disp=False
    )
    if not info.converged:
        return float("nan"), InversionStatus.NO_CONVERGENCE
    return float(root), InversionStatus.OK


def implied_vols(
    panel_day: pd.DataFrame, spots: Mapping[str, float], *, rate: float, carry: float = CARRY
) -> pd.DataFrame:
    """One report date's rows with `spot`, `years`, `inverted_as`, `iv` and `iv_status`.

    `spots` maps each underlying to its price on the date; an underlying missing from it
    gets NO_SPOT.
    """
    _one_date(panel_day)
    spot = panel_day["underlying"].map(dict(spots)).astype(float)
    return implied_vols_frame(panel_day.assign(spot=spot), rate=rate, carry=carry)


def implied_vols_frame(frame: pd.DataFrame, *, rate: float, carry: float = CARRY) -> pd.DataFrame:
    """`implied_vols` for a frame that carries its own `spot`, over any number of dates."""
    years = _years(frame)
    style = inversion_style(frame)
    iv, status = _invert(
        price=frame["mark_price"].to_numpy(dtype=float),
        spot=frame["spot"].to_numpy(dtype=float),
        strike=frame["strike"].to_numpy(dtype=float),
        years=years.to_numpy(dtype=float),
        is_call=_calls(frame),
        american=(style == "american").to_numpy(),
        rate=rate,
        carry=carry,
    )
    return frame.assign(years=years, inverted_as=style, iv=iv, iv_status=status)


def inversion_style(frame: pd.DataFrame) -> pd.Series:
    """The exercise style each row is inverted under: its heading's, else its prefix's,
    else American (see `style_source`).

    Only equity rows may lack a style: the panel reads an unmarked index heading as
    European, so an index row without one did not come through `load_panel`.
    """
    style = frame["exercise_style"].astype(object)
    unread = style.isna()
    if (unread & (frame["kind"] != "equity")).any():
        raise ValueError("An index row has no exercise style; load the panel with load_panel")
    by_prefix = product_prefix(frame["root"]).map(dict(PREFIX_STYLES))
    style = style.where(~unread, by_prefix.where(by_prefix.notna(), FALLBACK_STYLE))
    unknown = ~style.isin(STYLES)
    if unknown.any():
        raise ValueError(f"Unknown exercise style {style[unknown].iloc[0]!r}")
    return style.astype(object)


def style_source(frame: pd.DataFrame) -> pd.Series:
    """Where each row's inversion style comes from: `heading`, `prefix` or `fallback`."""
    unread = frame["exercise_style"].isna().to_numpy()
    known = product_prefix(frame["root"]).isin(set(PREFIX_STYLES)).to_numpy()
    source = np.where(~unread, "heading", np.where(known, "prefix", "fallback"))
    return pd.Series(source, index=frame.index, dtype=object)


def product_prefix(roots: pd.Series) -> pd.Series:
    """The leading digits of a FLEX product symbol (`1AAPL` to `1`)."""
    return roots.astype(str).str.extract(r"^(\d+)", expand=False)


def greeks(
    frame: pd.DataFrame, spots: Mapping[str, float], *, rate: float, carry: float = CARRY
) -> pd.DataFrame:
    """One report date's inverted rows with the GREEK_COLUMNS added (gross; see there)."""
    _one_date(frame)
    spot = frame["underlying"].map(dict(spots)).astype(float)
    return greeks_frame(frame.assign(spot=spot), rate=rate, carry=carry)


def greeks_frame(frame: pd.DataFrame, *, rate: float, carry: float = CARRY) -> pd.DataFrame:
    """`greeks` for a frame that carries its own `spot`, over any number of dates.

    A row is priced as it was inverted: on the tree where early exercise matters, in
    closed form elsewhere. A row without a volatility gets no greeks.
    """
    spot = frame["spot"].to_numpy(dtype=float)
    strike = frame["strike"].to_numpy(dtype=float)
    years = _years(frame).to_numpy(dtype=float)
    sigma = frame["iv"].to_numpy(dtype=float)
    is_call = _calls(frame)
    american = (inversion_style(frame) == "american").to_numpy()
    tree = american & early_exercise_matters(is_call, rate=rate, carry=carry)
    usable = np.isfinite(sigma) & (spot > 0) & (years > 0)
    delta, gamma, vega = (np.full(len(frame), np.nan) for _ in range(3))
    for on_tree, function in ((False, black_scholes_greeks), (True, binomial_greeks)):
        rows = np.flatnonzero(usable & (tree == on_tree))
        if rows.size:
            found = function(
                spot[rows],
                strike[rows],
                years[rows],
                sigma[rows],
                rate=rate,
                carry=carry,
                is_call=is_call[rows],
            )
            delta[rows], gamma[rows], vega[rows] = found
    contracts = frame["open_interest"].to_numpy(dtype=float) * CONTRACT_MULTIPLIER
    return frame.assign(
        delta=delta,
        gamma=gamma,
        vega=vega,
        delta_dollars=delta * contracts * spot,
        gamma_dollars=0.5 * gamma * contracts * spot**2 * ONE_PERCENT**2,
        vega_dollars=vega * contracts,
    )


def listed_twin(root: str, kind: str) -> str | None:
    """The listed product a FLEX series would match: its standard class, or None.

    An equity root drops its FLEX prefix (`2AAPL` to `AAPL`). An index root is looked up
    in INDEX_TWINS, so a series meets the listed product with its own settlement; a root
    without a listed twin in the chains gives None.
    """
    if kind == "index":
        return INDEX_TWINS.get(root)
    return listed_product(root, "equity")


def compare_with_listed(flex_iv: pd.DataFrame, chains: pd.DataFrame) -> pd.DataFrame:
    """FLEX rows that have a listed twin, with `iv_flex`, `iv_listed` and `diff`.

    A twin is the listed series of the same underlying, expiry, right and strike on the
    same date, in the listed product `listed_twin` names. The match is exact: strikes
    agree to the tenth of a cent OSI symbols carry. `chains` holds one listed series per
    match (`date`, `symbol`, `root`, `expiry`, `right`, `strike`, `iv`); a series listed
    twice is an error. FLEX rows keep their own columns; `diff` is `iv_flex - iv_listed`
    and is missing where either side has no volatility.
    """
    keys = ["_date", "_symbol", "_root", "_expiry", "right", "_strike"]
    pairs = flex_iv[["root", "kind"]].astype(str).drop_duplicates()
    twins = {(r, k): listed_twin(r, k) for r, k in pairs.itertuples(index=False)}
    flex = flex_iv.assign(
        _date=_day(flex_iv["report_date"]),
        _symbol=flex_iv["underlying"].astype(str),
        _root=pd.Series(
            [
                twins[(str(r), str(k))]
                for r, k in zip(flex_iv["root"], flex_iv["kind"], strict=True)
            ],
            index=flex_iv.index,
            dtype=object,
        ),
        _expiry=_day(flex_iv["expiry"]),
        _strike=_strike_key(flex_iv["strike"]),
    )
    listed = pd.DataFrame(
        {
            "_date": _day(chains["date"]),
            "_symbol": chains["symbol"].astype(str),
            "_root": chains["root"].astype(str),
            "_expiry": _day(chains["expiry"]),
            "right": chains["right"].astype(str),
            "_strike": _strike_key(chains["strike"]),
            "iv_listed": chains["iv"].astype(float),
        }
    )
    twice = listed.duplicated(keys, keep=False)
    if twice.any():
        first = listed[twice].iloc[0]
        raise ValueError(
            f"The chains list {first['_root']} {first['_expiry']:%Y-%m-%d} {first['right']} "
            f"{first['_strike'] / 1000:g} more than once on {first['_date']:%Y-%m-%d}"
        )
    matched = flex.merge(listed, on=keys, how="inner").drop(columns=keys[:4] + ["_strike"])
    matched = matched.rename(columns={"iv": "iv_flex"})
    matched["diff"] = matched["iv_flex"] - matched["iv_listed"]
    return matched


def bucket(moneyness: float, days_to_expiry: int) -> tuple[str, str]:
    """The moneyness (strike over spot) and days-to-expiry buckets of one contract."""
    if not np.isfinite(moneyness):
        raise ValueError(f"A bucket needs a finite moneyness, got {moneyness!r}")
    m = int(np.searchsorted(MONEYNESS_BINS, moneyness, side="right"))
    d = int(np.searchsorted(DTE_EDGES, days_to_expiry, side="left"))
    return MONEYNESS_LABELS[m], DTE_LABELS[d]


def buckets(moneyness: pd.Series, days_to_expiry: pd.Series) -> pd.DataFrame:
    """`bucket` over two aligned series; a row without a moneyness gets no moneyness bucket."""
    values = moneyness.to_numpy(dtype=float)
    m = np.searchsorted(MONEYNESS_BINS, values, side="right")
    d = np.searchsorted(DTE_EDGES, days_to_expiry.to_numpy(dtype=float), side="left")
    labels = np.array(MONEYNESS_LABELS, dtype=object)[m]
    labels[~np.isfinite(values)] = None
    return pd.DataFrame(
        {"moneyness_bucket": labels, "dte_bucket": np.array(DTE_LABELS, dtype=object)[d]},
        index=moneyness.index,
    )


def bucketed(frame: pd.DataFrame) -> pd.DataFrame:
    """`frame` with `moneyness` (strike over spot), `days_to_expiry` and both buckets."""
    moneyness = frame["strike"] / frame["spot"]
    days = (pd.to_datetime(frame["expiry"]) - pd.to_datetime(frame["report_date"])).dt.days
    out = frame.assign(moneyness=moneyness, days_to_expiry=days)
    return pd.concat([out, buckets(moneyness, days)], axis=1)


def validated_domain(
    validation: pd.DataFrame,
    *,
    max_median_diff: float = MAX_MEDIAN_DIFF,
    min_matched: int = MIN_MATCHED,
) -> frozenset[tuple[str, str]]:
    """The (moneyness, days-to-expiry) buckets where the inversion agrees with listed IV.

    A bucket qualifies when its median |iv_flex - iv_listed| is at most `max_median_diff`
    over at least `min_matched` series-days with both volatilities.
    """
    usable = validation[np.isfinite(validation["diff"]) & validation["moneyness_bucket"].notna()]
    gaps = usable.assign(gap=usable["diff"].abs()).groupby(["moneyness_bucket", "dte_bucket"])
    stats = gaps["gap"].agg(["size", "median"])
    keep = stats[(stats["size"] >= min_matched) & (stats["median"] <= max_median_diff)]
    return frozenset((str(m), str(d)) for m, d in keep.index)


def _invert(
    *,
    price: FloatArray,
    spot: FloatArray,
    strike: FloatArray,
    years: FloatArray,
    is_call: BoolArray,
    american: BoolArray,
    rate: float,
    carry: float,
) -> tuple[FloatArray, np.ndarray]:
    """Volatility and status for every row; the tree only where early exercise matters."""
    iv = np.full(price.size, np.nan)
    early = _precheck(price, spot, years)
    open_rows = early == ""
    status = np.where(open_rows, InversionStatus.OK.value, early).astype(object)
    tree = american & early_exercise_matters(is_call, rate=rate, carry=carry)
    for on_tree in (False, True):
        rows = np.flatnonzero(open_rows & (tree == on_tree))
        if rows.size:
            iv[rows], status[rows] = _invert_rows(
                price[rows],
                spot[rows],
                strike[rows],
                years[rows],
                is_call[rows],
                on_tree,
                rate,
                carry,
            )
    return iv, status


def _invert_rows(
    price: FloatArray,
    spot: FloatArray,
    strike: FloatArray,
    years: FloatArray,
    is_call: BoolArray,
    on_tree: bool,
    rate: float,
    carry: float,
) -> tuple[FloatArray, np.ndarray]:
    """Rows priced by one model: the bracket ends first, then the search inside it."""
    pricer = binomial if on_tree else black_scholes

    def model(rows: np.ndarray, sigma: FloatArray) -> FloatArray:
        return pricer(
            spot[rows],
            strike[rows],
            years[rows],
            sigma,
            rate=rate,
            carry=carry,
            is_call=is_call[rows],
        )

    def slope(rows: np.ndarray, sigma: FloatArray) -> FloatArray:
        return black_scholes_vega(
            spot[rows], strike[rows], years[rows], sigma, rate=rate, carry=carry
        )

    every = np.arange(price.size)
    low = _floor(years, on_tree, rate, carry)
    high = np.full(price.size, SIGMA_BOUNDS[1])
    at_low, at_high = model(every, low) - price, model(every, high) - price
    iv = np.full(price.size, np.nan)
    status = np.full(price.size, InversionStatus.OK.value, dtype=object)
    below = at_low > FLOOR_TOL
    on_low = ~below & (at_low >= -FLOOR_TOL)
    above = ~below & ~on_low & (at_high < -FLOOR_TOL)
    on_high = ~below & ~on_low & ~above & (at_high <= FLOOR_TOL)
    status[below] = InversionStatus.BELOW_INTRINSIC.value
    status[above] = InversionStatus.NO_CONVERGENCE.value
    iv[on_low], iv[on_high] = low[on_low], high[on_high]

    inside = np.flatnonzero(~(below | on_low | above | on_high))
    if inside.size:
        start = _start(price, spot, strike, years, is_call, inside, on_tree, rate, carry)
        sigma, converged = _search(
            lambda rows, s: model(inside[rows], s),
            lambda rows, s: slope(inside[rows], s),
            price[inside],
            low[inside],
            high[inside],
            start,
        )
        iv[inside[converged]] = sigma[converged]
        status[inside[~converged]] = InversionStatus.NO_CONVERGENCE.value
    return iv, status


def _start(
    price: FloatArray,
    spot: FloatArray,
    strike: FloatArray,
    years: FloatArray,
    is_call: BoolArray,
    rows: np.ndarray,
    on_tree: bool,
    rate: float,
    carry: float,
) -> FloatArray:
    """Where the search begins.

    In closed form, at the price curve's inflection, sqrt(2 |ln(F/K)| / T), from which
    Newton's method moves monotonically to the root (Manaster and Koehler 1982). On the
    tree, at the European volatility of the same mark: the early-exercise premium makes
    the American volatility lower, so the first step only has to come down.
    """
    s, k, t = spot[rows], strike[rows], years[rows]
    if not on_tree:
        forward = s * np.exp((rate - carry) * t)
        return np.asarray(np.sqrt(2.0 * np.abs(np.log(forward / k)) / t), dtype=np.float64)
    european, _ = _invert_rows(price[rows], s, k, t, is_call[rows], False, rate, carry)
    return np.where(np.isfinite(european), european, 0.5)


def _search(
    model: Model,
    slope: Model,
    target: FloatArray,
    low: FloatArray,
    high: FloatArray,
    start: FloatArray,
) -> tuple[FloatArray, BoolArray]:
    """Bracketed Newton over arrays: each row's price at `low` is below its target and at
    `high` above it.

    A Newton step that would leave the bracket is replaced by bisection, and so is the
    next step of a row whose bracket has not halved in two iterations. The second rule
    matters on the tree, whose price can bend sharply where early exercise starts to pay:
    there the closed-form vega used as the slope is far too steep and Newton's steps
    shrink without end.
    """
    low, high = low.copy(), high.copy()
    sigma = np.clip(start, low, high)
    converged = np.zeros(target.size, dtype=bool)
    older = np.full(target.size, np.inf)
    newer = np.full(target.size, np.inf)
    active = np.arange(target.size)
    for _ in range(MAX_ITERATIONS):
        if not active.size:
            break
        current = sigma[active]
        gap = model(active, current) - target[active]
        under = gap < 0
        low[active] = np.where(under, current, low[active])
        high[active] = np.where(under, high[active], current)
        width = high[active] - low[active]
        done = (np.abs(gap) <= PRICE_TOL) | (width <= SIGMA_TOL)
        converged[active[done]] = True
        slow = width > 0.5 * older[active]
        older[active], newer[active] = newer[active], width
        with np.errstate(divide="ignore", invalid="ignore"):
            step = current - gap / slope(active, current)
        within = np.isfinite(step) & (step > low[active]) & (step < high[active]) & ~slow
        middle = 0.5 * (low[active] + high[active])
        sigma[active] = np.where(done, current, np.where(within, step, middle))
        active = active[~done]
    return sigma, converged


def _precheck(price: FloatArray, spot: FloatArray, years: FloatArray) -> np.ndarray:
    """The status of rows that need no search: EXPIRED, ZERO_PRICE or NO_SPOT, in that
    order; an empty string for a row that goes on to the search."""
    with np.errstate(invalid="ignore"):
        expired = ~(years > 0)
        zero = ~expired & ~(price > 0)
        no_spot = ~expired & ~zero & ~(spot > 0)
    found = np.full(price.size, "", dtype=object)
    found[expired] = InversionStatus.EXPIRED.value
    found[zero] = InversionStatus.ZERO_PRICE.value
    found[no_spot] = InversionStatus.NO_SPOT.value
    return found


def _floor(years: FloatArray, on_tree: bool, rate: float, carry: float) -> FloatArray:
    """The bottom of the volatility bracket: 1e-4, or the tree's own floor."""
    if on_tree:
        return np.maximum(lowest_tree_sigma(years, rate=rate, carry=carry), SIGMA_BOUNDS[0])
    return np.full(years.size, SIGMA_BOUNDS[0])


def _years(frame: pd.DataFrame) -> pd.Series:
    days = (pd.to_datetime(frame["expiry"]) - pd.to_datetime(frame["report_date"])).dt.days
    return days / DAYS_PER_YEAR


def _calls(frame: pd.DataFrame) -> BoolArray:
    rights = frame["right"].astype(str)
    unknown = ~rights.isin(RIGHTS)
    if unknown.any():
        raise ValueError(f"An option right is one of {RIGHTS}, got {rights[unknown].iloc[0]!r}")
    return (rights == "C").to_numpy()


def _one_date(frame: pd.DataFrame) -> None:
    if frame["report_date"].nunique() > 1:
        raise ValueError("Pass one report date at a time: spots are keyed by underlying")


def _day(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values).astype("datetime64[ns]").dt.normalize()


def _strike_key(strikes: pd.Series) -> pd.Series:
    """A strike in thousandths of a dollar, the precision of an OSI symbol."""
    return (strikes.astype(float) * 1000).round().astype("int64")


__all__ = [
    "CARRY",
    "DTE_EDGES",
    "DTE_LABELS",
    "GREEK_COLUMNS",
    "FALLBACK_STYLE",
    "INDEX_TWINS",
    "MAX_MEDIAN_DIFF",
    "MIN_MATCHED",
    "MONEYNESS_BINS",
    "MONEYNESS_LABELS",
    "PREFIX_STYLES",
    "RATE",
    "SIGMA_BOUNDS",
    "InversionStatus",
    "bucket",
    "bucketed",
    "buckets",
    "compare_with_listed",
    "greeks",
    "greeks_frame",
    "implied_vol",
    "implied_vols",
    "implied_vols_frame",
    "inversion_style",
    "listed_twin",
    "product_prefix",
    "style_source",
    "validated_domain",
]
