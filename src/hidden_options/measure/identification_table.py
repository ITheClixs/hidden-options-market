"""Paper table `confusion`: the off-grid strike rule against the FLEX product symbol.

Cells are the result's own macro strings, so a count in the table reads exactly as the
text beside it quotes it.
"""

from __future__ import annotations

from collections.abc import Mapping

from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "identification"
NAME = "confusion"


@TABLES.register(NAME)
def confusion_table(results: Mapping[str, Result]) -> str:
    """Census series by what the rule says and what they are."""
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    macros = results[RESULT].macros
    rows = [
        {
            "label": "Strike off the grid",
            "flex": macros["RuleFlexFound"],
            "listed": macros["RuleListedFlagged"],
        },
        {
            "label": "Strike on the grid",
            "flex": macros["RuleFlexMissed"],
            "listed": macros["RuleListedPassed"],
        },
    ]
    columns = [
        Column("label", "", "{}", "l"),
        Column("flex", "FLEX", "{}"),
        Column("listed", "Listed", "{}"),
    ]
    notes = (
        "A series is one line of OCC's series search on the census date: a product, "
        "expiry and strike, with its call and put open interest together. A series is FLEX "
        "when its product symbol has a leading digit; the rule flags a strike whose cents "
        "are not 00, 25, 50 or 75. Adjusted-deliverable classes and series with no open "
        f"interest are left out, leaving {macros['CensusSeries']} series, "
        f"{macros['CensusFlexSeries']} of them FLEX. Precision ${macros['RulePrecision']}$, "
        f"recall ${macros['RuleRecall']}$, $F_1$ ${macros['RuleFOne']}$."
    )
    return render_table(
        rows,
        columns,
        caption="The off-grid strike rule against OCC's own labels, series by series.",
        label="tab:confusion",
        notes=notes,
    )
