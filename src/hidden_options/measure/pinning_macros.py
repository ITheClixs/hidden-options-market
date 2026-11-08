"""The strings the paper and README print for the `pinning` result.

D and the closeness statistics are in units of the event's daily sigma, printed to three
places. Banded statistics are differences in the frequency of closing within the band,
printed as percentage points.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hidden_options.predict.macros import p_value, t_stat
from hidden_options.publish import formats

DESCRIPTIVE_STEMS = {
    "band_0.25": "BandQuarter",
    "band_0.5": "BandHalf",
    "expiry_only": "ExpiryOnly",
    "pseudo_only": "PseudoOnly",
    "friday": "Friday",
    "calls": "Calls",
    "puts": "Puts",
}
BANDED = {"band_0.25", "band_0.5"}


def sigma(value: float) -> str:
    return formats.decimal(value, 3)


def points(value: float) -> str:
    """A difference in frequency, in percentage points to one place."""
    return formats.decimal(value * 100, 1)


def pinning_macros(values: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `pinning` result defines."""
    h1, h2, sample = values["h1"], values["h2"], values["sample"]
    out = {
        "PinMean": sigma(h1["mean"]),
        "PinSE": sigma(h1["std_error"]),
        "PinT": t_stat(h1["t_stat"]),
        "PinP": p_value(h1["p_value"]),
        "PinHolm": p_value(h1["holm_p"]),
        "PinFlipP": p_value(h1["sign_flip_p"]),
        "PinMDE": sigma(h1["mde80"]),
        "PinMDEHolm": sigma(h1["mde80_holm"]),
        "PinNetMean": sigma(values["h1_net"]["mean"]),
        "PinNetT": t_stat(values["h1_net"]["t_stat"]),
        "PinNetFlipP": p_value(values["h1_net"]["sign_flip_p"]),
        "PinNetMDE": sigma(values["h1_net"]["mde80"]),
        "PinPlaceboMatched": sigma(values["h1_net"]["placebo_mean"]),
        "PinSizeDiff": sigma(h2["difference"]),
        "PinSizeTop": sigma(h2["top"]),
        "PinSizeBottom": sigma(h2["bottom"]),
        "PinSizeT": t_stat(h2["t_stat"]),
        "PinSizeHolm": p_value(h2["holm_p"]),
        "PinEvents": formats.count(sample["events"]),
        "PinDates": formats.count(sample["expiry_dates"]),
        "PinUnderlyings": formats.count(sample["underlyings"]),
        "PinContracts": formats.count(round(sample["median_contracts"])),
        "PinMedianSize": formats.percent(sample["median_size"], 1),
        "PinNearExpiry": formats.percent(sample["near_expiry"], 1),
        "PinNearAfter": formats.percent(sample["near_after"], 1),
        "PinExcluded": formats.count(len(sample["excluded_names"])),
        "PinFridayEvents": formats.count(sample["friday_events"]),
        "PinSplitDropped": formats.count(sample["split_dropped"]),
        "PinInListed": formats.count(sample["in_listed_sources"]),
    }
    if values.get("control"):
        out.update(control_macros(values["control"]))
    if values.get("empirical_null"):
        out.update(null_macros(values["empirical_null"]))
    simulation = values["simulation"]
    out["PinSimSize"] = formats.percent(simulation["size"], 1)
    out["PinSimWorlds"] = formats.count(simulation["size_worlds"])
    out["PinSimPowerWorlds"] = formats.count(simulation["power_worlds"])
    for key, word in (("0.05", "Twenty"), ("0.10", "Ten"), ("0.15", "Seven")):
        row = simulation["power"][key]
        out[f"PinSimPower{word}"] = formats.percent(row["power_simulated"])
        out[f"PinPower{word}"] = formats.percent(row["power_observed"])
        out[f"PinEffect{word}"] = sigma(row["effect"])
    for key, stem in DESCRIPTIVE_STEMS.items():
        row = values["descriptive"][key]
        scale = points if key in BANDED else sigma
        empty = row["mean"] is None
        out[f"Pin{stem}Mean"] = "n/a" if empty else scale(row["mean"])
        out[f"Pin{stem}T"] = "n/a" if empty else t_stat(row["t_stat"])
    return out


def control_macros(control: Mapping[str, Any]) -> dict[str, str]:
    """The positive control at listed strikes (docs/log/2026-11-08-pinning-control-spec.md)."""
    monthly, quarter, weekly = control["monthly"], control["band_0.25"], control["weekly"]
    return {
        "PinCtlMean": sigma(monthly["mean"]),
        "PinCtlT": t_stat(monthly["t_stat"]),
        "PinCtlP": p_value(monthly["p_value"]),
        "PinCtlFlipP": p_value(monthly["sign_flip_p"]),
        "PinCtlMDE": sigma(monthly["mde80"]),
        "PinCtlEvents": formats.count(monthly["n_obs"]),
        "PinCtlDates": formats.count(monthly["clusters"]),
        "PinCtlUnderlyings": formats.count(monthly["underlyings"]),
        "PinCtlNearExpiry": formats.percent(monthly["near_expiry"], 1),
        "PinCtlNearAfter": formats.percent(monthly["near_after"], 1),
        "PinCtlBandQuarterMean": points(quarter["mean"]),
        "PinCtlBandQuarterT": t_stat(quarter["t_stat"]),
        "PinCtlBandQuarterMDE": points(quarter["mde80"]),
        "PinCtlWeeklyMean": sigma(weekly["mean"]),
        "PinCtlWeeklyT": t_stat(weekly["t_stat"]),
        "PinCtlWeeklyEvents": formats.count(weekly["n_obs"]),
        "PinCtlPlaceboMean": sigma(control["placebo"]["mean"]),
        "PinCtlPlaceboT": t_stat(control["placebo"]["t_stat"]),
        "PinCtlPlaceboDates": formats.count(control["placebo"]["clusters"]),
        "PinCtlNetMean": sigma(control["monthly_net"]["mean"]),
        "PinCtlNetT": t_stat(control["monthly_net"]["t_stat"]),
        "PinCtlNetFlipP": p_value(control["monthly_net"]["sign_flip_p"]),
        "PinCtlPlaceboMatched": sigma(control["monthly_net"]["placebo_mean"]),
        "PinCtlWeeklyNetMean": sigma(control["weekly_net"]["mean"]),
        "PinCtlWeeklyNetT": t_stat(control["weekly_net"]["t_stat"]),
    }


def null_macros(null: Mapping[str, Any]) -> dict[str, str]:
    """Size and power on real returns (docs/log/2026-11-08-pinning-empirical-null-spec.md)."""
    out = {
        "PinNullOffsets": formats.count(len(null["offsets"])),
        "PinNullEvents": formats.count(round(null["median_events"])),
        "PinNullCentre": sigma(null["centre"]),
        "PinNullSpread": sigma(null["spread"]),
        "PinNullSize": formats.percent(null["size"]),
        "PinNullShare": formats.percent(null["observed_share"]),
    }
    for key, word in (("0.05", "Twenty"), ("0.10", "Ten"), ("0.15", "Seven")):
        out[f"PinNullPower{word}"] = formats.percent(null["power"][key])
    return out


__all__ = ["control_macros", "null_macros", "pinning_macros"]
