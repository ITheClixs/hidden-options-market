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
THREE_MONTHS = 0.25


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
        "BoxRTradedFace": dollars(
            values["open_interest"]["face"] * values["open_interest"]["traded_face_share"]
        ),
        **_months(values["monthly"]),
        **_confirmation(values),
        **_diagnostics(values.get("diagnostics")),
        **_sizes(values["by_size"]),
        "BoxRMarkThreeMonth": basis_points(_three_month(values)),
    }
    for name, stem in MATURITY_STEMS.items():
        macros.update(_bucket(f"BoxR{stem}", values["by_maturity"][name]))
    for name, stem in GROUP_STEMS.items():
        macros.update(_bucket(f"BoxR{stem}", values["by_underlying"][name]))
    return macros


def _confirmation(values: Mapping[str, Any]) -> dict[str, str]:
    """Open-interest box face confirmed by traded packages, by underlying and over time,
    and whether a box's two lines first appeared together. Added after the first figures."""
    seen = values["open_interest"]
    macros: dict[str, str] = {}
    if "by_underlying" in seen:
        for name, stem in GROUP_STEMS.items():
            macros[f"BoxRTraded{stem}"] = formats.percent(seen["by_underlying"][name])
        macros["BoxRLargestOfTraded"] = formats.percent(seen["largest_share_of_traded"])
    confirmed = values.get("confirmed") or {}
    if confirmed.get("first"):
        first, last = confirmed["first"], confirmed["last"]
        macros.update(
            {
                "BoxRConfirmedFirst": dollars(first["strike_pair"]),
                "BoxRConfirmedLast": dollars(last["strike_pair"]),
                "BoxRConfirmedFirstShare": formats.percent(
                    _part(first["strike_pair"], first["face"])
                ),
                "BoxRConfirmedGrowth": formats.decimal(confirmed["growth"], 1),
            }
        )
    origins = values.get("origins") or {}
    if origins.get("same_date_share"):
        same = origins["same_date_share"]
        macros.update(
            {
                "BoxRCensored": formats.percent(origins["censored_share"]),
                "BoxRSameDateConfirmed": formats.percent(same["confirmed"]),
                "BoxRSameDateUnconfirmed": formats.percent(same["unconfirmed"]),
            }
        )
    return macros


def _diagnostics(found: Mapping[str, Any] | None) -> dict[str, str]:
    """How much the headline rests on a few dates, and how the spread moved by quarter.
    Added after the first figures."""
    if not found or found.get("top_dates_share") is None:
        return {}
    quarters = [row for row in found["by_quarter"] if row["median"] is not None]
    low = min(quarters, key=lambda row: row["median"])
    high = max(quarters, key=lambda row: row["median"])
    macros = {
        "BoxRTopDates": formats.count(found["top_dates"]),
        "BoxRTopDatesShare": formats.percent(found["top_dates_share"]),
        "BoxREffectiveDates": formats.count(found["effective_dates"]),
        "BoxRUnweighted": basis_points(found["unweighted_mean"]),
        "BoxRLeaveOneLow": basis_points(found["leave_one_low"]),
        "BoxRLeaveOneHigh": basis_points(found["leave_one_high"]),
        "BoxRQuarterLow": basis_points(low["median"]),
        "BoxRQuarterLowName": _quarter(low["quarter"]),
        "BoxRQuarterHigh": basis_points(high["median"]),
        "BoxRQuarterHighName": _quarter(high["quarter"]),
        "BoxRMarkGapHeadline": basis_points(found["marks_headline"]["mean"]),
        "BoxRMarkGapHeadlineMedian": basis_points(found["marks_headline"]["median"]),
    }
    longest = found.get("longest_largest")
    if longest:
        macros.update(
            {
                "BoxRLongestLargestFace": dollars(longest["face"]),
                "BoxRLongestLargestSpread": basis_points(longest["spread"]),
                "BoxRLongestLargestYear": longest["expiry"][:4],
                "BoxRLongestLargestShare": formats.percent(longest["face_share"]),
            }
        )
    return macros


def _quarter(label: str) -> str:
    """`2025Q2` as prose writes it: `the second quarter of 2025`."""
    names = {"1": "first", "2": "second", "3": "third", "4": "fourth"}
    return f"the {names[label[-1]]} quarter of {label[:4]}"


def _three_month(values: Mapping[str, Any]) -> float | None:
    """What the gap between OCC's marks and traded rates on boxes of up to a year comes to,
    as a share of face, over three months."""
    found = (values.get("diagnostics") or {}).get("marks_headline") or values["marks"]
    return None if found["mean"] is None else abs(found["mean"]) * THREE_MONTHS


def _part(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


def _months(monthly: list[Mapping[str, Any]]) -> dict[str, str]:
    """The range of the monthly median spread, and the share of traded face that falls in
    the last month of a calendar quarter."""
    medians = [row["median"] for row in monthly if row["median"] is not None]
    face = sum(row["traded_face"] for row in monthly)
    closing = sum(row["traded_face"] for row in monthly if int(row["month"][5:7]) % 3 == 0)
    return {
        "BoxRMonths": formats.count(len(medians)),
        "BoxRMonthLow": basis_points(min(medians) if medians else None),
        "BoxRMonthHigh": basis_points(max(medians) if medians else None),
        "BoxRQuarterEndShare": formats.percent(closing / face if face else 0.0),
    }


def _sizes(by_size: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """The lowest and highest median spread across bands of trade size."""
    medians = [band["median"] for band in by_size.values() if band["median"] is not None]
    return {
        "BoxRSizeMedianLow": basis_points(min(medians) if medians else None),
        "BoxRSizeMedianHigh": basis_points(max(medians) if medians else None),
    }


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
