"""A census small enough to score the strike rule on by hand.

Two underlyings on the settlement of 14 August 2026. Each row says what the rule should
make of it: nine series are scored (two FLEX found, three missed, one listed series
flagged, three passed), two hold nothing open and two belong to an adjusted class.
"""

from __future__ import annotations

import pandas as pd

from hidden_options.measure.hidden_share_data import CaptureDate

CENSUS_DATE = pd.Timestamp("2026-08-14")
COLUMNS = (
    "symbol",
    "product_symbol",
    "expiry",
    "strike",
    "call_open_interest",
    "put_open_interest",
    "position_limit",
)
ROWS = (
    ("AAA", "AAA", "2026-09-18", 100.00, 10, 5),  # listed, whole dollar: passed
    ("AAA", "AAA", "2026-09-18", 102.50, 3, 0),  # listed, half: passed
    ("AAA", "AAA", "2026-09-18", 105.25, 0, 0),  # listed, nothing open: left out
    ("AAA", "AAA", "2026-09-18", 33.33, 4, 4),  # listed, adjusted strike: flagged
    ("AAA", "2AAA", "2026-09-18", 100.00, 500, 0),  # FLEX on the listed strike: missed
    ("AAA", "2AAA", "2026-10-16", 101.37, 200, 200),  # FLEX off the grid: found
    ("AAA", "2AAA", "2026-10-16", 97.75, 0, 40),  # FLEX on a quarter: missed
    ("AAA", "AAA1", "2026-09-18", 10.00, 6, 0),  # adjusted class: left out
    ("AAA", "1AAA1", "2026-09-18", 10.13, 60, 0),  # adjusted FLEX class: left out
    ("BBB", "BBB", "2026-09-18", 50.00, 7, 7),  # listed, whole dollar: passed
    ("BBB", "1BBB", "2026-09-18", 50.01, 0, 0),  # FLEX, nothing open: left out
    ("BBB", "1BBB", "2026-12-18", 55.00, 1000, 1000),  # FLEX, whole dollar: missed
    ("BBB", "4BBB", "2026-12-18", 60.42, 300, 0),  # FLEX off the grid: found
)
DATED = CaptureDate(CENSUS_DATE, support=2, compared=2)


def census(rows: tuple[tuple[object, ...], ...] = ROWS) -> pd.DataFrame:
    """The census rows in the series search's columns."""
    return pd.DataFrame([(*row, 25_000_000) for row in rows], columns=list(COLUMNS))
