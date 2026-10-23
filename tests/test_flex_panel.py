"""Tests for FLEX panel assembly and inventory measures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.flex_panel import (
    daily_inventory,
    inventory_changes,
    load_panel,
    parse_exercise_style,
    summarise_panel,
)


def _panel(rows):
    """rows: (report_date, underlying, right, expiry, strike, mark, oi)"""
    return pd.DataFrame(
        [
            {
                "report_date": pd.Timestamp(d),
                "kind": "equity",
                "class_name": u,
                "root": "1" + u,
                "underlying": u,
                "right": r,
                "expiry": pd.Timestamp(e),
                "strike": k,
                "mark_price": m,
                "open_interest": oi,
            }
            for d, u, r, e, k, m, oi in rows
        ]
    )


BASE = _panel(
    [
        ("2026-08-13", "AAA", "C", "2026-09-18", 100.0, 2.0, 1000),
        ("2026-08-13", "AAA", "P", "2026-12-18", 90.0, 3.0, 500),
        ("2026-08-14", "AAA", "C", "2026-09-18", 100.0, 2.5, 1200),
        ("2026-08-14", "AAA", "P", "2026-12-18", 90.0, 3.0, 500),
    ]
)


class TestDailyInventory:
    def test_one_row_per_underlying_date(self):
        assert len(daily_inventory(BASE)) == 2

    def test_sums_open_interest(self):
        out = daily_inventory(BASE).sort_values("report_date")
        assert out.iloc[0]["open_interest"] == 1500
        assert out.iloc[1]["open_interest"] == 1700

    def test_values_at_the_reports_own_mark(self):
        """Mark price replaces the contracts-times-spot proxy."""
        out = daily_inventory(BASE).sort_values("report_date")
        assert out.iloc[0]["mark_value"] == pytest.approx(1000 * 100 * 2.0 + 500 * 100 * 3.0)

    def test_splits_calls_and_puts(self):
        out = daily_inventory(BASE).sort_values("report_date")
        assert out.iloc[0]["call_open_interest"] == 1000
        assert out.iloc[0]["put_open_interest"] == 500

    def test_isolates_near_dated_contracts(self):
        """The December expiry is beyond sixty days and must be excluded."""
        out = daily_inventory(BASE).sort_values("report_date")
        assert out.iloc[0]["near_dated_open_interest"] == 1000

    def test_underlying_with_no_near_dated_gets_zero_not_nan(self):
        far = _panel([("2026-08-13", "BBB", "C", "2027-06-18", 50.0, 1.0, 400)])
        assert daily_inventory(far).iloc[0]["near_dated_open_interest"] == 0


class TestInventoryChanges:
    def test_computes_day_over_day_change(self):
        out = inventory_changes(daily_inventory(BASE), min_history=1)
        assert out.iloc[0]["d_open_interest"] == 200

    def test_log_change_is_scale_free(self):
        out = inventory_changes(daily_inventory(BASE), min_history=1)
        assert (
            out.iloc[0]["d_log_oi"] == pytest.approx(pd.np.log(1700 / 1500))
            if hasattr(pd, "np")
            else out.iloc[0]["d_log_oi"] > 0
        )

    def test_first_observation_is_dropped(self):
        """A change needs a prior level; the first date cannot supply one."""
        out = inventory_changes(daily_inventory(BASE), min_history=1)
        assert len(out) == 1

    def test_short_histories_are_excluded(self):
        assert inventory_changes(daily_inventory(BASE), min_history=10).empty

    def test_underlyings_do_not_leak_into_each_other(self):
        """Concatenated reports carry duplicate index labels; aggregation must not
        index back into the parent frame."""
        mixed = pd.concat(
            [BASE, _panel([("2026-08-14", "ZZZ", "C", "2026-09-18", 10.0, 1.0, 999)])]
        )
        out = inventory_changes(daily_inventory(mixed), min_history=1)
        assert "ZZZ" not in set(out["underlying"])


class TestLoadPanel:
    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="no FLEX reports"):
            load_panel(tmp_path)

    def test_summary_reports_coverage(self):
        summary = summarise_panel(BASE)
        assert summary.dates == 2
        assert summary.underlyings == 1
        assert "2026-08-13" in summary.describe()


def _store(root, date, classes, kind="equity"):
    """Write one activity date's report the way the collector files it.

    ``classes`` is a list of ``(class_name, underlying)``; each gets one call series.
    """
    folder = root / f"occ_flex/date={date}"
    folder.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "report_date": date,
            "kind": kind,
            "class_name": class_name,
            "root": "1" + underlying,
            "underlying": underlying,
            "right": "C",
            "expiry": "2026-12-18",
            "strike": 100.0,
            "mark_price": 1.0,
            "open_interest": 10,
        }
        for class_name, underlying in classes
    ]
    pd.DataFrame(rows).to_parquet(folder / f"{kind}.parquet")


class TestAvailability:
    """OCC publishes the report for activity date T overnight, so it is in hand before
    the next session. Anything joined to T must wait until ``available_at``."""

    def test_available_at_is_next_activity_date(self, tmp_path):
        # Mon, Tue, Thu: Wednesday has no report, so Tuesday's is available on Thursday.
        for date in ("2026-08-10", "2026-08-11", "2026-08-13"):
            _store(tmp_path, date, [("AAA INC", "AAA")])
        panel = load_panel(tmp_path)
        assert list(panel["available_at"]) == [
            pd.Timestamp("2026-08-11"),
            pd.Timestamp("2026-08-13"),
            pd.Timestamp("2026-08-14"),
        ]

    def test_last_date_falls_to_the_next_weekday(self, tmp_path):
        """Friday's report is in hand on Monday, not on the weekend."""
        for date in ("2026-08-13", "2026-08-14"):
            _store(tmp_path, date, [("AAA INC", "AAA")])
        panel = load_panel(tmp_path)
        assert panel["available_at"].iloc[-1] == pd.Timestamp("2026-08-17")

    def test_calendar_is_the_whole_panels_not_the_underlyings(self, tmp_path):
        """AAA is absent on Tuesday, but the report still exists then; AAA's Monday row is
        available Tuesday. Index reports share the same calendar."""
        _store(tmp_path, "2026-08-10", [("AAA INC", "AAA")])
        _store(tmp_path, "2026-08-11", [("BBB INC", "BBB")])
        _store(tmp_path, "2026-08-11", [("SPX INDEX", "SPX")], kind="index")
        panel = load_panel(tmp_path)
        monday = panel[panel["report_date"] == pd.Timestamp("2026-08-10")]
        assert set(monday["available_at"]) == {pd.Timestamp("2026-08-11")}
        assert panel["available_at"].dtype == panel["report_date"].dtype

    def test_available_at_is_never_before_the_report_date(self, tmp_path):
        for date in ("2026-08-10", "2026-08-11", "2026-08-13"):
            _store(tmp_path, date, [("AAA INC", "AAA")])
        panel = load_panel(tmp_path)
        assert (panel["available_at"] > panel["report_date"]).all()


