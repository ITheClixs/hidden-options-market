"""The strings the paper and README print for the `market` result.

Each macro is formatted here, from the result's raw values, and nowhere else; the paper
and README only place them. See the `publish` package for the value convention.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.publish import formats


def market_macros(values: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `market` result defines, from its values."""
    return {
        **_panel_macros(values),
        **_growth_macros(values),
        **_cycle_macros(values),
        **_drop_macros(values),
        **_maturity_macros(values),
    }


def _panel_macros(values: Mapping[str, Any]) -> dict[str, str]:
    panel, start, end = values["panel"], values["start"], values["end"]
    within = values["shares_over_panel"]["within60d_share"]
    tops = values["concentration"]["top_shares"]
    return {
        "PanelDates": formats.count(panel["dates"]),
        "PanelUnderlyings": formats.count(panel["underlyings"]),
        "PanelSeriesDays": formats.count(panel["series_days"]),
        "PanelSeriesDaysMillions": formats.millions(panel["series_days"]),
        "PanelStart": formats.long_date(pd.Timestamp(panel["first_date"])),
        "PanelEnd": formats.long_date(pd.Timestamp(panel["last_date"])),
        "PanelMonths": formats.count(panel["months"]),
        "PanelMissingWeekdays": formats.count(len(panel["missing_weekdays"])),
        "OIStart": formats.millions(start["open_interest"]),
        "OIEnd": formats.millions(end["open_interest"]),
        "ValueStart": formats.usd_billions(start["mark_value"]),
        "ValueEnd": formats.usd_billions(end["mark_value"]),
        "SeriesStart": formats.count(start["series"]),
        "SeriesEnd": formats.count(end["series"]),
        "UnderlyingsStart": formats.count(start["underlyings"]),
        "UnderlyingsEnd": formats.count(end["underlyings"]),
        "TopTenShareStart": formats.percent(start["top10_share"]),
        "TopTenShare": formats.percent(end["top10_share"]),
        "WithinSixtyShareStart": formats.percent(start["within60d_share"]),
        "WithinSixtyShare": formats.percent(end["within60d_share"]),
        "CallShareStart": formats.percent(start["call_share"]),
        "CallShare": formats.percent(end["call_share"]),
        "WithinSixtyMean": formats.percent(within["mean"]),
        "WithinSixtyLow": formats.percent(within["min"]),
        "WithinSixtyHigh": formats.percent(within["max"]),
        "TopTwentyFiveShare": formats.percent(tops["25"]),
        "TopHundredShare": formats.percent(tops["100"]),
        "TopFiveUnderlyings": _name_list(values["concentration"]["largest"]),
    }


def _growth_macros(values: Mapping[str, Any]) -> dict[str, str]:
    growth, peak = values["growth"], values["peak"]
    breaks = pd.Timestamp(growth["break_date"])
    return {
        "OIPeak": formats.millions(peak["open_interest"]),
        "OIPeakDate": formats.long_date(pd.Timestamp(peak["date"])),
        "BreakDate": formats.long_date(breaks),
        "BreakMonth": formats.month_year(breaks),
        "BreakShiftDays": formats.count(growth["break_shift_days"]),
        "PreBreakGrowth": formats.signed_percent(growth["pre_growth"], digits=0),
        "PostBreakGrowth": formats.signed_percent(growth["post_growth"], digits=0),
        "PostBreakGrowthQuarter": formats.signed_percent(growth["post_growth_quarter"], digits=0),
    }


def _cycle_macros(values: Mapping[str, Any]) -> dict[str, str]:
    cycles = values["cycles"]
    return {
        "OIFlatLow": formats.millions(cycles["flat_low"]),
        "OIFlatHigh": formats.millions(cycles["flat_high"]),
        "OIFlatLevel": formats.millions(cycles["flat_level"]),
        "OICycleLatest": formats.millions(cycles["latest_level"]),
        "OICycleLatestEnd": formats.long_date(pd.Timestamp(cycles["latest_end"])),
        "FlatBandEnd": formats.long_date(pd.Timestamp(cycles["flat_band_end"])),
        "GrowthMultiple": formats.decimal(cycles["multiple"]),
        "OIQuarterChange": formats.signed_percent(cycles["quarter_change"]),
    }


def _drop_macros(values: Mapping[str, Any]) -> dict[str, str]:
    drops = values["drops"]
    landed = drops["on_expiry"]
    return {
        # Read as "of the ten largest falls, all land on ..." or "..., 7 land on ...".
        "DropsOnExpiry": "all" if landed == len(drops["largest"]) else formats.count(landed),
        "DropsOnExpiryDate": formats.count(drops["on_expiry_date"]),
        "DropsDayAfter": formats.count(drops["day_after_expiry"]),
        "DropExpiries": formats.count(drops["distinct_expiries"]),
        "DropLow": formats.percent(drops["fall_low"], digits=1),
        "DropHigh": formats.percent(drops["fall_high"], digits=1),
        "ExpiringRatioLow": formats.decimal(drops["expiring_ratio_low"]),
        "ExpiringRatioHigh": formats.decimal(drops["expiring_ratio_high"]),
        "ExpiryWindowChanges": formats.count(drops["window_changes"]),
        "DailyChanges": formats.count(drops["changes"]),
        "ExpiryWindowShare": formats.percent(drops["window_share"], digits=1),
    }


def _maturity_macros(values: Mapping[str, Any]) -> dict[str, str]:
    maturity = values["maturity"]
    one, two = maturity["over_one_year"], maturity["over_two_years"]
    median, beyond = maturity["median_days"], maturity["beyond_horizon"]
    return {
        "OverOneYearStart": formats.percent(one["start"]),
        "OverOneYear": formats.percent(one["end"]),
        "OverTwoYearsStart": formats.percent(two["start"]),
        "OverTwoYears": formats.percent(two["end"]),
        "MedianDaysMean": formats.count(median["mean"]),
        "MedianDaysLow": formats.count(median["min"]),
        "MedianDaysHigh": formats.count(median["max"]),
        "MapHorizonMonths": formats.count(maturity["horizon_months"]),
        "BeyondHorizonShare": formats.percent(beyond["end"]),
        "BeyondHorizonMean": formats.percent(beyond["mean"]),
    }


def _name_list(names: list[str]) -> str:
    """`SPY, SPX, NVDA, EWZ and EFA`."""
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"
