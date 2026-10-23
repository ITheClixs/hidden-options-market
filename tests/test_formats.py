"""Tests for the macro value formatters.

Every number the paper and README print passes through one of these, so they pin the
macro convention: ASCII text, `\\$` and `\\%` escaped, an ASCII hyphen for a minus sign,
and never a negative zero.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.publish import formats
from hidden_options.publish.latex import collect_macros
from hidden_options.publish.results import Result


class TestFormats:
    def test_count_groups_thousands(self):
        assert formats.count(15179194) == "15,179,194"
        assert formats.count(7) == "7"

    def test_millions_scales_and_rounds(self):
        assert formats.millions(35_213_339) == "35.2"
        assert formats.millions(15_179_194, digits=2) == "15.18"

    def test_usd_billions_escapes_the_dollar(self):
        assert formats.usd_billions(298_198_159_873.13) == r"\$298bn"
        assert formats.usd_billions(1_234_000_000_000) == r"\$1,234bn"

    def test_percent_escapes_the_sign(self):
        assert formats.percent(0.2971) == r"30\%"
        assert formats.percent(0.2971, digits=1) == r"29.7\%"

    def test_signed_percent_uses_ascii_signs(self):
        assert formats.signed_percent(0.015) == r"+1.5\%"
        assert formats.signed_percent(-0.0951, digits=0) == r"-10\%"

    @pytest.mark.parametrize("value", [-0.00001, -0.0])
    def test_no_negative_zero(self, value):
        assert formats.signed_percent(value) == r"+0.0\%"
        assert formats.decimal(value, digits=2) == "0.00"

    def test_decimal(self):
        assert formats.decimal(2.0833) == "2.1"
        assert formats.decimal(-1.25, digits=2) == "-1.25"

    def test_dates(self):
        day = pd.Timestamp("2024-12-02")
        assert formats.long_date(day) == "2 December 2024"
        assert formats.month_year(day) == "December 2024"
        assert formats.iso_date(day) == "2024-12-02"

    def test_every_format_is_a_valid_macro_value(self):
        macros = {
            "A": formats.count(1234),
            "B": formats.millions(1e6),
            "C": formats.usd_billions(5e11),
            "D": formats.percent(0.5),
            "E": formats.signed_percent(-0.2),
            "F": formats.long_date(pd.Timestamp("2026-10-22")),
            "G": formats.decimal(-3.0),
        }
        result = Result("fmt", values={}, macros=macros, inputs={}, generated_at="t")

        assert collect_macros({"fmt": result}) == dict(sorted(macros.items()))
        assert all(value.isascii() for value in macros.values())
