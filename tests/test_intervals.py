"""Tests for the Wilson interval."""

from __future__ import annotations

import pytest

from hidden_options.measure.intervals import wilson


def test_known_value():
    # 8 of 10: the textbook Wilson interval is about (0.490, 0.943).
    low, high = wilson(8, 10)
    assert low == pytest.approx(0.4902, abs=1e-3)
    assert high == pytest.approx(0.9433, abs=1e-3)


def test_bounded_at_zero_and_one():
    assert wilson(0, 5)[0] == 0.0
    assert wilson(5, 5)[1] == pytest.approx(1.0)


def test_narrows_with_trials():
    assert (wilson(500, 1000)[1] - wilson(500, 1000)[0]) < (wilson(5, 10)[1] - wilson(5, 10)[0])


def test_refuses_no_trials():
    with pytest.raises(ValueError):
        wilson(0, 0)
