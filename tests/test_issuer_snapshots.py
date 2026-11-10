"""Tests for the parsers of issuer holdings snapshots."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.collect.issuer_snapshots import (
    HOLDING_COLUMNS,
    SnapshotParseError,
    parse_box_fund_page,
    parse_family_file,
)

FAMILY = (
    b"Date,Account,StockTicker,CUSIP,SecurityName,Shares,Price,MarketValue,Weightings,"
    b"NetAssets,SharesOutstanding,CreationUnits,MoneyMarketFlag\n"
    b"11/10/2026,BJAN,4SPY  261231C00006830,x,SPY 12/31/2026 6.83 C,4623.0,743.4066,"
    b"343676871.18,98%,350000000.00,7000000,280,\n"
    b"11/10/2026,BJAN,4SPY  261231P00620560,x,SPY 12/31/2026 620.56 P,-4623.0,1.6658,"
    b"-770099.34,0%,350000000.00,7000000,280,\n"
    b"11/10/2026,BJAN,Cash&Other,x,Cash & Other,1000.0,1.0,1000.00,0%,350000000.00,"
    b"7000000,280,Y\n"
)
PAGE = b"""<html><body>
<p>For example, 2SPY 261218C00010010 would imply a European option.</p>
<table><tr><th>Ticker</th><th>Name</th><th>CUSIP</th><th>Shares</th><th>Price (Local)</th>
<th>Market Value ($mm)</th><th>% of Net Assets</th></tr>
<tr><td>2SPY  261218C00010010</td><td>SPY 12/18/2026 10.01 C</td><td></td>
<td>14,902</td><td>739.69</td><td>1,102.29</td><td>7.66</td></tr>
<tr><td>2SPY  261218P10010010</td><td>SPY 12/18/2026 10010.01 P</td><td></td>
<td>-14,902</td><td>9,212.91</td><td>-13,729.08</td><td>95.46</td></tr>
<tr><td>FGXXX</td><td>Government Fund</td><td>31846V336</td><td>1,469,986</td>
<td>100.00</td><td>1.47</td><td>0.01</td></tr>
</table><span>11/09/2026</span></body></html>"""


def test_family_file_keeps_option_lines_with_their_fund_and_side():
    frame = parse_family_file(FAMILY)
    assert list(frame.columns) == list(HOLDING_COLUMNS)
    assert len(frame) == 2  # the cash line is not an option
    call = frame.iloc[0]
    assert (call["fund"], call["option_root"], call["right"]) == ("BJAN", "4SPY", "C")
    assert call["as_of"] == pd.Timestamp("2026-11-10")
    assert call["expiry"] == pd.Timestamp("2026-12-31")
    assert call["strike"] == pytest.approx(6.83)
    assert call["contracts"] == pytest.approx(4623.0)
    assert frame.iloc[1]["contracts"] == pytest.approx(-4623.0)
    assert call["net_assets"] == pytest.approx(350e6)


def test_family_file_without_its_columns_is_an_error():
    with pytest.raises(SnapshotParseError, match="Account"):
        parse_family_file(b"Date,StockTicker,Shares\n11/10/2026,X,1\n")


def test_box_fund_page_reads_the_holdings_table_only():
    frame = parse_box_fund_page(PAGE, "BOXX", pd.Timestamp("2026-11-09"))
    assert list(frame.columns) == list(HOLDING_COLUMNS)
    assert len(frame) == 2  # the prose mention and the money fund are not rows
    put = frame.iloc[1]
    assert (put["fund"], put["option_root"], put["right"]) == ("BOXX", "2SPY", "P")
    assert put["strike"] == pytest.approx(10010.01)
    assert put["contracts"] == pytest.approx(-14902.0)
    assert put["price"] == pytest.approx(9212.91)
    assert put["as_of"] == pd.Timestamp("2026-11-09")


def test_a_page_without_option_rows_is_an_error():
    with pytest.raises(SnapshotParseError, match="no option"):
        parse_box_fund_page(b"<html><table><tr><td>x</td></tr></table></html>", "BOXX", None)
