"""The gamma-based predictive panel: hidden dollar gamma at T against volatility from T+1.

Specification: `docs/log/2026-11-08-gamma-predictive-spec.md`. The base panel, its
controls, outcomes and publication lag are `predict.panel.build_predictive_panel`'s; this
module adds the predictors built from FLEX gamma and the range outcome.

Per underlying and activity date, `aggregate_gamma` sums dollar gamma (the change in
dollar delta for a 1% move) over the series whose own mark inverts inside a validated
cell: pair-netted (`g_net`), gross (`g_gross`) and in the vendor convention, calls up and
puts down (`g_signed`). `coverage` is the share of the underlying's live FLEX open
interest that is priced. `gamma_predictors` scales each by the mean dollar volume of the
twenty sessions ending at T and sets the predictor missing where coverage is below
COVERAGE_MIN.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hidden_options.measure.hidden_gamma import dollar_gamma
from hidden_options.predict.panel import _sessions

COVERAGE_MIN = 0.5
ADV_WINDOW = 20
LEAD = 2
WINSOR = (0.01, 0.99)
RAW_PREDICTORS = ("x_net_raw", "x_gross_raw", "x_signed_raw", "x_net_lead_raw")
GAMMA_COLUMNS = ("date", "underlying", "g_net", "g_gross", "g_signed", "coverage", "flex_oi")


def aggregate_gamma(rows: pd.DataFrame) -> pd.DataFrame:
    """Per date and underlying: dollar gamma of the validated rows and their coverage.

    `rows` are one or more dates' live FLEX series with `netted_oi` (from
    `hidden_gamma.pair_netted`), `in_domain`, `gamma` and `spot`.
    """
    usable = rows["in_domain"].astype(bool) & rows["gamma"].notna() & rows["spot"].notna()
    gamma = rows["gamma"].where(usable, 0.0).to_numpy(dtype=float)
    spot = rows["spot"].fillna(0.0).to_numpy(dtype=float)
    gross = dollar_gamma(gamma, rows["open_interest"], spot)
    frame = rows[["date", "underlying"]].assign(
        g_gross=gross,
        g_net=dollar_gamma(gamma, rows["netted_oi"], spot),
        g_signed=np.where(rows["right"] == "C", gross, -gross),
        priced_oi=rows["open_interest"].where(usable, 0),
        flex_oi=rows["open_interest"],
    )
    sums = frame.groupby(["date", "underlying"], as_index=False)[
        ["g_net", "g_gross", "g_signed", "priced_oi", "flex_oi"]
    ].sum()
    total = sums["flex_oi"].where(sums["flex_oi"] > 0)
    sums["coverage"] = (sums["priced_oi"] / total).fillna(0.0)
    return sums[list(GAMMA_COLUMNS)]


def gamma_predictors(daily: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Raw predictors per symbol and date: dollar gamma over twenty-session dollar volume.

    `daily` is `aggregate_gamma` output over all dates; `bars` the daily bars. The lead is
    the netted predictor LEAD report dates later, on the calendar of `daily`.
    """
    adv = _adv(bars)
    frame = daily.rename(columns={"underlying": "symbol"}).merge(
        adv, on=["symbol", "date"], how="left"
    )
    covered = frame["coverage"] >= COVERAGE_MIN
    for name, column in (
        ("x_net_raw", "g_net"),
        ("x_gross_raw", "g_gross"),
        ("x_signed_raw", "g_signed"),
    ):
        frame[name] = (frame[column] / frame["adv"]).where(covered)

    calendar = pd.DatetimeIndex(sorted(frame["date"].unique()))
    position = calendar.get_indexer(frame["date"])  # type: ignore[arg-type]
    later = frame[["symbol", "x_net_raw"]].assign(position=position - LEAD)
    frame = frame.assign(position=position).merge(
        later.rename(columns={"x_net_raw": "x_net_lead_raw"}),
        on=["symbol", "position"],
        how="left",
    )
    return frame[["symbol", "date", "coverage", *RAW_PREDICTORS]]


def standardise(values: pd.Series) -> pd.Series:
    """Winsorised at the pooled WINSOR quantiles, then divided by its standard deviation.

    Not demeaned: every regression it enters carries fixed effects.
    """
    low, high = values.quantile(list(WINSOR))
    clipped = values.clip(lower=low, upper=high)
    sd = clipped.std(ddof=1)
    scaled: pd.Series = clipped / sd if sd and np.isfinite(sd) else clipped * np.nan
    return scaled


def range_outcome(bars: pd.DataFrame) -> pd.DataFrame:
    """Per symbol and session: log(high / low), the Parkinson range of that session."""
    frame = bars[["symbol", "timestamp", "high", "low"]].copy()
    frame["session"] = _sessions(frame["timestamp"])
    valid = (frame["high"] > 0) & (frame["low"] > 0)
    frame["log_range"] = pd.Series(np.log(frame["high"] / frame["low"]), index=frame.index).where(
        valid
    )
    return frame[["symbol", "session", "log_range"]].reset_index(drop=True)


def _adv(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars[["symbol", "timestamp", "close", "volume"]].copy()
    frame["date"] = _sessions(frame["timestamp"])
    frame = frame.sort_values(["symbol", "date"])
    dollar = frame["close"] * frame["volume"]
    frame["adv"] = dollar.groupby(frame["symbol"], sort=False).transform(
        lambda s: s.rolling(ADV_WINDOW, min_periods=ADV_WINDOW).mean()
    )
    frame["adv"] = frame["adv"].where(frame["adv"] > 0)
    return frame[["symbol", "date", "adv"]]


__all__ = [
    "ADV_WINDOW",
    "COVERAGE_MIN",
    "GAMMA_COLUMNS",
    "LEAD",
    "RAW_PREDICTORS",
    "aggregate_gamma",
    "gamma_predictors",
    "range_outcome",
    "standardise",
]
