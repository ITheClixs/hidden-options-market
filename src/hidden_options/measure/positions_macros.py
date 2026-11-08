"""The strings the paper prints for the `positions` result.

Shares print as percentages to one place, ratios as plain numbers, dollars with their
escaped sign. A count that a sentence follows with its noun carries the noun, in the right
number. A worked case missing from the panel prints as MISSING. See the `publish` package
for the value convention.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.measure.intervals import wilson
from hidden_options.publish import formats

MISSING = "--"
_MILLION, _BILLION, _TRILLION = 1e6, 1e9, 1e12


def positions_macros(values: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `positions` result defines, from its values."""
    return {
        **_setting_macros(values),
        **_score_macros(values["validation"]),
        **_holdings_macros(values["validation"]),
        **_market_macros(values["market"]),
        **_ratio_macros(values["ratios"]),
        **_butterfly_macros(values["cases"]["butterfly"]),
        **_collar_macros(values["cases"]["collar"]),
    }


def _share(value: float | None) -> str:
    return MISSING if value is None else formats.percent(value, 1)


def _times(value: float | None, digits: int = 1) -> str:
    return MISSING if value is None else formats.decimal(value, digits)


def usd(value: float | None) -> str:
    r"""Dollars at a scale that reads: `\$7.0m`, `\$1.30bn`, `\$63.8bn`, `\$4.26tn`."""
    if value is None:
        return MISSING
    if value >= _TRILLION:
        return f"\\${value / _TRILLION:.2f}tn"
    if value >= 10 * _BILLION:
        return f"\\${value / _BILLION:.1f}bn"
    if value >= _BILLION:
        return f"\\${value / _BILLION:.2f}bn"
    return f"\\${value / _MILLION:.1f}m"


def _day(value: str | None) -> str:
    return MISSING if value is None else formats.long_date(pd.Timestamp(value))


def _setting_macros(values: Mapping[str, Any]) -> dict[str, str]:
    settings, window = values["settings"], values["window"]
    grouping = settings["grouping"]
    low, high = sorted(settings["sensitivity_rates"])
    return {
        "PosTolerance": formats.percent(grouping["count_tolerance"]),
        "PosMinContracts": formats.count(grouping["min_contracts"]),
        "PosStaleBdays": formats.count(settings["max_staleness_bdays"]),
        "PosRate": formats.percent(settings["rate"]),
        "PosRateLow": formats.percent(low),
        "PosRateHigh": formats.percent(high),
        "PosDates": formats.count(window["dates"]),
    }


def _score_macros(validation: Mapping[str, Any]) -> dict[str, str]:
    score, same_day, by_date = validation["score"], validation["same_day"], validation["by_date"]
    synthetic = validation["by_type"].get("synthetic", {})
    return {
        "PosPrecision": _share(score["precision"]),
        "PosRecall": _share(score["recall"]),
        "PosGrouped": _share(score["recall_grouped"]),
        "PosTypeAgreement": _share(score["type_agreement"]),
        "PosPrecisionExact": _share(score["precision_exact"]),
        "PosTruth": formats.count(score["n_truth_structures"]),
        "PosTouching": formats.count(score["n_detected_touching"]),
        "PosFunds": formats.counted(score["n_funds"], "fund"),
        "PosUnderlyings": formats.counted(score["n_underlyings"], "underlying"),
        "PosStructureDates": formats.count(score["n_structure_dates"]),
        "PosSameDayPrecision": _share(same_day["precision"]),
        "PosSameDayRecall": _share(same_day["recall"]),
        "PosScoreDates": formats.count(by_date["dates"]),
        "PosMedianPrecision": _share(by_date["median_precision"]),
        "PosMedianRecall": _share(by_date["median_recall"]),
        "PosLowRecall": _share(by_date["low_recall"]),
        "PosHighRecall": _share(by_date["high_recall"]),
        "PosSyntheticTruth": formats.count(synthetic.get("truth", 0)),
        "PosSyntheticPrecision": _share(synthetic.get("precision")),
        "PosSyntheticTouching": formats.count(synthetic.get("touching", 0)),
        **_intervals(score),
    }


def _intervals(score: Mapping[str, Any]) -> dict[str, str]:
    """Wilson 95% intervals, one trial per detected structure (precision) or per disclosed
    structure (recall). They ignore clustering by fund, so they understate the uncertainty."""
    touching, truth = int(score["n_detected_touching"]), int(score["n_truth_structures"])
    out: dict[str, str] = {}
    for stem, share, trials in (
        ("Precision", score["precision"], touching),
        ("PrecisionExact", score["precision_exact"], touching),
        ("Recall", score["recall"], truth),
    ):
        low, high = wilson(share * trials, trials)
        out[f"Pos{stem}Low"], out[f"Pos{stem}High"] = _share(low), _share(high)
    return out


