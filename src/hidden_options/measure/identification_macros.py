"""The strings the paper and README print for the `identification` result.

Precision, recall and F1 print to three places, as scores usually are; shares print as
percentages to one place. A count that a sentence follows with its noun carries the noun,
in the right number, so the sentence reads right for any count. See the `publish`
package for the value convention.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.measure.hidden_share_macros import name_list
from hidden_options.publish import formats

SCORE_DIGITS = 3


def identification_macros(values: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `identification` result defines, from its values."""
    return {**_census_macros(values), **_rule_macros(values), **_grid_macros(values)}


def _score(value: float) -> str:
    return formats.decimal(value, SCORE_DIGITS)


def _share(value: float) -> str:
    return formats.percent(value, 1)


def _census_macros(values: Mapping[str, Any]) -> dict[str, str]:
    census = values["census"]
    return {
        "CensusRows": formats.count(census["rows"]),
        "CensusAdjustedSeries": formats.count(census["adjusted"]),
        "CensusEmptySeries": formats.count(census["empty"]),
        "CensusSeries": formats.count(census["series"]),
        "CensusFlexSeries": formats.count(census["flex"]),
        "CensusListedSeries": formats.count(census["listed"]),
    }


def _rule_macros(values: Mapping[str, Any]) -> dict[str, str]:
    rule, weighted, empty = values["rule"], values["rule_open_interest"], values["rule_with_empty"]
    flagged = values["listed_flagged"]
    return {
        "RuleFlexFound": formats.count(rule["tp"]),
        "RuleListedFlagged": formats.count(rule["fp"]),
        "RuleFlexMissed": formats.count(rule["fn"]),
        "RuleListedPassed": formats.count(rule["tn"]),
        "RulePrecision": _score(rule["precision"]),
        "RuleRecall": _score(rule["recall"]),
        "RuleFOne": _score(rule["f1"]),
        "RuleFalseShare": _share(rule["fp"] / (rule["tp"] + rule["fp"])),
        "FlexOnGridShare": _share(rule["fn"] / (rule["tp"] + rule["fn"])),
        "FlexOnGridOpenInterest": _share(weighted["fn"] / (weighted["tp"] + weighted["fn"])),
        "RulePrecisionOpenInterest": _score(weighted["precision"]),
        "RulePrecisionWithEmpty": _score(empty["precision"]),
        "RuleRecallWithEmpty": _score(empty["recall"]),
        "RuleListedFlaggedUnderlyings": formats.counted(flagged["underlyings"], "underlying"),
        "RuleListedFlaggedTopNames": name_list([row["symbol"] for row in flagged["top"]]),
        "RuleListedFlaggedTopShare": formats.percent(flagged["top_share"]),
    }


def _grid_macros(values: Mapping[str, Any]) -> dict[str, str]:
    flex, listed = values["grid"]["flex"], values["grid"]["listed"]
    line = values["largest_whole_dollar"]
    return {
        "FlexDollarShare": _share(flex["series"]["dollar"]),
        "FlexDollarOpenInterest": _share(flex["open_interest"]["dollar"]),
        "ListedDollarShare": _share(listed["series"]["dollar"]),
        "ListedOffGridShare": _share(listed["series"]["off_grid"]),
        "RuleExampleProduct": line["product_symbol"],
        "RuleExampleStrike": f"\\${line['strike']:,.2f}",
        "RuleExampleExpiry": formats.long_date(pd.Timestamp(line["expiry"])),
        "RuleExampleOpenInterest": formats.counted(line["open_interest"], "contract"),
    }