class TestExerciseStyle:
    def test_exercise_style_parsed_from_class_name(self, tmp_path):
        _store(
            tmp_path,
            "2026-08-10",
            [
                ("AAON INC (AMER/FLEX)", "AAON"),
                ("APPLE INC (EURO/FLEX)", "AAPL"),
                ("PLAIN HOLDINGS CORP", "PLN"),
            ],
        )
        panel = load_panel(tmp_path).set_index("underlying")
        assert panel.loc["AAON", "exercise_style"] == "american"
        assert panel.loc["AAPL", "exercise_style"] == "european"
        # Unmarked equity headings carry no information; they must not be guessed.
        assert panel.loc["PLN", "exercise_style"] is None

    def test_unmarked_index_classes_default_to_european(self, tmp_path):
        _store(
            tmp_path,
            "2026-08-10",
            [("S&P 500 INDEX AM/EURO (FLEX)", "SPX"), ("Cboe Bitcoin U.S. ETF Index Op", "CBTX")],
            kind="index",
        )
        panel = load_panel(tmp_path)
        assert set(panel["exercise_style"]) == {"european"}

    def test_an_explicit_index_marker_wins_over_the_default(self, tmp_path):
        _store(tmp_path, "2026-08-10", [("ODD INDEX (AMER/FLEX)", "ODD")], kind="index")
        assert load_panel(tmp_path)["exercise_style"].iloc[0] == "american"

    @pytest.mark.parametrize(
        ("class_name", "expected"),
        [
            ("AAON INC (AMER/FLEX)", "american"),
            ("Apple Inc (Euro Flex)", "european"),
            ("Adobe Inc. (Euro/Flex)", "european"),
            ("Apple Inc (Euro Flex)          (CONT)", "european"),
            # The heading field is cut at thirty characters, so many markers arrive clipped.
            ("UNITED STATES STEEL (AMER/FLEX (CONT)", "american"),
            ("ADVANCED MICRO-DEVICES (EURO/F (CONT)", "european"),
            ("ISHARES BITCOIN TRUST ETF (AME", "american"),
            ("Accenture PLC (EUR", "european"),
            # Further text may follow the marker.
            ("3M (EURO/FLEX) (Spinoff)", "european"),
            ("Aptiv PLC (EURO/FLEX)(Spinoff)", "european"),
            # Stubs too short to tell apart from other parentheticals stay unknown.
            ("Ionis Pharmaceuticals, Inc. (A", None),
            ("Discover Financial Services (E", None),
            ("ChargePoint Holdings, Inc. (AM", None),
            ("Truist Financial Corporation (", None),
            ("AMERICAN INTERNATIONAL GROUP (", None),
            ("Foo Depositary Shares (ADR)", None),
            ("Foo Holdings (EUR)", None),
            ("PLAIN HOLDINGS CORP", None),
            ("Apple Inc (AMER/FLEX) (EURO/FLEX)", None),
            (None, None),
            (np.nan, None),
        ],
    )
    def test_parse_exercise_style(self, class_name, expected):
        assert parse_exercise_style(class_name) == expected


