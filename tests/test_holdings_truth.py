"""Disclosed holdings as truth for the structure detector: which files count, and the score."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.holdings_truth import (
    ValidationScore,
    floor_check,
    globalx_overlap,
    holdings_structures,
    load_fund_holdings,
    load_globalx_options,
    score_against_holdings,
    score_by_date,
)
from hidden_options.measure.structures import group_legs

MON, TUE, WED = pd.Timestamp("2026-09-14"), pd.Timestamp("2026-09-15"), pd.Timestamp("2026-09-16")
EXPIRY = pd.Timestamp("2026-11-20")
FLEX_DATES = [MON, TUE, WED]


def _holding(fund, as_of, root, right, strike, contracts, *, expiry=EXPIRY, captured=None):
    return {
        "fund": fund,
        "as_of": as_of,
        "capture_date": as_of if captured is None else captured,
        "option_root": root,
        "expiry": expiry,
        "right": right,
        "strike": strike,
        "contracts": contracts,
    }


def _synthetic(fund="AAAY", as_of=TUE, root="2AAA", strike=50.0, size=1000.0, **kwargs):
    return [
        _holding(fund, as_of, root, "C", strike, size, **kwargs),
        _holding(fund, as_of, root, "P", strike, -size, **kwargs),
    ]


def _report(rows, day=MON):
    """rows: (root, right, strike, open interest), as `legs_with_ids` needs them."""
    frame = pd.DataFrame(rows, columns=["root", "right", "strike", "contracts"])
    return frame.assign(
        report_date=day, underlying=frame["root"].str.lstrip("0123456789"), expiry=EXPIRY
    )


def _detected(rows, day=MON):
    legs, _ = group_legs(_report(rows, day), {"AAA": 50.0, "BBB": 20.0})
    return legs


class TestHoldingsStructures:
    def test_legs_of_one_fund_underlying_and_expiry_form_a_structure(self):
        truth = holdings_structures(pd.DataFrame(_synthetic()), FLEX_DATES)
        assert len(truth) == 2
        assert truth["truth_id"].nunique() == 1
        assert (truth["n_legs"] == 2).all()
        assert (truth["structure"] == "synthetic").all()
        assert (truth["underlying"] == "AAA").all()

    def test_a_file_shows_the_settlement_before_its_as_of_date(self):
        truth = holdings_structures(pd.DataFrame(_synthetic(as_of=TUE)), FLEX_DATES)
        assert (truth["report_date"] == MON).all()
        assert (truth["as_of"] == TUE).all()

    def test_it_can_be_set_against_the_as_of_date_itself(self):
        truth = holdings_structures(pd.DataFrame(_synthetic(as_of=TUE)), FLEX_DATES, same_day=True)
        assert (truth["report_date"] == TUE).all()

    def test_holdings_join_excludes_stale_as_of(self):
        """A file whose as_of is four business days behind its capture is out, and counted."""
        stale_as_of = TUE - pd.tseries.offsets.BDay(4)
        rows = [
            *_synthetic("OLDY", as_of=stale_as_of, captured=TUE),
            *_synthetic("NEWY", as_of=TUE),
        ]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES, max_staleness_bdays=3)
        assert set(truth["fund"]) == {"NEWY"}
        assert truth.attrs["stale_files"] == 1
        assert truth.attrs["files"] == 2

    def test_a_file_three_business_days_old_stays(self):
        as_of = TUE - pd.tseries.offsets.BDay(3)
        rows = _synthetic("OKAY", as_of=as_of, captured=TUE)
        dates = [as_of - pd.tseries.offsets.BDay(1), *FLEX_DATES]
        truth = holdings_structures(pd.DataFrame(rows), dates, max_staleness_bdays=3)
        assert set(truth["fund"]) == {"OKAY"}
        assert truth.attrs["stale_files"] == 0

    def test_a_file_far_past_the_last_report_is_stale_too(self):
        as_of = WED + pd.tseries.offsets.BDay(4)
        truth = holdings_structures(
            pd.DataFrame(_synthetic(as_of=as_of)), FLEX_DATES, max_staleness_bdays=3
        )
        assert truth.empty
        assert truth.attrs["stale_files"] == 1

    def test_a_file_before_every_report_is_stale(self):
        truth = holdings_structures(pd.DataFrame(_synthetic(as_of=MON)), FLEX_DATES)
        assert truth.empty
        assert truth.attrs["stale_files"] == 1

    def test_a_file_captured_twice_counts_once_and_stale_captures_do_not_condemn_it(self):
        later = TUE + pd.tseries.offsets.BDay(10)
        rows = [*_synthetic(captured=TUE), *_synthetic(captured=later)]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES)
        assert len(truth) == 2
        assert truth.attrs["stale_files"] == 0

    def test_listed_legs_are_left_out_and_a_lone_flex_leg_is_kept_as_one_leg(self):
        rows = [
            _holding("AAAY", TUE, "AAA", "C", 55.0, -100.0),
            _holding("AAAY", TUE, "2AAA", "P", 50.0, -100.0),
        ]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES)
        assert list(truth["root"]) == ["2AAA"]
        assert list(truth["n_legs"]) == [1]

    def test_the_same_structure_keeps_its_id_across_dates(self):
        rows = [*_synthetic(as_of=TUE), *_synthetic(as_of=WED)]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES)
        assert truth["truth_id"].nunique() == 1
        assert truth["report_date"].nunique() == 2

    def test_nothing_to_score_gives_typed_frame(self):
        rows = pd.DataFrame([_holding("AAAY", TUE, "AAA", "C", 55.0, -100.0)])
        truth = holdings_structures(rows, FLEX_DATES)
        assert truth.empty
        assert "truth_id" in truth.columns


PAIR = [("2AAA", "C", 50.0, 1000), ("2AAA", "P", 50.0, 1000)]


class TestScore:
    def test_score_perfect_and_disjoint(self):
        truth = holdings_structures(pd.DataFrame(_synthetic()), FLEX_DATES)
        perfect = score_against_holdings(_detected(PAIR), truth)
        assert isinstance(perfect, ValidationScore)
        assert perfect.precision == 1.0
        assert perfect.recall == 1.0
        assert perfect.type_agreement == 1.0
        assert perfect.n_truth_structures == 1
        assert perfect.n_detected_touching == 1

        elsewhere = _detected([("2BBB", "C", 20.0, 1000), ("2BBB", "P", 20.0, 1000)])
        disjoint = score_against_holdings(elsewhere, truth)
        assert disjoint.precision == 0.0
        assert disjoint.recall == 0.0
        assert disjoint.type_agreement is None
        assert disjoint.n_detected_touching == 0

    def test_legs_grouped_apart_score_zero_though_they_touch(self):
        truth = holdings_structures(pd.DataFrame(_synthetic()), FLEX_DATES)
        apart = _detected(
            [
                ("2AAA", "C", 50.0, 1000),
                ("2AAA", "C", 60.0, 1000),
                ("2AAA", "P", 50.0, 5000),
                ("2AAA", "P", 40.0, 5000),
            ]
        )
        score = score_against_holdings(apart, truth)
        assert score.recall == 0.0
        assert score.precision == 0.0
        assert score.n_detected_touching == 2

    def test_a_structure_with_an_undisclosed_extra_leg_is_grouped_but_of_another_type(self):
        truth = holdings_structures(pd.DataFrame(_synthetic()), FLEX_DATES)
        extra = _detected([*PAIR, ("2AAA", "C", 70.0, 1000)])
        score = score_against_holdings(extra, truth)
        assert score.recall_grouped == 1.0
        assert score.recall == 0.0
        assert score.type_agreement == 0.0
        assert score.precision == 1.0
        assert score.precision_exact == 0.0

    def test_a_lone_holding_touches_a_structure_without_confirming_it(self):
        rows = [_holding("AAAY", TUE, "2AAA", "C", 50.0, 1000.0)]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES)
        score = score_against_holdings(_detected(PAIR), truth)
        assert score.n_truth_structures == 0
        assert score.n_detected_touching == 1
        assert score.precision == 0.0

    def test_each_structure_counts_once_however_many_dates_it_lasts(self):
        """Persisting positions are not independent evidence."""
        rows = [
            *_synthetic("AAAY", as_of=TUE),
            *_synthetic("AAAY", as_of=WED),
            *_synthetic("BBBY", as_of=TUE, root="2BBB", strike=20.0),
        ]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES)
        monday = _report(
            [*PAIR, ("2BBB", "C", 20.0, 900), ("2BBB", "P", 20.0, 100)],
            MON,
        )
        tuesday = _report(PAIR, TUE)
        legs = pd.concat(
            [
                group_legs(monday, {"AAA": 50.0, "BBB": 20.0})[0],
                group_legs(tuesday, {"AAA": 50.0, "BBB": 20.0})[0],
            ],
            ignore_index=True,
        )
        score = score_against_holdings(legs, truth)
        assert score.n_truth_structures == 2
        assert score.n_structure_dates == 3
        # AAA recovered on both dates, BBB on neither: one of two structures, not two of three.
        assert score.recall == pytest.approx(0.5)

    def test_a_structure_found_on_some_dates_scores_its_share_of_them(self):
        rows = [*_synthetic(as_of=TUE), *_synthetic(as_of=WED)]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES)
        apart = _report([("2AAA", "C", 50.0, 900), ("2AAA", "P", 50.0, 100)], TUE)
        legs = pd.concat(
            [_detected(PAIR, MON), group_legs(apart, {"AAA": 50.0})[0]], ignore_index=True
        )
        assert score_against_holdings(legs, truth).recall == pytest.approx(0.5)

    def test_it_states_how_many_funds_and_underlyings_the_score_rests_on(self):
        rows = [
            *_synthetic("AAAY"),
            *_synthetic("BBBY"),
            *_synthetic("CCCY", root="2BBB", strike=20.0),
        ]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES)
        score = score_against_holdings(_detected(PAIR), truth)
        assert score.n_funds == 3
        assert score.n_underlyings == 2
        assert score.n_truth_structures == 3

    def test_by_date_scores_each_date_alone(self):
        rows = [*_synthetic(as_of=TUE), *_synthetic(as_of=WED)]
        truth = holdings_structures(pd.DataFrame(rows), FLEX_DATES)
        apart = _report([("2AAA", "C", 50.0, 900), ("2AAA", "P", 50.0, 100)], TUE)
        legs = pd.concat(
            [_detected(PAIR, MON), group_legs(apart, {"AAA": 50.0})[0]], ignore_index=True
        )
        daily = score_by_date(legs, truth)
        assert list(daily["report_date"]) == [MON, TUE]
        assert list(daily["recall"]) == [1.0, 0.0]


class TestFloorCheck:
    def test_counts_legs_whose_open_interest_covers_the_holding(self):
        truth = holdings_structures(pd.DataFrame(_synthetic()), FLEX_DATES)
        report = _report([("2AAA", "C", 50.0, 1000), ("2AAA", "P", 50.0, 999)]).rename(
            columns={"contracts": "open_interest"}
        )
        check = floor_check(truth, report)
        assert check == {"legs": 2, "found": 2, "covered": 1}

    def test_a_leg_missing_from_the_report_is_not_found(self):
        truth = holdings_structures(pd.DataFrame(_synthetic()), FLEX_DATES)
        report = _report([("2AAA", "C", 50.0, 1000)]).rename(columns={"contracts": "open_interest"})
        assert floor_check(truth, report) == {"legs": 2, "found": 1, "covered": 1}


class TestLoaders:
    def test_fund_files_are_read_with_their_capture_date_and_only_option_rows(self, tmp_path: Path):
        folder = tmp_path / "fund_holdings/date=2026-09-15"
        folder.mkdir(parents=True)
        rows = pd.DataFrame(
            {
                "fund": ["AAAY", "AAAY"],
                "as_of": [TUE.date(), TUE.date()],
                "is_option": [True, False],
                "option_root": ["2AAA", None],
                "expiry": [EXPIRY.date(), None],
                "right": ["C", None],
                "strike": [50.0, np.nan],
                "contracts": [10.0, 500.0],
            }
        )
        rows.to_parquet(folder / "AAAY.parquet")
        loaded = load_fund_holdings([tmp_path])
        assert len(loaded) == 1
        assert loaded["capture_date"].iloc[0] == TUE
        assert loaded["as_of"].iloc[0] == TUE
        assert loaded["expiry"].iloc[0] == EXPIRY

    def test_an_empty_folder_is_refused(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="fund_holdings"):
            load_fund_holdings([tmp_path])

    def test_globalx_option_lines_are_parsed_and_the_as_of_read_from_the_header(
        self, tmp_path: Path
    ):
        folder = tmp_path / "globalx_holdings/date=2025-03-14"
        folder.mkdir(parents=True)
        (folder / "XYLD.csv").write_text(
            "Global X S&P 500 Covered Call ETF\n"
            "Fund Holdings Data as of 03/14/2025\n"
            "% of Net Assets,Ticker,Name,SEDOL,Market Price ($),Shares Held,Market Value ($)\n"
            '1.0,AAPL,APPLE INC,2046251,200.0,"1,000.00","200,000.00"\n'
            '-0.01,"",SPX US 03/21/25 C6085,"",32.5,"-5,428.00","-176,410.00"\n'
            '"The information contained herein may not be reproduced."\n'
        )
        options = load_globalx_options(tmp_path)
        assert len(options) == 1
        row = options.iloc[0]
        assert (row["fund"], row["underlying"], row["right"]) == ("XYLD", "SPX", "C")
        assert row["strike"] == 6085.0
        assert row["contracts"] == -5428.0
        assert row["as_of"] == pd.Timestamp("2025-03-14")
        assert row["expiry"] == pd.Timestamp("2025-03-21")
        assert row["capture_date"] == pd.Timestamp("2025-03-14")

    def test_globalx_overlap_counts_legs_on_the_flex_report_and_multi_leg_holdings(self):
        options = pd.DataFrame(
            {
                "fund": ["XYLD", "XYLD", "QYLD"],
                "as_of": [TUE, TUE, TUE],
                "underlying": ["SPX", "SPX", "NDX"],
                "expiry": [EXPIRY, EXPIRY, EXPIRY],
                "right": ["C", "C", "C"],
                "strike": [6000.0, 6100.0, 20000.0],
                "contracts": [-1.0, -1.0, -1.0],
            }
        )
        report = pd.DataFrame(
            {
                "report_date": [MON],
                "underlying": ["SPX"],
                "expiry": [EXPIRY],
                "right": ["C"],
                "strike": [6000.0],
            }
        )
        overlap = globalx_overlap(options, report, FLEX_DATES)
        assert overlap["fund_dates"] == 2
        assert overlap["legs"] == 3
        assert overlap["legs_on_flex_report"] == 1
        assert overlap["multi_leg_holdings"] == 1


def test_fund_intervals_collapse_on_a_perfect_score_and_bound_the_point():
    from hidden_options.measure.holdings_truth import fund_intervals

    truth = holdings_structures(pd.DataFrame(_synthetic()), FLEX_DATES)
    perfect = fund_intervals(_detected(PAIR), truth, n_boot=200, seed=1)
    assert perfect["recall_low"] == perfect["recall_high"] == 1.0
    assert perfect["precision_low"] == perfect["precision_high"] == 1.0
    assert perfect["funds"] == 1
