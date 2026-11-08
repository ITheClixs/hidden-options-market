"""The gamma test's timing rows: gamma priced on another date's inputs.

Specification: `docs/log/2026-11-08-gamma-timing-spec.md`. The registered predictor prices
report T's open interest with T's spot and implied volatilities. Here one date's open
interest is priced with the per-series gamma and spot of another:

- R1 holds report T's open interest at T-1's pricing, so only open interest is dated T;
- R4 holds report T+2's open interest at T's pricing, so only open interest moves
  between the registered lead's two dates.

A series is the same across dates when root, expiry, right and strike agree. One that was
not priced inside a validated cell on the pricing date counts as unpriced.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

from hidden_options.measure.hidden_gamma import dollar_gamma
from hidden_options.predict.gamma_panel import ADV_WINDOW, COVERAGE_MIN, LEAD
from hidden_options.predict.panel import _sessions

SERIES = ["root", "expiry", "right", "strike"]
PRICING_COLUMNS = [*SERIES, "gamma", "spot"]
TIMING_COLUMNS = (
    "date",
    "underlying",
    "g_net_pre",
    "coverage_pre",
    "g_net_lead_fixed",
    "coverage_lead_fixed",
    "iv_oi",
)


def pricing(priced: pd.DataFrame) -> pd.DataFrame:
    """The per-series gamma and spot of one date's validated rows, for `carried_gamma`."""
    usable = priced["in_domain"].astype(bool) & priced["gamma"].notna() & priced["spot"].notna()
    return priced.loc[usable, PRICING_COLUMNS].drop_duplicates(SERIES).reset_index(drop=True)


def carried_gamma(
    priced_from: pd.DataFrame, held: pd.DataFrame, date: pd.Timestamp
) -> pd.DataFrame:
    """Per underlying: pair-netted dollar gamma of `held`'s open interest at the gamma and
    spot each series had in `priced_from`, and the share of open interest so priced.

    `priced_from` is a `priced_rows` frame or its `pricing`; `held` one date's rows with
    `netted_oi`. The output is dated `date`.
    """
    prices = pricing(priced_from) if "in_domain" in priced_from else priced_from
    frame = held[["underlying", *SERIES, "open_interest", "netted_oi"]].merge(
        prices, on=SERIES, how="left"
    )
    known = frame["gamma"].notna()
    frame = frame.assign(
        g_net=np.where(
            known,
            dollar_gamma(frame["gamma"].fillna(0.0), frame["netted_oi"], frame["spot"].fillna(0.0)),
            0.0,
        ),
        priced_oi=frame["open_interest"].where(known, 0),
    )
    sums = frame.groupby("underlying", as_index=False)[
        ["g_net", "priced_oi", "open_interest"]
    ].sum()
    total = sums["open_interest"].where(sums["open_interest"] > 0)
    return pd.DataFrame(
        {
            "date": date,
            "underlying": sums["underlying"],
            "g_net": sums["g_net"],
            "coverage": (sums["priced_oi"] / total).fillna(0.0),
        }
    )


def oi_weighted_iv(priced: pd.DataFrame) -> pd.DataFrame:
    """Per date and underlying: the open-interest-weighted implied volatility of the series
    priced inside a validated cell."""
    usable = priced["in_domain"].astype(bool) & priced["iv"].notna()
    frame = priced.loc[usable, ["date", "underlying", "iv", "open_interest"]]
    frame = frame.assign(weighted=frame["iv"] * frame["open_interest"])
    sums = frame.groupby(["date", "underlying"], as_index=False)[
        ["weighted", "open_interest"]
    ].sum()
    sums["iv_oi"] = sums["weighted"] / sums["open_interest"].where(sums["open_interest"] > 0)
    return sums[["date", "underlying", "iv_oi"]]


def timing_daily(
    days: Iterable[pd.Timestamp], priced_on: Callable[[pd.Timestamp], pd.DataFrame]
) -> pd.DataFrame:
    """TIMING_COLUMNS per report date and underlying, over `days` in order.

    `priced_on(day)` gives that report's `priced_rows` with `netted_oi`. Only the pricing
    of the last LEAD dates is held, so the walk runs in the memory of one report.
    """
    history: deque[tuple[pd.Timestamp, pd.DataFrame]] = deque(maxlen=LEAD)
    pre, lead, iv = [], [], []
    for day in days:
        priced = priced_on(day)
        if history:
            pre.append(carried_gamma(history[-1][1], priced, day))
        if len(history) == LEAD:
            lead.append(carried_gamma(history[0][1], priced, history[0][0]))
        iv.append(oi_weighted_iv(priced))
        history.append((day, pricing(priced)))
    return _combine(pre, lead, iv)