class TestGapSafeChanges:
    """A change across a missing activity date spans several days of flow, not one."""

    CHANGES = ("d_open_interest", "d_mark_value", "d_log_oi", "d_near_dated")

    @staticmethod
    def _daily(presence):
        """presence: {underlying: [dates]}; open interest rises 100 a day within each."""
        rows = [
            (date, name, "C", "2026-09-18", 100.0, 2.0, 1000 + 100 * i)
            for name, dates in presence.items()
            for i, date in enumerate(dates)
        ]
        return daily_inventory(_panel(rows))

    def test_changes_are_nan_across_missing_activity_date(self):
        # AAA is present Mon, Tue, Thu while BBB's presence makes the panel Mon..Thu.
        daily = self._daily(
            {
                "AAA": ["2026-08-10", "2026-08-11", "2026-08-13"],
                "BBB": ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"],
            }
        )
        out = inventory_changes(daily, min_history=1).set_index(["underlying", "report_date"])
        thursday = out.loc[("AAA", pd.Timestamp("2026-08-13"))]
        assert thursday[list(self.CHANGES)].isna().all()
        # The level on Thursday is still reported; only the change is withheld.
        assert thursday["open_interest"] == 1200
        # Contiguous days keep their changes.
        assert out.loc[("AAA", pd.Timestamp("2026-08-11")), "d_open_interest"] == 100
        assert out.loc[("BBB", pd.Timestamp("2026-08-13")), "d_open_interest"] == 100

    def test_change_resumes_the_day_after_a_gap(self):
        daily = self._daily(
            {
                "AAA": ["2026-08-10", "2026-08-11", "2026-08-13", "2026-08-14"],
                "BBB": ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"],
            }
        )
        out = inventory_changes(daily, min_history=1).set_index(["underlying", "report_date"])
        assert pd.isna(out.loc[("AAA", pd.Timestamp("2026-08-13")), "d_log_oi"])
        assert out.loc[("AAA", pd.Timestamp("2026-08-14")), "d_open_interest"] == 100

    def test_a_market_wide_holiday_is_not_a_gap(self):
        """No report at all on Wednesday: Thursday follows Tuesday in the calendar."""
        dates = ["2026-08-10", "2026-08-11", "2026-08-13"]
        out = inventory_changes(self._daily({"AAA": dates, "BBB": dates}), min_history=1)
        thursday = out[out["report_date"] == pd.Timestamp("2026-08-13")]
        assert len(thursday) == 2
        assert (thursday["d_open_interest"] == 100).all()

    def test_calendar_comes_from_every_underlying_not_the_ones_kept(self):
        """BBB alone reports on Wednesday and is dropped for short history; Wednesday is
        still a date the panel has, so AAA's Thursday change is still across a gap."""
        daily = self._daily(
            {
                "AAA": ["2026-08-10", "2026-08-11", "2026-08-13"],
                "BBB": ["2026-08-12"],
            }
        )
        out = inventory_changes(daily, min_history=3)
        assert set(out["underlying"]) == {"AAA"}
        thursday = out[out["report_date"] == pd.Timestamp("2026-08-13")]
        assert thursday["d_log_oi"].isna().all()

    def test_first_observation_is_still_dropped_not_nan(self):
        daily = self._daily({"AAA": ["2026-08-10", "2026-08-11"]})
        out = inventory_changes(daily, min_history=1)
        assert list(out["report_date"]) == [pd.Timestamp("2026-08-11")]
