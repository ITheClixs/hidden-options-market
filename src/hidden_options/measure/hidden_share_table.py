"""Paper table `hidden_share`: the census and the daily universe side by side.

Cells are the result's own macro strings, so a number in the table reads exactly as the
text beside it quotes it.
"""

from __future__ import annotations

from collections.abc import Mapping

from hidden_options.measure.hidden_share_macros import THRESHOLD_WORDS
from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "hidden_share"


@TABLES.register(RESULT)
def hidden_share_table(results: Mapping[str, Result]) -> str:
    """Counts of underlyings at or above each FLEX share, once and on every date."""
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    macros = results[RESULT].macros
    rows = [
        {
            "label": "Underlyings",
            "census": macros["HiddenCensusUnderlyings"],
            "daily": macros["HiddenDailyComplete"],
        },
        {
            "label": "Median FLEX share",
            "census": macros["HiddenCensusMedian"],
            "daily": macros["HiddenDailyMedian"],
        },
        *(
            {
                "label": f"At least {key}\\%",
                "census": macros[f"HiddenCensus{word}"],
                "daily": macros[f"HiddenStable{word}"],
            }
            for key, word in THRESHOLD_WORDS.items()
        ),
        {
            "label": "FLEX share of all open interest",
            "census": macros["HiddenCensusAggregate"],
            "daily": f"{macros['HiddenDailyAggregateLow']} to {macros['HiddenDailyAggregateHigh']}",
        },
    ]
    columns = [
        Column("label", "", "{}", "l"),
        Column("census", "Census", "{}"),
        Column("daily", "On every date", "{}"),
    ]
    notes = (
        "Census: OCC's series search for each of the "
        f"{macros['HiddenCensusSymbols']} symbols with listed weekly options, on the "
        f"settlement of {macros['HiddenCensusDate']}. On every date: the "
        f"{macros['HiddenDailyComplete']} followed underlyings observed on all "
        f"{macros['HiddenDailyDates']} settlements from {macros['HiddenDailyFirst']} to "
        f"{macros['HiddenDailyLast']}; a count is of underlyings at or above the share on "
        "each of them, the median is the median underlying's median over the dates, and the "
        "last row is the range over the dates for the "
        f"{macros['HiddenDailySearch']} names in the series search. Adjusted-deliverable "
        "classes are left out of both columns."
    )
    return render_table(
        rows,
        columns,
        caption="Underlyings by the FLEX share of their option open interest.",
        label="tab:hidden",
        notes=notes,
    )
