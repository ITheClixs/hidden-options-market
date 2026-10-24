"""The strings the paper and README print for the `hidden_share` result.

Shares print as percentages: to one place where a value is quoted on its own, to whole
points in lists of names. Each macro is formatted here, from the result's raw values,
and nowhere else; see the `publish` package for the value convention. A list of names
that comes out empty prints as `none`, so a sentence built around it still reads.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from hidden_options.publish import formats

THRESHOLD_WORDS = {"10": "Ten", "25": "Quarter", "50": "Half"}
RIGHT_WORDS = {"C": "call", "P": "put"}


def hidden_share_macros(values: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `hidden_share` result defines, from its values."""
    return {
        **_census_macros(values),
        **_daily_macros(values),
        **_check_macros(values),
        **_value_macros(values),
    }


def name_list(names: Sequence[str]) -> str:
    """`A`, `A and B`, `A, B and C`; `none` for no names."""
    if not names:
        return "none"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def usd_billions(value: float) -> str:
    r"""Dollars in billions to one place: `\$14.7bn`."""
    return f"\\${value / 1e9:,.1f}bn"


def _share(value: float) -> str:
    return formats.percent(value, 1)


def _census_macros(values: Mapping[str, Any]) -> dict[str, str]:
    census = values["census"]
    quantiles, at_least = census["quantiles"], census["at_least"]
    macros = {
        "HiddenCensusDate": formats.long_date(pd.Timestamp(census["date"])),
        "HiddenCensusSymbols": formats.count(census["symbols"]),
        "HiddenCensusUnderlyings": formats.count(census["underlyings"]),
        "HiddenCensusOnlyAdjusted": formats.count(len(census["only_adjusted"])),
        "HiddenCensusWithFlex": formats.count(census["with_flex"]),
        "HiddenCensusWithoutFlex": formats.count(census["underlyings"] - census["with_flex"]),
        "HiddenCensusMedian": _share(quantiles["50"]),
        "HiddenCensusUpperQuartile": _share(quantiles["75"]),
        "HiddenCensusNinetieth": _share(quantiles["90"]),
        "HiddenCensusMaxName": census["max"]["symbol"],
        "HiddenCensusMax": formats.percent(census["max"]["share"]),
        "HiddenCensusHalfNames": name_list([row["symbol"] for row in census["half_or_more"]]),
        "HiddenCensusAggregate": _share(census["aggregate_share"]),
        "HiddenCensusCoverage": _share(census["report_coverage"]),
        "HiddenCensusSupport": formats.count(census["support"]),
        "HiddenCensusCompared": formats.count(census["compared"]),
    }
    for key, word in THRESHOLD_WORDS.items():
        macros[f"HiddenCensus{word}"] = formats.count(at_least[key])
    for row in values["census_indices"]:
        macros[f"HiddenCensus{row['symbol'].title()}"] = formats.percent(row["share"])
    return macros


def _daily_macros(values: Mapping[str, Any]) -> dict[str, str]:
    daily = values["daily"]
    names, stable = daily["names"], daily["stable"]
    incomplete = daily["incomplete"]
    macros = {
        "HiddenDailyDates": formats.count(daily["dates"]),
        "HiddenDailyFirst": formats.long_date(pd.Timestamp(daily["first_date"])),
        "HiddenDailyLast": formats.long_date(pd.Timestamp(daily["last_date"])),
        "HiddenDailyCaptures": formats.count(daily["captures"]),
        "HiddenDailyDuplicates": formats.count(daily["duplicate_captures"]),
        "HiddenDailySupportLow": formats.count(daily["min_support"]),
        "HiddenDailyCompared": formats.count(daily["compared"]),
        "HiddenDailyUniverse": formats.count(daily["universe"]),
        "HiddenDailyProgramme": formats.count(daily["universe_by_group"]["programme"]),
        "HiddenDailyControl": formats.count(daily["universe_by_group"]["control"]),
        "HiddenDailySearch": formats.count(daily["search_symbols"]),
        "HiddenDailyComplete": formats.count(daily["complete"]),
        "HiddenDailyIncompleteNames": name_list(sorted(incomplete)),
        "HiddenDailyIncompleteDates": formats.count(min(incomplete.values(), default=0)),
        "HiddenDailyMedian": _share(daily["median_of_medians"]),
        "HiddenDailyAggregateLow": _share(daily["aggregate"]["min"]),
        "HiddenDailyAggregateHigh": _share(daily["aggregate"]["max"]),
        "HiddenCompleteProgramme": formats.count(daily["complete_by_group"]["programme"]),
        "HiddenCompleteControl": formats.count(daily["complete_by_group"]["control"]),
        "HiddenQuarterRanges": name_list(
            [
                f"{name} from {_share(names[name]['min'])} to {_share(names[name]['max'])}"
                for name in stable["25"]["symbols"]
            ]
        ),
    }
    for key, word in THRESHOLD_WORDS.items():
        macros[f"HiddenStable{word}"] = formats.count(stable[key]["count"])
        macros[f"HiddenStable{word}Names"] = name_list(stable[key]["symbols"])
        for group in ("programme", "control"):
            macros[f"HiddenStable{word}{group.title()}"] = formats.count(
                stable[key]["by_group"][group]
            )
    for index in daily["not_in_search"]:
        if index in names:
            stem = f"Hidden{index.title()}"
            macros[f"{stem}Low"] = _share(names[index]["min"])
            macros[f"{stem}High"] = _share(names[index]["max"])
    return macros


