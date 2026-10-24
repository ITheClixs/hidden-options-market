"""Tests for reading the hidden-share inputs and dating each capture."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hidden_options.measure import hidden_share_data as data
from hidden_options.measure.hidden_share_data import (
    chain_dates,
    chain_open_interest,
    date_capture,
    date_captures,
    index_rows,
    load_captures,
    load_census,
    load_chains,
    load_reports,
    priced_chains,
    trading_calendar,
)

CALENDAR = pd.DatetimeIndex(
    ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08"]
)


class TestChainDates:
    @pytest.mark.parametrize(
        ("utc", "oi_date", "session"),
        [
            # 16:15 in New York, after the close: that day's quotes, the previous settlement.
            ("2026-09-02 20:15:00", "2026-09-01", "2026-09-02"),
            # Mid-session: the session is under way, open interest is still the previous one.
            ("2026-09-02 14:36:00", "2026-09-01", "2026-09-02"),
            # 22:06 in New York is still the same calendar day there.
            ("2026-09-03 02:06:00", "2026-09-01", "2026-09-02"),
            # Before the open: the last session was the day before.
            ("2026-09-03 12:00:00", "2026-09-02", "2026-09-02"),
            # Labor Day night: Friday's quotes, and Friday's settlement already processed.
            ("2026-09-08 03:55:00", "2026-09-04", "2026-09-04"),
        ],
    )
    def test_dates(self, utc, oi_date, session):
        dates = chain_dates(pd.Series([utc]), CALENDAR)
        assert dates.iloc[0]["oi_date"] == pd.Timestamp(oi_date)
        assert dates.iloc[0]["session"] == pd.Timestamp(session)

    def test_a_timestamp_before_the_calendar_is_refused(self):
        with pytest.raises(ValueError, match="calendar"):
            chain_dates(pd.Series(["2026-08-31 20:00:00"]), CALENDAR)


def chain_frame(rows):
    """rows: (key, quote_timestamp, root, expiry, right, oi, bid, ask)"""
    return pd.DataFrame(
        [
            {
                "symbol": key,
                "quote_timestamp": pd.Timestamp(ts, tz="UTC"),
                "contract": f"{root}C",
                "root": root,
                "expiry": pd.Timestamp(e),
                "right": r,
                "strike": 100.0,
                "bid": bid,
                "ask": ask,
                "theo": 1.0,
                "open_interest": oi,
                **chain_dates(pd.Series([ts]), CALENDAR).iloc[0].to_dict(),
            }
            for key, ts, root, e, r, oi, bid, ask in rows
        ]
    )


class TestChainOpenInterest:
    def test_latest_capture_of_a_settlement_wins(self):
        chains = chain_frame(
            [
                ("SPY", "2026-09-02 20:15:00", "SPY", "2026-09-18", "C", 10, 1.0, 1.2),
                ("SPY", "2026-09-03 02:06:00", "SPY", "2026-09-18", "C", 11, 1.0, 1.2),
            ]
        )
        oi = chain_open_interest(chains)

        assert len(oi) == 1
        assert oi.iloc[0]["open_interest"] == 11
        assert oi.iloc[0]["date"] == pd.Timestamp("2026-09-01")

    def test_priced_chains_take_quotes_from_the_session_of_the_settlement(self):
        chains = chain_frame(
            [
                # Quotes from 2 September, open interest of 1 September.
                ("SPY", "2026-09-02 20:15:00", "SPY", "2026-09-18", "C", 10, 2.0, 2.2),
                # Quotes from 3 September, open interest of 2 September.
                ("SPY", "2026-09-03 20:15:00", "SPY", "2026-09-18", "C", 12, 3.0, 3.2),
            ]
        )
        priced = priced_chains(chains).set_index("date")

        assert priced.loc[pd.Timestamp("2026-09-02"), "open_interest"] == 12
        assert priced.loc[pd.Timestamp("2026-09-02"), "bid"] == 2.0
        # 1 September's settlement has no quotes from its own session in the data.
        assert pd.isna(priced.loc[pd.Timestamp("2026-09-01"), "bid"])


def capture(rows, symbol="AAA"):
    """rows: (product, expiry, call_oi, put_oi)"""
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "product_symbol": p,
                "expiry": pd.Timestamp(e).date(),
                "strike": 100.0,
                "call_open_interest": c,
                "put_open_interest": put,
                "position_limit": 1,
            }
            for p, e, c, put in rows
        ]
    )


def chain_oi(rows):
    """rows: (date, symbol, expiry, right, oi)"""
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp(d),
                "symbol": s,
                "root": s,
                "expiry": pd.Timestamp(e),
                "right": r,
                "strike": 100.0,
                "open_interest": oi,
            }
            for d, s, e, r, oi in rows
        ]
    )


class TestDateCapture:
    CHAIN = chain_oi(
        [
            ("2026-09-01", "AAA", "2026-09-18", "C", 10),
            ("2026-09-01", "AAA", "2026-09-18", "P", 5),
            ("2026-09-02", "AAA", "2026-09-18", "C", 12),
            ("2026-09-02", "AAA", "2026-09-18", "P", 5),
            ("2026-09-01", "BBB", "2026-09-18", "C", 7),
            ("2026-09-02", "BBB", "2026-09-18", "C", 8),
        ]
    )

    def test_capture_takes_the_settlement_its_listed_open_interest_matches(self):
        frame = pd.concat(
            [
                capture([("AAA", "2026-09-18", 12, 5), ("2AAA", "2026-09-18", 99, 0)]),
                capture([("BBB", "2026-09-18", 8, 0)], symbol="BBB"),
            ]
        )
        dated = date_capture(frame, self.CHAIN)

        assert dated.date == pd.Timestamp("2026-09-02")
        assert (dated.support, dated.compared) == (2, 2)

    def test_an_ambiguous_capture_is_refused(self):
        chain = chain_oi(
            [
                ("2026-09-01", "AAA", "2026-09-18", "C", 10),
                ("2026-09-02", "AAA", "2026-09-18", "C", 10),
            ]
        )
        with pytest.raises(ValueError, match="ambiguous"):
            date_capture(capture([("AAA", "2026-09-18", 10, 0)]), chain)

    def test_a_capture_no_chain_matches_is_refused(self):
        with pytest.raises(ValueError, match="no chain"):
            date_capture(capture([("AAA", "2026-09-18", 1, 1)]), self.CHAIN)

    def test_captures_are_dated_and_duplicates_kept_once(self):
        first = capture([("AAA", "2026-09-18", 12, 5)]).assign(capture=pd.Timestamp("2026-09-03"))
        again = first.assign(capture=pd.Timestamp("2026-09-04"))
        earlier = capture([("AAA", "2026-09-18", 10, 5)]).assign(capture=pd.Timestamp("2026-09-02"))

        dated, log = date_captures(pd.concat([earlier, first, again]), self.CHAIN)

        assert sorted(dated["date"].unique()) == [
            pd.Timestamp("2026-09-01"),
            pd.Timestamp("2026-09-02"),
        ]
        assert len(dated) == 2
        assert list(log["date"]) == [
            pd.Timestamp("2026-09-01"),
            pd.Timestamp("2026-09-02"),
            pd.Timestamp("2026-09-02"),
        ]
        assert log["duplicate"].tolist() == [False, False, True]
        assert log["support"].tolist() == [1, 1, 1]

    def test_differing_captures_of_one_settlement_are_refused(self):
        first = capture([("AAA", "2026-09-18", 12, 5)]).assign(capture=pd.Timestamp("2026-09-03"))
        other = capture([("AAA", "2026-09-18", 12, 5), ("1AAA", "2026-09-18", 3, 0)]).assign(
            capture=pd.Timestamp("2026-09-04")
        )
        with pytest.raises(ValueError, match="differ"):
            date_captures(pd.concat([first, other]), self.CHAIN)


class TestIndexRows:
    def test_listed_and_flex_index_products_after_the_date(self):
        chain = chain_oi(
            [
                ("2026-09-01", "SPX", "2026-09-18", "C", 10),
                ("2026-09-01", "SPX", "2026-09-01", "C", 99),
            ]
        )
        chain.loc[len(chain)] = {
            "date": pd.Timestamp("2026-09-01"),
            "symbol": "SPX",
            "root": "SPXW",
            "expiry": pd.Timestamp("2026-09-18"),
            "right": "P",
            "strike": 100.0,
            "open_interest": 20,
        }
        reports = pd.DataFrame(
            {
                "report_date": pd.Timestamp("2026-09-01"),
                "kind": ["index", "index", "index", "equity"],
                "root": ["2SPX", "4SPX", "4XSP", "4SPY"],
                "underlying": ["SPX", "SPX", "XSP", "SPY"],
                "right": ["C", "P", "C", "C"],
                "expiry": pd.Timestamp("2026-09-18"),
                "strike": 100.0,
                "mark_price": 1.0,
                "open_interest": [3, 4, 500, 600],
            }
        )

        rows = index_rows(chain, reports)

        assert set(rows["symbol"]) == {"SPX"}
        assert set(rows["product_symbol"]) == {"SPX", "SPXW", "2SPX", "4SPX"}
        total = rows["call_open_interest"] + rows["put_open_interest"]
        assert total.sum() == 10 + 20 + 3 + 4

    def test_an_unknown_listed_index_root_is_refused(self):
        chain = chain_oi([("2026-09-01", "SPX", "2026-09-18", "C", 10)])
        chain["root"] = "SPXQ"
        with pytest.raises(KeyError, match="SPXQ"):
            index_rows(chain, pd.DataFrame(columns=data.REPORT_COLUMNS))


class TestLoaders:
    def write(self, path: Path, frame: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)

    def test_calendar_census_captures_reports_and_chains(self, tmp_path):
        for day in ("2026-09-01", "2026-09-02"):
            for kind in ("equity", "index"):
                report = pd.DataFrame(
                    {
                        "report_date": [day],
                        "kind": [kind],
                        "class_name": ["X"],
                        "root": ["1AAA" if kind == "equity" else "2SPX"],
                        "underlying": ["AAA" if kind == "equity" else "SPX"],
                        "right": ["C"],
                        "expiry": [pd.Timestamp("2026-09-18").date()],
                        "strike": [100.0],
                        "mark_price": [1.0],
                        "open_interest": [5],
                    }
                )
                self.write(tmp_path / f"occ_flex/date={day}/{kind}.parquet", report)
        oi = capture([("AAA", "2026-09-18", 1, 2)])
        self.write(tmp_path / "occ_census/AAA.parquet", oi)
        self.write(tmp_path / "occ_open_interest/date=2026-09-02/AAA.parquet", oi)
        chain = pd.DataFrame(
            {
                "symbol": ["_SPX"],
                "quote_timestamp": ["2026-09-02 20:15:00"],
                "contract": ["SPXW260918C00100000"],
                "expiry": [pd.Timestamp("2026-09-18").date()],
                "right": ["C"],
                "strike": [100.0],
                "bid": [1.0],
                "ask": [1.2],
                "theo": [1.1],
                "open_interest": [7.0],
            }
        )
        self.write(tmp_path / "cboe_chain/date=2026-09-02/index_SPX.parquet", chain)

        calendar = trading_calendar(tmp_path)
        assert list(calendar[:2]) == [pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02")]
        assert len(calendar) > 2  # weekdays after the last report, for later captures

        assert len(load_census(tmp_path)) == 1
        assert load_captures(tmp_path)["capture"].iloc[0] == pd.Timestamp("2026-09-02")

        reports = load_reports(tmp_path, pd.Timestamp("2026-09-02"))
        assert set(reports["kind"]) == {"equity", "index"}
        assert reports["report_date"].unique().tolist() == [pd.Timestamp("2026-09-02")]

        chains = load_chains(tmp_path, calendar)
        row = chains.iloc[0]
        assert (row["symbol"], row["root"], row["oi_date"]) == (
            "SPX",
            "SPXW",
            pd.Timestamp("2026-09-01"),
        )

    def test_missing_inputs_are_named(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="occ_flex"):
            trading_calendar(tmp_path)
        with pytest.raises(FileNotFoundError, match="occ_census"):
            load_census(tmp_path)
        with pytest.raises(FileNotFoundError, match="occ_open_interest"):
            load_captures(tmp_path)
        with pytest.raises(FileNotFoundError, match="cboe_chain"):
            load_chains(tmp_path, CALENDAR)
        with pytest.raises(FileNotFoundError, match="occ_flex"):
            load_reports(tmp_path, pd.Timestamp("2026-09-01"))

    def test_a_contract_that_is_not_osi_is_refused(self, tmp_path):
        chain = pd.DataFrame(
            {
                "symbol": ["SPY"],
                "quote_timestamp": ["2026-09-02 20:15:00"],
                "contract": ["SPY-SEP-100"],
                "expiry": [pd.Timestamp("2026-09-18").date()],
                "right": ["C"],
                "strike": [100.0],
                "bid": [1.0],
                "ask": [1.2],
                "theo": [1.1],
                "open_interest": [7.0],
            }
        )
        self.write(tmp_path / "cboe_chain/date=2026-09-02/equity_SPY.parquet", chain)
        with pytest.raises(ValueError, match="SPY-SEP-100"):
            load_chains(tmp_path, CALENDAR)
