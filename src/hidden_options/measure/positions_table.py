"""Paper table `positions`: the structure detector against disclosed fund holdings.

One row for the score as frozen, one for the same detector against the report of a file's
own date, and one per structure type. Each row states its denominators, since the score
rests on few funds.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "positions"
TYPE_LABELS = {
    "synthetic": "Synthetic (call and put, one strike)",
    "risk_reversal": "Risk reversal",
    "vertical_spread": "Vertical spread",
    "butterfly": "Three legs, evenly spaced",
    "three_leg": "Three legs",
    "collar_buffer": "Two calls and two puts",
}


@TABLES.register(RESULT)
def validation_table(results: Mapping[str, Result]) -> str:
    """Recall and precision with their denominators, overall and by type."""
    values = _values(results)["validation"]
    rows: list[dict[str, Any]] = [
        _overall("Report before the file's date", values["score"]),
        _overall("Report of the file's date", values["same_day"]),
        _blank("\\textit{By structure type}"),
    ]
    rows.extend(_by_type(name, stats) for name, stats in _ordered(values["by_type"]))
    columns = [
        Column("label", "", "{}", "l"),
        Column("truth", "Held", "{}"),
        Column("grouped", "Grouped", "{}"),
        Column("recall", "Recall", "{}"),
        Column("touching", "Touching", "{}"),
        Column("precision", "Precision", "{}"),
    ]
    notes = (
        "Held counts distinct structures, a fund's FLEX legs of one underlying and expiry "
        "with the same set of legs, each averaged over its dates. Grouped is the share whose "
        "legs all lie in one detected structure; recall requires that structure's type to be "
        "the type of the fund's legs. Touching counts distinct detected structures with a "
        "leg some fund holds, and precision is the share with two or more legs held by one "
        "fund. Types are those of the fund's legs for the first three columns and of the "
        "detected structure for the last two. A dash marks a type with nothing to score. A "
        "match says a structure is consistent with a disclosed holder, not that it is the "
        "holder's position."
    )
    return render_table(
        rows,
        columns,
        caption="Detected structures against disclosed fund holdings.",
        label="tab:positions",
        notes=notes,
    )


def _values(results: Mapping[str, Result]) -> Mapping[str, Any]:
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    return results[RESULT].values


def _ordered(by_type: Mapping[str, Any]) -> list[tuple[str, Any]]:
    named = [(name, by_type[name]) for name in TYPE_LABELS if name in by_type]
    rest = [(name, by_type[name]) for name in sorted(by_type) if name not in TYPE_LABELS]
    return named + rest


def _share(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:.1f}\\%"


def _overall(label: str, score: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": label,
        "truth": f"{score['n_truth_structures']:,}",
        "grouped": _share(score["recall_grouped"]),
        "recall": _share(score["recall"]),
        "touching": f"{score['n_detected_touching']:,}",
        "precision": _share(score["precision"]),
    }


def _blank(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "truth": "",
        "grouped": "",
        "recall": "",
        "touching": "",
        "precision": "",
    }


def _by_type(name: str, stats: Mapping[str, Any]) -> dict[str, Any]:
    label = TYPE_LABELS.get(name, name.replace("_leg", " legs"))
    return {
        "label": label,
        "truth": f"{stats['truth']:,}",
        "grouped": _share(stats["recall_grouped"]),
        "recall": _share(stats["recall"]),
        "touching": f"{stats['touching']:,}",
        "precision": _share(stats["precision"]),
    }
