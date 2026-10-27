"""Implied volatility and greeks from OCC's FLEX marks (M5)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hidden_options.measure.implied import (
    GREEK_COLUMNS,
    MONEYNESS_BINS,
    RATE,
    SIGMA_BOUNDS,
    InversionStatus,
    bucket,
    bucketed,
    buckets,
    compare_with_listed,
    greeks,
    implied_vol,
    implied_vols,
    inversion_style,
    listed_twin,
    validated_domain,
)
from hidden_options.measure.pricing import binomial, black_scholes

DAY = pd.Timestamp("2026-09-01")
SPOT = 100.0
HALF_YEAR = pd.Timedelta(days=182)
HALF = 182 / 365


def model_price(strike, years, sigma, right, style, *, spot=SPOT, carry=0.0, rate=RATE):
    """What the model says a contract is worth, the input every round trip starts from."""
    args = [np.array([value], dtype=float) for value in (spot, strike, years, sigma)]
    pricer = binomial if style == "american" else black_scholes
    return float(pricer(*args, rate=rate, carry=carry, is_call=right == "C")[0])


def row(**fields):
    """One FLEX report row on DAY: AAA, a one-year European call at 100, unless told otherwise."""
    base = {
        "report_date": DAY,
        "kind": "equity",
        "class_name": "AAA INC (EURO/FLEX)",
        "root": "2AAA",
        "underlying": "AAA",
        "right": "C",
        "expiry": DAY + pd.Timedelta(days=365),
        "strike": 100.0,
        "mark_price": model_price(100.0, 1.0, 0.3, "C", "european"),
        "open_interest": 10,
        "exercise_style": "european",
    }
    return {**base, **fields}


def frame(*rows):
    panel = pd.DataFrame(list(rows))
    panel["exercise_style"] = panel["exercise_style"].astype(object)
    return panel


class TestImpliedVol:
    @pytest.mark.parametrize("right", ["C", "P"])
    @pytest.mark.parametrize("carry", [0.0, 0.02])
    @pytest.mark.parametrize(("strike", "years"), [(100.0, 0.25), (85.0, 2.0), (120.0, 0.5)])
    def test_european_roundtrip(self, right, carry, strike, years):
        price = model_price(strike, years, 0.3, right, "european", carry=carry)
        iv, status = implied_vol(
            price, SPOT, strike, years, rate=RATE, carry=carry, right=right, style="european"
        )
        assert status is InversionStatus.OK
        assert iv == pytest.approx(0.3, abs=1e-6)

    @pytest.mark.parametrize("strike", [80.0, 100.0, 125.0])
    def test_american_roundtrip(self, strike):
        price = model_price(strike, 0.5, 0.4, "P", "american")
        iv, status = implied_vol(
            price, SPOT, strike, 0.5, rate=RATE, carry=0.0, right="P", style="american"
        )
        assert status is InversionStatus.OK
        assert iv == pytest.approx(0.4, abs=1e-6)

    def test_american_put_above_european(self):
        american = model_price(110.0, 1.0, 0.3, "P", "american")
        european = model_price(110.0, 1.0, 0.3, "P", "european")
        assert american > european
        # Read as European, the early-exercise premium passes for extra volatility.
        as_european, _ = implied_vol(
            american, SPOT, 110.0, 1.0, rate=RATE, carry=0.0, right="P", style="european"
        )
        as_american, _ = implied_vol(
            american, SPOT, 110.0, 1.0, rate=RATE, carry=0.0, right="P", style="american"
        )
        assert as_american == pytest.approx(0.3, abs=1e-6)
        assert as_european > as_american

    def test_an_american_call_without_carry_inverts_as_its_european_twin(self):
        price = model_price(95.0, 1.0, 0.25, "C", "european")
        kwargs = {"rate": RATE, "carry": 0.0, "right": "C"}
        american = implied_vol(price, SPOT, 95.0, 1.0, style="american", **kwargs)
        european = implied_vol(price, SPOT, 95.0, 1.0, style="european", **kwargs)
        assert american == european

    def test_implied_vol_returns_nan_with_reason_below_intrinsic(self):
        # An American put struck at 100 on a spot of 80 pays 20 now; a mark of 19.5 is less.
        iv, status = implied_vol(
            19.5, 80.0, 100.0, 1.0, rate=RATE, carry=0.0, right="P", style="american"
        )
        assert status is InversionStatus.BELOW_INTRINSIC
        assert math.isnan(iv)
        # A European call is worth at least spot less the discounted strike, 23.14 here.
        iv, status = implied_vol(
            22.0, 100.0, 80.0, 1.0, rate=RATE, carry=0.0, right="C", style="european"
        )
        assert status is InversionStatus.BELOW_INTRINSIC
        assert math.isnan(iv)

    @pytest.mark.parametrize(
        ("price", "spot", "years", "expected"),
        [
            (5.0, SPOT, 0.0, InversionStatus.EXPIRED),
            (5.0, SPOT, -0.01, InversionStatus.EXPIRED),
            (0.0, SPOT, 1.0, InversionStatus.ZERO_PRICE),
            (float("nan"), SPOT, 1.0, InversionStatus.ZERO_PRICE),
            (5.0, float("nan"), 1.0, InversionStatus.NO_SPOT),
            (5.0, 0.0, 1.0, InversionStatus.NO_SPOT),
            # A call is never worth more than the spot; no volatility in the bracket fits.
            (150.0, SPOT, 1.0, InversionStatus.NO_CONVERGENCE),
            # Order of precedence: expiry, then the mark, then the spot.
            (0.0, float("nan"), 0.0, InversionStatus.EXPIRED),
            (0.0, float("nan"), 1.0, InversionStatus.ZERO_PRICE),
        ],
    )
    def test_reason_codes(self, price, spot, years, expected):
        iv, status = implied_vol(
            price, spot, 100.0, years, rate=RATE, carry=0.0, right="C", style="european"
        )
        assert status is expected
        assert math.isnan(iv)

    def test_a_mark_at_the_floor_inverts_to_the_bottom_of_the_bracket(self):
        floor = model_price(50.0, 1.0, SIGMA_BOUNDS[0], "C", "european")
        iv, status = implied_vol(
            floor, SPOT, 50.0, 1.0, rate=RATE, carry=0.0, right="C", style="european"
        )
        assert (iv, status) == (SIGMA_BOUNDS[0], InversionStatus.OK)

    def test_unknown_right_or_style_is_refused(self):
        with pytest.raises(ValueError, match="right"):
            implied_vol(5.0, SPOT, 100.0, 1.0, rate=RATE, carry=0.0, right="X", style="european")
        with pytest.raises(ValueError, match="style"):
            implied_vol(5.0, SPOT, 100.0, 1.0, rate=RATE, carry=0.0, right="C", style="bermudan")


class TestImpliedVols:
    def rows(self):
        put_mark = model_price(110.0, HALF, 0.35, "P", "american")
        return frame(
            row(),  # European call, sigma 0.3
            row(right="P", strike=90.0, mark_price=model_price(90.0, 1.0, 0.45, "P", "european")),
            row(
                class_name="AAA INC (AMER/FLEX)",
                root="1AAA",
                exercise_style="american",
                right="P",
                strike=110.0,
                expiry=DAY + HALF_YEAR,
                mark_price=put_mark,
            ),
            # Unmarked: inverted as American under the default.
            row(
                class_name="AAA INC",
                exercise_style=None,
                right="P",
                strike=110.0,
                expiry=DAY + HALF_YEAR,
                mark_price=put_mark,
            ),
            row(
                kind="index",
                class_name="S&P 500 INDEX",
                root="4SPX",
                underlying="SPX",
                strike=5000.0,
                mark_price=model_price(5000.0, 1.0, 0.2, "C", "european", spot=5100.0),
            ),
            row(expiry=DAY),  # expires today
            row(mark_price=0.0),
            row(underlying="NOSPOT"),
            row(right="P", strike=150.0, mark_price=10.0),  # below the European floor
            row(mark_price=500.0),  # above any call price
        )

    SPOTS = {"AAA": SPOT, "SPX": 5100.0}

    def test_matches_the_scalar_inversion_row_by_row(self):
        panel = self.rows()
        inverted = implied_vols(panel, self.SPOTS, rate=RATE)
        for _, line in inverted.iterrows():
            iv, status = implied_vol(
                line["mark_price"],
                self.SPOTS.get(line["underlying"], float("nan")),
                line["strike"],
                (line["expiry"] - line["report_date"]).days / 365,
                rate=RATE,
                carry=0.0,
                right=line["right"],
                style=line["inverted_as"],
            )
            assert line["iv_status"] == status
            if status is InversionStatus.OK:
                assert line["iv"] == pytest.approx(iv, abs=1e-6)
            else:
                assert math.isnan(line["iv"])

    def test_every_row_gets_a_status_and_keeps_its_place(self):
        panel = self.rows().set_index(pd.Index(range(10, 20)))
        inverted = implied_vols(panel, self.SPOTS, rate=RATE)
        assert inverted.index.equals(panel.index)
        assert inverted["iv_status"].tolist() == [
            "ok",
            "ok",
            "ok",
            "ok",
            "ok",
            "expired",
            "zero_price",
            "no_spot",
            "below_intrinsic",
            "no_convergence",
        ]
        assert inverted["iv"].iloc[:2].tolist() == pytest.approx([0.3, 0.45], abs=1e-6)
        assert inverted["iv"].iloc[2] == pytest.approx(0.35, abs=1e-6)
        assert inverted["spot"].iloc[4] == 5100.0
        assert inverted["years"].iloc[0] == 1.0

    def test_unmarked_equity_rows_are_inverted_as_american(self):
        inverted = implied_vols(self.rows(), self.SPOTS, rate=RATE)
        assert inverted["inverted_as"].tolist()[:5] == [
            "european",
            "european",
            "american",
            "american",
            "european",
        ]
        # Same mark, same contract: the unmarked row inverts exactly as the marked American.
        assert inverted["iv"].iloc[3] == inverted["iv"].iloc[2]

    def test_inversion_style(self):
        panel = frame(
            row(exercise_style=None),
            row(exercise_style="american"),
            row(kind="index", exercise_style="european"),
        )
        assert inversion_style(panel).tolist() == ["american", "american", "european"]

    def test_an_unmarked_index_row_is_refused(self):
        # The panel reads unmarked index headings as European; a None here means it did not.
        with pytest.raises(ValueError, match="exercise style"):
            inversion_style(frame(row(kind="index", exercise_style=None)))

    def test_one_date_at_a_time(self):
        panel = frame(row(), row(report_date=DAY + pd.Timedelta(days=1)))
        with pytest.raises(ValueError, match="one report date"):
            implied_vols(panel, self.SPOTS, rate=RATE)

    def test_the_rate_is_the_one_asked_for(self):
        panel = frame(row(mark_price=model_price(100.0, 1.0, 0.3, "C", "european", rate=0.05)))
        assert implied_vols(panel, self.SPOTS, rate=0.05)["iv"].iloc[0] == pytest.approx(0.3)
        assert implied_vols(panel, self.SPOTS, rate=0.03)["iv"].iloc[0] > 0.3


class TestGreeks:
    def test_greeks_delta_dollars_sign_and_scale(self):
        expiry = DAY + pd.Timedelta(days=30)
        panel = frame(
            row(expiry=expiry, mark_price=model_price(100.0, 30 / 365, 0.3, "C", "european")),
            row(
                expiry=expiry,
                right="P",
                mark_price=model_price(100.0, 30 / 365, 0.3, "P", "european"),
            ),
        )
        priced = greeks(implied_vols(panel, {"AAA": SPOT}, rate=RATE), {"AAA": SPOT}, rate=RATE)
        call, put = priced.iloc[0], priced.iloc[1]
        # One at-the-money call, 10 contracts, spot 100: about 0.5 x 10 x 100 x 100.
        assert call["delta_dollars"] == pytest.approx(0.5 * 10 * 100 * 100, rel=0.1)
        assert call["delta_dollars"] == pytest.approx(call["delta"] * 10 * 100 * SPOT)
        assert put["delta_dollars"] < 0
        assert call["delta"] - put["delta"] == pytest.approx(1.0, abs=1e-6)

    def test_gamma_and_vega_dollars(self):
        priced = greeks(
            implied_vols(frame(row()), {"AAA": SPOT}, rate=RATE), {"AAA": SPOT}, rate=RATE
        )
        line = priced.iloc[0]
        assert line["gamma_dollars"] == pytest.approx(
            0.5 * line["gamma"] * 10 * 100 * SPOT**2 * 0.01**2
        )
        assert line["vega_dollars"] == pytest.approx(line["vega"] * 10 * 100)
        assert line["gamma"] > 0 and line["vega"] > 0

    def test_an_american_put_takes_the_trees_greeks(self):
        deep = frame(
            row(
                class_name="AAA INC", exercise_style=None, right="P", strike=200.0, mark_price=100.0
            )
        )
        inverted = implied_vols(deep, {"AAA": SPOT}, rate=RATE)
        assert inverted["iv_status"].iloc[0] == "ok"
        priced = greeks(inverted, {"AAA": SPOT}, rate=RATE)
        assert priced["delta"].iloc[0] == pytest.approx(-1.0)

    def test_rows_without_a_volatility_get_no_greeks(self):
        inverted = implied_vols(frame(row(mark_price=0.0)), {"AAA": SPOT}, rate=RATE)
        priced = greeks(inverted, {"AAA": SPOT}, rate=RATE)
        assert priced[list(GREEK_COLUMNS)].isna().all(axis=None)

    def test_every_greek_column_is_documented_as_gross(self):
        priced = greeks(
            implied_vols(frame(row()), {"AAA": SPOT}, rate=RATE), {"AAA": SPOT}, rate=RATE
        )
        assert set(GREEK_COLUMNS) <= set(priced.columns)
        dollars = [name for name in GREEK_COLUMNS if name.endswith("_dollars")]
        assert dollars == ["delta_dollars", "gamma_dollars", "vega_dollars"]
        assert all("gross" in GREEK_COLUMNS[name].lower() for name in dollars)


def listed(**fields):
    base = {
        "date": DAY,
        "symbol": "AAA",
        "root": "AAA",
        "expiry": DAY + pd.Timedelta(days=365),
        "right": "C",
        "strike": 100.0,
        "iv": 0.28,
    }
    return {**base, **fields}


class TestCompareWithListed:
    def test_compare_with_listed_exact_match_only(self):
        flex = frame(
            row(iv=0.30),
            row(strike=100.01, iv=0.31),  # off the listed strike
            row(right="P", iv=0.32),  # the listed side has only the call
            row(report_date=DAY + pd.Timedelta(days=1), iv=0.33),  # another date
            row(expiry=DAY + pd.Timedelta(days=366), iv=0.34),  # another expiry
            row(underlying="BBB", root="2BBB", iv=0.35),  # another underlying
        )
        chains = pd.DataFrame([listed()])
        matched = compare_with_listed(flex, chains)
        assert len(matched) == 1
        line = matched.iloc[0]
        assert (line["iv_flex"], line["iv_listed"]) == (0.30, 0.28)
        assert line["diff"] == pytest.approx(0.02)

    def test_index_series_meet_the_listed_product_of_their_settlement(self):
        flex = frame(
            row(kind="index", root="2SPX", underlying="SPX", strike=5000.0, iv=0.20),
            row(kind="index", root="4SPX", underlying="SPX", strike=5000.0, iv=0.21),
            row(kind="index", root="4XSP", underlying="XSP", strike=500.0, iv=0.22),
        )
        chains = pd.DataFrame(
            [
                listed(symbol="SPX", root="SPX", strike=5000.0, iv=0.19),
                listed(symbol="SPX", root="SPXW", strike=5000.0, iv=0.18),
            ]
        )
        matched = compare_with_listed(flex, chains).set_index("root")
        assert matched.loc["2SPX", "iv_listed"] == 0.19
        assert matched.loc["4SPX", "iv_listed"] == 0.18
        assert "4XSP" not in matched.index

    def test_a_series_listed_twice_is_refused(self):
        chains = pd.DataFrame([listed(), listed(iv=0.5)])
        with pytest.raises(ValueError, match="more than once"):
            compare_with_listed(frame(row(iv=0.3)), chains)

    def test_a_flex_row_without_a_volatility_is_kept_without_a_diff(self):
        matched = compare_with_listed(frame(row(iv=float("nan"))), pd.DataFrame([listed()]))
        assert len(matched) == 1
        assert math.isnan(matched["diff"].iloc[0])

    @pytest.mark.parametrize(
        ("root", "kind", "twin"),
        [
            ("2AAPL", "equity", "AAPL"),
            ("1AAON", "equity", "AAON"),
            ("2SPX", "index", "SPX"),
            ("4SPX", "index", "SPXW"),
            ("2NDX", "index", "NDX"),
            ("4NDX", "index", "NDXP"),
            ("2RUT", "index", "RUT"),
            ("4RUT", "index", "RUTW"),
            ("4XSP", "index", None),
        ],
    )
    def test_listed_twin(self, root, kind, twin):
        assert listed_twin(root, kind) == twin


class TestBuckets:
    def test_moneyness_bins_are_the_exposure_profiles(self):
        assert MONEYNESS_BINS == (0.7, 0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.3)

    @pytest.mark.parametrize(
        ("moneyness", "days", "expected"),
        [
            (0.5, 0, ("<0.70", "<=7")),
            (0.7, 7, ("0.70-0.80", "<=7")),
            (0.95, 8, ("0.95-1.00", "8-30")),
            (0.9999, 30, ("0.95-1.00", "8-30")),
            (1.0, 31, ("1.00-1.05", "31-90")),
            (1.29, 90, ("1.20-1.30", "31-90")),
            (1.3, 91, (">=1.30", "91-365")),
            (4.0, 365, (">=1.30", "91-365")),
            (1.0, 366, ("1.00-1.05", ">365")),
        ],
    )
    def test_bucket_edges(self, moneyness, days, expected):
        assert bucket(moneyness, days) == expected

    def test_vectorised_buckets_agree_with_bucket(self):
        moneyness = pd.Series([0.5, 0.75, 0.95, 1.0, 1.07, 1.15, 1.3, 2.0, float("nan")])
        days = pd.Series([1, 7, 8, 30, 31, 90, 91, 365, 400])
        frame_ = buckets(moneyness, days)
        for m, d, (mb, db) in zip(
            moneyness[:-1], days[:-1], frame_.iloc[:-1].itertuples(index=False), strict=True
        ):
            assert bucket(m, d) == (mb, db)
        # No spot, no moneyness: the row has no moneyness bucket.
        assert pd.isna(frame_["moneyness_bucket"].iloc[-1])

    def test_bucket_refuses_a_missing_moneyness(self):
        with pytest.raises(ValueError, match="moneyness"):
            bucket(float("nan"), 10)

    def test_bucketed_adds_moneyness_and_days(self):
        panel = frame(row(strike=95.0)).assign(spot=SPOT)
        out = bucketed(panel)
        assert out["moneyness"].iloc[0] == pytest.approx(0.95)
        assert out["days_to_expiry"].iloc[0] == 365
        assert (out["moneyness_bucket"].iloc[0], out["dte_bucket"].iloc[0]) == (
            "0.95-1.00",
            "91-365",
        )


class TestValidatedDomain:
    def validation(self, cells):
        rows = [
            {"moneyness_bucket": m, "dte_bucket": d, "diff": diff}
            for (m, d), diffs in cells.items()
            for diff in diffs
        ]
        return pd.DataFrame(rows)

    def test_keeps_buckets_whose_median_gap_is_within_two_vol_points(self):
        validation = self.validation(
            {
                ("0.95-1.00", "8-30"): [0.01, -0.015, 0.02, 0.5],
                ("<0.70", "<=7"): [0.05, -0.04, 0.03, 0.0],
            }
        )
        assert validated_domain(validation, min_matched=4) == frozenset({("0.95-1.00", "8-30")})
        assert validated_domain(validation, max_median_diff=0.04, min_matched=4) == frozenset(
            {("0.95-1.00", "8-30"), ("<0.70", "<=7")}
        )

    def test_a_bucket_with_too_few_matches_is_not_validated(self):
        validation = self.validation({("0.95-1.00", "8-30"): [0.0, 0.0, 0.0]})
        assert validated_domain(validation, min_matched=4) == frozenset()
        assert validated_domain(validation, min_matched=3) == frozenset({("0.95-1.00", "8-30")})

    def test_rows_without_a_diff_do_not_count(self):
        validation = self.validation({("0.95-1.00", "8-30"): [0.0, 0.0, float("nan")]})
        assert validated_domain(validation, min_matched=3) == frozenset()