def _holdings_macros(validation: Mapping[str, Any]) -> dict[str, str]:
    truth, floor = validation["truth"], validation["floor"]
    previous, same = floor["as_of_previous"], floor["as_of_same_day"]
    globalx, signs = validation["globalx"], validation["signs"]
    return {
        "PosFiles": formats.count(truth["files"]),
        "PosStaleFiles": formats.counted(truth["stale_files"], "file"),
        "PosFirstAsOf": _day(truth["first_as_of"]),
        "PosLastAsOf": _day(truth["last_as_of"]),
        "PosHoldingFunds": formats.counted(truth["funds_with_flex"], "fund"),
        "PosFloorLegs": formats.count(previous["legs"]),
        "PosFloorPrevious": _share(_over(previous["covered"], previous["found"])),
        "PosFloorSame": _share(_over(same["covered"], same["found"])),
        "PosHolderShare": _share(validation["holder_share"]),
        "PosSignStructures": formats.count(signs["structures"]),
        "PosRuleOverSigned": _times(signs["rule_over_signed"], 2),
        "PosGlobalxFunds": formats.counted(globalx["funds"], "fund"),
        "PosGlobalxLegs": formats.count(globalx["legs"]),
        "PosGlobalxOnReport": formats.count(globalx["legs_on_flex_report"]),
        "PosGlobalxMulti": formats.count(globalx["multi_leg_holdings"]),
        **_fund_interval_macros(validation.get("fund_intervals")),
    }


def _fund_interval_macros(intervals: Mapping[str, Any] | None) -> dict[str, str]:
    if not intervals:
        return {}
    return {
        "PosRecallFundLow": _share(intervals["recall_low"]),
        "PosRecallFundHigh": _share(intervals["recall_high"]),
        "PosPrecisionFundLow": _share(intervals["precision_low"]),
        "PosPrecisionFundHigh": _share(intervals["precision_high"]),
        "PosBootFunds": formats.count(intervals["funds"]),
    }


def _over(part: float, whole: float) -> float | None:
    return part / whole if whole else None


def _market_macros(market: Mapping[str, Any]) -> dict[str, str]:
    types, tolerance = market["types_mean"], market["tolerance_last"]
    return {
        "PosStructuredMean": _share(market["structured_mean"]),
        "PosStructuredLast": _share(market["structured_last"]),
        "PosStructuredMin": _share(market["structured_min"]),
        "PosStructuredMax": _share(market["structured_max"]),
        "PosChance": _share(market["chance_mean"]),
        "PosChanceDates": formats.count(market["chance_dates"]),
        "PosGroupedLast": formats.count(market["grouped_series_last"]),
        "PosSeriesLast": formats.count(market["series_last"]),
        "PosStructuresLast": formats.count(market["structures_last"]),
        "PosShareSynthetic": _share(types["synthetic"]),
        "PosShareFour": _share(types["collar_buffer"]),
        "PosShareVertical": _share(types["vertical_spread"]),
        "PosToleranceExact": _share(tolerance["0.00"]),
        "PosToleranceWide": _share(tolerance["0.10"]),
    }


