"""The `pinning` result on a synthetic world.

SPY gives the calendar. Fifty names have FLEX expiring on a run of Tuesdays and close
exactly at their FLEX strike on expiry. WKLY has the same planted pin but lists a
Wednesday weekly, so it must be left out. Every name also has FLEX expiring on Fridays,
without a pin.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.pinning_result import PinningInputs, pinning_result
from hidden_options.publish.latex import render_macros
from hidden_options.publish.results import read_results, write_result

DAYS = pd.bdate_range("2025-01-02", periods=260)
# Letters only: a trailing digit marks an adjusted-deliverable root, which is left out.
NAMES = [f"N{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(50)]


def world(seed: int = 0) -> PinningInputs:
    rng = np.random.default_rng(seed)
    bars, reports = [], []
    tuesdays = [d for d in DAYS[80:250] if d.day_of_week == 1]
    fridays = [d for d in DAYS[80:250] if d.day_of_week == 4]
    for name in ["SPY", *NAMES, "WKLY"]:
        path = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=len(DAYS))))
        for expiry in tuesdays + fridays:
            pos = DAYS.get_loc(expiry)
            strike = round(float(path[pos - 1] * np.exp(rng.uniform(-0.02, 0.02))), 2)
            if expiry.day_of_week == 1:
                path[pos] = strike
            reports.append(
                {
                    "report_date": DAYS[pos - 1],
                    "kind": "equity",
                    "root": f"1{name}",
                    "underlying": name,
                    "right": "C",
                    "expiry": expiry,
                    "strike": strike,
                    "mark_price": 1.0,
                    "open_interest": 500,
                }
            )
        stamps = [d.tz_localize("America/New_York") + pd.Timedelta(hours=9.5) for d in DAYS]
        bars.append(
            pd.DataFrame(
                {
                    "symbol": name,
                    "timestamp": stamps,
                    "open": path,
                    "high": path,
                    "low": path,
                    "close": path,
                    "volume": 1e6,
                }
            )
        )
    listed = pd.DataFrame(
        {"symbol": ["WKLY", "NAA"], "expiry": pd.to_datetime(["2025-06-04", "2025-06-20"])}
    )
    return PinningInputs(pd.concat(bars, ignore_index=True), pd.DataFrame(reports), listed)


@pytest.fixture(scope="module")
def result():
    return pinning_result(world())


def test_the_planted_pin_is_found(result):
    h1 = result.values["h1"]
    assert h1["mean"] > 0
    assert h1["p_value"] < 0.001
    assert h1["sign_flip_p"] < 0.01


def test_a_name_with_listed_weekday_expiries_is_left_out(result):
    assert "WKLY" in result.values["sample"]["excluded_names"]
    # NAA's listed expiry is a Friday, so it stays in.
    assert "NAA" not in result.values["sample"]["excluded_names"]


def test_unpinned_fridays_show_no_pin(result):
    assert result.values["descriptive"]["friday"]["p_value"] > 0.01


def test_macros_render_and_values_round_trip(result, tmp_path):
    assert "PinMean" in render_macros({"pinning": result})
    write_result(result, tmp_path)
    again = read_results(tmp_path)["pinning"]
    assert json.dumps(again.values, sort_keys=True) == json.dumps(result.values, sort_keys=True)


def test_table_renders_from_the_macros(result):
    from hidden_options.measure.pinning_table import pinning_table

    text = pinning_table({"pinning": result})
    assert "\\label{tab:pinning}" in text
    assert result.macros["PinMean"] in text


def with_split(inputs: PinningInputs, name: str, ex_date: pd.Timestamp) -> PinningInputs:
    """`inputs` with a 10:1 split of `name` on `ex_date`: bars before it on their own,
    unadjusted basis, as `read_bars` gives them, with the factor carried alongside."""
    bars = inputs.bars.assign(split_factor=1.0)
    sessions = bars["timestamp"].dt.tz_localize(None).dt.normalize()
    before = (bars["symbol"] == name) & (sessions < ex_date)
    for column in ("open", "high", "low", "close"):
        bars.loc[before, column] *= 10
    bars.loc[before, "volume"] /= 10
    bars.loc[before, "split_factor"] = 10.0
    reports = inputs.reports.copy()
    early = (reports["underlying"] == name) & (reports["expiry"] < ex_date)
    reports.loc[early, "strike"] *= 10
    return PinningInputs(bars, reports, inputs.listed)


def test_a_split_inside_an_event_window_drops_only_that_event(result):
    ex_date = DAYS[152]
    split = pinning_result(with_split(world(), "NAB", ex_date))
    sample = split.values["sample"]
    # Expiries from E = ex_date - 5 sessions to E = ex_date straddle the split.
    straddling = [d for d in DAYS[147:153] if d.day_of_week == 1]
    assert sample["split_dropped"] == len(straddling)
    assert sample["events"] == result.values["sample"]["events"] - len(straddling)
    # Away from the split, sigma and the statistics are those of the unsplit world.
    assert split.values["h1"]["mean"] == pytest.approx(result.values["h1"]["mean"], rel=0.05)
