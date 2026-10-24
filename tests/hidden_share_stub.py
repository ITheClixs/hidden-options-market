"""A small, internally consistent world for the hidden-share result tests.

Activity dates run from Monday 31 August to Friday 4 September 2026. Four followed
underlyings: AAA (FLEX over half of its market), BBB (about a fortieth), CCC
(FLEX on one date only) and the SPX index (listed SPX and SPXW, FLEX 2SPX and 4SPX).
AAA also has an adjusted-deliverable class, AAA1 with FLEX 1AAA1. The census adds DDD,
which has no chain, and EEE, which has only an adjusted class.

Listed open interest moves by one contract a day, so every settlement is told apart. A
chain is read at 16:15 New York time each day: its quotes are that day's and its open
interest the previous settlement's. The local root holds the series search for 1 and 3
September (the last twice) and every chain but the one read on 3 September. Two CI roots
fill the gap: one holds the search for 2 September and that missing chain, the other
holds 3 September again, which must agree with the local capture.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DAYS = pd.bdate_range("2026-08-31", "2026-09-04")
EXPIRY = pd.Timestamp("2026-10-16")
STRIKES = (100.0, 110.0)
CAPTURED = pd.bdate_range("2026-09-01", "2026-09-04")
SETTLEMENTS = DAYS[1:4]  # 1, 2 and 3 September: the ones a daily capture shows
CENSUS_DATE = DAYS[1]
UNIVERSE = {"AAA": "programme", "BBB": "control", "CCC": "programme", "SPX": "programme"}
LISTED_ROOTS = {"AAA": ("AAA", "AAA1"), "BBB": ("BBB",), "CCC": ("CCC",), "SPX": ("SPX", "SPXW")}
MID, MARK, SPOT = 1.1, 2.0, 105.0
CI_ONLY_CHAIN = pd.Timestamp("2026-09-03")


def listed_oi(root: str, day: pd.Timestamp, strike: float, right: str) -> int:
    base = {"AAA": 400, "AAA1": 50, "BBB": 1900, "CCC": 700, "SPX": 3000, "SPXW": 4000}[root]
    return base + int(strike) + (5 if right == "P" else 0) + DAYS.get_loc(day)


def flex_oi(root: str, day: pd.Timestamp) -> int:
    """FLEX open interest of one series (strike 100, call) of `root` on `day`."""
    if root == "3CCC":
        return 300 if day == DAYS[2] else 0
    return {"2AAA": 2500, "1AAA1": 60, "1BBB": 210, "4DDD": 90, "2SPX": 9000, "4SPX": 6000}[root]


FLEX_ROOTS = {"equity": ("2AAA", "1AAA1", "1BBB", "3CCC", "4DDD"), "index": ("2SPX", "4SPX")}


def report(day: pd.Timestamp, kind: str) -> pd.DataFrame:
    rows = [
        {
            "report_date": day.date(),
            "kind": kind,
            "class_name": root,
            "root": root,
            "underlying": root.lstrip("0123456789"),
            "right": "C",
            "expiry": EXPIRY.date(),
            "strike": 100.0,
            "mark_price": MARK,
            "open_interest": flex_oi(root, day),
        }
        for root in FLEX_ROOTS[kind]
        if flex_oi(root, day) > 0
    ]
    if kind == "index":  # a mini product, which must stay out of the followed indices
        rows.append({**rows[0], "root": "4XSP", "underlying": "XSP", "open_interest": 5000})
    return pd.DataFrame(rows)


def series_search(symbol: str, day: pd.Timestamp) -> pd.DataFrame:
    rows = [
        _search_row(
            symbol,
            root,
            strike,
            listed_oi(root, day, strike, "C"),
            listed_oi(root, day, strike, "P"),
        )
        for root in LISTED_ROOTS[symbol]
        for strike in STRIKES
    ]
    for root in FLEX_ROOTS["equity"]:
        if root.lstrip("0123456789").rstrip("0123456789") == symbol and flex_oi(root, day) > 0:
            rows.append(_search_row(symbol, root, 100.0, flex_oi(root, day), 0))
    return pd.DataFrame(rows)


def _search_row(symbol: str, product: str, strike: float, calls: int, puts: int) -> dict:
    return {
        "symbol": symbol,
        "product_symbol": product,
        "expiry": EXPIRY.date(),
        "strike": strike,
        "call_open_interest": calls,
        "put_open_interest": puts,
        "position_limit": 25_000_000,
    }


def census_frames() -> dict[str, pd.DataFrame]:
    frames = {symbol: series_search(symbol, CENSUS_DATE) for symbol in ("AAA", "BBB", "CCC")}
    frames["DDD"] = pd.DataFrame(
        [
            _search_row("DDD", "DDD", 100.0, 900, 10),
            _search_row("DDD", "4DDD", 100.0, flex_oi("4DDD", CENSUS_DATE), 0),
        ]
    )
    frames["EEE"] = pd.DataFrame([_search_row("EEE", "EEE1", 100.0, 40, 0)])
    return frames


def chain(symbol: str, captured: pd.Timestamp) -> pd.DataFrame:
    """The chain read at 16:15 New York time on `captured`."""
    settlement = DAYS[DAYS.get_loc(captured) - 1]
    rows = []
    for root in LISTED_ROOTS[symbol]:
        for strike in STRIKES:
            for right in ("C", "P"):
                rows.append(
                    {
                        "symbol": f"_{symbol}" if symbol == "SPX" else symbol,
                        "quote_timestamp": f"{captured:%Y-%m-%d} 20:15:00",
                        "underlying_price": SPOT,
                        "contract": f"{root}{EXPIRY:%y%m%d}{right}{int(strike * 1000):08d}",
                        "expiry": EXPIRY.date(),
                        "right": right,
                        "strike": strike,
                        "bid": MID - 0.1,
                        "ask": MID + 0.1,
                        "theo": MID,
                        "open_interest": float(listed_oi(root, settlement, strike, right)),
                    }
                )
    return pd.DataFrame(rows)


def write_world(raw: Path, ci: Path | None = None) -> None:
    """Write the world under `raw`, and its CI captures under `ci` if given."""
    for day in DAYS:
        for kind in ("equity", "index"):
            _write(raw / f"occ_flex/date={day:%Y-%m-%d}/{kind}.parquet", report(day, kind))
    for symbol, frame in census_frames().items():
        _write(raw / f"occ_census/{symbol}.parquet", frame)
    local = [SETTLEMENTS[0], SETTLEMENTS[2], SETTLEMENTS[2]]
    folders = [day + pd.offsets.BDay(1) for day in local[:2]] + [local[2] + pd.Timedelta(days=2)]
    for folder, day in zip(folders, local, strict=True):
        _write_search(raw, folder, day)
    for captured in CAPTURED:
        root = raw if captured != CI_ONLY_CHAIN or ci is None else ci / "2026-09-03" / "raw"
        _write_chains(root, captured)
    if ci is not None:
        _write_search(ci / "2026-09-03" / "raw", pd.Timestamp("2026-09-03"), SETTLEMENTS[1])
        _write_search(ci / "2026-09-05" / "raw", pd.Timestamp("2026-09-05"), SETTLEMENTS[2])


def _write_search(root: Path, folder: pd.Timestamp, day: pd.Timestamp) -> None:
    for symbol in ("AAA", "BBB", "CCC"):
        path = root / f"occ_open_interest/date={folder:%Y-%m-%d}/{symbol}.parquet"
        _write(path, series_search(symbol, day))


def _write_chains(root: Path, captured: pd.Timestamp) -> None:
    for symbol in UNIVERSE:
        kind = "index" if symbol == "SPX" else "equity"
        path = root / f"cboe_chain/date={captured:%Y-%m-%d}/{kind}_{symbol}.parquet"
        _write(path, chain(symbol, captured))


def _write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
