"""Paper tables `implied` and `implied_domain`: FLEX mark volatilities against listed ones.

`implied` gives the gap by moneyness, by days to expiry and by how the exercise style was
read; `implied_domain` gives the median gap in each moneyness and maturity cell, with the
validated cells set in bold. Gaps print in vol points.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hidden_options.measure.implied import DTE_LABELS, MONEYNESS_LABELS
from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "implied_validation"
GROUP_LABELS = {
    "strict": "Heading, spelled out",
    "clipped": "Heading, clipped",
    "prefix": "Product prefix",
    "fallback": "Neither (as American)",
    "index": "Index (European)",
}


def latex_label(label: str) -> str:
    """A bucket label as the table sets it: `<0.70` -> `$<0.70$`, `8-30` -> `8--30`."""
    for plain, math in ((">=", "\\geq "), ("<=", "\\leq "), ("<", "<"), (">", ">")):
        if label.startswith(plain):
            return f"${math}{label[len(plain) :]}$"
    return label.replace("-", "--")


@TABLES.register("implied")
def validation_table(results: Mapping[str, Result]) -> str:
    """Matched series-days and their gaps, in three panels."""
    values = _values(results)["validation"]
    rows: list[dict[str, Any]] = []
    panels: Sequence[tuple[str, str, Mapping[str, str]]] = (
        ("Strike over spot", "by_moneyness", {m: latex_label(m) for m in MONEYNESS_LABELS}),
        ("Days to expiry", "by_dte", {d: latex_label(d) for d in DTE_LABELS}),
        ("Exercise style", "by_group", GROUP_LABELS),
    )
    for title, key, labels in panels:
        rows.append({"label": f"\\textit{{{title}}}", "n": "", "gap": "", "within": "", "bias": ""})
        rows.extend(_row(labels[name], values[key][name]) for name in labels)
    rows.append(_row("All", values["overall"]))
    columns = [
        Column("label", "", "{}", "l"),
        Column("n", "Matched", "{}"),
        Column("gap", "Median $|$gap$|$", "{}"),
        Column("within", "Within 2 pts", "{}"),
        Column("bias", "Median gap", "{}"),
    ]
    notes = (
        "A FLEX series-day is matched when the listed series of the same underlying, expiry, "
        "right, strike and settlement was read after the close the same day with an implied "
        "volatility. The gap is the volatility backed out of OCC's mark less Cboe's listed "
        "one, in vol points; within 2 pts is the share whose gap is at most two vol points."
    )
    return render_table(
        rows,
        columns,
        caption="Volatility backed out of OCC's marks against the listed chain.",
        label="tab:implied",
        notes=notes,
    )


@TABLES.register("implied_domain")
def domain_table(results: Mapping[str, Result]) -> str:
    """The median gap in each moneyness and maturity cell; validated cells in bold."""
    values = _values(results)
    cells = values["validation"]["by_bucket"]
    validated = {tuple(cell) for cell in values["domain"]["buckets"]}
    rows = []
    for m in MONEYNESS_LABELS:
        row: dict[str, Any] = {"label": latex_label(m)}
        for d in DTE_LABELS:
            row[d] = _cell(cells[f"{m}|{d}"], (m, d) in validated)
        rows.append(row)
    columns = [Column("label", "Strike over spot", "{}", "l")] + [
        Column(d, latex_label(d), "{}") for d in DTE_LABELS
    ]
    settings = values["settings"]
    notes = (
        "Median absolute gap between FLEX mark and listed implied volatility, in vol points, "
        "by strike over spot (rows) and days to expiry (columns). Bold cells are validated: a "
        f"median gap of at most {settings['max_median_diff'] * 100:.0f} vol points over at "
        f"least {settings['min_matched']} matched series-days. A dash marks a cell with no "
        "match."
    )
    return render_table(
        rows,
        columns,
        caption="Where the inversion agrees with the listed market.",
        label="tab:implied-domain",
        notes=notes,
    )


def _values(results: Mapping[str, Result]) -> Mapping[str, Any]:
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    return results[RESULT].values


def _row(label: str, stats: Mapping[str, Any]) -> dict[str, Any]:
    if not stats["n"]:
        return {"label": label, "n": "0", "gap": None, "within": None, "bias": None}
    return {
        "label": label,
        "n": f"{stats['n']:,}",
        "gap": f"{stats['median_abs'] * 100:.2f}",
        "within": f"{stats['within'] * 100:.1f}\\%",
        "bias": f"${stats['median_diff'] * 100:.2f}$",
    }


def _cell(stats: Mapping[str, Any], validated: bool) -> str | None:
    if not stats["n"]:
        return None
    text = f"{stats['median_abs'] * 100:.2f}"
    return f"\\textbf{{{text}}}" if validated else text
