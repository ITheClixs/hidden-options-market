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
NAMES = [f"N{i:02d}" for i in range(50)]


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
        {"symbol": ["WKLY", "N00"], "expiry": pd.to_datetime(["2025-06-04", "2025-06-20"])}
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
    # N00's listed expiry is a Friday, so it stays in.
    assert "N00" not in result.values["sample"]["excluded_names"]


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
