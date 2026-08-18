"""Tests for FLEX panel assembly and inventory measures."""

from __future__ import annotations

import pandas as pd
import pytest

from absorb.measure.flex_panel import (
    daily_inventory,
    inventory_changes,
    load_panel,
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
