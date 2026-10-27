"""A small world for the implied-volatility result: FLEX rows, chain readings and bars.

Two report dates inside the chains' window, 1 and 2 September 2026, and one before it,
3 August, which only the full-panel style counts see. AAA closes at 100 on both dates,
CCC at 50 (but its chain shows 51, so its listed side is set aside), BBB has no bars.
SPX's chain reads 5000, so XSP is 500 by the fixed ratio; DJX has no spot at all.

Each FLEX row says what should become of it. Every mark is a model price at a known
volatility, so a matched row's gap is known before the result is computed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hidden_options.measure.pricing import binomial, black_scholes

D0, D1, D2 = pd.Timestamp("2026-08-03"), pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02")
RATE = 0.04
YEAR = pd.Timedelta(days=365)
MONTH = pd.Timedelta(days=30)
SPOT = {"AAA": 100.0, "CCC": 50.0, "SPX": 5000.0}


def mark(spot, strike, days, sigma, right, model="european"):
    args = [np.array([value], dtype=float) for value in (spot, strike, days / 365, sigma)]
    pricer = binomial if model == "american" else black_scholes
    return float(pricer(*args, rate=RATE, carry=0.0, is_call=right == "C")[0])


def _flex(date, kind, class_name, root, underlying, right, expiry, strike, price, oi, style):
    return {
        "report_date": date,
        "kind": kind,
        "class_name": class_name,
        "root": root,
        "underlying": underlying,
        "right": right,
        "expiry": expiry,
        "strike": strike,
        "mark_price": price,
        "open_interest": oi,
        "exercise_style": style,
    }


EURO, AMER, CLIPPED, PLAIN = "AAA INC (EURO/FLEX)", "AAA INC (AMER/FLEX)", "AAA INC (AME", "AAA INC"


def panel() -> pd.DataFrame:
    """The FLEX rows, in `load_panel`'s columns (less `available_at`, which nothing reads)."""
    y1, m1 = D1 + YEAR, D1 + MONTH
    rows = [
        # Matched rows: (listed iv on the twin in the comment).
        _flex(
            D1,
            "equity",
            EURO,
            "2AAA",
            "AAA",
            "C",
            y1,
            100.0,
            mark(100, 100, 365, 0.30, "C"),
            100,
            "european",
        ),  # listed 0.29
        _flex(
            D1,
            "equity",
            EURO,
            "2AAA",
            "AAA",
            "P",
            y1,
            100.0,
            mark(100, 100, 365, 0.32, "P"),
            200,
            "european",
        ),  # listed 0.35
        _flex(
            D1,
            "equity",
            CLIPPED,
            "1AAA",
            "AAA",
            "P",
            m1,
            90.0,
            mark(100, 90, 30, 0.40, "P", "american"),
            300,
            "american",
        ),  # listed 0.40
        # Unmarked, priced as a European put; its prefix 2 says European.
        _flex(
            D1,
            "equity",
            PLAIN,
            "2AAA",
            "AAA",
            "P",
            m1,
            110.0,
            mark(100, 110, 30, 0.35, "P"),
            400,
            None,
        ),  # listed 0.35
        _flex(
            D1,
            "index",
            "S&P 500 INDEX PM/EURO (FLEX)",
            "4SPX",
            "SPX",
            "C",
            D1 + 45 * pd.Timedelta(days=1),
            5000.0,
            mark(5000, 5000, 45, 0.20, "C"),
            10,
            "european",
        ),  # listed SPXW 0.19
        # Not matched.
        _flex(
            D1,
            "equity",
            EURO,
            "2AAA",
            "AAA",
            "C",
            y1,
            100.5,
            mark(100, 100.5, 365, 0.30, "C"),
            50,
            "european",
        ),  # off the listed strike
        _flex(
            D1,
            "equity",
            EURO,
            "2CCC",
            "CCC",
            "C",
            y1,
            50.0,
            mark(50, 50, 365, 0.30, "C"),
            60,
            "european",
        ),  # its chain disagrees with bars
        _flex(
            D1,
            "index",
            "CBOE MINI S&P 500 PM/EURO INDE",
            "4XSP",
            "XSP",
            "C",
            y1,
            500.0,
            mark(500, 500, 365, 0.20, "C"),
            70,
            "european",
        ),  # spot from SPX / 10
        # Statuses.
        _flex(D1, "equity", EURO, "2AAA", "AAA", "C", D1, 100.0, 1.0, 1, "european"),  # expired
        _flex(D1, "equity", EURO, "2AAA", "AAA", "C", y1, 120.0, 0.0, 1, "european"),  # zero
        _flex(D1, "equity", EURO, "2BBB", "BBB", "C", y1, 10.0, 1.0, 1, "european"),  # no spot
        _flex(
            D1,
            "index",
            "CBOE DOW JONES INDUSTRIAL (EUR",
            "2DJX",
            "DJX",
            "C",
            y1,
            400.0,
            5.0,
            1,
            "european",
        ),  # no spot
        _flex(D1, "equity", EURO, "2AAA", "AAA", "C", y1, 50.0, 45.0, 1, "european"),  # below
        _flex(D1, "equity", EURO, "2AAA", "AAA", "C", y1, 60.0, 150.0, 1, "european"),  # above
        # The second date: the first series again, its listed twin now at 0.30.
        _flex(
            D2,
            "equity",
            EURO,
            "2AAA",
            "AAA",
            "C",
            y1,
            100.0,
            mark(100, 100, 364, 0.30, "C"),
            100,
            "european",
        ),
        # Before the chains: only the full-panel style counts see these.
        _flex(D0, "equity", AMER, "1AAA", "AAA", "C", y1, 100.0, 5.0, 1, "american"),
        _flex(D0, "equity", PLAIN, "4AAA", "AAA", "C", y1, 100.0, 5.0, 1, None),
        _flex(D0, "equity", PLAIN, "1AAA", "AAA", "P", y1, 100.0, 5.0, 1, None),
        _flex(D0, "equity", PLAIN, "3AAA", "AAA", "P", y1, 100.0, 5.0, 1, None),
        # A heading that contradicts its prefix: American under a European digit.
        _flex(D0, "equity", AMER, "2AAA", "AAA", "C", y1, 100.0, 5.0, 1, "american"),
    ]
    frame = pd.DataFrame(rows)
    frame["exercise_style"] = frame["exercise_style"].astype(object)
    return frame


