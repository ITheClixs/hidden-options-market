"""The regressions the paper reports, each a two-way fixed-effects fit with the controls.

The table has six rows: four predictors on next-day absolute return, the main predictor
on next-day squared return, and the placebo. Longer horizons, the restriction to large
inventory changes, the open-to-close timing check and the start-date windows are the
same specification on another outcome or sample, and are reported as values.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from hidden_options.measure.panel import Estimate, fit
from hidden_options.predict.panel import CONTROLS, HORIZONS, build_predictive_panel

MAIN_PREDICTOR = "oi_innov"
MAIN_OUTCOME = "abs_ret_next"
PLACEBO_PREDICTOR = "oi_innov_placebo"
TIMING_OUTCOME = "oc_abs_next"

# (predictor, outcome, placebo), in the order the table prints them.
TABLE_SPECS: tuple[tuple[str, str, bool], ...] = (
    (MAIN_PREDICTOR, MAIN_OUTCOME, False),
    ("d_log_oi", MAIN_OUTCOME, False),
    ("d_near_share", MAIN_OUTCOME, False),
    ("put_share", MAIN_OUTCOME, False),
    (MAIN_PREDICTOR, "sq_ret_next", False),
    (PLACEBO_PREDICTOR, MAIN_OUTCOME, True),
)

# The restriction to large creations and extinguishments: the tenth of underlying-days
# with the largest absolute change in log open interest.
TOP_SHARE = 0.1


@dataclass(frozen=True)
class PredictiveRow:
    """One coefficient from one regression, with its two-way clustered inference."""

    predictor: str
    outcome: str
    coefficient: float
    t_stat: float
    mde80: float
    n_obs: int
    placebo: bool
    std_error: float
    p_value: float
    ci_low: float
    ci_high: float
    n_underlyings: int
    n_dates: int

    @classmethod
    def from_estimate(cls, est: Estimate, outcome: str, *, placebo: bool) -> PredictiveRow:
        low, high = est.ci95
        return cls(
            predictor=est.name,
            outcome=outcome,
            coefficient=est.coefficient,
            t_stat=est.t_stat,
            mde80=est.mde80,
            n_obs=est.n_obs,
            placebo=placebo,
            std_error=est.std_error,
            p_value=est.p_value,
            ci_low=low,
            ci_high=high,
            n_underlyings=est.n_names,
            n_dates=est.n_dates,
        )


def estimate(
    panel: pd.DataFrame, predictor: str, outcome: str, *, placebo: bool = False
) -> PredictiveRow:
    """``outcome`` on ``predictor`` and the controls, underlying and date fixed effects."""
    est = fit(panel, outcome, [predictor, *CONTROLS], entity="symbol", time="date")
    return PredictiveRow.from_estimate(est[predictor], outcome, placebo=placebo)


def run_predictive(panel: pd.DataFrame) -> list[PredictiveRow]:
    """The six table rows, in order."""
    return [
        estimate(panel, predictor, outcome, placebo=placebo)
        for predictor, outcome, placebo in TABLE_SPECS
    ]


def horizon_rows(panel: pd.DataFrame, horizons: Sequence[int] = HORIZONS) -> list[PredictiveRow]:
    """The main predictor on mean absolute return over each horizon from availability."""
    return [estimate(panel, MAIN_PREDICTOR, f"abs_ret_next_{days}d") for days in horizons]


def top_decile_row(panel: pd.DataFrame, share: float = TOP_SHARE) -> tuple[PredictiveRow, float]:
    """The main row on the underlying-days with the largest absolute inventory changes.

    The cut is the ``1 - share`` quantile of ``|d_log_oi|`` over the main row's sample,
    returned with the row.
    """
    complete = panel.dropna(subset=[MAIN_PREDICTOR, MAIN_OUTCOME, *CONTROLS])
    threshold = float(complete["d_log_oi"].abs().quantile(1 - share))
    large = complete[complete["d_log_oi"].abs() >= threshold]
    return estimate(large, MAIN_PREDICTOR, MAIN_OUTCOME), threshold


def timing_row(panel: pd.DataFrame) -> PredictiveRow:
    """The main predictor on the open-to-close move of the session it becomes usable.

    The close-to-close outcome includes the overnight move before the report could be
    read; this one does not.
    """
    return estimate(panel, MAIN_PREDICTOR, TIMING_OUTCOME)


def window_robustness(
    daily: pd.DataFrame, bars: pd.DataFrame, starts: Sequence[str], *, min_history: int = 40
) -> list[PredictiveRow]:
    """The main row and its placebo with the panel loaded from each start date.

    Two rows per start, in the order given: the main predictor, then the placebo. Each
    panel is rebuilt from its start, so trailing levels and history counts restart too.
    """
    rows: list[PredictiveRow] = []
    for start in starts:
        loaded = daily[daily["report_date"] >= pd.Timestamp(start)]
        panel = build_predictive_panel(loaded, bars, min_history=min_history)
        rows.append(estimate(panel, MAIN_PREDICTOR, MAIN_OUTCOME))
        rows.append(estimate(panel, PLACEBO_PREDICTOR, MAIN_OUTCOME, placebo=True))
    return rows


__all__ = [
    "MAIN_OUTCOME",
    "MAIN_PREDICTOR",
    "PLACEBO_PREDICTOR",
    "TABLE_SPECS",
    "TIMING_OUTCOME",
    "TOP_SHARE",
    "PredictiveRow",
    "estimate",
    "horizon_rows",
    "run_predictive",
    "timing_row",
    "top_decile_row",
    "window_robustness",
]
