"""Tests for the predictive panel, its regressions and the permutation test.

The failures that matter here look like results. An outcome joined on the activity date
rather than the date the report could be used, a change measured across a missing date,
or a placebo not dated after its outcome would each put information where the design
says there is none. The permutation test is checked on noise, where it must find
nothing, and on a planted effect, where it must find it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.panel import fit
from hidden_options.predict.inference import (
    PermutationResult,
    permutation_test,
    permute_within,
    two_way_residuals,
)
from hidden_options.predict.panel import (
    CONTROLS,
    HORIZONS,
    INNOVATION_WINDOW,
    build_predictive_panel,
    join_outcomes,
    session_frame,
)
from hidden_options.predict.regressions import (
    MAIN_OUTCOME,
    MAIN_PREDICTOR,
    PLACEBO_PREDICTOR,
    TABLE_SPECS,
    PredictiveRow,
    estimate,
    horizon_rows,
    run_predictive,
    timing_row,
    top_decile_row,
    window_robustness,
)
from predict_stub import noise_panel, session_table, synthetic_bars, synthetic_daily

DAILY = synthetic_daily(names=8, dates=90)
BARS = synthetic_bars(DAILY)


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return build_predictive_panel(DAILY, BARS, min_history=20)


class TestOutcomeTiming:
    def test_predictor_meets_return_on_available_at(self, panel):
        sessions = session_table(BARS)
        expected = [
            abs(sessions.loc[(row.symbol, row.available_at), "ret"]) for row in panel.itertuples()
        ]
        assert panel["abs_ret_next"].to_numpy() == pytest.approx(expected)
        assert (panel["available_at"] > panel["date"]).all()

        # Bars dated one session later carry different returns on each date, so the join
        # must change with them. A join that ignored the dates would not notice.
        shifted = BARS.assign(timestamp=BARS["timestamp"] + pd.offsets.BDay(1))
        moved = build_predictive_panel(DAILY, shifted, min_history=20)
        both = panel.merge(moved, on=["symbol", "date"], suffixes=("", "_moved"))
        assert len(both) > 100
        assert not np.allclose(both["abs_ret_next"], both["abs_ret_next_moved"])

    def test_a_late_report_waits_for_its_availability_date(self):
        """No report on 2025-03-05: the report for 03-04 is first usable on 03-06, so it
        meets the return realised on 03-06, not the one realised on 03-05."""
        calendar = pd.bdate_range("2025-01-02", periods=90).drop(pd.Timestamp("2025-03-05"))
        daily = synthetic_daily(names=4, calendar=calendar)
        built = build_predictive_panel(daily, synthetic_bars(daily), min_history=20)
        sessions = session_table(synthetic_bars(daily))

        row = built[built["date"] == pd.Timestamp("2025-03-04")].iloc[0]
        assert row["available_at"] == pd.Timestamp("2025-03-06")
        realised = sessions.loc[(row["symbol"], pd.Timestamp("2025-03-06")), "ret"]
        assert row["abs_ret_next"] == pytest.approx(abs(realised))

    def test_lookahead_join_is_rejected(self):
        frame = pd.DataFrame(
            {
                "symbol": ["N00"],
                "date": [pd.Timestamp("2025-03-04")],
                "available_at": [pd.Timestamp("2025-03-05")],
            }
        )
        outcomes = session_frame(BARS)
        with pytest.raises(ValueError, match="after the activity date"):
            join_outcomes(frame, outcomes, at="date")

    def test_a_row_usable_on_its_own_activity_date_is_rejected(self):
        frame = pd.DataFrame(
            {
                "symbol": ["N00", "N00"],
                "date": pd.to_datetime(["2025-03-04", "2025-03-05"]),
                "available_at": pd.to_datetime(["2025-03-05", "2025-03-05"]),
            }
        )
        with pytest.raises(ValueError, match="2025-03-05"):
            join_outcomes(frame, session_frame(BARS))

    def test_controls_are_known_by_the_close_of_the_activity_date(self, panel):
        sessions = session_table(BARS)
        row = panel.iloc[len(panel) // 2]
        history = sessions.loc[row["symbol"]]
        before = history.loc[: row["date"]].iloc[:-1]
        assert row["abs_ret"] == pytest.approx(abs(history.loc[row["date"], "ret"]))
        assert row["rv5"] == pytest.approx(before["ret"].abs().iloc[-5:].mean())
        assert row["rv22"] == pytest.approx(before["ret"].abs().iloc[-22:].mean())
        dollar_volume = history.loc[row["date"], "close"] * history.loc[row["date"], "volume"]
        assert row["log_dv"] == pytest.approx(np.log(dollar_volume))

    def test_open_to_close_outcome_is_the_availability_session_alone(self, panel):
        sessions = session_table(BARS)
        row = panel.iloc[10]
        bar = sessions.loc[(row["symbol"], row["available_at"])]
        assert row["oc_abs_next"] == pytest.approx(abs(bar["close"] / bar["open"] - 1))

    def test_horizon_outcomes_average_sessions_from_availability(self, panel):
        sessions = session_table(BARS)
        row = panel.iloc[10]
        future = sessions.loc[row["symbol"]].loc[row["available_at"] :, "ret"].abs()
        for days in HORIZONS:
            assert row[f"abs_ret_next_{days}d"] == pytest.approx(future.iloc[:days].mean())

    def test_horizons_that_run_past_the_bars_are_missing(self):
        """Three sessions of bars after the last date: enough for next day, not ten."""
        short = build_predictive_panel(DAILY, synthetic_bars(DAILY, tail=3), min_history=20)
        last = short[short["date"] == short["date"].max()]
        assert len(last) > 0
        assert last["abs_ret_next"].notna().all()
        assert last["abs_ret_next_3d"].notna().all()
        assert last["abs_ret_next_5d"].isna().all()
        assert last["abs_ret_next_10d"].isna().all()

    def test_bars_with_two_rows_for_one_session_are_refused(self):
        doubled = pd.concat([BARS, BARS.iloc[:1]], ignore_index=True)
        with pytest.raises(ValueError, match="more than one bar"):
            session_frame(doubled)


class TestPredictors:
    def test_innovation_is_the_level_less_its_trailing_mean(self, panel):
        name = panel["symbol"].iloc[0]
        levels = np.log(
            DAILY[DAILY["underlying"] == name].set_index("report_date")["open_interest"]
        )
        row = panel[panel["symbol"] == name].iloc[30]
        previous = levels.loc[: row["date"]].iloc[:-1].iloc[-INNOVATION_WINDOW:]
        assert row["oi_innov"] == pytest.approx(levels.loc[row["date"]] - previous.mean())

    def test_a_change_across_a_missing_date_is_not_used(self):
        """N00 skips 2025-03-05 while the others report: its 03-06 change spans two days."""
        daily = synthetic_daily(names=4, dates=90, skip={"N00": ["2025-03-05"]})
        built = build_predictive_panel(daily, synthetic_bars(daily), min_history=20)
        n00 = built[built["symbol"] == "N00"].set_index("date")
        assert pd.Timestamp("2025-03-06") not in n00.index
        assert pd.Timestamp("2025-03-07") in n00.index
        others = built[built["symbol"] == "N01"].set_index("date")
        assert pd.Timestamp("2025-03-06") in others.index

    def test_inventory_change_and_shares_come_from_the_activity_date(self, panel):
        name = panel["symbol"].iloc[0]
        own = DAILY[DAILY["underlying"] == name].set_index("report_date")
        row = panel[panel["symbol"] == name].iloc[12]
        today, yesterday = own.loc[row["date"]], own.loc[: row["date"]].iloc[-2]
        assert row["d_log_oi"] == pytest.approx(
            np.log(today["open_interest"]) - np.log(yesterday["open_interest"])
        )
        assert row["put_share"] == pytest.approx(
            today["put_open_interest"] / today["open_interest"]
        )
        near = today["near_dated_open_interest"] / today["open_interest"]
        near_before = yesterday["near_dated_open_interest"] / yesterday["open_interest"]
        assert row["d_near_share"] == pytest.approx(near - near_before)

    def test_placebo_is_inventory_dated_after_the_outcome(self, panel):
        calendar = pd.DatetimeIndex(sorted(DAILY["report_date"].unique()))
        name = panel["symbol"].iloc[0]
        own = panel[panel["symbol"] == name].set_index("date")
        row_date = own.index[15]
        later = calendar[calendar.get_loc(row_date) + 2]
        assert later > own.loc[row_date, "available_at"]
        assert own.loc[row_date, "oi_innov_placebo"] == pytest.approx(own.loc[later, "oi_innov"])

    def test_the_last_two_dates_have_no_placebo(self, panel):
        calendar = sorted(DAILY["report_date"].unique())
        tail = panel[panel["date"].isin(calendar[-2:])]
        assert len(tail) > 0
        assert tail["oi_innov_placebo"].isna().all()

    def test_short_histories_are_dropped(self):
        assert build_predictive_panel(DAILY, BARS, min_history=200).empty

    def test_an_underlying_without_bars_drops_out(self):
        bars = BARS[BARS["symbol"] != "N03"]
        built = build_predictive_panel(DAILY, bars, min_history=20)
        assert "N03" not in set(built["symbol"])
        assert len(set(built["symbol"])) == 7

    def test_controls_are_the_four_the_design_names(self):
        assert CONTROLS == ("rv5", "rv22", "abs_ret", "log_dv")


class TestRegressions:
    def test_six_table_rows_in_the_published_order(self, panel):
        rows = run_predictive(panel)
        assert [(r.predictor, r.outcome, r.placebo) for r in rows] == list(TABLE_SPECS)
        assert [r.placebo for r in rows] == [False] * 5 + [True]
        assert rows[0].predictor == MAIN_PREDICTOR and rows[0].outcome == MAIN_OUTCOME
        assert rows[-1].predictor == PLACEBO_PREDICTOR

    def test_a_row_is_the_fixed_effects_estimate_with_the_controls(self, panel):
        row = estimate(panel, "d_log_oi", "abs_ret_next")
        est = fit(panel, "abs_ret_next", ["d_log_oi", *CONTROLS])["d_log_oi"]
        assert isinstance(row, PredictiveRow)
        assert row.coefficient == est.coefficient
        assert row.std_error == est.std_error
        assert row.t_stat == est.t_stat
        assert row.mde80 == est.mde80
        assert (row.ci_low, row.ci_high) == est.ci95
        assert row.n_obs == est.n_obs
        assert (row.n_underlyings, row.n_dates) == (est.n_names, est.n_dates)

    def test_horizons_are_values_for_the_main_predictor(self, panel):
        rows = horizon_rows(panel)
        assert [r.outcome for r in rows] == [f"abs_ret_next_{d}d" for d in HORIZONS]
        assert {r.predictor for r in rows} == {MAIN_PREDICTOR}

    def test_top_decile_keeps_the_largest_tenth_of_inventory_changes(self, panel):
        row, threshold = top_decile_row(panel)
        complete = panel.dropna(subset=[MAIN_PREDICTOR, MAIN_OUTCOME, *CONTROLS])
        kept = complete[complete["d_log_oi"].abs() >= threshold]
        assert row.n_obs == len(kept)
        assert len(kept) == pytest.approx(0.1 * len(complete), abs=2)

    def test_timing_row_uses_the_open_to_close_outcome(self, panel):
        row = timing_row(panel)
        assert (row.predictor, row.outcome) == (MAIN_PREDICTOR, "oc_abs_next")

    def test_window_robustness_gives_the_main_row_and_its_placebo_per_start(self):
        starts = ["2025-01-02", "2025-02-03"]
        rows = window_robustness(DAILY, BARS, starts, min_history=20)
        assert [(r.predictor, r.placebo) for r in rows] == [
            (MAIN_PREDICTOR, False),
            (PLACEBO_PREDICTOR, True),
        ] * 2
        assert rows[2].n_obs < rows[0].n_obs

    def test_a_window_loads_the_panel_from_its_start(self):
        """The innovation's trailing mean restarts with the window, as if loaded from it."""
        late = build_predictive_panel(DAILY[DAILY["report_date"] >= "2025-02-03"], BARS)
        rows = window_robustness(DAILY, BARS, ["2025-02-03"])
        assert rows[0] == estimate(late, MAIN_PREDICTOR, MAIN_OUTCOME)