def _reading(symbol, stamp, session, price, rows):
    """Chain rows of one reading, in `load_chains`'s columns (iv read beside them)."""
    out = []
    for root, expiry, right, strike, iv in rows:
        contract = f"{root}{expiry:%y%m%d}{right}{round(strike * 1000):08d}"
        out.append(
            {
                "symbol": symbol,
                "quote_timestamp": pd.Timestamp(stamp, tz="UTC"),
                "underlying_price": price,
                "contract": contract,
                "expiry": expiry,
                "right": right,
                "strike": strike,
                "bid": 1.0,
                "ask": 1.1,
                "theo": 1.05,
                "open_interest": 10.0,
                "iv": iv,
                "root": root,
                "oi_date": session - pd.offsets.BDay(1),
                "session": session,
            }
        )
    return out


def chains() -> pd.DataFrame:
    y1, m1 = D1 + YEAR, D1 + MONTH
    aaa_d1 = [
        ("AAA", y1, "C", 100.0, 0.29),
        ("AAA", y1, "P", 100.0, 0.35),
        ("AAA", m1, "P", 90.0, 0.40),
        ("AAA", m1, "P", 110.0, 0.35),
        ("AAA", y1, "C", 50.0, 0.0),  # no iv: not a twin
        ("AAA1", y1, "C", 100.0, 0.5),  # adjusted class: not a twin
    ]
    rows = [
        # During the session, then 16:10 (before the delayed close), then the first reading
        # after it (20:15 UTC is 16:15 in New York), then a late one. The first after wins.
        *_reading("AAA", "2026-09-01 18:00", D1, 99.0, [("AAA", y1, "C", 100.0, 0.9)]),
        *_reading("AAA", "2026-09-01 20:10", D1, 99.5, [("AAA", y1, "C", 100.0, 0.8)]),
        *_reading("AAA", "2026-09-01 20:16", D1, 100.02, aaa_d1),
        *_reading("AAA", "2026-09-02 03:50", D1, 104.0, [("AAA", y1, "C", 100.0, 0.7)]),
        *_reading("AAA", "2026-09-02 20:20", D2, 100.0, [("AAA", y1, "C", 100.0, 0.30)]),
        *_reading("SPX", "2026-09-02 20:30", D2, 5010.0, [("SPX", y1, "C", 5000.0, 0.2)]),
        *_reading("CCC", "2026-09-01 20:16", D1, 51.0, [("CCC", y1, "C", 50.0, 0.31)]),
        *_reading(
            "SPX",
            "2026-09-01 20:30",
            D1,
            5000.0,
            [
                ("SPXW", D1 + 45 * pd.Timedelta(days=1), "C", 5000.0, 0.19),
                ("SPX", D1 + 45 * pd.Timedelta(days=1), "C", 5000.0, 0.25),
            ],
        ),
    ]
    return pd.DataFrame(rows)


def bars() -> pd.DataFrame:
    rows = [
        (symbol, pd.Timestamp(f"{day:%Y-%m-%d} 13:30", tz="UTC"), close)
        for day in (D0, D1, D2)
        for symbol, close in (("AAA", 100.0), ("CCC", 50.0))
    ]
    return pd.DataFrame(rows, columns=["symbol", "timestamp", "close"])
