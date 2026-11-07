"""The strings the paper and README print for the `hidden_gamma` result.

Shares print as percentages to one place; counts as whole numbers. Every macro is
formatted here from the result's values and nowhere else.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.measure.hidden_share_macros import name_list
from hidden_options.publish import formats

RULE_WORDS = {"share_gross": "Gross", "share_netted": "Netted", "share_netted_both": "Both"}
THRESHOLD_WORDS = {"0.05": "Five", "0.10": "Ten", "0.25": "Quarter"}
GROUP_WORDS = {"programme": "Programme", "control": "Control"}
INDEX_WORDS = {"SPX": "SPX", "SPY": "SPY", "QQQ": "QQQ", "NDX": "NDX", "IWM": "IWM", "RUT": "RUT"}
DAY_WORDS = {"<=7": "Week", "8-30": "Month", "31-90": "Quarter", ">90": "Long"}


def hidden_gamma_macros(values: Mapping[str, Any], inputs: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `hidden_gamma` result defines."""
    return {
        **_sample(inputs),
        **_distribution(values["distribution"]),
        **_pooled(values["pooled"]),
        **_index(values["index"]),
        **_where(values["where"]),
        **_signed(values["signed"]),
        **_marks(values["marks"]),
        **_names(values["underlyings"]),
        "GammaPricedShare": formats.percent(values["coverage"]["priced_oi_share"], 1),
        "GammaInteriorShare": formats.percent(values["coverage"]["interior_oi_share"], 1),
    }


def _sample(inputs: Mapping[str, Any]) -> dict[str, str]:
    return {
        "GammaSettlements": formats.count(inputs["settlements"]),
        "GammaUnderlyings": formats.count(inputs["underlyings"]),
        "GammaStart": formats.long_date(pd.Timestamp(inputs["first_date"])),
        "GammaEnd": formats.long_date(pd.Timestamp(inputs["last_date"])),
    }


def _distribution(dist: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rule, word in RULE_WORDS.items():
        figures = dist[rule]
        out[f"GammaMedian{word}"] = formats.percent(figures["median"], 1)
        out[f"GammaLow{word}"] = formats.percent(figures["q25"], 1)
        out[f"GammaHigh{word}"] = formats.percent(figures["q75"], 1)
        for threshold, count in figures["at_least"].items():
            out[f"GammaAtLeast{THRESHOLD_WORDS[threshold]}{word}"] = formats.count(count)
        for group, median in figures["by_group"].items():
            if group in GROUP_WORDS:
                text = "n/a" if median is None else formats.percent(median, 1)
                out[f"Gamma{GROUP_WORDS[group]}{word}"] = text
    counts = dist["share_gross"]["group_counts"]
    for group, word in GROUP_WORDS.items():
        out[f"Gamma{word}Count"] = formats.count(counts[group])
    return out


def _pooled(pooled: Mapping[str, float]) -> dict[str, str]:
    return {f"GammaPooled{word}": formats.percent(pooled[r], 1) for r, word in RULE_WORDS.items()}


def _index(index: Mapping[str, Mapping[str, float]]) -> dict[str, str]:
    return {
        f"Gamma{INDEX_WORDS[symbol]}{word}": formats.percent(shares[rule], 1)
        for symbol, shares in index.items()
        for rule, word in RULE_WORDS.items()
    }


def _where(found: Mapping[str, Any]) -> dict[str, str]:
    out = {
        f"GammaDays{DAY_WORDS[label]}{rule.title()}": formats.percent(found["days"][label][rule])
        for label in DAY_WORDS
        for rule in ("gross", "netted")
    }
    near = found["moneyness"]["0.95-1.05"]
    out["GammaNearMoneyGross"] = formats.percent(near["gross"])
    out["GammaNearMoneyNetted"] = formats.percent(near["netted"])
    return out


def _signed(signed: Mapping[str, Any]) -> dict[str, str]:
    return {
        "GammaFlipShare": formats.percent(signed["flip_share"], 1),
        "GammaSignedRelative": formats.percent(signed["median_relative"], 1),
        "GammaSignedDays": formats.count(signed["underlying_days"]),
    }


def _names(underlyings: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """Underlyings whose median share is at least a tenth, largest first, per netted rule."""
    out = {}
    for rule, word in (("share_netted", "Netted"), ("share_netted_both", "Both")):
        above = [(s, f[rule]) for s, f in underlyings.items() if f[rule] >= 0.10]
        names = [s for s, _ in sorted(above, key=lambda pair: (-pair[1], pair[0]))]
        out[f"GammaTen{word}Names"] = name_list(names)
    return out


def _marks(marks: Mapping[str, Any]) -> dict[str, str]:
    return {
        "GammaMarkShare": formats.percent(marks["oi_share"], 1),
        "GammaMarkRatio": formats.decimal(marks["gamma_ratio"], 2),
        "GammaMarkVolGap": formats.decimal(marks["median_vol_gap"] * 100, 2),
    }


__all__ = ["hidden_gamma_macros"]