def _combine(
    pre: list[pd.DataFrame], lead: list[pd.DataFrame], iv: list[pd.DataFrame]
) -> pd.DataFrame:
    keys = ["date", "underlying"]
    empty = pd.DataFrame(columns=[*keys, "g_net", "coverage"])
    pre_frame = (pd.concat(pre, ignore_index=True) if pre else empty).rename(
        columns={"g_net": "g_net_pre", "coverage": "coverage_pre"}
    )
    lead_frame = (pd.concat(lead, ignore_index=True) if lead else empty).rename(
        columns={"g_net": "g_net_lead_fixed", "coverage": "coverage_lead_fixed"}
    )
    out = pd.concat(iv, ignore_index=True) if iv else pd.DataFrame(columns=[*keys, "iv_oi"])
    for frame in (pre_frame, lead_frame):
        out = out.merge(frame, on=keys, how="outer")
    return out[list(TIMING_COLUMNS)].sort_values(keys).reset_index(drop=True)


def timing_predictors(
    daily: pd.DataFrame, bars: pd.DataFrame, splits: pd.DataFrame
) -> pd.DataFrame:
    """Raw timing predictors per symbol and date.

    `daily` holds TIMING_COLUMNS. `x_pre_raw` is R1's gamma over the dollar volume of the
    ADV_WINDOW sessions ending at T-1; `x_lead_fixed_raw` is R4's over the window ending at
    T; `log_iv` is R2's control. A split ex-date on T drops `x_pre_raw`, one in the LEAD
    sessions after T drops `x_lead_fixed_raw`: strikes and spot would be on two bases.
    """
    adv = _adv_with_previous(bars)
    frame = daily.rename(columns={"underlying": "symbol"}).merge(
        adv, on=["symbol", "date"], how="left"
    )
    pre_split, lead_split = _split_flags(frame, adv, splits)
    frame["x_pre_raw"] = (frame["g_net_pre"] / frame["adv_prev"]).where(
        (frame["coverage_pre"] >= COVERAGE_MIN) & ~pre_split
    )
    frame["x_lead_fixed_raw"] = (frame["g_net_lead_fixed"] / frame["adv"]).where(
        (frame["coverage_lead_fixed"] >= COVERAGE_MIN) & ~lead_split
    )
    iv = frame["iv_oi"].where(frame["iv_oi"] > 0)
    frame["log_iv"] = np.log(iv.astype(float))
    return frame[["symbol", "date", "x_pre_raw", "x_lead_fixed_raw", "log_iv"]]


def _adv_with_previous(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars[["symbol", "timestamp", "close", "volume"]].copy()
    frame["date"] = _sessions(frame["timestamp"])
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    dollar = frame["close"] * frame["volume"]
    adv = dollar.groupby(frame["symbol"], sort=False).transform(
        lambda s: s.rolling(ADV_WINDOW, min_periods=ADV_WINDOW).mean()
    )
    frame["adv"] = adv.where(adv > 0)
    frame["adv_prev"] = frame.groupby("symbol", sort=False)["adv"].shift(1)
    frame["position"] = frame.groupby("symbol", sort=False).cumcount()
    return frame[["symbol", "date", "adv", "adv_prev", "position"]]


def _split_flags(
    frame: pd.DataFrame, adv: pd.DataFrame, splits: pd.DataFrame
) -> tuple[pd.Series, pd.Series]:
    """Whether a split ex-date falls on T, and whether one falls in the LEAD sessions after,
    on each symbol's own bar sessions."""
    none = pd.Series(False, index=frame.index)
    if splits.empty:
        return none, none.copy()
    ex = splits.assign(session=pd.to_datetime(splits["session"]))
    ex = ex.merge(
        adv[["symbol", "date", "position"]].rename(
            columns={"date": "session", "position": "ex_position"}
        ),
        on=["symbol", "session"],
        how="inner",
    )
    pre = pd.Series(
        pd.MultiIndex.from_frame(frame[["symbol", "date"]]).isin(
            pd.MultiIndex.from_frame(ex[["symbol", "session"]])
        ),
        index=frame.index,
    )
    pairs = (
        frame[["symbol", "position"]]
        .reset_index()
        .merge(ex[["symbol", "ex_position"]], on="symbol")
    )
    ahead = pairs["ex_position"] - pairs["position"]
    hit = pairs.loc[(ahead > 0) & (ahead <= LEAD), "index"].unique()
    lead = pd.Series(frame.index.isin(hit), index=frame.index)
    return pre, lead


__all__ = [
    "PRICING_COLUMNS",
    "TIMING_COLUMNS",
    "carried_gamma",
    "oi_weighted_iv",
    "pricing",
    "timing_daily",
    "timing_predictors",
]