def _check_macros(values: Mapping[str, Any]) -> dict[str, str]:
    parts = values["reconciliation"].values()
    symbol_dates = sum(part["symbol_dates"] for part in parts)
    agreeing = sum(part["agreeing"] for part in parts)
    adjusted, expiry = values["adjusted"], values["expiry_check"]
    return {
        "HiddenReconSymbolDates": formats.count(symbol_dates),
        "HiddenReconAgreeing": formats.count(agreeing),
        "HiddenReconMax": formats.percent(max(part["max_rel_diff"] for part in parts), 2),
        "HiddenReconCensus": formats.count(values["reconciliation"]["census"]["symbol_dates"]),
        "HiddenReconDaily": formats.count(values["reconciliation"]["daily"]["symbol_dates"]),
        "HiddenAdjustedCensus": formats.count(adjusted["census"]),
        "HiddenAdjustedCensusFlex": formats.count(adjusted["census_with_flex"]),
        "HiddenAdjustedCensusNames": name_list([row["symbol"] for row in adjusted["census_flex"]]),
        "HiddenAdjustedCensusShare": _share(adjusted["census_flex_share"]),
        "HiddenAdjustedDailyNames": name_list(sorted(adjusted["daily_with_flex"])),
        "HiddenExpiryMax": formats.decimal(expiry["max_abs_diff"] * 100),
        "HiddenExpiryMoved": formats.count(expiry["moved"]),
        "HiddenExpiryNameDates": formats.count(expiry["name_dates"]),
    }


def _value_macros(values: Mapping[str, Any]) -> dict[str, str]:
    value = values["value"]
    line = value["largest_line"]
    leaders = value["leaders"][:3]
    return {
        "HiddenValueDates": formats.count(value["dates"]),
        "HiddenValueCompleteDates": formats.count(value["complete_dates"]),
        "HiddenValueNames": formats.count(value["names"]),
        "HiddenValueTheo": _share(value["theo_share"]),
        "HiddenValueMedian": _share(value["aggregate"]["median"]),
        "HiddenValueLow": _share(value["aggregate"]["min"]),
        "HiddenValueHigh": _share(value["aggregate"]["max"]),
        "HiddenValueOpenInterestLow": _share(value["aggregate_oi"]["min"]),
        "HiddenValueOpenInterestHigh": _share(value["aggregate_oi"]["max"]),
        "HiddenValueMedianName": _share(value["median_name"]),
        "HiddenValueMedianNameOpenInterest": _share(value["median_name_oi"]),
        "HiddenValueAbove": formats.count(value["above_oi_share"]),
        "HiddenValueLastDate": formats.long_date(pd.Timestamp(value["last_date"])),
        "HiddenValueLeaders": name_list(
            [f"{row['symbol']} ({formats.percent(row['value_share'])})" for row in leaders]
        ),
        "HiddenValueLeadersOpenInterest": name_list(
            [f"{row['symbol']} ({formats.percent(row['oi_share'])})" for row in leaders]
        ),
        "HiddenLineSymbol": line["symbol"],
        "HiddenLineRight": RIGHT_WORDS[line["right"]],
        "HiddenLineOpposite": RIGHT_WORDS["P" if line["right"] == "C" else "C"],
        "HiddenLineStrike": f"{line['strike']:,.2f}",
        "HiddenLineExpiry": formats.long_date(pd.Timestamp(line["expiry"])),
        "HiddenLineOpenInterest": formats.count(line["open_interest"]),
        "HiddenLineOppositeOpenInterest": formats.count(line["opposite_open_interest"]),
        "HiddenLineValue": usd_billions(line["value"]),
        "HiddenLineListed": usd_billions(line["listed_value"]),
    }
