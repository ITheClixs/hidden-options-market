"""Paper tables `predictive` and `windows`, rendered from the `predictive` result."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hidden_options.predict.macros import BASIS_POINTS, p_value
from hidden_options.publish import formats
from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "predictive"

ROW_LABELS = {
    "innovation": "Inventory innovation",
    "change": "Inventory change",
    "near_share": "Near-dated share change",
    "put_share": "Put share",
    "innovation_squared": "Inventory innovation",
    "placebo": "Placebo: innovation at $T+2$",
}
OUTCOME_LABELS = {"abs_ret_next": "$|r_{t+1}|$", "sq_ret_next": "$r_{t+1}^2$"}

_SIGNED = "${:+.2f}$"
_SPECIFICATION = (
    "Underlying and date fixed effects; standard errors clustered by underlying and by "
    "date. Controls: mean absolute return over the previous 5 and 22 sessions, the same "
    "day's absolute return, and log dollar volume."
)


@TABLES.register("predictive")
def predictive_table(results: Mapping[str, Result]) -> str:
    """The six regressions, with the clustered and the permutation p-value of each.

    p-values print as the macros print them, so a value the text quotes reads the same
    in the table.
    """
    values = _values(results)
    rows = [
        {
            "label": ROW_LABELS[row["key"]],
            "outcome": OUTCOME_LABELS[row["outcome"]],
            "beta": _scaled(row["coefficient"]),
            "t": _rounded(row["t_stat"]),
            "mde": _scaled(row["mde80"]),
            "clustered_p": p_value(row["p_value"]),
            "permutation_p": p_value(row["permutation_p"]),
        }
        for row in values["rows"]
    ]
    columns = [
        Column("label", "Predictor", "{}", "l"),
        Column("outcome", "Outcome", "{}", "l"),
        Column("beta", "$10^4\\beta$", _SIGNED),
        Column("t", "$t$", _SIGNED),
        Column("mde", "$10^4\\,$MDE80", ".2f"),
        Column("clustered_p", "Clust.\\ $p$", "{}"),
        Column("permutation_p", "Perm.\\ $p$", "{}"),
    ]
    sample = values["sample"]
    notes = (
        f"{_SPECIFICATION} {formats.count(sample['underlying_days'])} underlying-days, "
        f"{formats.count(sample['underlyings'])} underlyings, "
        f"{formats.count(sample['dates'])} activity dates; the placebo row loses the last "
        "two dates. Coefficients and MDE80, the effect detectable with 80\\% power at the "
        "5\\% level, are multiplied by $10^4$, which for $|r|$ is basis points. Clust.\\ $p$ "
        "uses the clustered errors; Perm.\\ $p$ comes from "
        f"{formats.count(values['permutation']['n_perm'])} re-estimations with the "
        "predictor shuffled across underlyings within each date."
    )
    return render_table(
        rows,
        columns,
        caption="Hidden inventory at $T$ and the underlying's volatility from $T+1$.",
        label="tab:pred",
        notes=notes,
    )


@TABLES.register("windows")
def windows_table(results: Mapping[str, Result]) -> str:
    """The main row and its placebo with the panel loaded from each start date."""
    values = _values(results)
    rows = [
        {
            "start": window["start"],
            "days": window["main"]["n_obs"],
            "beta": _scaled(window["main"]["coefficient"]),
            "t": _rounded(window["main"]["t_stat"]),
            "placebo_beta": _scaled(window["placebo"]["coefficient"]),
            "placebo_t": _rounded(window["placebo"]["t_stat"]),
        }
        for window in values["windows"]
    ]
    columns = [
        Column("start", "Panel from", "{}", "l"),
        Column("days", "Underlying-days", ",d"),
        Column("beta", "Innovation $10^4\\beta$", _SIGNED),
        Column("t", "$t$", _SIGNED),
        Column("placebo_beta", "Placebo $10^4\\beta$", _SIGNED),
        Column("placebo_t", "$t$", _SIGNED),
    ]
    notes = (
        "Next-day $|r|$ on the inventory innovation and on its placebo, with the "
        "specification of Table~\\ref{tab:pred}, rebuilding the panel from each start date. "
        "The first row is the full panel."
    )
    return render_table(
        rows,
        columns,
        caption="The main estimate and its placebo with the panel loaded from later dates.",
        label="tab:windows",
        notes=notes,
    )


def _values(results: Mapping[str, Result]) -> Mapping[str, Any]:
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    return results[RESULT].values


def _scaled(value: float) -> float:
    return _rounded(value * BASIS_POINTS)


def _rounded(value: float) -> float:
    """Rounded to the two places printed, with a negative zero made positive."""
    return round(value, 2) + 0.0