def _ratio_macros(ratios: Mapping[str, Any]) -> dict[str, str]:
    rule, gross, market = ratios["rule"], ratios["gross"], ratios["market"]
    quantiles, coverage = rule["quantiles"], ratios["coverage"]
    rates = [ratios["rates"][key] for key in sorted(ratios["rates"])]
    gross_rates = [ratios["rates_gross"][key] for key in sorted(ratios["rates_gross"])]
    across, legs, floor = ratios["structured_by_underlying"], ratios["legs"], ratios["floor_delta"]
    return {
        "PosRatioUnderlyings": formats.count(ratios["underlyings"]),
        "PosRatioMedian": _times(quantiles["0.50"], 2),
        "PosRatioTen": _times(quantiles["0.10"]),
        "PosRatioQuarter": _times(quantiles["0.25"]),
        "PosRatioThreeQuarters": _times(quantiles["0.75"]),
        "PosRatioNinety": _times(quantiles["0.90"]),
        "PosAboveOne": _share(rule["above_one"]),
        "PosBelowOne": _share(rule["below_one"]),
        "PosAboveTen": _share(rule["above_ten"]),
        "PosRatioRateLow": _times(rates[0]["quantiles"]["0.50"], 2),
        "PosRatioRateHigh": _times(rates[-1]["quantiles"]["0.50"], 2),
        "PosGrossRateLow": _times(gross_rates[0]["quantiles"]["0.50"], 2),
        "PosGrossRateHigh": _times(gross_rates[-1]["quantiles"]["0.50"], 2),
        "PosGrossMedian": _times(gross["quantiles"]["0.50"], 2),
        "PosGrossQuarter": _times(gross["quantiles"]["0.25"]),
        "PosGrossThreeQuarters": _times(gross["quantiles"]["0.75"]),
        "PosGrossTen": _times(gross["quantiles"]["0.10"]),
        "PosGrossNinety": _times(gross["quantiles"]["0.90"]),
        "PosGrossAboveOne": _share(gross["above_one"]),
        "PosGrossAboveTen": _share(gross["above_ten"]),
        "PosGrossBelowOne": _share(gross["below_one"]),
        "PosFloorGrossMedian": _times(ratios["floor_delta_gross"]["quantiles"]["0.50"], 2),
        "PosFloorGrossBelowOne": _share(ratios["floor_delta_gross"]["below_one"]),
        "PosMarketRatio": _times(market["strike_over_delta"]),
        "PosMarketGross": _times(market["strike_over_gross"]),
        "PosMarketMark": _times(market["strike_over_mark"]),
        "PosNettingShare": _share(market["netting_share_of_gap"]),
        "PosStrikeLast": usd(market["last_strike_notional"]),
        "PosCovered": _share(coverage["covered_share"]),
        "PosOutside": _share(coverage["outside_share"]),
        "PosPriced": _share(coverage["priced_share"]),
        "PosNoSpot": _share(coverage["no_spot_share"]),
        "PosMedianStructured": _share(across["median"]),
        "PosHalfStructured": _share(across["at_least_half"]),
        "PosUnderstated": _share(legs["understated_share"]),
        "PosBelowFloor": _share(legs["below_floor_share"]),
        "PosFloorMedian": _times(floor["quantiles"].get("0.50"), 2),
        "PosFloorBelowOne": _share(floor["below_one"]),
    }


def _butterfly_macros(case: Mapping[str, Any] | None) -> dict[str, str]:
    found = case or {}
    return {
        "PosButterflyDate": _day(found.get("report_date")),
        "PosButterflyName": found.get("underlying", MISSING),
        "PosButterflyLines": _whole(found.get("lines")),
        "PosButterflyExpiries": _whole(len(found["expiries"]) if case else None),
        "PosButterflyNotional": usd(found.get("strike_notional")),
        "PosButterflyMax": usd(found.get("max_value")),
        "PosButterflyTimes": _whole(found.get("overstatement")),
        "PosButterflyGrouped": _whole(found.get("wings_grouped")),
        "PosButterflyWing": _whole(_wing(found.get("legs"))),
    }


def _collar_macros(case: Mapping[str, Any] | None) -> dict[str, str]:
    found = case or {}
    deep = found.get("deep_call", {})
    return {
        "PosCollarDate": _day(found.get("report_date")),
        "PosCollarExpiry": _day(found.get("expiry")),
        "PosCollarName": found.get("underlying", MISSING),
        "PosCollarSize": _whole(found.get("size")),
        "PosCollarSpot": _dollars(found.get("spot"), 0),
        "PosCollarNotional": usd(found.get("strike_notional")),
        "PosCollarMax": usd(found.get("max_value")),
        "PosCollarExposure": usd(found.get("spot_exposure")),
        "PosCollarTimes": _times(found.get("overstatement")),
        "PosDeepStrike": _dollars(deep.get("strike"), 2),
        "PosDeepMark": _dollars(deep.get("mark"), 2),
        "PosDeepNotional": usd(deep.get("strike_notional")),
        "PosDeepExposure": usd(deep.get("exposure")),
        "PosDeepTimes": _whole(deep.get("ratio")),
        "PosDeepMoneyness": _moneyness(deep.get("strike"), found.get("spot")),
    }


def _wing(legs: list[Mapping[str, Any]] | None) -> float | None:
    return None if not legs else max(leg["contracts"] for leg in legs)


def _moneyness(strike: float | None, spot: float | None) -> str:
    return MISSING if strike is None or not spot else formats.percent(strike / spot, 1)


def _whole(value: float | None) -> str:
    return MISSING if value is None else formats.count(value)


def _dollars(value: float | None, digits: int) -> str:
    return MISSING if value is None else f"\\${value:,.{digits}f}"
