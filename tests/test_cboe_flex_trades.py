"""Tests for the collector of Cboe's daily FLEX execution reports."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from hidden_options.collect.cboe_flex_trades import (
    EXECUTION_COLUMNS,
    TradeReportError,
    backfill,
    parse_executions,
    report_url,
    snapshot_path,
)

HEADER = [
    "transact_time",
    "price",
    "size",
    "osi_root",
    "expire_date",
    "call_put_flag",
    "strike_price",
    "spread",
]
# Excel serials: 46317 is 2026-10-22, 46374 is 2026-12-18.
ROWS = [
    ["46317.369587615", "752.33", "52", "2SPY", "46374", "C", "10.01", "Y"],
    ["46317.369587615", "0.01", "52", "2SPY", "46374", "P", "10.01", "Y"],
    ["46317.5", "2.17", "800", "1DVN", "46346", "C", "50.01", "N"],
    ["46317.41013584546", "766", "5000", None, "46317", None, "0", "Y"],  # a stock leg
]


def workbook(header, rows) -> bytes:
    """A minimal .xlsx: shared strings for text, plain values for numbers."""
    strings: list[str] = []

    def cell(column: int, row: int, value) -> str:
        ref = f"{chr(ord('A') + column)}{row}"
        if value is None:
            return ""
        try:
            float(value)
        except ValueError:
            if value not in strings:
                strings.append(value)
            return f'<c r="{ref}" t="s"><v>{strings.index(value)}</v></c>'
        return f'<c r="{ref}"><v>{value}</v></c>'

    lines = []
    for number, row in enumerate([header, *rows], start=1):
        cells = "".join(cell(place, number, value) for place, value in enumerate(row))
        lines.append(f'<row r="{number}">{cells}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sheet = f"<worksheet {ns}><sheetData>{''.join(lines)}</sheetData></worksheet>"
    shared = f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/sharedStrings.xml", shared)
    return buffer.getvalue()


class TestParse:
    def test_rows_become_typed_executions(self):
        frame = parse_executions(workbook(HEADER, ROWS))
        assert list(frame.columns) == list(EXECUTION_COLUMNS)
        first = frame.iloc[0]
        assert first["trade_date"] == pd.Timestamp("2026-10-22")
        assert first["time"].floor("min") == pd.Timestamp("2026-10-22 08:52")
        assert first["expiry"] == pd.Timestamp("2026-12-18")
        assert (first["root"], first["right"]) == ("2SPY", "C")
        assert first["price"] == pytest.approx(752.33)
        assert first["size"] == 52
        assert first["strike"] == pytest.approx(10.01)
        assert bool(first["spread"]) is True
        assert bool(frame.iloc[2]["spread"]) is False

    def test_a_stock_leg_has_no_root_or_right(self):
        frame = parse_executions(workbook(HEADER, ROWS))
        stock = frame.iloc[3]
        assert pd.isna(stock["root"]) and pd.isna(stock["right"])
        assert stock["size"] == 5000

    def test_a_missing_column_is_an_error(self):
        with pytest.raises(TradeReportError, match="strike_price"):
            parse_executions(workbook(HEADER[:6] + ["spread"], [r[:6] + r[7:] for r in ROWS]))

    def test_an_empty_report_is_an_error(self):
        with pytest.raises(TradeReportError, match="no executions"):
            parse_executions(workbook(HEADER, []))

    def test_bytes_that_are_not_a_workbook_are_an_error(self):
        with pytest.raises(TradeReportError, match="workbook"):
            parse_executions(b"<?xml version='1.0'?><Error>AccessDenied</Error>")


class TestPaths:
    def test_url_and_snapshot_path_carry_the_date(self):
        day = date(2026, 10, 22)
        assert report_url(day).endswith("cone_options_rpt_flex_executions_late_20261022.xlsx")
        assert snapshot_path(day) == "cboe_flex_trades/date=2026-10-22/executions.parquet"


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content
        self.ok = status_code == 200


class FakeSession:
    def __init__(self, answers):
        self.answers = answers
        self.asked: list[str] = []

    def get(self, url, timeout=None):
        self.asked.append(url)
        return self.answers[url]


class TestBackfill:
    def test_weekdays_are_fetched_once_and_absent_days_recorded(self, tmp_path, monkeypatch):
        monkeypatch.setattr("hidden_options.collect.cboe_flex_trades.time.sleep", lambda _: None)
        blank, held, missing = date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)
        session = FakeSession(
            {
                report_url(blank): FakeResponse(200, workbook(HEADER, [])),
                report_url(held): FakeResponse(200, workbook(HEADER, ROWS)),
                report_url(missing): FakeResponse(403),
            }
        )
        summary = backfill(blank, date(2026, 10, 25), tmp_path, session=session)
        assert summary == {"written": 1, "absent": 1, "empty": 1, "held": 0, "failed": 0}
        stored = pd.read_parquet(tmp_path / snapshot_path(held))
        assert len(stored) == 4
        assert len(session.asked) == 3  # the weekend is not asked for

        again = backfill(blank, date(2026, 10, 25), tmp_path, session=session)
        assert again == {"written": 0, "absent": 1, "empty": 1, "held": 1, "failed": 0}
