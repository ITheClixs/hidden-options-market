"""Option pricers behind the mark inversion: Black-Scholes with a carry yield and a CRR tree."""

from __future__ import annotations

import numpy as np
import pytest

from hidden_options.measure.pricing import (
    TREE_STEPS,
    binomial,
    binomial_greeks,
    black_scholes,
    black_scholes_greeks,
    black_scholes_vega,
    early_exercise_matters,
    lowest_tree_sigma,
)

RATE = 0.04


def arrays(*values):
    return [np.atleast_1d(np.asarray(value, dtype=float)) for value in values]


class TestBlackScholes:
    def test_put_call_parity_with_a_carry_yield(self):
        spot, strike, years, sigma = arrays([100.0, 80.0], [95.0, 120.0], [0.5, 2.0], [0.3, 0.6])
        calls = black_scholes(spot, strike, years, sigma, rate=RATE, carry=0.02, is_call=True)
        puts = black_scholes(spot, strike, years, sigma, rate=RATE, carry=0.02, is_call=False)
        forward = spot * np.exp(-0.02 * years) - strike * np.exp(-RATE * years)
        assert calls - puts == pytest.approx(forward)

    def test_a_known_value(self):
        # S = K = 100, one year, 20% volatility, 4% rate, no carry: 9.925 to three places.
        price = black_scholes(*arrays(100, 100, 1, 0.2), rate=RATE, carry=0.0, is_call=True)
        assert price[0] == pytest.approx(9.9251, abs=1e-4)

    def test_mixed_rights_in_one_call(self):
        spot, strike, years, sigma = arrays([100, 100], [100, 100], [1, 1], [0.2, 0.2])
        mixed = black_scholes(
            spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=np.array([True, False])
        )
        one = (spot[:1], strike[:1], years[:1], sigma[:1])
        call = black_scholes(*one, rate=RATE, carry=0.0, is_call=True)
        put = black_scholes(*one, rate=RATE, carry=0.0, is_call=False)
        assert mixed == pytest.approx([call[0], put[0]])

    def test_greeks_match_finite_differences(self):
        spot, strike, years, sigma = arrays(100, 105, 0.75, 0.35)
        greeks = black_scholes_greeks(
            spot, strike, years, sigma, rate=RATE, carry=0.01, is_call=False
        )

        def price(s, v):
            return black_scholes(s, strike, years, v, rate=RATE, carry=0.01, is_call=False)[0]

        h = 1e-3
        delta = (price(spot + h, sigma) - price(spot - h, sigma)) / (2 * h)
        gamma = (price(spot + h, sigma) - 2 * price(spot, sigma) + price(spot - h, sigma)) / h**2
        vega = (price(spot, sigma + h) - price(spot, sigma - h)) / (2 * h)
        assert greeks.delta[0] == pytest.approx(delta, rel=1e-6)
        assert greeks.gamma[0] == pytest.approx(gamma, rel=1e-4)
        # Vega is quoted per vol point, a 0.01 change in volatility.
        assert greeks.vega[0] == pytest.approx(vega * 0.01, rel=1e-6)
        assert black_scholes_vega(spot, strike, years, sigma, rate=RATE, carry=0.01)[0] == (
            pytest.approx(vega, rel=1e-6)
        )


class TestTree:
    def test_converges_on_black_scholes_without_early_exercise(self):
        # An American call on an asset with no carry yield is worth its European twin.
        spot, strike, years, sigma = arrays([100, 100, 100], [80, 100, 130], [0.5, 1, 2], 0.3)
        tree = binomial(spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=True)
        closed = black_scholes(spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=True)
        assert tree == pytest.approx(closed, rel=5e-3)

    def test_american_put_is_worth_more_than_the_european(self):
        spot, strike, years, sigma = arrays([100, 100, 100], [90, 100, 130], [1, 1, 1], 0.25)
        american = binomial(spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=False)
        european = black_scholes(spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=False)
        assert (american > european).all()
        # Deep in the money it is worth at least what exercise pays now.
        assert american[2] >= 30.0

    def test_rows_are_priced_in_chunks_without_changing_the_answer(self, monkeypatch):
        from hidden_options.measure import pricing

        spot, strike, years, sigma = arrays(
            [100] * 5, [80, 90, 100, 110, 120], [0.5] * 5, [0.2, 0.3, 0.4, 0.5, 0.6]
        )
        whole = binomial(spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=False)
        monkeypatch.setattr(pricing, "TREE_CHUNK", 2)
        chunked = binomial(spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=False)
        assert chunked == pytest.approx(whole, rel=0, abs=0)

    def test_tree_greeks_of_a_call_match_black_scholes(self):
        # No early exercise, so the tree should reproduce the closed form's greeks.
        spot, strike, years, sigma = arrays(100, 100, 1, 0.3)
        greeks = binomial_greeks(spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=True)
        closed = black_scholes_greeks(
            spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=True
        )
        assert greeks.delta[0] == pytest.approx(closed.delta[0], abs=0.01)
        assert greeks.gamma[0] == pytest.approx(closed.gamma[0], rel=0.05)
        assert greeks.vega[0] == pytest.approx(closed.vega[0], rel=0.05)

    def test_tree_greeks_of_american_puts(self):
        spot, strike, years, sigma = arrays([100, 100], [100, 200], [1, 1], [0.3, 0.3])
        greeks = binomial_greeks(spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=False)
        european = black_scholes_greeks(
            spot, strike, years, sigma, rate=RATE, carry=0.0, is_call=False
        )
        # At the money the right to exercise early makes the put more sensitive to spot.
        assert -1.0 < greeks.delta[0] < european.delta[0]
        # Deep in the money it is exercised at once: delta -1, no gamma, no vega.
        assert greeks.delta[1] == pytest.approx(-1.0)
        assert greeks.gamma[1] == pytest.approx(0.0, abs=1e-9)
        assert greeks.vega[1] == pytest.approx(0.0, abs=1e-9)

    def test_lowest_tree_sigma_keeps_probabilities_inside_zero_one(self):
        years = np.array([1e-4, 1.0, 5.0])
        floor = lowest_tree_sigma(years, rate=RATE, carry=0.0)
        dt = years / TREE_STEPS
        up = np.exp(floor * np.sqrt(dt))
        growth = np.exp(RATE * dt)
        probability = (growth - 1 / up) / (up - 1 / up)
        assert ((probability > 0) & (probability < 1)).all()
        assert floor[0] == pytest.approx(1e-4)

    def test_early_exercise_matters_for_puts_with_a_rate_and_calls_with_a_carry(self):
        is_call = np.array([True, False])
        assert early_exercise_matters(is_call, rate=RATE, carry=0.0).tolist() == [False, True]
        assert early_exercise_matters(is_call, rate=RATE, carry=0.02).tolist() == [True, True]
        assert early_exercise_matters(is_call, rate=0.0, carry=0.0).tolist() == [False, False]
