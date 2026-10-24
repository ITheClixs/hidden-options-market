"""Tests for the hidden share: product symbols, the share itself, stability, the
reconciliation of the two FLEX sources and the value share."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from hidden_options.measure import hidden_share as hs
from hidden_options.measure.hidden_share import (
    FLEX_INDEX_ROOTS,
    hidden_share,
    is_adjusted_product,
    is_flex_product,
    listed_index,
    listed_product,
    quote_price,
    reconcile_flex_sources,
    stable_headline,
    stable_symbols,
    value_composition,
    value_share,
)


def occ_rows(rows, date="2026-08-14"):
    """rows: (symbol, product_symbol, call_oi, put_oi[, expiry])"""
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp(date),
                "symbol": row[0],
                "product_symbol": row[1],
                "expiry": pd.Timestamp(row[4] if len(row) > 4 else "2026-09-18"),
                "strike": 100.0,
                "call_open_interest": row[2],
                "put_open_interest": row[3],
            }
            for row in rows
        ]
    )


def share_rows(rows):
    """rows: (date, symbol, flex_share)"""
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp(d),
                "symbol": s,
                "adjusted": False,
                "flex_oi": share * 100,
                "listed_oi": (1 - share) * 100,
                "flex_share": share,
            }
            for d, s, share in rows
        ]
    )


class TestProducts:
    def test_listed_product_strips_equity_prefix(self):
        assert listed_product("1AAON") == "AAON"
        assert listed_product("4SPY") == "SPY"
        assert listed_product("2SPY", kind="equity") == "SPY"

    def test_flex_root_mapping_rejects_unknown_index_root(self):
        # ZZZ is an index here, and no table entry says which listed product it is.
        with pytest.raises(KeyError, match="7ZZZ"):
            listed_product("7ZZZ", kind="index")

    def test_index_roots_map_through_the_table(self):
        assert listed_product("4SPX", kind="index") == "SPX"
        assert listed_product("2SPX", kind="index") == "SPX"
        assert listed_product("2NDX", kind="index") == "NDX"
        assert listed_product("2DJX", kind="index") == "DJX"

    def test_mini_and_micro_index_products_stay_separate(self):
        # A mini contract is a different product on the same index, so it is not folded in.
        assert listed_product("4XSP", kind="index") == "XSP"
        assert listed_product("4XND", kind="index") == "XND"
        assert listed_product("4MRUT", kind="index") == "MRUT"

    def test_every_index_root_is_a_flex_root(self):
        assert all(is_flex_product(root) for root in FLEX_INDEX_ROOTS)
        assert {"SPX", "NDX", "RUT", "DJX"} <= set(FLEX_INDEX_ROOTS.values())

    def test_a_listed_symbol_is_not_a_flex_root(self):
        with pytest.raises(ValueError, match="SPY"):
            listed_product("SPY")

    def test_unknown_kind_is_refused(self):
        with pytest.raises(ValueError, match="kind"):
            listed_product("4SPY", kind="future")

    def test_listed_index_products_settle_on_their_index(self):
        assert listed_index("SPX") == "SPX"
        assert listed_index("SPXW") == "SPX"
        assert listed_index("NDXP") == "NDX"
        assert listed_index("RUTW") == "RUT"
        with pytest.raises(KeyError, match="XYZW"):
            listed_index("XYZW")

    @pytest.mark.parametrize(
        ("product", "flex", "adjusted"),
        [
            ("SPY", False, False),
            ("4SPY", True, False),
            ("1AAON", True, False),
            ("HON2", False, True),
            ("1HON2", True, True),
            ("SPXW", False, False),
            ("2SPX", True, False),
        ],
    )
    def test_flex_and_adjusted_products(self, product, flex, adjusted):
        assert is_flex_product(product) is flex
        assert is_adjusted_product(product) is adjusted


class TestHiddenShare:
    def test_hidden_share_counts_digit_products_as_flex(self):
        share = hidden_share(occ_rows([("SPY", "SPY", 60, 40), ("SPY", "4SPY", 30, 20)]))

        row = share.iloc[0]
        assert (row["symbol"], row["flex_oi"], row["listed_oi"]) == ("SPY", 50, 100)
        assert row["flex_share"] == pytest.approx(1 / 3)

    def test_columns(self):
        share = hidden_share(occ_rows([("SPY", "SPY", 1, 0)]))
        assert tuple(share.columns) == hs.SHARE_COLUMNS

    def test_every_flex_prefix_adds_up(self):
        share = hidden_share(
            occ_rows(
                [
                    ("SPY", "SPY", 100, 0),
                    ("SPY", "1SPY", 10, 0),
                    ("SPY", "2SPY", 0, 20),
                    ("SPY", "4SPY", 30, 40),
                ]
            )
        )
        assert share.iloc[0]["flex_oi"] == 100

    def test_adjusted_products_are_their_own_underlying(self):
        """R20: a class renamed after a corporate action is not folded into its parent."""
        share = hidden_share(
            occ_rows(
                [
                    ("HON", "HON", 100, 0),
                    ("HON", "1HON", 25, 0),
                    ("HON", "HON2", 60, 0),
                    ("HON", "1HON2", 40, 0),
                ]
            )
        ).set_index("symbol")

        assert share.loc["HON", "flex_share"] == pytest.approx(0.2)
        assert not share.loc["HON", "adjusted"]
        assert share.loc["HON2", "flex_share"] == pytest.approx(0.4)
        assert share.loc["HON2", "adjusted"]

    def test_a_listed_weekly_product_folds_into_its_symbol(self):
        share = hidden_share(occ_rows([("VIX", "VIX", 10, 0), ("VIX", "VIXW", 30, 0)]))
        assert list(share["symbol"]) == ["VIX"]
        assert share.iloc[0]["listed_oi"] == 40

    def test_one_row_per_date_and_no_row_without_open_interest(self):
        frame = pd.concat(
            [
                occ_rows([("AAA", "AAA", 3, 1), ("BBB", "BBB", 0, 0)], "2026-08-14"),
                occ_rows([("AAA", "AAA", 2, 0), ("AAA", "2AAA", 2, 0)], "2026-08-17"),
            ]
        )
        share = hidden_share(frame)

        assert list(share["symbol"]) == ["AAA", "AAA"]
        assert list(share["flex_share"]) == [0.0, 0.5]


class TestStableHeadline:
    def test_stable_headline_requires_every_date(self):
        share = share_rows(
            [("2026-08-14", "EFA", 0.6), ("2026-08-17", "EFA", 0.6), ("2026-08-18", "EFA", 0.4)]
        )
        assert stable_headline(share, 0.5) == 0

    def test_counts_names_above_the_threshold_on_every_date(self):
        share = share_rows(
            [
                ("2026-08-14", "EFA", 0.6),
                ("2026-08-17", "EFA", 0.5),
                ("2026-08-14", "SPY", 0.2),
                ("2026-08-17", "SPY", 0.3),
            ]
        )
        assert stable_headline(share, 0.5) == 1
        assert stable_symbols(share, 0.2) == ["EFA", "SPY"]

    def test_a_name_missing_on_a_date_is_not_confirmed_on_it(self):
        share = share_rows(
            [("2026-08-14", "EFA", 0.6), ("2026-08-17", "EFA", 0.6), ("2026-08-17", "RUT", 0.9)]
        )
        assert stable_symbols(share, 0.5) == ["EFA"]

    def test_an_empty_share_has_no_stable_name(self):
        assert stable_headline(share_rows([]), 0.1) == 0


class TestReconcile:
    def report(self, rows):
        """rows: (report_date, underlying, open_interest)"""
        return pd.DataFrame(
            [
                {"report_date": pd.Timestamp(d), "underlying": u, "open_interest": oi}
                for d, u, oi in rows
            ]
        )

    def test_both_sources_agree(self):
        share = hidden_share(occ_rows([("SPY", "SPY", 100, 0), ("SPY", "4SPY", 30, 20)]))
        report = self.report([("2026-08-14", "SPY", 30), ("2026-08-14", "SPY", 20)])

        rec = reconcile_flex_sources(share, report)

        assert tuple(rec.columns) == hs.RECONCILE_COLUMNS
        assert rec.iloc[0][["flex_oi_search", "flex_oi_report", "rel_diff"]].tolist() == [
            50,
            50,
            0.0,
        ]

    def test_difference_is_relative_to_the_larger_source(self):
        share = hidden_share(occ_rows([("SPY", "SPY", 100, 0), ("SPY", "4SPY", 90, 0)]))
        rec = reconcile_flex_sources(share, self.report([("2026-08-14", "SPY", 100)]))
        assert rec.iloc[0]["rel_diff"] == pytest.approx(0.1)

    def test_flex_in_one_source_only_is_a_full_disagreement(self):
        share = hidden_share(occ_rows([("AAA", "AAA", 100, 0), ("BBB", "BBB", 5, 0)]))
        rec = reconcile_flex_sources(share, self.report([("2026-08-14", "AAA", 10)]))

        by_symbol = rec.set_index("symbol")["rel_diff"]
        assert by_symbol["AAA"] == 1.0
        # Neither source has FLEX for BBB: nothing to disagree about.
        assert by_symbol["BBB"] == 0.0

    def test_dates_are_matched(self):
        share = hidden_share(occ_rows([("AAA", "AAA", 1, 0), ("AAA", "1AAA", 4, 0)]))
        rec = reconcile_flex_sources(share, self.report([("2026-08-17", "AAA", 4)]))
        assert rec.iloc[0]["flex_oi_report"] == 0


class TestQuotePrice:
    def test_two_sided_quotes_use_the_mid_and_others_the_model_value(self):
        price, at_theo = quote_price(
            pd.Series([1.0, 0.0, 0.0, 2.0, 1.0]),
            pd.Series([1.2, 0.05, 0.0, 1.5, 0.0]),
            pd.Series([9.0, 0.02, 0.01, 1.7, 0.9]),
        )
        assert price.tolist() == pytest.approx([1.1, 0.02, 0.01, 1.7, 0.9])
        assert at_theo.tolist() == [False, True, True, True, True]

    def test_missing_quotes_stay_missing(self):
        price, at_theo = quote_price(
            pd.Series([math.nan]), pd.Series([math.nan]), pd.Series([math.nan])
        )
        assert price.isna().all()
        assert not at_theo.any()


def chain(rows, date="2026-08-14"):
    """rows: (symbol, root, expiry, right, oi, bid, ask, theo)"""
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp(date),
                "symbol": s,
                "root": root,
                "expiry": pd.Timestamp(e),
                "right": r,
                "strike": 100.0,
                "open_interest": oi,
                "bid": bid,
                "ask": ask,
                "theo": theo,
            }
            for s, root, e, r, oi, bid, ask, theo in rows
        ]
    )


def flex(rows, date="2026-08-14"):
    """rows: (kind, root, expiry, mark, oi)"""
    return pd.DataFrame(
        [
            {
                "report_date": pd.Timestamp(date),
                "kind": kind,
                "root": root,
                "underlying": root.lstrip("0123456789"),
                "right": "C",
                "expiry": pd.Timestamp(e),
                "strike": 100.0,
                "mark_price": mark,
                "open_interest": oi,
            }
            for kind, root, e, mark, oi in rows
        ],
        columns=list(FLEX_COLUMNS),
    )


FLEX_COLUMNS = (
    "report_date",
    "kind",
    "root",
    "underlying",
    "right",
    "expiry",
    "strike",
    "mark_price",
    "open_interest",
)


class TestValueShare:
    def test_listed_value_is_mid_times_open_interest_and_flex_is_mark(self):
        listed = chain([("SPY", "SPY", "2026-09-18", "C", 10, 1.0, 3.0, 9.0)])
        panel = flex([("equity", "4SPY", "2026-09-18", 6.0, 5)])

        row = value_share(listed, panel).iloc[0]

        assert row["listed_value"] == pytest.approx(2.0 * 10 * 100)
        assert row["flex_value"] == pytest.approx(6.0 * 5 * 100)
        assert row["value_share"] == pytest.approx(3000 / 5000)
        assert row["oi_share"] == pytest.approx(5 / 15)
        assert tuple(value_share(listed, panel).columns) == hs.VALUE_COLUMNS

    def test_series_expiring_on_the_date_are_left_out_on_both_sides(self):
        listed = chain(
            [
                ("SPY", "SPY", "2026-09-18", "C", 10, 1.0, 1.0, 1.0),
                ("SPY", "SPY", "2026-08-14", "C", 99, 1.0, 1.0, 1.0),
            ]
        )
        panel = flex(
            [("equity", "4SPY", "2026-09-18", 1.0, 10), ("equity", "4SPY", "2026-08-14", 1.0, 99)]
        )
        row = value_share(listed, panel).iloc[0]
        assert (row["listed_oi"], row["flex_oi"]) == (10, 10)

    def test_index_products_on_both_sides_add_up(self):
        listed = chain(
            [
                ("SPX", "SPX", "2026-09-18", "C", 10, 1.0, 1.0, 1.0),
                ("SPX", "SPXW", "2026-09-18", "P", 30, 1.0, 1.0, 1.0),
            ]
        )
        panel = flex(
            [
                ("index", "2SPX", "2026-09-18", 1.0, 5),
                ("index", "4SPX", "2026-09-18", 1.0, 15),
                ("index", "4XSP", "2026-09-18", 1.0, 1000),
            ]
        )
        row = value_share(listed, panel).iloc[0]
        assert (row["symbol"], row["listed_oi"], row["flex_oi"]) == ("SPX", 40, 20)

    def test_unknown_flex_index_root_stops_the_analysis(self):
        listed = chain([("SPX", "SPX", "2026-09-18", "C", 10, 1.0, 1.0, 1.0)])
        panel = flex([("index", "9ABC", "2026-09-18", 1.0, 5)])
        with pytest.raises(KeyError, match="9ABC"):
            value_share(listed, panel)

    def test_adjusted_classes_are_left_out_on_both_sides(self):
        listed = chain(
            [
                ("HON", "HON", "2026-09-18", "C", 10, 1.0, 1.0, 1.0),
                ("HON", "HON2", "2026-09-18", "C", 50, 1.0, 1.0, 1.0),
            ]
        )
        panel = flex(
            [("equity", "1HON", "2026-09-18", 1.0, 10), ("equity", "1HON2", "2026-09-18", 1.0, 70)]
        )
        row = value_share(listed, panel).iloc[0]
        assert (row["listed_oi"], row["flex_oi"]) == (10, 10)

    def test_a_listed_root_of_another_underlying_is_refused(self):
        listed = chain([("SPX", "NDXP", "2026-09-18", "C", 10, 1.0, 1.0, 1.0)])
        with pytest.raises(ValueError, match="NDXP"):
            value_share(listed, flex([]))

    def test_unpriced_series_lower_the_priced_share(self):
        listed = chain(
            [
                ("SPY", "SPY", "2026-09-18", "C", 90, 1.0, 1.0, 1.0),
                ("SPY", "SPY", "2026-10-16", "C", 10, math.nan, math.nan, math.nan),
            ]
        )
        row = value_share(listed, flex([])).iloc[0]

        assert row["priced_share"] == pytest.approx(0.9)
        assert not row["usable"]
        assert row["listed_value"] == pytest.approx(90 * 100)
        assert row["flex_value"] == 0

    def test_theo_share_counts_open_interest_valued_by_the_model(self):
        listed = chain(
            [
                ("SPY", "SPY", "2026-09-18", "C", 75, 1.0, 1.2, 1.0),
                ("SPY", "SPY", "2026-10-16", "C", 25, 0.0, 0.05, 0.02),
            ]
        )
        row = value_share(listed, flex([])).iloc[0]
        assert row["theo_share"] == pytest.approx(0.25)
        assert row["usable"]


class TestValueComposition:
    SERIES = pd.DataFrame(
        {
            "date": pd.Timestamp("2026-10-22"),
            "symbol": "SPY",
            "root": "4SPY",
            "right": ["C", "P", "C", "C"],
            "expiry": pd.Timestamp("2026-12-18"),
            "strike": [2.0, 200.0, 200.0, 120.0],
            "mark_price": [100.0, 100.5, 0.01, 1.0],
            "open_interest": [10, 10, 10, 10],
        }
    ).assign(flex_value=lambda f: f["mark_price"] * f["open_interest"] * 100)

    def test_intrinsic_deep_and_paired_value(self):
        parts = value_composition(self.SERIES, {"SPY": 100.0})

        assert parts["value"] == pytest.approx(201_510)
        # The call at 2 and the put at 200 are each worth their intrinsic value nearly whole.
        assert parts["intrinsic"] == pytest.approx(98 * 1000 + 100 * 1000)
        assert parts["deep_share"] == pytest.approx(200_500 / 201_510)
        # Only strike 200 carries both a call and a put.
        assert parts["paired_share"] == pytest.approx(100_510 / 201_510)

    def test_a_symbol_without_a_spot_is_refused(self):
        with pytest.raises(KeyError, match="SPY"):
            value_composition(self.SERIES, {})
