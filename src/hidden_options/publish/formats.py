r"""Formatters for macro values, following the convention in the package docstring.

An analysis decides the rounding of every number it publishes, and it does so through
these, so the same kind of number reads the same way everywhere: `15,179,194`,
`35.2` (millions), `\$298bn`, `30\%`, `+1.5\%`, `2 December 2024`. A value that rounds to
zero prints without a sign, never as `-0.0`.
"""

from __future__ import annotations

import pandas as pd


def count(value: float) -> str:
    """A whole number with thousands separators: `15,179,194`."""
    return f"{round(value):,}"


def counted(value: float, noun: str, plural: str | None = None) -> str:
    """A count with its noun, which agrees in number: `1 underlying`, `15 underlyings`.

    The plural is the noun with an `s` unless given (`series`, `series`). A sentence that
    prints the macro then reads right whatever the count turns out to be.
    """
    many = f"{noun}s" if plural is None else plural
    return f"{count(value)} {noun if round(value) == 1 else many}"


def decimal(value: float, digits: int = 1) -> str:
    """A plain number at `digits` places: `2.1`, `-1.25`."""
    return f"{_unsigned_zero(value, digits):.{digits}f}"


def millions(value: float, digits: int = 1) -> str:
    """A count in millions, unit left to the text: 35,213,339 -> `35.2`."""
    return decimal(value / 1e6, digits)


def usd_billions(value: float) -> str:
    r"""Dollars in whole billions with the escaped sign: `\$298bn`."""
    return f"\\${round(value / 1e9):,}bn"


def percent(share: float, digits: int = 0) -> str:
    r"""A share as a percentage: 0.2971 -> `30\%`."""
    return f"{decimal(share * 100, digits)}\\%"


def signed_percent(share: float, digits: int = 1) -> str:
    r"""A change as a signed percentage: `+1.5\%`, `-10\%`. Zero takes the plus sign."""
    return f"{_unsigned_zero(share * 100, digits):+.{digits}f}\\%"


def long_date(day: pd.Timestamp) -> str:
    """A date as prose writes it: `2 December 2024`."""
    return f"{day.day} {day:%B %Y}"


def month_year(day: pd.Timestamp) -> str:
    """The month a date falls in: `December 2024`."""
    return f"{day:%B %Y}"


def iso_date(day: pd.Timestamp) -> str:
    """`2024-12-02`, the form result values store dates in."""
    return f"{day:%Y-%m-%d}"


def _unsigned_zero(value: float, digits: int) -> float:
    """`value` rounded, with a negative zero turned positive so it prints as `0.0`."""
    rounded = round(value, digits)
    return 0.0 if rounded == 0 else rounded
