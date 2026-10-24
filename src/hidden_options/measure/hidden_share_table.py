"""Paper table `hidden_share`: the census and the daily universe side by side.

Cells are the result's own macro strings, so a number in the table reads exactly as the
text beside it quotes it. A daily count that rests on the index counting rule, because
one of the underlyings in it is an index product whose share falls below the threshold
once the series expiring on a date count too, is marked and the note says which.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hidden_options.measure.hidden_share_macros import THRESHOLD_WORDS
from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "hidden_share"
DAGGER = "$^{\\dagger}$"


@TABLES.register(RESULT)
def hidden_share_table(results: Mapping[str, Result]) -> str:
    """Counts of underlyings at or above each FLEX share, once and on every date."""
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    macros, values = results[RESULT].macros, results[RESULT].values
    marked = _resting_on_the_index_rule(values)
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
                "daily": macros[f"HiddenStable{word}"] + (DAGGER if marked.get(key) else ""),
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
    return render_table(
        rows,
        columns,
        caption="Underlyings by the FLEX share of their option open interest.",
        label="tab:hidden",
        notes=_notes(macros, marked),
    )


def _resting_on_the_index_rule(values: Mapping[str, Any]) -> dict[str, list[str]]:
    """Per threshold, the index products counted that miss it with expiring series in."""
    whole = values["index_full_book"]
    marked: dict[str, list[str]] = {}
    for key, stable in values["daily"]["stable"].items():
        threshold = int(key) / 100
        names = [s for s in stable["symbols"] if s in whole and whole[s]["min"] < threshold]
        if names:
            marked[key] = names
    return marked


def _notes(macros: Mapping[str, str], marked: Mapping[str, list[str]]) -> str:
    notes = (
        "Census: OCC's series search for each of the "
        f"{macros['HiddenCensusSymbols']} symbols with listed weekly options, on the "
        f"settlement of {macros['HiddenCensusDate']}. On every date: the "
        f"{macros['HiddenDailyComplete']} underlyings on the collector's list, chosen mostly "
        "for the option-income programmes written on them, that are observed on all "
        f"{macros['HiddenDailyDates']} settlements captured from {macros['HiddenDailyFirst']} "
        f"to {macros['HiddenDailyLast']}, of the {macros['HiddenDailySpan']} in that span; a "
        "count is of underlyings at or above the share on each of them, the median is the "
        "median underlying's median over the dates, and the last row is the range over the "
        f"dates for the {macros['HiddenDailySearch']} names in the series search. "
        "Adjusted-deliverable classes are left out of both columns."
    )
    for key, names in marked.items():
        for name in names:
            notes += (
                f" {DAGGER}{name}, counting only series that expire after each date; with "
                f"the series expiring on a date counted too, its lowest share is "
                f"{macros[f'Hidden{name.title()}FullLow']} "
                f"({macros[f'Hidden{name.title()}FullLowDate']}), below {key}\\%."
            )
    return notes
