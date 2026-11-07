"""Paper table `hidden_gamma`: FLEX share of option gamma under each attribution rule.

Cells are the result's own macro strings, so the table reads exactly as the text quotes.
"""

from __future__ import annotations

from collections.abc import Mapping

from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "hidden_gamma"
RULES = (
    ("Gross", "Gross"),
    ("Netted", "FLEX pairs netted"),
    ("Both", "Both sides netted"),
)


@TABLES.register(RESULT)
def hidden_gamma_table(results: Mapping[str, Result]) -> str:
    """The FLEX share of total dollar gamma, across underlyings and in the index products."""
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    m = results[RESULT].macros
    rows = [
        {
            "label": label,
            "median": m[f"GammaMedian{word}"],
            "iqr": f"{m[f'GammaLow{word}']}--{m[f'GammaHigh{word}']}",
            "ten": m[f"GammaAtLeastTen{word}"],
            "pooled": m[f"GammaPooled{word}"],
            "spx": m.get(f"GammaSPX{word}"),
            "spy": m.get(f"GammaSPY{word}"),
            "ndx": m.get(f"GammaNDX{word}"),
        }
        for word, label in RULES
    ]
    columns = [
        Column("label", "FLEX attribution", "{}", "l"),
        Column("median", "Median", "{}"),
        Column("iqr", "Interquartile", "{}"),
        Column("ten", "$\\geq$10\\%", "{}"),
        Column("pooled", "Pooled", "{}"),
        Column("spx", "SPX", "{}"),
        Column("spy", "SPY", "{}"),
        Column("ndx", "NDX", "{}"),
    ]
    return render_table(
        rows,
        columns,
        caption="FLEX share of option dollar gamma, by attribution rule.",
        label="tab:gamma",
        notes=_notes(m),
    )


def _notes(m: Mapping[str, str]) -> str:
    return (
        f"Dollar gamma, the change in dollar delta for a 1\\% move, of every live listed and "
        f"FLEX series on {m['GammaSettlements']} settlements from {m['GammaStart']} to "
        f"{m['GammaEnd']}, for the {m['GammaUnderlyings']} underlyings with stored chains. "
        "Both sides are priced on the listed implied-volatility surface of the same "
        "session. The share is FLEX over FLEX plus listed. Gross counts every contract. "
        "FLEX pairs netted counts at each strike only the excess of call over put open "
        "interest or the reverse on the FLEX side, against gross listed gamma; both sides "
        "netted applies the same rule to the listed side too. Median and "
        "interquartile range are across underlyings of each one's median over "
        "settlements; $\\geq$10\\% counts underlyings whose median share is at least 10\\%; "
        "pooled sums gamma over all underlyings and settlements before dividing; the last "
        "three columns are those products' medians over settlements."
    )


__all__ = ["hidden_gamma_table"]
