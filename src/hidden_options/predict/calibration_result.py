"""Result `gamma_calibration`: what the gamma test's null rules out.

Read from the `gamma_predictive` result alone (its sample statistics and minimum
detectable effect); see `predict.calibration`. Added after the test's result was seen.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hidden_options.predict.calibration import calibration
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import RESULTS_DIR, Result, now_iso, read_results

NAME = "gamma_calibration"
SOURCE = "gamma_predictive"
BASIS_POINTS = 1e4


def calibration_result(source: Result) -> Result:
    values = calibration(dict(source.values["sample"]), float(source.values["h1"]["mde80"]))
    return Result(NAME, values, calibration_macros(values), {"source": SOURCE}, now_iso())


def calibration_macros(values: Mapping[str, Any]) -> dict[str, str]:
    effects = values["effects"]

    def bp(value: float) -> str:
        return formats.decimal(value * BASIS_POINTS, 0)

    return {
        "GCalPooledLow": bp(effects["pooled"]["0.5"]),
        "GCalPooledHigh": bp(effects["pooled"]["1.0"]),
        "GCalWithinLow": bp(effects["within"]["0.5"]),
        "GCalWithinHigh": bp(effects["within"]["1.0"]),
        "GCalRatio": formats.decimal(values["smallest_over_mde"], 0),
    }


@ANALYSES.register(NAME)
def calibration_analysis() -> Result:
    found = read_results(RESULTS_DIR)
    if SOURCE not in found:
        raise FileNotFoundError(
            f"No {SOURCE!r} result; run `hidden-options results --only {SOURCE}`"
        )
    return calibration_result(found[SOURCE])


__all__ = ["NAME", "calibration_analysis", "calibration_macros", "calibration_result"]
