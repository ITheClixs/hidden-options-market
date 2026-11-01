"""The loaders behind the `positions` result, on a small tree of files."""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.measure.hidden_share_data import CICapturesError
from hidden_options.measure.positions_data import load_domain, load_inputs
from hidden_options.publish.results import Result, write_result
from implied_stub import D1, bars, chains, panel


def _domain_result(results):
    write_result(
        Result(
            "implied_validation",
            {"domain": {"buckets": [["0.95-1.00", "31-90"]]}},
            {},
            {},
            "2026-10-27T00:00:00+00:00",
        ),
        results,
    )


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    flex = panel()
    for (day, kind), rows in flex.groupby(["report_date", "kind"]):
        folder = raw / f"occ_flex/date={day:%Y-%m-%d}"
        folder.mkdir(parents=True, exist_ok=True)
        rows.drop(columns=["exercise_style"]).to_parquet(folder / f"{kind}.parquet")
    late = raw / "occ_flex/date=2026-10-23"
    late.mkdir(parents=True)
    flex.drop(columns=["exercise_style"]).head(1).to_parquet(late / "equity.parquet")
    stored = chains().drop(columns=["root", "oi_date", "session"])
    stored["quote_timestamp"] = stored["quote_timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    for (day, symbol), rows in stored.groupby([stored["quote_timestamp"].str[:10], "symbol"]):
        folder = raw / f"cboe_chain/date={day}"
        folder.mkdir(parents=True, exist_ok=True)
        kind = "index" if str(symbol).lstrip("_") == "SPX" else "equity"
        rows.to_parquet(folder / f"{kind}_{symbol}.parquet")
    holdings = raw / f"fund_holdings/date={D1:%Y-%m-%d}"
    holdings.mkdir(parents=True)
    pd.DataFrame(
        {
            "fund": ["AAAY"],
            "as_of": [D1.date()],
            "is_option": [True],
            "option_root": ["2AAA"],
            "expiry": [pd.Timestamp("2026-12-18").date()],
            "right": ["C"],
            "strike": [100.0],
            "contracts": [10.0],
        }
    ).to_parquet(holdings / "AAAY.parquet")
    bars_path = tmp_path / "bars.parquet"
    bars().to_parquet(bars_path)
    ci = tmp_path / "ci"
    (ci / "2026-09-03" / "raw").mkdir(parents=True)
    results = tmp_path / "results"
    _domain_result(results)
    return raw, ci, bars_path, results


class TestLoadInputs:
    def test_reads_everything_up_to_the_panel_end(self, world):
        inputs = load_inputs(*world)
        assert max(inputs.dates) == pd.Timestamp("2026-09-02")
        assert inputs.ci_runs == ["2026-09-03"]
        assert inputs.local_only is False
        assert len(inputs.holdings) == 1
        assert inputs.globalx.empty
        assert inputs.domain == frozenset({("0.95-1.00", "31-90")})

    def test_a_day_is_read_with_its_exercise_style(self, world):
        inputs = load_inputs(*world)
        rows = inputs.read_day(D1)
        assert set(rows["report_date"]) == {D1}
        assert "exercise_style" in rows.columns

    def test_spots_come_from_bars_and_the_index_chains_alone(self, world):
        spots = load_inputs(*world).spots
        on_d1 = spots[spots["date"] == D1].set_index("underlying")
        assert on_d1.loc["AAA", "spot"] == 100.0
        assert on_d1.loc["AAA", "source"] == "bars"
        assert on_d1.loc["SPX", "spot"] == 5000.0
        assert on_d1.loc["XSP", "spot"] == 500.0

    def test_local_only_reads_no_ci_run(self, world):
        raw, _, bars_path, results = world
        inputs = load_inputs(raw, None, bars_path, results, local_only=True)
        assert inputs.ci_runs == []
        assert inputs.local_only is True

    def test_other_ci_runs_are_refused_unless_accepted(self, world):
        raw, ci, bars_path, results = world
        write_result(
            Result("positions", {}, {}, {"ci_runs": ["2026-01-01"]}, "2026-10-27T00:00:00+00:00"),
            results,
        )
        with pytest.raises(CICapturesError):
            load_inputs(raw, ci, bars_path, results)
        assert load_inputs(raw, ci, bars_path, results, accept_ci_runs=True).ci_runs


def test_the_domain_must_have_been_computed(tmp_path):
    with pytest.raises(FileNotFoundError, match="implied_validation"):
        load_domain(tmp_path)
