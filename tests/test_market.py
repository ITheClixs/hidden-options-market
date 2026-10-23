"""Tests for the market-level measures: size, composition, the growth break and cohorts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure import market, market_macros, market_result
from hidden_options.measure.market import (
    composition,
    composition_by_date,
    expiring_decline,
    expiry_cohorts,
    expiry_cycles,
    expiry_window_changes,
    fit_growth,
    growth_break,
    largest_drops,
    market_daily,
    maturity_by_date,
    maturity_profile,
    monthly_expiries,
)
from hidden_options.publish.latex import collect_macros
from market_stub import make_panel, synthetic_market


class TestMarketDaily:
    PANEL = make_panel(
        [
            ("2026-08-13", "AAA", "C", "2026-09-18", 100.0, 2.0, 1000),
            ("2026-08-13", "AAA", "P", "2026-12-18", 90.0, 3.0, 500),
            ("2026-08-13", "BBB", "C", "2026-09-18", 50.0, 1.0, 0),
            ("2026-08-14", "AAA", "C", "2026-09-18", 100.0, 2.5, 1200),
        ]
    )

    def test_columns_and_one_row_per_date(self):
        daily = market_daily(self.PANEL)

        assert tuple(daily.columns) == market.MARKET_DAILY_COLUMNS
        assert list(daily["report_date"]) == [
            pd.Timestamp("2026-08-13"),
            pd.Timestamp("2026-08-14"),
        ]

    def test_totals(self):
        first = market_daily(self.PANEL).iloc[0]

        assert first["open_interest"] == 1500
        assert first["mark_value"] == pytest.approx(1000 * 100 * 2.0 + 500 * 100 * 3.0)
        # A series with no open interest is still a listed series of the report.
        assert first["series"] == 3
        assert first["underlyings"] == 2


class TestComposition:
    def test_composition_shares_sum_correctly(self):
        panel = make_panel(
            [
                ("2026-08-14", "AAA", "C", "2026-09-18", 100.0, 2.0, 100),
                ("2026-08-14", "AAA", "C", "2027-09-17", 110.0, 2.0, 100),
                ("2026-08-14", "BBB", "P", "2026-08-21", 90.0, 1.0, 100),
                ("2026-08-15", "AAA", "P", "2026-09-18", 90.0, 1.0, 999),
            ]
        )

        shares = composition(panel, pd.Timestamp("2026-08-14"))

        assert set(shares) == set(market.COMPOSITION_KEYS)
        assert shares["call_share"] == pytest.approx(2 / 3)
        assert shares["series"] == 3
        assert shares["underlyings"] == 2
        # Two of the three equal lines expire within sixty days; the 2027 one does not.
        assert shares["within60d_share"] == pytest.approx(2 / 3)
        # With fewer than ten underlyings the top ten hold everything.
        assert shares["top10_share"] == pytest.approx(1.0)

    def test_top_ten_share_ignores_the_tail(self):
        rows = [
            ("2026-08-14", f"U{i:02d}", "C", "2026-09-18", 100.0, 1.0, 100 if i < 10 else 25)
            for i in range(14)
        ]
        shares = composition(make_panel(rows), pd.Timestamp("2026-08-14"))

        assert shares["top10_share"] == pytest.approx(1000 / 1100)

    def test_sixty_days_is_inclusive(self):
        panel = make_panel(
            [
                ("2026-08-14", "AAA", "C", "2026-10-13", 100.0, 1.0, 100),  # 60 days
                ("2026-08-14", "AAA", "C", "2026-10-14", 100.0, 1.0, 100),  # 61 days
            ]
        )
        assert composition(panel, pd.Timestamp("2026-08-14"))["within60d_share"] == 0.5

    def test_date_without_rows_raises(self):
        panel = make_panel([("2026-08-14", "AAA", "C", "2026-09-18", 100.0, 1.0, 1)])
        with pytest.raises(ValueError, match="2026-08-15"):
            composition(panel, pd.Timestamp("2026-08-15"))

    def test_by_date_matches_the_single_date_view(self):
        panel = synthetic_market(end="2025-02-28")
        frame = composition_by_date(panel)
        on = pd.Timestamp("2025-02-03")

        assert frame.loc[on].to_dict() == pytest.approx(composition(panel, on))


class TestGrowthBreak:
    @staticmethod
    def planted(flat_days: int = 100, total: int = 240, slope: float = 0.003):
        """Flat for `flat_days` activity dates, then `slope` log points a calendar day."""
        dates = pd.bdate_range("2025-01-01", periods=total)
        pivot = dates[flat_days]
        elapsed = np.maximum(0, (dates - pivot).days.to_numpy())
        level = np.exp(np.log(1e6) + slope * elapsed)
        return pd.DataFrame({"report_date": dates, "open_interest": level}), pivot

    def test_growth_break_recovers_planted_break(self):
        daily, planted = self.planted()

        found = growth_break(daily)

        assert abs((found - planted).days) <= 3

    def test_recovers_a_break_under_noise(self):
        daily, planted = self.planted()
        noise = np.random.default_rng(7).normal(0, 0.01, len(daily))
        daily = daily.assign(open_interest=daily["open_interest"] * np.exp(noise))

        assert abs((growth_break(daily) - planted).days) <= 7

    def test_fit_reports_log_growth_per_year_on_each_side(self):
        daily, planted = self.planted(slope=0.003)

        fit = fit_growth(daily)

        assert fit.break_date == planted
        assert fit.pre_growth == pytest.approx(0.0, abs=1e-9)
        assert fit.post_growth == pytest.approx(0.003 * 365.25)

    def test_break_needs_min_side_dates_each_side(self):
        daily, _ = self.planted(flat_days=10, total=120)

        found = growth_break(daily, min_side=40)

        assert daily["report_date"].iloc[40] <= found <= daily["report_date"].iloc[-41]

    def test_too_few_dates_raises(self):
        daily, _ = self.planted(flat_days=40, total=80)
        with pytest.raises(ValueError, match="81"):
            growth_break(daily)

    def test_uses_the_named_column_and_ignores_row_order(self):
        daily, planted = self.planted()
        daily = daily.rename(columns={"open_interest": "mark_value"}).iloc[::-1]

        assert abs((growth_break(daily, "mark_value") - planted).days) <= 3


class TestExpiryCohorts:
    def test_expiry_cohorts_conserve_open_interest(self):
        panel = synthetic_market(end="2025-03-31")

        cohorts = expiry_cohorts(panel)
        daily = market_daily(panel).set_index("report_date")["open_interest"]

        pd.testing.assert_series_equal(
            cohorts.sum(axis=0), daily, check_names=False, check_index_type=False
        )

    def test_rows_are_expiry_months_and_columns_report_dates(self):
        panel = make_panel(
            [
                ("2026-08-13", "AAA", "C", "2026-09-04", 100.0, 1.0, 10),
                ("2026-08-13", "AAA", "C", "2026-09-18", 100.0, 1.0, 20),
                ("2026-08-14", "AAA", "C", "2026-11-20", 100.0, 1.0, 5),
            ]
        )
        cohorts = expiry_cohorts(panel)

        assert list(cohorts.index) == [pd.Timestamp("2026-09-01"), pd.Timestamp("2026-11-01")]
        assert cohorts.loc["2026-09-01", pd.Timestamp("2026-08-13")] == 30
        assert cohorts.loc["2026-09-01", pd.Timestamp("2026-08-14")] == 0


class TestMonthlyExpiries:
    def test_third_fridays_inside_the_calendar(self):
        calendar = pd.bdate_range("2025-01-02", "2025-03-31")

        assert list(monthly_expiries(calendar)) == list(
            pd.DatetimeIndex(["2025-01-17", "2025-02-21", "2025-03-21"])
        )

    def test_holiday_moves_expiry_to_the_previous_activity_date(self):
        # Good Friday 2025 fell on the third Friday of April.
        calendar = pd.bdate_range("2025-04-01", "2025-04-30").drop(pd.Timestamp("2025-04-18"))

        assert list(monthly_expiries(calendar)) == [pd.Timestamp("2025-04-17")]

    def test_third_friday_after_the_last_date_is_left_out(self):
        calendar = pd.bdate_range("2025-04-01", "2025-05-09")

        assert list(monthly_expiries(calendar)) == [pd.Timestamp("2025-04-18")]


class TestDropsAndCycles:
    PANEL = synthetic_market(end="2025-08-29")

    def test_largest_drops_fall_on_expiry_in_a_sawtooth_market(self):
        daily = market_daily(self.PANEL)
        expiries = monthly_expiries(pd.DatetimeIndex(daily["report_date"]))

        drops = largest_drops(daily, expiries, n=5)

        assert len(drops) == 5
        assert drops["on_expiry"].all()
        assert (drops["change"] < 0).all()
        assert drops["pct_change"].is_monotonic_increasing

    def test_drop_off_expiry_is_flagged(self):
        daily = pd.DataFrame(
            {
                "report_date": pd.bdate_range("2025-03-03", periods=4),
                "open_interest": [100.0, 50.0, 60.0, 59.0],
            }
        )
        drops = largest_drops(daily, pd.DatetimeIndex(["2025-03-05"]), n=2)

        assert list(drops["report_date"]) == [
            pd.Timestamp("2025-03-04"),
            pd.Timestamp("2025-03-06"),
        ]
        # 03-04: the expiry is after the drop. 03-06: the expiry is the previous date.
        assert list(drops["on_expiry"]) == [False, True]
        assert pd.isna(drops["expiry"].iloc[0])
        assert drops["expiry"].iloc[1] == pd.Timestamp("2025-03-05")

    def test_expiring_decline_counts_only_the_expiring_cohort(self):
        panel = make_panel(
            [
                ("2026-08-20", "AAA", "C", "2026-08-21", 100.0, 1.0, 100),
                ("2026-08-20", "AAA", "C", "2026-09-18", 100.0, 1.0, 50),
                ("2026-08-21", "AAA", "C", "2026-08-21", 100.0, 1.0, 40),
                ("2026-08-21", "AAA", "C", "2026-09-18", 100.0, 1.0, 70),
            ]
        )

        decline = expiring_decline(panel, pd.Timestamp("2026-08-20"), pd.Timestamp("2026-08-21"))

        assert decline == 60

    def test_expiry_cycles_keep_complete_cycles_only(self):
        daily = market_daily(self.PANEL)
        expiries = monthly_expiries(pd.DatetimeIndex(daily["report_date"]))

        cycles = expiry_cycles(daily, expiries)

        # January's expiry opens the first complete cycle; August's closes the last.
        assert cycles["end"].iloc[0] == expiries[1]
        assert cycles["end"].iloc[-1] == expiries[-1]
        assert (cycles["start"] > expiries[0]).all()
        inside = daily[(daily["report_date"] > expiries[0]) & (daily["report_date"] <= expiries[1])]
        assert cycles["open_interest"].iloc[0] == pytest.approx(inside["open_interest"].mean())


@pytest.fixture(scope="module")
def result():
    return market_result.market_result(synthetic_market())


class TestMarketResult:
    def test_named_market_with_valid_macros(self, result):
        assert result.name == "market"
        assert collect_macros({"market": result}) == dict(sorted(result.macros.items()))

    def test_carries_the_macros_the_paper_uses(self, result):
        for name in (
            "OverOneYear",
            "OverOneYearStart",
            "OverTwoYears",
            "OverTwoYearsStart",
            "MedianDaysMean",
            "MedianDaysLow",
            "MedianDaysHigh",
            "BeyondHorizonShare",
            "BeyondHorizonMean",
            "MapHorizonMonths",
            "ExpiryWindowShare",
            "ExpiryWindowChanges",
            "DailyChanges",
            "DropsOnExpiryDate",
            "DropsDayAfter",
            "FlatBandEnd",
            "PanelDates",
            "PanelUnderlyings",
            "PanelSeriesDays",
            "PanelStart",
            "PanelEnd",
            "OIStart",
            "OIEnd",
            "ValueStart",
            "ValueEnd",
            "BreakDate",
            "TopTenShare",
            "WithinSixtyShare",
            "CallShare",
            "DropsOnExpiry",
        ):
            assert name in result.macros

    def test_panel_counts(self, result):
        panel = synthetic_market()
        assert result.macros["PanelDates"] == str(panel["report_date"].nunique())
        assert result.macros["PanelUnderlyings"] == "12"
        assert result.macros["PanelStart"] == "2 January 2025"
        assert result.values["panel"]["series_days"] == len(panel)

    def test_break_is_near_the_planted_one(self, result):
        found = pd.Timestamp(result.values["growth"]["break_date"])
        assert abs((found - pd.Timestamp("2025-05-01")).days) <= 31

    def test_sawtooth_check_is_recorded(self, result):
        drops = result.values["drops"]
        assert len(drops["largest"]) == market.TOP_DROPS
        assert drops["on_expiry"] == sum(d["on_expiry"] for d in drops["largest"])
        named = {d["expiry"] for d in drops["largest"] if d["expiry"] is not None}
        assert drops["distinct_expiries"] == len(named)
        assert result.macros["DropExpiries"] == str(len(named))
        # Every fall in the sawtooth market lands on an expiry, and the text says "all".
        assert result.macros["DropsOnExpiry"] == "all"
        on_day = drops["on_expiry_date"] + drops["day_after_expiry"]
        assert on_day == drops["on_expiry"]

    def test_values_are_plain_json(self, result, tmp_path):
        from hidden_options.publish.results import read_results, write_result

        write_result(result, tmp_path)
        assert read_results(tmp_path)["market"].macros == result.macros


def test_registered_analysis_reads_the_raw_panel(monkeypatch, tmp_path):
    seen = []

    def fake_load(root):
        seen.append(root)
        return synthetic_market()

    monkeypatch.setattr(market_result, "load_panel", fake_load)
    monkeypatch.setattr(market_result, "RAW_DIR", tmp_path)

    result = market_result.market()

    assert seen == [tmp_path]
    assert result.name == "market"


class TestRefusals:
    def test_log_fit_needs_positive_levels(self):
        daily = pd.DataFrame(
            {"report_date": pd.bdate_range("2025-01-01", periods=90), "open_interest": 0.0}
        )
        with pytest.raises(ValueError, match="positive"):
            fit_growth(daily)

    def test_cumulative_share_of_an_absent_date_raises(self):
        panel = make_panel([("2026-08-14", "AAA", "C", "2026-09-18", 100.0, 1.0, 1)])
        with pytest.raises(ValueError, match="2026-08-15"):
            market.cumulative_share(panel, pd.Timestamp("2026-08-15"))

    def test_cumulative_share_ranks_from_one(self):
        panel = make_panel(
            [
                ("2026-08-14", "AAA", "C", "2026-09-18", 100.0, 1.0, 1),
                ("2026-08-14", "BBB", "C", "2026-09-18", 100.0, 1.0, 3),
            ]
        )
        shares = market.cumulative_share(panel, pd.Timestamp("2026-08-14"))

        assert list(shares.index) == [1, 2]
        assert list(shares) == [0.75, 1.0]

    def test_a_break_before_any_complete_cycle_is_refused(self):
        daily = market_daily(synthetic_market(end="2025-08-29"))
        expiries = monthly_expiries(pd.DatetimeIndex(daily["report_date"]))
        with pytest.raises(ValueError, match="before the break"):
            market_result._cycles(daily, expiries, pd.Timestamp("2025-01-20"))

    def test_too_few_cycles_for_a_quarter_is_refused(self):
        daily = market_daily(synthetic_market(end="2025-04-30"))
        expiries = monthly_expiries(pd.DatetimeIndex(daily["report_date"]))
        with pytest.raises(ValueError, match="complete cycles"):
            market_result._cycles(daily, expiries, pd.Timestamp("2025-03-31"))

    def test_an_underlying_that_is_not_a_plain_ticker_is_refused(self):
        panel = make_panel([("2026-08-14", "A&B", "C", "2026-09-18", 100.0, 1.0, 1)])
        with pytest.raises(ValueError, match="plain ticker"):
            market_result._concentration(panel, pd.Timestamp("2026-08-14"))

    @pytest.mark.parametrize(
        ("names", "text"),
        [(["SPY"], "SPY"), (["SPY", "SPX"], "SPY and SPX"), (["A", "B", "C"], "A, B and C")],
    )
    def test_name_list(self, names, text):
        assert market_macros._name_list(names) == text


class TestMaturity:
    def test_profile_rows_are_calendar_months_ahead_with_one_later_row(self):
        panel = make_panel(
            [
                ("2026-08-14", "AAA", "C", "2026-08-21", 100.0, 1.0, 50),  # this month
                ("2026-08-14", "AAA", "C", "2026-09-04", 100.0, 1.0, 30),  # next month
                ("2026-08-14", "AAA", "C", "2028-08-18", 100.0, 1.0, 15),  # 24 months on
                ("2026-08-14", "AAA", "C", "2030-01-18", 100.0, 1.0, 5),
            ]
        )

        profile = maturity_profile(expiry_cohorts(panel), horizon_months=24)
        column = profile[pd.Timestamp("2026-08-14")]

        assert list(profile.index) == list(range(25))
        assert column[0] == pytest.approx(0.5)
        assert column[1] == pytest.approx(0.3)
        # Row 24 gathers every expiry 24 or more calendar months ahead.
        assert column[24] == pytest.approx(0.2)
        assert column[2:24].sum() == 0

    def test_profile_columns_are_shares_of_each_date(self):
        profile = maturity_profile(expiry_cohorts(synthetic_market(end="2025-03-31")))

        assert profile.sum(axis=0).to_numpy() == pytest.approx(1.0)

    def test_long_dated_shares_and_weighted_median(self):
        panel = make_panel(
            [
                ("2026-01-02", "AAA", "C", "2026-01-12", 100.0, 1.0, 40),  # 10 days
                ("2026-01-02", "AAA", "C", "2027-02-06", 100.0, 1.0, 30),  # 400 days
                ("2026-01-02", "AAA", "C", "2028-03-12", 100.0, 1.0, 30),  # 800 days
                ("2026-01-05", "AAA", "C", "2026-01-15", 100.0, 1.0, 60),  # 10 days
                ("2026-01-05", "AAA", "C", "2027-02-09", 100.0, 1.0, 40),  # 400 days
            ]
        )

        frame = maturity_by_date(panel)
        first, second = frame.iloc[0], frame.iloc[1]

        assert first["over_one_year_share"] == pytest.approx(0.6)
        assert first["over_two_years_share"] == pytest.approx(0.3)
        # Half the open interest is reached only at the 400-day line.
        assert first["median_days"] == 400
        assert second["median_days"] == 10
        assert second["over_two_years_share"] == 0

    def test_expiry_window_changes_count_the_spans_that_touch_an_expiry(self):
        daily = pd.DataFrame(
            {
                "report_date": pd.bdate_range("2025-03-03", periods=6),
                "open_interest": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        )

        touching, changes = expiry_window_changes(daily, pd.DatetimeIndex(["2025-03-05"]))

        # 03-04 -> 03-05 and 03-05 -> 03-06 touch the expiry; five changes in all.
        assert (touching, changes) == (2, 5)


def test_a_market_that_never_leaves_its_band_is_refused():
    daily = pd.DataFrame(
        {"report_date": pd.bdate_range("2025-01-02", "2025-12-31"), "open_interest": 1e6}
    )
    expiries = monthly_expiries(pd.DatetimeIndex(daily["report_date"]))
    with pytest.raises(ValueError, match="above the pre-break band"):
        market_result._cycles(daily, expiries, pd.Timestamp("2025-06-02"))
