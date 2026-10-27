"""The strings the paper prints for the `implied_validation` result.

Gaps between FLEX and listed volatilities print in vol points to two places (a gap of
0.0044 is `0.44`); shares print as percentages to one place; rates as whole percentages.
A count that a sentence follows with its noun carries the noun, in the right number. See
the `publish` package for the value convention.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.measure.hidden_share_macros import name_list
from hidden_options.publish import formats

MISSING = "--"


def implied_macros(values: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `implied_validation` result defines, from its values."""
    return {
        **_setting_macros(values),
        **_coverage_macros(values),
        **_validation_macros(values),
        **_style_macros(values),
        **_rate_macros(values),
    }


def _points(value: float | None) -> str:
    """A volatility gap in vol points: 0.0044 -> `0.44`."""
    return MISSING if value is None else formats.decimal(value * 100, 2)


def _share(value: float | None) -> str:
    return MISSING if value is None else formats.percent(value, 1)


def _setting_macros(values: Mapping[str, Any]) -> dict[str, str]:
    settings, window = values["settings"], values["window"]
    low, high = sorted(settings["sensitivity_rates"])
    return {
        "IvRate": formats.percent(settings["rate"]),
        "IvRateLow": formats.percent(low),
        "IvRateHigh": formats.percent(high),
        "IvTreeSteps": formats.count(settings["tree_steps"]),
        "IvSigmaLow": formats.percent(settings["sigma_bounds"][0], 2),
        "IvSigmaHigh": formats.percent(settings["sigma_bounds"][1]),
        "IvDeepMoneyness": formats.percent(settings["deep_moneyness"]),
        "IvWithinPoints": formats.decimal(settings["within"] * 100, 0),
        "IvMinMatched": formats.count(settings["min_matched"]),
        "IvSpotAgreement": formats.percent(settings["spot_agreement"], 1),
        "IvFirstDate": formats.long_date(pd.Timestamp(window["first_date"])),
        "IvLastDate": formats.long_date(pd.Timestamp(window["last_date"])),
        "IvDates": formats.count(window["dates"]),
        "IvRows": formats.count(window["rows"]),
    }


def _coverage_macros(values: Mapping[str, Any]) -> dict[str, str]:
    coverage, spots = values["coverage"], values["spots"]
    status, rows = coverage["by_status"], coverage["rows"]
    below = coverage["below_intrinsic"]
    return {
        "IvOkShare": _share(status["ok"] / rows),
        "IvExpired": formats.count(status["expired"]),
        "IvZeroPrice": formats.count(status["zero_price"]),
        "IvNoSpot": formats.count(status["no_spot"]),
        "IvBelowIntrinsic": formats.count(status["below_intrinsic"]),
        "IvBelowDeepCalls": _share(below["deep_calls"] / below["rows"] if below["rows"] else None),
        "IvBelowTopNames": name_list([row["symbol"] for row in below["top"]]),
        "IvBelowTopShare": _share(below["top_share"]),
        "IvNoConvergence": formats.count(status["no_convergence"]),
        "IvAtFloor": formats.count(coverage["at_floor"]),
        "IvSpotReadings": formats.count(spots["agreement"]["readings"]),
        "IvSpotSetAside": formats.count(spots["agreement"]["set_aside"]),
    }


def _validation_macros(values: Mapping[str, Any]) -> dict[str, str]:
    validation, domain = values["validation"], values["domain"]
    overall, short = validation["overall"], validation["by_dte"]["<=7"]
    return {
        "IvMatched": formats.count(validation["matched"]),
        "IvMatchedSeries": formats.count(validation["matched_series"]),
        "IvCompared": formats.count(validation["compared"]),
        "IvIndexMatched": formats.count(validation["by_kind"]["index"]["n"]),
        "IvMedianGap": _points(overall["median_abs"]),
        "IvWithinTwo": _share(overall["within"]),
        "IvMedianBias": _points(overall["median_diff"]),
        "IvMedianBiasCalls": _points(validation["by_right"]["C"]["median_diff"]),
        "IvMedianBiasPuts": _points(validation["by_right"]["P"]["median_diff"]),
        "IvShortMedianGap": _points(short["median_abs"]),
        "IvShortWithinTwo": _share(short["within"]),
        "IvDomainCells": formats.count(domain["cells"]),
        "IvDomainOfCells": formats.count(domain["of_cells"]),
        "IvDomainFail": formats.count(domain["of_cells"] - domain["cells"]),
        "IvDomainFailShort": formats.count(domain["failing_short"]),
        "IvDomainCompared": _share(domain["compared_share"]),
        "IvOkOpenInterest": _share(domain["ok_open_interest"]),
        "IvDomainOpenInterest": _share(domain["usable_open_interest"]),
        "IvDomainOpenInterestEquity": _share(domain["usable_open_interest_by_kind"]["equity"]),
        "IvDomainOpenInterestIndex": _share(domain["usable_open_interest_by_kind"]["index"]),
    }


def _style_macros(values: Mapping[str, Any]) -> dict[str, str]:
    styles, groups = values["styles"], values["validation"]["by_group"]
    agreement = styles["prefix_agreement"]
    return {
        "IvUnreadShare": _share(styles["panel"]["unread_share"]),
        "IvFallbackRows": formats.counted(
            styles["panel"]["by_group"]["fallback"], "series-day", "series-days"
        ),
        "IvPrefixMarked": formats.count(agreement["checked"]),
        "IvPrefixContradict": formats.count(agreement["contradict"]),
        "IvPrefixOther": formats.counted(agreement["other"], "series-day"),
        "IvStrictGap": _points(groups["strict"]["median_abs"]),
        "IvClippedGap": _points(groups["clipped"]["median_abs"]),
        "IvPrefixGap": _points(groups["prefix"]["median_abs"]),
    }


def _rate_macros(values: Mapping[str, Any]) -> dict[str, str]:
    rates = [values["rates"][key] for key in sorted(values["rates"])]
    low, high = rates[0], rates[-1]
    return {
        "IvMedianGapLow": _points(low["overall"]["median_abs"]),
        "IvMedianGapHigh": _points(high["overall"]["median_abs"]),
        "IvWithinTwoLow": _share(low["overall"]["within"]),
        "IvWithinTwoHigh": _share(high["overall"]["within"]),
        "IvDomainCellsLow": formats.count(low["domain_cells"]),
        "IvDomainCellsHigh": formats.count(high["domain_cells"]),
    }
