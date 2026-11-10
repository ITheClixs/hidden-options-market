"""Paper table `box_rates`: traded box rates against Treasuries, by maturity and product.

Cells are the result's own macro strings, so the table reads exactly as the text quotes.
"""

from __future__ import annotations

from collections.abc import Mapping

from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "box_rates"
ROWS = (
    ("ToOneMonth", "7 days to 1 month"),
    ("OneToThree", "1 to 3 months"),
    ("ThreeToTwelve", "3 to 12 months"),
    ("OneToTwoYears", "1 to 2 years"),
    ("OverTwoYears", "Over 2 years"),
    ("SPX", "SPX, up to 1 year"),
    ("SPY", "SPY, up to 1 year"),
    ("Else", "Other, up to 1 year"),
)


@TABLES.register(RESULT)
def box_rates_table(results: Mapping[str, Result]) -> str:
    """Box trades, their face and their spread over the Treasury curve."""
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    m = results[RESULT].macros
    rows = [
        {
            "label": "All, up to 1 year",
            "trades": m["BoxRHeadlineTrades"],
            "face": m["BoxRHeadlineFace"],
            "mean": m["BoxRSpread"],
            "median": m["BoxRSpreadMedian"],
            "iqr": f"{m['BoxRSpreadLow']} to {m['BoxRSpreadHigh']}",
        },
        *(
            {
                "label": label,
                "trades": m[f"BoxR{stem}Trades"],
                "face": m[f"BoxR{stem}Face"],
                "mean": m[f"BoxR{stem}Spread"],
                "median": m[f"BoxR{stem}Median"],
                "iqr": f"{m[f'BoxR{stem}Low']} to {m[f'BoxR{stem}High']}",
            }
            for stem, label in ROWS
        ),
    ]
    columns = [
        Column("label", "Box trades", "{}", "l"),
        Column("trades", "Trades", "{}"),
        Column("face", "Face", "{}"),
        Column("mean", "Mean", "{}"),
        Column("median", "Median", "{}"),
        Column("iqr", "Interquartile", "{}"),
    ]
    return render_table(
        rows,
        columns,
        caption="Traded box-spread rates less the Treasury curve, in basis points.",
        label="tab:box-rates",
        notes=_notes(m),
    )


def _notes(m: Mapping[str, str]) -> str:
    return (
        f"Box spreads traded as four-leg orders in Cboe's FLEX execution reports from "
        f"{m['BoxRFirstDate']} to {m['BoxRLastDate']}, with at least 7 days to expiry. "
        "A box's rate discounts the distance between its strikes to its net price, "
        "continuously compounded over calendar days. The spread is that rate less the "
        "Treasury par yield curve of the trade date at the same maturity, converted to "
        "continuous compounding. Mean is weighted by face; median and interquartile range "
        "are across trades. Beyond one year the benchmark is a par yield, not a zero rate, "
        "so those rows are approximate."
    )


__all__ = ["box_rates_table"]
