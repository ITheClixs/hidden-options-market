"""The implied-volatility inputs: listed readings after the close, spots and style groups."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.hidden_share_data import CICapturesError
from hidden_options.measure.implied import product_prefix
from hidden_options.measure.implied_data import (
    SPOT_AGREEMENT,
    close_readings,
    equity_closes,
    listed_quotes,
    overlap_dates,
    reading_agreement,
    spot_table,
    style_groups,
    usable_listed,
    with_spots,
)
from hidden_options.publish.results import Result, write_result
from implied_stub import D0, D1, D2, YEAR, _reading, bars, chains, panel


class TestCloseReadings:
    def test_the_first_reading_after_the_delayed_close_is_kept(self):
        readings = close_readings(chains())
        aaa = readings[(readings["symbol"] == "AAA") & (readings["date"] == D1)]
        # 14:00 and 16:10 are before the close shows; 16:16 is the first after; 23:50 is later.
        assert set(aaa["underlying_price"]) == {100.02}
        assert len(aaa) == 6

    def test_a_weekend_reading_belongs_to_the_friday_session(self):
        friday = pd.Timestamp("2026-09-04")
        rows = _reading(
            "AAA", "2026-09-05 16:00", friday, 101.0, [("AAA", D1 + YEAR, "C", 100.0, 0.3)]
        )
        readings = close_readings(pd.DataFrame(rows))
        assert readings["date"].tolist() == [friday]

    def test_a_session_read_only_while_trading_has_no_reading(self):
        rows = _reading("AAA", "2026-09-01 18:00", D1, 99.0, [("AAA", D1 + YEAR, "C", 100.0, 0.3)])
        assert close_readings(pd.DataFrame(rows)).empty


class TestListedQuotes:
    def test_standard_classes_with_a_volatility_only(self):
        listed = listed_quotes(close_readings(chains()))
        aaa = listed[(listed["symbol"] == "AAA") & (listed["date"] == D1)]
        assert len(aaa) == 4
        assert set(aaa["root"]) == {"AAA"}
        spx = listed[(listed["symbol"] == "SPX") & (listed["date"] == D1)]
        assert sorted(spx["root"]) == ["SPX", "SPXW"]

    def test_readings_that_disagree_with_the_close_are_set_aside(self):
        readings = close_readings(chains())
        agreement = reading_agreement(readings, equity_closes(bars()))
        ccc = agreement.set_index("symbol").loc["CCC"]
        assert ccc["rel_diff"] == pytest.approx(0.02)
        assert not ccc["agrees"]
        assert agreement.set_index("symbol").loc["AAA"]["agrees"].all()
        usable = usable_listed(readings, agreement)
        assert "CCC" not in set(usable["symbol"])
        # Indices have no bars to check against; their reading is their spot.
        assert "SPX" in set(usable["symbol"])
        assert SPOT_AGREEMENT == 0.005


class TestSpots:
    def test_equity_closes_on_the_new_york_date(self):
        closes = equity_closes(bars())
        assert closes.set_index(["date", "symbol"]).loc[(D1, "AAA"), "close"] == 100.0

    def test_spot_table(self):
        spots = spot_table(close_readings(chains()), equity_closes(bars()))
        on_d1 = spots[spots["date"] == D1].set_index("underlying")
        assert on_d1.loc["AAA", ["spot", "source"]].tolist() == [100.0, "bars"]
        assert on_d1.loc["SPX", ["spot", "source"]].tolist() == [5000.0, "chain"]
        assert on_d1.loc["XSP", ["spot", "source"]].tolist() == [500.0, "fraction"]
        assert "DJX" not in on_d1.index
        assert "BBB" not in on_d1.index

    def test_with_spots_keeps_every_row_in_place(self):
        rows = panel()
        rows = rows[rows["report_date"].isin([D1, D2])].set_index(pd.Index(range(100, 115)))
        joined = with_spots(rows, spot_table(close_readings(chains()), equity_closes(bars())))
        assert joined.index.equals(rows.index)
        assert joined["spot"].isna().sum() == 2  # BBB and DJX

    def test_overlap_dates(self):
        assert overlap_dates(panel(), close_readings(chains())) == [D1, D2]

    def test_a_date_read_for_only_a_few_symbols_is_outside_the_window(self):
        flex = pd.DataFrame({"report_date": [D0, D1, D2]})
        readings = pd.DataFrame(
            {
                "date": [D0, D1, D1, D1, D2, D2],
                "symbol": ["AAA", "AAA", "BBB", "CCC", "AAA", "BBB"],
            }
        )
        # Two of three symbols is more than half; one of three is not.
        assert overlap_dates(flex, readings) == [D1, D2]


class TestStyles:
    def test_style_groups(self):
        groups = style_groups(panel())
        assert groups.iloc[:5].tolist() == ["strict", "strict", "clipped", "prefix", "index"]
        # 3AAA on 3 August: no heading marker and no prefix answer.
        assert groups.iloc[-2] == "fallback"

    def test_product_prefix(self):
        assert product_prefix(pd.Series(["1AAA", "2SPX", "4MRUT", "13ABC"])).tolist() == [
            "1",
            "2",
            "4",
            "13",
        ]


class TestLoadInputs:
    @pytest.fixture
    def world(self, tmp_path):
        raw = tmp_path / "raw"
        flex = panel()
        for (day, kind), rows in flex.groupby(["report_date", "kind"]):
            folder = raw / f"occ_flex/date={day:%Y-%m-%d}"
            folder.mkdir(parents=True, exist_ok=True)
            rows.drop(columns=["exercise_style"]).to_parquet(folder / f"{kind}.parquet")
        stored = chains().drop(columns=["root", "oi_date", "session"])
        stored["quote_timestamp"] = stored["quote_timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        for (day, symbol), rows in stored.groupby([stored["quote_timestamp"].str[:10], "symbol"]):
            folder = raw / f"cboe_chain/date={day}"
            folder.mkdir(parents=True, exist_ok=True)
            rows.to_parquet(folder / f"equity_{symbol}.parquet")
        bars_path = tmp_path / "bars.parquet"
        bars().to_parquet(bars_path)
        ci = tmp_path / "ci"
        (ci / "2026-09-03" / "raw").mkdir(parents=True)
        return raw, ci, bars_path, tmp_path / "results"

    def load(self, monkeypatch, world, **kwargs):
        from hidden_options.measure import implied_data

        raw, ci, bars_path, results = world
        monkeypatch.setattr(implied_data, "RESULTS_DIR", results)
        return implied_data.load_inputs(raw, ci, bars_path, **kwargs)

    def test_reads_the_panel_readings_and_bars(self, monkeypatch, world):
        inputs = self.load(monkeypatch, world)
        # The rows to invert start at the first date read after the close; the style
        # counts see every date, with only the columns they need.
        assert set(inputs.panel["report_date"]) == {D1, D2}
        assert inputs.panel["exercise_style"].iloc[0] == "european"
        assert set(inputs.styles["report_date"]) == {D0, D1, D2}
        assert list(inputs.styles.columns) == [
            "report_date",
            "kind",
            "class_name",
            "root",
            "exercise_style",
        ]
        assert set(inputs.styles["kind"]) == {"equity"}
        assert len(inputs.bars) == 6

    def test_readings_are_reduced_file_by_file_to_the_first_after_the_close(
        self, monkeypatch, world
    ):
        inputs = self.load(monkeypatch, world)
        expected = close_readings(chains())
        key = ["date", "symbol", "contract"]
        got = inputs.readings.sort_values(key).reset_index(drop=True)
        want = expected.sort_values(key).reset_index(drop=True)
        assert got[[*key, "iv", "underlying_price"]].equals(want[[*key, "iv", "underlying_price"]])
        assert (list(inputs.ci_runs), inputs.local_only) == (["2026-09-03"], False)

    def test_without_the_ci_captures_the_inputs_are_refused(self, monkeypatch, world):
        raw, _, bars_path, results = world
        with pytest.raises(CICapturesError, match="--local-only"):
            self.load(monkeypatch, (raw, results.parent / "absent", bars_path, results))
        inputs = self.load(
            monkeypatch, (raw, results.parent / "absent", bars_path, results), local_only=True
        )
        assert (list(inputs.ci_runs), inputs.local_only) == ([], True)

    def test_ci_runs_other_than_the_committed_ones_are_refused(self, monkeypatch, world):
        results = world[3]
        stored = {"ci_runs": ["2026-09-03", "2026-09-09"]}
        write_result(Result("implied_validation", {}, {}, stored, "t"), results)
        with pytest.raises(CICapturesError, match="2026-09-09"):
            self.load(monkeypatch, world)
        assert list(self.load(monkeypatch, world, accept_ci_runs=True).ci_runs) == ["2026-09-03"]
