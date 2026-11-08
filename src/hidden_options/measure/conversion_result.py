"""Result `conversion`: how much FLEX open interest converts into listed series.

On the settlements with stored chains, which give listed open interest per series. The
inputs are those of the `hidden_gamma` result: chains dated by settlement, and the FLEX
report.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.measure.conversion import KEY, MATCH_SHARE, conversion_check
from hidden_options.measure.hidden_gamma_result import GammaInputs
from hidden_options.measure.hidden_gamma_result import load_inputs as load_gamma_inputs
from hidden_options.measure.hidden_share import flex_series
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "conversion"


def conversion_result(inputs: GammaInputs) -> Result:
    listed = pd.DataFrame(
        inputs.chains.groupby(["date", *KEY], as_index=False)["open_interest"].sum()
    )
    dates = pd.DatetimeIndex(sorted(listed["date"].unique()))
    flex = flex_series(inputs.panel, dates)
    flex = flex[flex["symbol"].isin(set(listed["symbol"]))]
    values = {**conversion_check(flex, listed), "match_share": MATCH_SHARE}
    run_inputs = {
        "first_date": f"{dates.min():%Y-%m-%d}",
        "last_date": f"{dates.max():%Y-%m-%d}",
        "ci_runs": list(inputs.ci_runs),
        "local_only": inputs.local_only,
    }
    return Result(NAME, values, conversion_macros(values), run_inputs, now_iso())


def conversion_macros(values: Mapping[str, Any]) -> dict[str, str]:
    return {
        "ConvTwinShare": formats.percent(values["twin_oi_share"]),
        "ConvDropped": formats.millions(values["dropped_contracts"]),
        "ConvDroppedTwin": formats.percent(values["dropped_with_twin"]),
        "ConvMatched": formats.percent(values["dropped_matched"], 1),
        "ConvCreatedMatched": formats.percent(values["created_matched"], 1),
        "ConvSettlements": formats.count(values["settlements"]),
        "ConvMatchShare": formats.percent(values["match_share"]),
    }


@ANALYSES.register(NAME)
def conversion_analysis() -> Result:
    return conversion_result(load_gamma_inputs())


__all__ = ["NAME", "conversion_analysis", "conversion_macros", "conversion_result"]
