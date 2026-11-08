"""The strings the paper and README print for the `gamma_predictive` result.

Coefficients and MDEs are per standard deviation of the predictor and are printed times
10^4, which for absolute-return outcomes is basis points; t-statistics and p-values as in
the `predictive` result. Dollar gamma over dollar volume prints in basis points of a
day's dollar volume.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hidden_options.predict.macros import bp, p_value, t_stat
from hidden_options.publish import formats

SECONDARY_STEMS = {
    ("x_gross", "abs_ret_next"): "Gross",
    ("x_signed", "abs_ret_next"): "Signed",
    ("x_net", "oc_abs_next"): "OpenClose",
    ("x_net", "range_next"): "Range",
    ("x_net_lead", "abs_ret_next"): "Lead",
}
# The robustness rows of docs/log/2026-11-08-gamma-timing-spec.md.
TIMING_STEMS = {
    "pre": "Pre",
    "iv_control": "Iv",
    "pre_iv": "PreIv",
    "lead_fixed": "LeadFixed",
}
VERDICT_WORDS = {
    "finding": "a finding",
    "bounded_null": "a bounded null",
    "inconclusive": "inconclusive",
}


def gamma_predictive_macros(values: Mapping[str, Any]) -> dict[str, str]:
    """Every macro the `gamma_predictive` result defines."""
    h1, h2, sample = values["h1"], values["h2"], values["sample"]
    out = {
        "GPredBeta": bp(h1["coefficient"]),
        "GPredT": t_stat(h1["t_stat"]),
        "GPredP": p_value(h1["p_value"]),
        "GPredHolm": p_value(h1["holm_p"]),
        "GPredPermP": p_value(h1["permutation_p"]),
        "GPredSE": bp(h1["std_error"]),
        "GPredMDE": bp(h1["mde80"]),
        "GPredMDEShare": formats.percent(values["verdict"]["mde_share"], 1),
        "GPredLow": bp(h1["ci_low"]),
        "GPredHigh": bp(h1["ci_high"]),
        "GPredTopBeta": bp(h2["coefficient"]),
        "GPredTopT": t_stat(h2["t_stat"]),
        "GPredTopHolm": p_value(h2["holm_p"]),
        "GPredVerdict": VERDICT_WORDS[values["verdict"]["kind"]],
        "GPredDays": formats.count(sample["underlying_days"]),
        "GPredUnderlyings": formats.count(sample["underlyings"]),
        "GPredDates": formats.count(sample["dates"]),
        "GPredExcluded": formats.count(sample["excluded_low_coverage"]),
        "GPredCoverage": formats.percent(sample["median_coverage"], 1),
        "GPredMedianX": formats.decimal(sample["x_net_raw_median"] * 1e4, 2),
        "GPredNinetyX": formats.decimal(sample["x_net_raw_p90"] * 1e4, 1),
        "GPredSdX": formats.decimal(sample["x_net_sd"] * 1e4, 1),
        "GPredMeanAbs": bp(sample["mean_abs_ret"]),
    }
    for row in values["secondary"]:
        stem = SECONDARY_STEMS[(row["predictor"], row["outcome"])]
        out[f"GPred{stem}Beta"] = bp(row["coefficient"])
        out[f"GPred{stem}T"] = t_stat(row["t_stat"])
    for key, row in (values.get("timing") or {}).items():
        stem = TIMING_STEMS[key]
        out[f"GPred{stem}Beta"] = bp(row["coefficient"])
        out[f"GPred{stem}T"] = t_stat(row["t_stat"])
        out[f"GPred{stem}P"] = p_value(row["p_value"])
        out[f"GPred{stem}MDE"] = bp(row["mde80"])
        out[f"GPred{stem}Days"] = formats.count(row["n_obs"])
    if values.get("programme"):
        out.update(programme_macros(values["programme"]))
    return out


def programme_macros(programme: Mapping[str, Any]) -> dict[str, str]:
    """The one-sided test in the programme names (docs/log/2026-11-08-programme-gamma-spec.md)."""
    test, control, pre = programme["test"], programme["control"], programme["pre"]
    out = {
        "GProgBeta": bp(test["coefficient"]),
        "GProgT": t_stat(test["t_stat"]),
        "GProgTwoWayT": t_stat(test["two_way_t"]),
        "GProgWildP": p_value(test["p_value"]),
        "GProgMDE": bp(test["mde80"]),
        "GProgMDEShare": formats.percent(test["mde_share"], 1),
        "GProgVerdict": VERDICT_WORDS[test["kind"]],
        "GProgNames": formats.count(test["clusters"]),
        "GProgListed": formats.count(programme["names_listed"]),
        "GProgDays": formats.count(test["n_obs"]),
        "GProgDraws": formats.count(test["n_draws"]),
        "GProgControlBeta": bp(control["coefficient"]),
        "GProgControlT": t_stat(control["t_stat"]),
        "GProgControlWildP": p_value(control["p_value"]),
        "GProgControlNames": formats.count(control["clusters"]),
    }
    if pre is not None:
        out["GProgPreBeta"] = bp(pre["coefficient"])
        out["GProgPreT"] = t_stat(pre["t_stat"])
        out["GProgPreWildP"] = p_value(pre["p_value"])
    return out


__all__ = ["gamma_predictive_macros", "programme_macros"]
