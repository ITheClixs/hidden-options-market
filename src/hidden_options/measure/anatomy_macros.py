"""The `anatomy` result's figures as the paper and README print them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.publish import formats

STEMS = {
    "box": "Box",
    "stock_leg": "Stock",
    "package_leg": "Package",
    "pair": "Pair",
    "other": "Other",
}
WHOLE_BILLIONS_FROM = 10e9


def dollars(value: float) -> str:
    r"""Dollars in billions: whole from ten billion (`\$68bn`), one decimal below."""
    if abs(value) >= WHOLE_BILLIONS_FROM:
        return formats.usd_billions(value)
    return f"\\${formats.decimal(value / 1e9, 1)}bn"


def anatomy_macros(values: Mapping[str, Any]) -> dict[str, str]:
    first, last = values["first"], values["last"]
    parts = last["split"]
    value = sum(part["value"] for part in parts.values())
    held = sum(part["open_interest"] for part in parts.values())
    mean, gamma = values["mean_share"], values["gamma"]["share"]
    macros = {
        "AnatDates": formats.count(values["dates"]),
        "AnatFirstDate": formats.long_date(pd.Timestamp(first["date"])),
        "AnatLastDate": formats.long_date(pd.Timestamp(last["date"])),
        "AnatFinancingValueShare": formats.percent(
            sum(parts[name]["value"] for name in ("box", "stock_leg", "pair")) / value
        ),
        "AnatOptionOIShare": formats.percent(
            sum(parts[name]["open_interest"] for name in ("package_leg", "other")) / held
        ),
        "AnatGammaOptions": formats.percent(gamma["package_leg"] + gamma["other"]),
        "AnatGammaDates": formats.count(values["gamma"]["dates"]),
        "AnatColocated": formats.percent(last["colocated_other_share"]),
    }
    for name, stem in STEMS.items():
        macros[f"Anat{stem}Series"] = formats.count(parts[name]["series"])
        macros[f"Anat{stem}Value"] = dollars(parts[name]["value"])
        macros[f"Anat{stem}ValueShare"] = formats.percent(parts[name]["value"] / value)
        macros[f"Anat{stem}OIShare"] = formats.percent(parts[name]["open_interest"] / held)
        macros[f"Anat{stem}MeanValueShare"] = formats.percent(mean["value"][name])
        macros[f"Anat{stem}MeanOIShare"] = formats.percent(mean["open_interest"][name])
        macros[f"AnatGamma{stem}"] = formats.percent(gamma[name])
    return {**macros, **_boxes(values["boxes"]), **_rest(values)}


def _boxes(boxes: Mapping[str, Any]) -> dict[str, str]:
    first, last = boxes["first"], boxes["last"]
    face = last["face"]
    short = last["by_maturity"]["to_1m"] + last["by_maturity"]["1m_3m"]
    rate = last["mark_rate"]
    return {
        "AnatBoxFace": dollars(face),
        "AnatBoxFaceFirst": dollars(first["face"]),
        "AnatBoxGrowth": formats.decimal(boxes["growth"], 1),
        "AnatBoxNetValue": dollars(last["value"]),
        "AnatBoxNeighbourFace": dollars(last["neighbour_face"]),
        "AnatBoxNeighbourFaceFirst": dollars(first["neighbour_face"]),
        "AnatBoxUnambiguousFace": dollars(last["unambiguous_face"]),
        "AnatBoxUnambiguousFaceFirst": dollars(first["unambiguous_face"]),
        "AnatBoxUnambiguousShare": formats.percent(
            last["unambiguous_face"] / face if face else 0.0
        ),
        "AnatBoxCount": formats.count(last["boxes"]),
        "AnatBoxWideShare": formats.percent(last["wide_share"]),
        "AnatBoxEuropeanShare": formats.percent(last["european_share"]),
        "AnatBoxMarkRate": "n/a" if rate is None else formats.percent(rate, 1),
        "AnatBoxSPXFace": dollars(last["by_underlying"]["SPX"]),
        "AnatBoxSPYFace": dollars(last["by_underlying"]["SPY"]),
        "AnatBoxElseFace": dollars(last["by_underlying"]["other"]),
        "AnatBoxToThreeMonths": formats.percent(short / face if face else 0.0),
        "AnatBoxOverOneYear": dollars(
            last["by_maturity"]["1y_2y"] + last["by_maturity"]["over_2y"]
        ),
        "AnatBoxOverTwoYears": dollars(last["by_maturity"]["over_2y"]),
        "AnatBoxPeakFace": dollars(boxes["peak"]),
        "AnatBoxPeakDate": formats.long_date(pd.Timestamp(boxes["peak_date"])),
        **_peak(boxes.get("peak_largest", [])),
    }


def _peak(largest: list[Mapping[str, Any]]) -> dict[str, str]:
    """The largest boxes on the peak date: underlying, expiry and face of each."""
    macros = {}
    for row, label in zip(largest, ("First", "Second", "Third"), strict=False):
        macros[f"AnatBoxPeak{label}Underlying"] = str(row["root"]).lstrip("0123456789")
        macros[f"AnatBoxPeak{label}Expiry"] = formats.long_date(pd.Timestamp(row["expiry"]))
        macros[f"AnatBoxPeak{label}Face"] = dollars(row["face"])
    return macros


def _rest(values: Mapping[str, Any]) -> dict[str, str]:
    stock, pairs, chance = values["stock_legs"], values["pairs"], values["chance"]
    names = list(stock["last_by_underlying"].items())
    macros = {
        "AnatStockFirst": dollars(stock["first_value"]),
        "AnatStockGrowth": formats.decimal(stock["growth"], 1),
        "AnatStockUnderlyings": formats.count(stock["underlyings"]),
        "AnatPairNotional": dollars(pairs["last_notional"]),
        "AnatPairNotionalFirst": dollars(pairs["first_notional"]),
        "AnatChanceDates": formats.count(chance["dates"]),
        "AnatChanceBox": formats.percent(chance["box_face_share"]),
        "AnatChanceBoxPairsKept": formats.percent(chance["box_face_share_pairs_kept"]),
        "AnatChancePackage": formats.percent(chance["package_oi_share"]),
        "AnatChancePair": formats.percent(chance["pair_oi_share"]),
    }
    for place, label in enumerate(("Top", "Second", "Third")):
        if place < len(names):
            macros[f"AnatStock{label}Name"] = str(names[place][0])
            macros[f"AnatStock{label}Value"] = dollars(names[place][1])
    return macros


__all__ = ["STEMS", "anatomy_macros", "dollars"]
