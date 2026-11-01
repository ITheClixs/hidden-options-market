"""A small world for the `positions` result: three report dates, spots, holdings, one call
that a fund holds as a synthetic, and the two worked cases.

AAA is a synthetic (call and put at 50, 1000 contracts each) beside a lone put. A fund holds
the synthetic in full, another fund holds BBB's two legs at sizes the report does not pair,
so one structure is recovered and one is not. A third fund's file is long out of date.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hidden_options.measure.implied import DTE_LABELS, MONEYNESS_LABELS
from hidden_options.measure.positions_data import PositionsInputs
from hidden_options.measure.pricing import black_scholes

D0, D1, D2 = pd.Timestamp("2026-09-14"), pd.Timestamp("2026-09-15"), pd.Timestamp("2026-09-16")
AFTER_END = pd.Timestamp("2026-10-23")
EXPIRY = pd.Timestamp("2026-11-20")
RATE = 0.04
SIGMA = 0.3
SPOT = {"AAA": 50.0, "BBB": 20.0, "MSFT": 550.0, "SPY": 765.0, "SPX": 5000.0}
DOMAIN = frozenset((m, d) for m in MONEYNESS_LABELS for d in DTE_LABELS)


def mark(underlying, right, strike, expiry, day):
    args = [
        np.array([value], dtype=float)
        for value in (SPOT[underlying], strike, (expiry - day).days / 365, SIGMA)
    ]
    return float(black_scholes(*args, rate=RATE, carry=0.0, is_call=right == "C")[0])


def _row(day, underlying, right, strike, oi, *, expiry=EXPIRY, kind="equity", prefix="2"):
    return {
        "report_date": day,
        "kind": kind,
        "class_name": f"{underlying} (EURO/FLEX)",
        "root": f"{prefix}{underlying}",
        "underlying": underlying,
        "right": right,
        "expiry": expiry,
        "strike": strike,
        "mark_price": mark(underlying, right, strike, expiry, day),
        "open_interest": oi,
        "exercise_style": "european",
    }


BUTTERFLY_EXPIRIES = tuple(pd.Timestamp(day) for day in ("2026-11-20", "2026-12-17", "2027-01-14"))
BUTTERFLY_LINES = ((510.0, 100_000), (550.0, 200_000), (590.0, 100_000))
COLLAR_EXPIRY = pd.Timestamp("2026-12-31")
COLLAR_LINES = (
    ("C", 1.87, 37_507),
    ("C", 765.66, 37_507),
    ("P", 746.77, 38_317),
    ("P", 597.42, 37_540),
)


def rows_of(day):
    rows = [
        _row(day, "AAA", "C", 50.0, 1000),
        _row(day, "AAA", "P", 50.0, 1000),
        _row(day, "AAA", "P", 40.0, 3000),
        _row(day, "BBB", "C", 20.0, 9000),
        _row(day, "BBB", "P", 20.0, 700),
        _row(day, "SPX", "C", 5000.0, 900, kind="index", prefix="4"),
    ]
    rows += [
        _row(day, "MSFT", "C", strike, oi, expiry=expiry, prefix="1")
        for expiry in BUTTERFLY_EXPIRIES
        for strike, oi in BUTTERFLY_LINES
    ]
    rows += [
        _row(day, "SPY", right, strike, oi, expiry=COLLAR_EXPIRY, prefix="4")
        for right, strike, oi in COLLAR_LINES
    ]
    return pd.DataFrame(rows)


def read_day(day):
    if day > D2:
        raise AssertionError(f"Read a report past the panel end: {day}")
    return rows_of(day)


def spots():
    return pd.DataFrame(
        [
            {"date": day, "underlying": name, "spot": level, "source": "bars"}
            for day in (D0, D1, D2)
            for name, level in SPOT.items()
        ]
    )


def _holding(fund, as_of, root, right, strike, contracts, captured=None):
    return {
        "fund": fund,
        "as_of": as_of,
        "capture_date": as_of if captured is None else captured,
        "option_root": root,
        "expiry": EXPIRY,
        "right": right,
        "strike": strike,
        "contracts": contracts,
    }


def holdings():
    rows = []
    for as_of in (D1, D2):
        rows += [
            _holding("AAAY", as_of, "2AAA", "C", 50.0, 900.0),
            _holding("AAAY", as_of, "2AAA", "P", 50.0, -900.0),
            _holding("BBBY", as_of, "2BBB", "C", 20.0, 700.0),
            _holding("BBBY", as_of, "2BBB", "P", 20.0, -700.0),
        ]
    rows += [
        _holding("OLDY", pd.Timestamp("2026-03-02"), "2AAA", "C", 50.0, 10.0, captured=D2),
        _holding("LATE", AFTER_END, "2AAA", "C", 50.0, 10.0),
    ]
    return pd.DataFrame(rows)


def globalx():
    return pd.DataFrame(
        {
            "fund": ["XYLD", "XYLD"],
            "as_of": [D1, AFTER_END],
            "underlying": ["SPX", "SPX"],
            "expiry": [EXPIRY, EXPIRY],
            "right": ["C", "C"],
            "strike": [5000.0, 6000.0],
            "contracts": [-5.0, -5.0],
        }
    )


def inputs(**overrides):
    fields = {
        "dates": [D0, D1, D2, AFTER_END],
        "read_day": read_day,
        "spots": spots(),
        "holdings": holdings(),
        "globalx": globalx(),
        "domain": DOMAIN,
        "ci_runs": ["2026-09-16"],
    }
    return PositionsInputs(**{**fields, **overrides})
