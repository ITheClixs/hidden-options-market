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

from typing import Any

import pandas as pd

KEY = ["symbol", "expiry", "right", "strike"]
# A listed rise of at least this share of the FLEX change counts as matching it.
MATCH_SHARE = 0.9


def conversion_check(flex: pd.DataFrame, listed: pd.DataFrame) -> dict[str, Any]:
    """`flex`: FLEX series (date, root, symbol, expiry, right, strike, open_interest) on the
    settlements of `listed`, listed open interest per (date, symbol, expiry, right, strike)."""
    dates = pd.DatetimeIndex(sorted(listed["date"].unique()))
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
    pairs = _with_listed(pairs, listed)

    drop = (pairs["open_interest"] - pairs["oi_next"]).clip(lower=0)
    rise = (pairs["oi_next"] - pairs["open_interest"]).clip(lower=0)
    listed_rise = pairs["listed_next"] - pairs["listed"]
    twin = pairs["listed"].notna() & pairs["listed_next"].notna()

    twins = flex.merge(listed[["date", *KEY]].drop_duplicates(), on=["date", *KEY], how="inner")
    return {
        "twin_oi_share": _share(twins["open_interest"].sum(), flex["open_interest"].sum()),
        "dropped_contracts": float(drop.sum()),
        "dropped_series_days": int((drop > 0).sum()),
        "dropped_with_twin": _share(drop[twin].sum(), drop.sum()),
        "dropped_matched": _share(
            drop[twin & (listed_rise >= MATCH_SHARE * drop) & (drop > 0)].sum(), drop.sum()
        ),
        "created_contracts": float(rise.sum()),
        "created_matched": _share(
            rise[twin & (listed_rise >= MATCH_SHARE * rise) & (rise > 0)].sum(), rise.sum()
        ),
        "settlements": len(dates),
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
