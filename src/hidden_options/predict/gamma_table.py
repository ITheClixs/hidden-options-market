"""Paper table `gamma_predictive`: hidden dollar gamma against next-day volatility.

Cells are the result's own macro strings, so the table reads as the text quotes it.
"""

from __future__ import annotations

from collections.abc import Mapping

from hidden_options.predict.macros import p_value
from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "gamma_predictive"
PREDICTOR_LABELS = {
    "x_net": "Netted gamma",
    "x_net_top": "Netted $\\times$ top tercile",
    "x_gross": "Gross gamma",
    "x_signed": "Vendor-signed gamma",
    "x_net_lead": "Netted gamma, two dates later",
}
OUTCOME_LABELS = {
    "abs_ret_next": "$|r_{t+1}|$",
    "oc_abs_next": "$|r^{oc}_{t+1}|$",
    "range_next": "$\\log(H/L)_{t+1}$",
}


@TABLES.register(RESULT)
def gamma_predictive_table(results: Mapping[str, Result]) -> str:
    """The two tests of record, then the descriptive rows."""
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    values, macros = results[RESULT].values, results[RESULT].macros
    records = [("H1: ", values["h1"]), ("H2: ", values["h2"])]
    records += [("", row) for row in values["secondary"]]
    rows = [
        {
            "predictor": kind + PREDICTOR_LABELS[row["predictor"]],
            "outcome": OUTCOME_LABELS[row["outcome"]],
            "beta": f"{row['coefficient'] * 1e4:.2f}",
            "t": f"{row['t_stat']:.2f}",
            "p": _p(row["p_value"]),
            "holm": p_value(row["holm_p"]) if "holm_p" in row else None,
        }
        for kind, row in records
    ]
    columns = [
        Column("predictor", "Predictor", "{}", "l"),
        Column("outcome", "Outcome", "{}", "l"),
        Column("beta", "$\\hat\\beta\\times10^4$", "{}"),
        Column("t", "$t$", "{}"),
        Column("p", "$p$", "{}"),
        Column("holm", "Holm $p$", "{}"),
    ]
    return render_table(
        rows,
        columns,
        caption="Hidden dollar gamma and next-day volatility.",
        label="tab:gamma-pred",
        notes=_notes(macros),
    )


def _p(value: float) -> str:
    return "$<$0.001" if value < 0.001 else p_value(value)


def _notes(m: Mapping[str, str]) -> str:
    return (
        f"{m['GPredDays']} underlying-days, {m['GPredUnderlyings']} underlyings, "
        f"{m['GPredDates']} activity dates. Predictors are FLEX dollar gamma, the change in "
        "dollar delta for a 1\\% move, over the mean dollar volume of the twenty sessions "
        "ending at $t$, winsorised at the 1st and 99th percentiles and scaled to unit "
        "standard deviation, so $\\hat\\beta$ is per standard deviation. Each series is "
        "priced at the volatility its own mark inverts to in a validated cell; an "
        "underlying-day with under half its FLEX open interest priced is left out "
        f"({m['GPredExcluded']} of them). Netted gamma nets same-strike call and put open "
        "interest first. Every regression has underlying and date fixed effects and the "
        "controls of Table~\\ref{tab:pred}; errors are clustered by underlying and date. "
        "H1 and H2 are the two tests of record, fixed in advance with Holm's adjustment across "
        "them; the other rows are descriptive. The lead row's predictor is dated after its "
        "outcome."
    )


__all__ = ["gamma_predictive_table"]
