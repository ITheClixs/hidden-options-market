"""Result `programme_book`: the programme test's sign assumption, checked against holdings.

A check added after the programme test was run (`measure.programme_book`). The inputs are
the fund holdings and the FLEX report, both frozen at PANEL_END as in the `positions`
result, and the programme names in the universe file.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.config import CI_CAPTURES_DIR, PANEL_END, RAW_DIR, load_universe
from hidden_options.measure.hidden_share_data import ci_roots, load_reports
from hidden_options.measure.holdings_truth import load_fund_holdings
from hidden_options.measure.positions_result import through
from hidden_options.measure.programme_book import fund_legs, programme_book
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "programme_book"


def programme_book_result(
    holdings: pd.DataFrame, reports: pd.DataFrame, names: frozenset[str]
) -> Result:
    values = {**fund_legs(holdings, names), **programme_book(holdings, reports, names)}
    dates = pd.to_datetime(holdings["as_of"])
    run_inputs = {
        "first_date": f"{dates.min():%Y-%m-%d}",
        "last_date": f"{dates.max():%Y-%m-%d}",
        "panel_end": f"{PANEL_END:%Y-%m-%d}",
    }
    return Result(NAME, values, programme_book_macros(values), run_inputs, now_iso())


def programme_book_macros(values: Mapping[str, Any]) -> dict[str, str]:
    return {
        "PBookWrittenFlex": formats.percent(values["written_call_flex_share"]),
        "PBookPutFlex": formats.percent(values["short_put_flex_share"]),
        "PBookPutsPaired": formats.percent(values["short_puts_paired"]),
        "PBookFunds": formats.count(values["funds"]),
        "PBookCaptureDates": formats.count(values["capture_dates"]),
        "PBookFundShare": formats.percent(values["fund_share"], 1),
        "PBookCallShare": formats.percent(values["netted_call_share"]),
        "PBookNames": formats.count(values["names"]),
        "PBookDates": formats.count(values["dates"]),
    }


@ANALYSES.register(NAME)
def programme_book_analysis() -> Result:
    end = pd.Timestamp(PANEL_END)
    holdings = through(load_fund_holdings([RAW_DIR, *ci_roots(CI_CAPTURES_DIR)]), end)
    dates = pd.to_datetime(holdings["as_of"])
    reports = load_reports(RAW_DIR, dates.min(), end)
    names = frozenset(load_universe().treated_single_name)
    return programme_book_result(holdings, reports, names)


__all__ = ["NAME", "programme_book_analysis", "programme_book_macros", "programme_book_result"]
