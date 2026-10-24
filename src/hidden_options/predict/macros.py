"""The strings the paper and README print for the `predictive` result.

Coefficients and minimum detectable effects are printed multiplied by 10^4, which for an
absolute-return outcome is basis points; t-statistics and p-values as they are. Each
macro is formatted here, from the result's raw values, and nowhere else. See the
`publish` package for the value convention.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.publish import formats

BASIS_POINTS = 1e4

# Macro stems for the table rows, keyed as in the result.
ROW_STEMS = {
    "innovation": "Innov",
    "change": "Change",
    "near_share": "Near",
    "put_share": "Put",
    "innovation_squared": "InnovSq",
    "placebo": "Placebo",
}
HORIZON_WORDS = {3: "Three", 5: "Five", 10: "Ten"}
WINDOW_WORDS = ("One", "Two", "Three")


def bp(value: float) -> str:
    """A coefficient times 10^4, to two places: 0.000304 -> `3.04`."""
    return formats.decimal(value * BASIS_POINTS, 2)


def t_stat(value: float) -> str:
    return formats.decimal(value, 2)


def p_value(value: float) -> str:
    """Two places, or three below 0.1 so a small p keeps a significant digit."""
    return formats.decimal(value, 2 if value >= 0.1 else 3)


def predictive_macros(values: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `predictive` result defines, from its values."""
    return {
        **_sample_macros(values),
        **_row_macros(values),
        **_permutation_macros(values),
        **_robustness_macros(values),
        **_window_macros(values),
    }


def _sample_macros(values: Mapping[str, Any]) -> dict[str, str]:
    sample = values["sample"]
    main = values["rows"][0]
    mean_abs = sample["mean_abs_ret"]
    reasons = sample["without_bars_by_reason"]
    return {
        "PredUnderlyingDays": formats.count(sample["underlying_days"]),
        "PredUnderlyings": formats.count(sample["underlyings"]),
        "PredDates": formats.count(sample["dates"]),
        "PredFirstDate": formats.long_date(pd.Timestamp(sample["first_date"])),
        "PredLastDate": formats.long_date(pd.Timestamp(sample["last_date"])),
        "PredIndexUnderlyings": formats.count(sample["index_underlyings"]),
        "PredQualifying": formats.count(sample["qualifying_underlyings"]),
        "PredQualifyingDates": formats.count(sample["qualifying_min_dates"]),
        "PredNoBars": formats.count(len(sample["without_bars"])),
        "PredNoBarsAdjusted": formats.count(reasons["adjusted_deliverable"]),
        "PredNoBarsShareClass": formats.count(reasons["share_class"]),
        "PredNoBarsOther": formats.count(reasons["other"]),
        "PredMeanAbsRet": formats.decimal(mean_abs * BASIS_POINTS, 0),
        # The main row's MDE80 per log point of innovation, as a share of the mean outcome.
        "PredMDEShare": formats.percent(main["mde80"] / mean_abs, 1),
        "PredMaxAbsT": t_stat(values["max_abs_t"]),
    }


def _row_macros(values: Mapping[str, Any]) -> dict[str, str]:
    genuine = [row for row in values["rows"] if not row["placebo"]]
    macros = {
        "PredMinGenuinePermP": p_value(min(row["permutation_p"] for row in genuine)),
        "PredMinGenuineClusterP": p_value(min(row["p_value"] for row in genuine)),
    }
    for row in values["rows"]:
        stem = f"Pred{ROW_STEMS[row['key']]}"
        macros[f"{stem}Beta"] = bp(row["coefficient"])
        macros[f"{stem}T"] = t_stat(row["t_stat"])
        macros[f"{stem}SE"] = bp(row["std_error"])
        macros[f"{stem}ClusterP"] = p_value(row["p_value"])
        macros[f"{stem}MDE"] = bp(row["mde80"])
        macros[f"{stem}PermP"] = p_value(row["permutation_p"])
    return macros


def _permutation_macros(values: Mapping[str, Any]) -> dict[str, str]:
    permutation = values["permutation"]
    return {
        "PredPermutations": formats.count(permutation["n_perm"]),
        "PredNullSd": bp(permutation["null_sd"]),
        "PredNullLow": bp(permutation["null_low"]),
        "PredNullHigh": bp(permutation["null_high"]),
    }


def _robustness_macros(values: Mapping[str, Any]) -> dict[str, str]:
    decile, timing = values["top_decile"], values["timing"]
    macros = {
        "PredDecileBeta": bp(decile["coefficient"]),
        "PredDecileT": t_stat(decile["t_stat"]),
        "PredDecileDays": formats.count(decile["n_obs"]),
        "PredDecileCut": formats.decimal(decile["threshold"], 3),
        "PredOpenCloseBeta": bp(timing["coefficient"]),
        "PredOpenCloseT": t_stat(timing["t_stat"]),
        "PredOpenCloseMDE": bp(timing["mde80"]),
    }
    for horizon in values["horizons"]:
        word = HORIZON_WORDS[horizon["days"]]
        macros[f"PredHorizon{word}Beta"] = bp(horizon["coefficient"])
        macros[f"PredHorizon{word}T"] = t_stat(horizon["t_stat"])
    return macros


def _window_macros(values: Mapping[str, Any]) -> dict[str, str]:
    windows = values["windows"]
    if len(windows) > len(WINDOW_WORDS):
        raise ValueError(f"{len(windows)} windows, but macro names exist for {len(WINDOW_WORDS)}")
    macros: dict[str, str] = {}
    for word, window in zip(WINDOW_WORDS, windows, strict=False):
        stem = f"PredWindow{word}"
        main, placebo = window["main"], window["placebo"]
        macros[f"{stem}Start"] = formats.iso_date(pd.Timestamp(window["start"]))
        macros[f"{stem}Days"] = formats.count(main["n_obs"])
        macros[f"{stem}Beta"] = bp(main["coefficient"])
        macros[f"{stem}T"] = t_stat(main["t_stat"])
        macros[f"{stem}PlaceboBeta"] = bp(placebo["coefficient"])
        macros[f"{stem}PlaceboT"] = t_stat(placebo["t_stat"])
    return macros
