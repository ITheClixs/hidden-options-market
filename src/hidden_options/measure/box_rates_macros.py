"""The `box_rates` result's figures as the paper and README print them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.measure.anatomy_macros import dollars
from hidden_options.publish import formats

MATURITY_STEMS = {
    "to_1m": "ToOneMonth",
    "1m_3m": "OneToThree",
    "3m_12m": "ThreeToTwelve",
    "1y_2y": "OneToTwoYears",
    "over_2y": "OverTwoYears",
}
GROUP_STEMS = {"SPX": "SPX", "SPY": "SPY", "other": "Else"}
MISSING = "n/a"


def basis_points(rate: float | None, digits: int = 0) -> str:
    """A rate difference in basis points: 0.00123 -> `12`."""
    return MISSING if rate is None else formats.decimal(rate * 1e4, digits)


def box_rates_macros(values: Mapping[str, Any]) -> dict[str, str]:
    sample, headline = values["sample"], values["headline"]
    marks, dropped = values["marks"], values["sample"]["dropped"]
    macros = {
        "BoxRFiles": formats.count(sample["files"]),
        "BoxRFirstDate": formats.long_date(pd.Timestamp(sample["first_date"])),
        "BoxRLastDate": formats.long_date(pd.Timestamp(sample["last_date"])),
        "BoxRExecutions": formats.count(sample["executions"]),
        "BoxRTrades": formats.count(sample["box_trades"]),
        "BoxRFace": dollars(sample["box_face"]),
        "BoxRUnresolved": formats.count(sample["unresolved"]),
        "BoxRDroppedShort": formats.count(dropped["short"]),
        "BoxRDroppedRange": formats.count(dropped["out_of_range"]),
        "BoxRDroppedPrice": formats.count(dropped["no_price"]),
        "BoxRNoBenchmark": formats.count(sample["no_benchmark"]),
        "BoxRSampleTrades": formats.count(sample["rate_trades"]),
        "BoxRSampleFace": dollars(sample["rate_face"]),
        "BoxRHeadlineTrades": formats.count(headline["trades"]),
        "BoxRHeadlineFace": dollars(headline["face"]),
        "BoxRHeadlineDates": formats.count(headline["dates"]),
        "BoxRSpread": basis_points(headline["mean"]),
        "BoxRSpreadSE": basis_points(headline["std_error"], 1),
        "BoxRSpreadMedian": basis_points(headline["median"]),
        "BoxRSpreadLow": basis_points(headline["q25"]),
        "BoxRSpreadHigh": basis_points(headline["q75"]),
        "BoxRRate": _percent(headline["rate"]),
        "BoxRBenchmark": _percent(headline["benchmark"]),
        "BoxRMarkMatched": formats.count(marks["matched"]),
        "BoxRMarkMatchedShare": formats.percent(marks["matched_share"]),
        "BoxRMarkGap": basis_points(marks["mean"]),
        "BoxRMarkGapMedian": basis_points(marks["median"]),
        "BoxRTradedShare": formats.percent(values["open_interest"]["traded_face_share"]),
    }
    for name, stem in MATURITY_STEMS.items():
        macros.update(_bucket(f"BoxR{stem}", values["by_maturity"][name]))
    for name, stem in GROUP_STEMS.items():
        macros.update(_bucket(f"BoxR{stem}", values["by_underlying"][name]))
    return macros


def _bucket(stem: str, found: Mapping[str, Any]) -> dict[str, str]:
    return {
        f"{stem}Trades": formats.count(found["trades"]),
        f"{stem}Face": dollars(found["face"]),
        f"{stem}Spread": basis_points(found["mean"]),
        f"{stem}Median": basis_points(found["median"]),
        f"{stem}Low": basis_points(found["q25"]),
        f"{stem}High": basis_points(found["q75"]),
    }


def _percent(rate: float | None) -> str:
    return MISSING if rate is None else formats.percent(rate, 2)


__all__ = ["GROUP_STEMS", "MATURITY_STEMS", "basis_points", "box_rates_macros"]