class TestPermutation:
    def test_permutation_null_centred_on_zero_for_noise(self):
        result = permutation_test(noise_panel(), "y", "x", ["c1", "c2"], n_perm=300)
        assert isinstance(result, PermutationResult)
        assert abs(result.null.mean()) < 0.1 * result.null.std()
        assert result.p_value > 0.05

    def test_permutation_detects_planted_effect(self):
        result = permutation_test(noise_panel(beta=0.1), "y", "x", ["c1", "c2"], n_perm=300)
        assert result.observed == pytest.approx(0.1, abs=0.03)
        assert result.p_value < 0.01

    def test_observed_is_the_fixed_effects_coefficient(self):
        frame = noise_panel(beta=0.05).sample(frac=0.8, random_state=1)  # unbalanced
        result = permutation_test(frame, "y", "x", ["c1", "c2"], n_perm=10)
        est = fit(frame, "y", ["x", "c1", "c2"])["x"]
        assert result.observed == pytest.approx(est.coefficient, rel=1e-6)

    def test_draws_are_reproducible_from_the_seed(self):
        frame = noise_panel()
        first = permutation_test(frame, "y", "x", ["c1"], n_perm=50, seed=5)
        again = permutation_test(frame, "y", "x", ["c1"], n_perm=50, seed=5)
        other = permutation_test(frame, "y", "x", ["c1"], n_perm=50, seed=6)
        assert np.array_equal(first.null, again.null)
        assert not np.array_equal(first.null, other.null)
        assert len(first.null) == 50

    def test_p_value_counts_the_observed_estimate_among_the_draws(self):
        result = permutation_test(noise_panel(beta=1.0), "y", "x", ["c1"], n_perm=40)
        assert result.p_value == pytest.approx(1 / 41)

    def test_missing_rows_are_left_out_before_permuting(self):
        frame = noise_panel()
        frame.loc[frame.index[:25], "x"] = np.nan
        result = permutation_test(frame, "y", "x", ["c1", "c2"], n_perm=20)
        assert result.n_obs == len(frame) - 25

    def test_a_missing_column_is_named(self):
        with pytest.raises(ValueError, match="nope"):
            permutation_test(noise_panel(), "y", "nope", ["c1"], n_perm=5)

    def test_permute_within_moves_values_only_inside_their_group(self):
        rng = np.random.default_rng(0)
        groups = np.array([0, 1, 0, 2, 1, 0, 2, 2, 1, 0])
        values = np.arange(10.0)
        moved = permute_within(values, groups, rng)
        for group in np.unique(groups):
            assert sorted(moved[groups == group]) == sorted(values[groups == group])
        assert not np.array_equal(moved, values)

    def test_two_way_residuals_match_alternating_projection(self):
        from hidden_options.measure.panel import partial_out_two_way

        frame = noise_panel().sample(frac=0.7, random_state=2).reset_index(drop=True)
        exact = two_way_residuals(frame["symbol"], frame["date"], frame[["y", "x"]].to_numpy())
        iterated = partial_out_two_way(
            frame, ["y", "x"], entity="symbol", time="date", iterations=500
        )
        assert exact == pytest.approx(iterated.to_numpy(), abs=1e-8)
