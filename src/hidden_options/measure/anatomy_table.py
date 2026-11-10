"""Paper table `anatomy`: the FLEX market split into products.

Cells are the result's own macro strings, so the table reads exactly as the text quotes.
"""

from __future__ import annotations

from collections.abc import Mapping

from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "anatomy"
ROWS = (
    ("Box", "Box spreads"),
    ("Stock", "Stock-leg calls"),
    ("Package", "Package legs"),
    ("Pair", "Same-strike pairs"),
    ("Other", "Other"),
)


@TABLES.register(RESULT)
def anatomy_table(results: Mapping[str, Result]) -> str:
    """Series, open interest, mark value and gamma in each product category."""
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    m = results[RESULT].macros
    rows = [
        {
            "label": label,
            "series": m[f"Anat{stem}Series"],
            "oi": m[f"Anat{stem}OIShare"],
            "value": m[f"Anat{stem}Value"],
            "share": m[f"Anat{stem}ValueShare"],
            "mean": m[f"Anat{stem}MeanValueShare"],
            "gamma": m[f"AnatGamma{stem}"],
        }
        for stem, label in ROWS
    ]
    columns = [
        Column("label", "Category", "{}", "l"),
        Column("series", "Series", "{}"),
        Column("oi", "Open interest", "{}"),
        Column("value", "Mark value", "{}"),
        Column("share", "Value share", "{}"),
        Column("mean", "Mean value share", "{}"),
        Column("gamma", "Gross gamma", "{}"),
    ]
    return render_table(
        rows,
        columns,
        caption="What the FLEX market is made of.",
        label="tab:anatomy",
        notes=_notes(m),
    )


def _notes(m: Mapping[str, str]) -> str:
    return (
        f"Every FLEX series with open interest on {m['AnatLastDate']}, assigned to one "
        "category within its root and expiry, in the order of the rows. A box is two "
        "strikes that each carry equal call and put open interest, with one count at both. "
        "A stock-leg call is an unpaired call struck at no more than 5\\% of its mark plus "
        "its strike. A package leg is any other series with the count of a stock-leg call "
        "at its root and expiry. A same-strike pair is a strike with equal call and put "
        "open interest that is in neither. Open interest and value share are of the "
        f"date's totals; mean value share averages the {m['AnatDates']} report dates. "
        "Gross gamma is each category's share of gross FLEX dollar gamma on the "
        f"{m['AnatGammaDates']} settlements and underlyings of Table~\\ref{{tab:gamma}}."
    )


__all__ = ["anatomy_table"]
