"""Does FLEX open interest convert into listed series?

Exchange rules allow FLEX open interest in a series whose terms match a listed series to
be consolidated into the listed one. A conversion shows in the data as FLEX open interest
vanishing before expiry while the listed twin, same underlying, expiry, right and strike,
gains as much on the same settlement. `conversion_check` measures how much of the FLEX
open interest that vanishes before expiry is matched that way. As a baseline it applies
the same matching to FLEX creations, which no conversion explains: matching there is
coincidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

KEY = ["symbol", "expiry", "right", "strike"]
# A listed rise of at least this share of the FLEX change counts as matching it.
MATCH_SHARE = 0.9


def conversion_check(
    flex: pd.DataFrame,
    listed: pd.DataFrame,
    *,
    lags: Sequence[int] = (),
    n_boot: int = 0,
    seed: int = 0,
) -> dict[str, Any]:
    """`flex`: FLEX series (date, root, symbol, expiry, right, strike, open_interest) on the
    settlements of `listed`, listed open interest per (date, symbol, expiry, right, strike).

    Shares are of contracts. `*_twin` shares are conditioned on the listed twin existing on
    both settlements, so dropped and created contracts are compared on the same base.
    `detect_power` is the share of dropped contracts with a twin whose conversion the rule
    would have caught, given the twin's other flow that day. `lags` re-measures the
    matched shares with listed open interest read that many settlements later. With
    `n_boot`, the excess of dropped over created matching is bootstrapped by settlement.
    """
    dates = pd.DatetimeIndex(sorted(listed["date"].unique()))
    pairs = _pairs(flex, listed, dates, lag=0)
    twins = flex.merge(listed[["date", *KEY]].drop_duplicates(), on=["date", *KEY], how="inner")
    out: dict[str, Any] = {
        "twin_oi_share": _share(twins["open_interest"].sum(), flex["open_interest"].sum()),
        **_shares(pairs),
        "settlements": len(dates),
    }
    if lags:
        out["lags"] = {str(k): _shares(_pairs(flex, listed, dates, lag=k)) for k in lags}
    if n_boot:
        out.update(_bootstrap(pairs, n_boot, seed))
    return out


def _pairs(
    flex: pd.DataFrame, listed: pd.DataFrame, dates: pd.DatetimeIndex, *, lag: int
) -> pd.DataFrame:
    """Per FLEX series and pair of consecutive settlements: the drop, the creation, and the
    listed twin's change, read `lag` settlements later."""
    following = pd.Series(dates[1:], index=dates[:-1])
    by_series = pd.DataFrame(
        flex.groupby(["date", "root", *KEY], as_index=False)["open_interest"].sum()
    )
    by_series["next"] = by_series["date"].map(following)
    later = by_series[["date", "root", *KEY, "open_interest"]].rename(
        columns={"date": "next", "open_interest": "oi_next"}
    )
    pairs = by_series.merge(later, on=["next", "root", *KEY], how="left").fillna({"oi_next": 0})
    pairs = pairs[pairs["next"].notna() & (pairs["expiry"] > pairs["next"])]
    pairs = _with_listed(pairs, _relabelled(listed, dates, lag))
    return pairs.assign(
        drop=(pairs["open_interest"] - pairs["oi_next"]).clip(lower=0),
        rise=(pairs["oi_next"] - pairs["open_interest"]).clip(lower=0),
        listed_rise=pairs["listed_next"] - pairs["listed"],
        twin=pairs["listed"].notna() & pairs["listed_next"].notna(),
    )


def _relabelled(listed: pd.DataFrame, dates: pd.DatetimeIndex, lag: int) -> pd.DataFrame:
    """`listed` with each settlement labelled `lag` settlements earlier, so a merge on date
    reads the listed open interest of `lag` settlements later."""
    if lag == 0:
        return listed
    position = dates.get_indexer(pd.DatetimeIndex(listed["date"]))
    target = position - lag
    keep = (target >= 0) & (target < len(dates))
    return listed[keep].assign(date=dates[target[keep]])


def _shares(pairs: pd.DataFrame) -> dict[str, Any]:
    drop, rise, listed_rise, twin = (
        pairs["drop"],
        pairs["rise"],
        pairs["listed_rise"],
        pairs["twin"],
    )
    dropped_matched = drop[twin & (listed_rise >= MATCH_SHARE * drop) & (drop > 0)].sum()
    created_matched = rise[twin & (listed_rise >= MATCH_SHARE * rise) & (rise > 0)].sum()
    detectable = drop[twin & (listed_rise + drop >= MATCH_SHARE * drop) & (drop > 0)].sum()
    return {
        "dropped_contracts": float(drop.sum()),
        "dropped_series_days": int((drop > 0).sum()),
        "dropped_with_twin": _share(drop[twin].sum(), drop.sum()),
        "dropped_matched": _share(dropped_matched, drop.sum()),
        "dropped_matched_twin": _share(dropped_matched, drop[twin].sum()),
        "created_contracts": float(rise.sum()),
        "created_with_twin": _share(rise[twin].sum(), rise.sum()),
        "created_matched": _share(created_matched, rise.sum()),
        "created_matched_twin": _share(created_matched, rise[twin].sum()),
        "detect_power": _share(detectable, drop[twin].sum()),
    }


def _bootstrap(pairs: pd.DataFrame, n_boot: int, seed: int) -> dict[str, float]:
    """The excess of dropped over created matching, given a twin, resampling settlements."""
    twin = pairs[pairs["twin"]]
    matched_drop = twin["drop"].where(twin["listed_rise"] >= MATCH_SHARE * twin["drop"], 0)
    matched_rise = twin["rise"].where(twin["listed_rise"] >= MATCH_SHARE * twin["rise"], 0)
    sums = (
        twin.assign(matched_drop=matched_drop, matched_rise=matched_rise)
        .groupby("date")[["drop", "rise", "matched_drop", "matched_rise"]]
        .sum()
        .to_numpy()
    )

    def excess(rows: np.ndarray) -> float:
        total = rows.sum(axis=0)
        return _share(total[2], total[0]) - _share(total[3], total[1])

    rng = np.random.default_rng(seed)
    draws = np.array([excess(sums[rng.integers(0, len(sums), len(sums))]) for _ in range(n_boot)])
    low, high, upper = np.quantile(draws, [0.025, 0.975, 0.95])
    return {
        "excess": excess(sums),
        "excess_ci_low": float(low),
        "excess_ci_high": float(high),
        "excess_upper95": float(upper),
        "n_boot": n_boot,
    }


def _with_listed(pairs: pd.DataFrame, listed: pd.DataFrame) -> pd.DataFrame:
    now = listed.rename(columns={"open_interest": "listed"})[["date", *KEY, "listed"]]
    then = listed.rename(columns={"date": "next", "open_interest": "listed_next"})[
        ["next", *KEY, "listed_next"]
    ]
    return pairs.merge(now, on=["date", *KEY], how="left").merge(
        then, on=["next", *KEY], how="left"
    )


def _share(part: float, whole: float) -> float:
    return float(part / whole) if whole else 0.0


__all__ = ["MATCH_SHARE", "conversion_check"]
