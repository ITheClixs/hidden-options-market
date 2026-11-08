"""Paper table `pinning`: closeness to the largest FLEX strike on FLEX-only expiries."""

from __future__ import annotations

from collections.abc import Mapping

from hidden_options.publish.latex import Column, render_table
from hidden_options.publish.registry import TABLES
from hidden_options.publish.results import Result

RESULT = "pinning"
ROWS = (
    ("H1: expiry less the five sessions after", "PinMean", "PinT", "PinHolm", "$\\sigma$"),
    ("H2: top less bottom size tercile", "PinSizeDiff", "PinSizeT", "PinSizeHolm", "$\\sigma$"),
    ("Expiry alone", "PinExpiryOnlyMean", "PinExpiryOnlyT", None, "$\\sigma$"),
    ("Sessions after alone", "PinPseudoOnlyMean", "PinPseudoOnlyT", None, "$\\sigma$"),
    (
        "Within $0.25\\sigma$, expiry less after",
        "PinBandQuarterMean",
        "PinBandQuarterT",
        None,
        "pp",
    ),
    ("Within $0.5\\sigma$, expiry less after", "PinBandHalfMean", "PinBandHalfT", None, "pp"),
    ("Pin strike mostly calls", "PinCallsMean", "PinCallsT", None, "$\\sigma$"),
    ("Pin strike mostly puts", "PinPutsMean", "PinPutsT", None, "$\\sigma$"),
    ("Friday expiries, listed also expiring", "PinFridayMean", "PinFridayT", None, "$\\sigma$"),
)


@TABLES.register(RESULT)
def pinning_table(results: Mapping[str, Result]) -> str:
    """The tests of record, then the descriptive rows."""
    if RESULT not in results:
        raise KeyError(f"No {RESULT!r} result; run `hidden-options results --only {RESULT}`")
    m = results[RESULT].macros
    rows = [
        {
            "label": label,
            "value": m[value],
            "unit": unit,
            "t": m[t],
            "holm": m[holm] if holm else None,
        }
        for label, value, t, holm, unit in ROWS
    ]
    columns = [
        Column("label", "", "{}", "l"),
        Column("value", "Estimate", "{}"),
        Column("unit", "", "{}", "l"),
        Column("t", "$t$", "{}"),
        Column("holm", "Holm $p$", "{}"),
    ]
    return render_table(
        rows,
        columns,
        caption="Closing at the largest FLEX strike on FLEX-only expiries.",
        label="tab:pinning",
        notes=_notes(m),
    )


def _notes(m: Mapping[str, str]) -> str:
    return (
        f"{m['PinEvents']} events on {m['PinDates']} expiry dates in {m['PinUnderlyings']} "
        "underlyings: FLEX expiries on Monday to Thursday, in names that list no option "
        f"expiring that day ({m['PinExcluded']} names with listed weekday expiries are left "
        "out). The pin strike is the expiring FLEX strike with the most open interest, at "
        "least 100 contracts, within $2\\sigma$ of the previous close, $\\sigma$ being the "
        "standard deviation of daily log returns over the 60 sessions before. Closeness is "
        "distance to the strike's mirror about the previous close less distance to the "
        "strike, each in $\\sigma$ units and capped at 2; positive is nearer the strike. "
        "The sessions after are the five after expiry, with the strike held fixed. Banded "
        "rows difference the frequency of closing within the band of the strike and of its "
        "mirror, in percentage points. Errors are clustered by expiry date. H1 and H2 were "
        "fixed in advance with Holm's adjustment across them; the other rows are descriptive."
    )


__all__ = ["pinning_table"]
