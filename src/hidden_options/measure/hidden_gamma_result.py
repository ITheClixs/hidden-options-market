"""Result `hidden_gamma`: how much option gamma a listed-only calculation leaves out.

Specification: `docs/log/2026-11-07-hidden-gamma-spec.md`. Each settlement pairs the FLEX
report for that activity date with the listed open interest of the same settlement and
the quotes and implied volatilities of the same session, dated as `priced_chains` dates
them. The chains are read from the local captures and the CI runs, guarded as the
hidden-share result guards them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.config import (
    ACCEPT_CI_RUNS_ENV,
    CI_CAPTURES_DIR,
    LOCAL_ONLY_ENV,
    PANEL_END,
    RAW_DIR,
    load_universe,
)
from hidden_options.measure.hidden_gamma import (
    dollar_gamma,
    flex_gamma,
    gamma_shares,
    listed_gamma,
)
from hidden_options.measure.hidden_gamma_macros import hidden_gamma_macros
from hidden_options.measure.hidden_gamma_summary import (
    distribution,
    mark_check,
    per_underlying,
    pooled,
    signed_view,
    where,
)
from hidden_options.measure.hidden_share import flex_series
from hidden_options.measure.hidden_share_data import (
    check_ci_runs,
    ci_roots,
    load_chains,
    priced_chains,
    switch_on,
    trading_calendar,
)
from hidden_options.measure.implied import RATE, InversionStatus, buckets, implied_vols_frame
from hidden_options.measure.implied_data import PANEL_READ_COLUMNS, read_panel
from hidden_options.measure.pricing import black_scholes_greeks
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import RESULTS_DIR, Result, now_iso, read_results

NAME = "hidden_gamma"
PROGRAMME, CONTROL = "programme", "control"
GROUPS = (PROGRAMME, CONTROL, "other")
INDEX_PRODUCTS = ("SPX", "SPY", "QQQ", "NDX", "IWM", "RUT")
SERIES_KEYS = ["date", "root", "right", "expiry", "strike"]


@dataclass(frozen=True)
class GammaInputs:
    """Priced listed series with their volatility, FLEX report rows with exercise style,
    the universe groups and the validated mark-volatility buckets."""

    chains: pd.DataFrame
    panel: pd.DataFrame
    groups: dict[str, str]
    domain: frozenset[tuple[str, str]]
    ci_runs: Sequence[str] = ()
    local_only: bool = False


def hidden_gamma_result(inputs: GammaInputs) -> Result:
    """The figures the specification lists, from `inputs`."""
    chains = inputs.chains
    dates = pd.DatetimeIndex(sorted(chains["date"].unique()))
    series = flex_series(inputs.panel, dates)
    series = series[series["symbol"].isin(set(chains["symbol"]))]
    listed = listed_gamma(chains, rate=RATE)
    flex = flex_gamma(series, chains, rate=RATE)
    shares = gamma_shares(listed, flex)
    medians = per_underlying(shares, inputs.groups)
    marks = _mark_volatility(flex, inputs.panel, chains, inputs.domain)

    live_oi = float(series.loc[series["expiry"] > series["date"], "open_interest"].sum())
    values: dict[str, Any] = {
        "distribution": distribution(medians, GROUPS),
        "pooled": pooled(shares),
        "where": where(flex),
        "signed": signed_view(shares),
        "marks": marks,
        "coverage": {
            "priced_oi_share": float(flex["open_interest"].sum() / live_oi) if live_oi else 0.0,
            "interior_oi_share": float(
                flex.loc[flex["interior"].astype(bool), "open_interest"].sum()
                / flex["open_interest"].sum()
            ),
        },
        "index": {
            symbol: {
                rule: float(medians.at[symbol, rule])  # type: ignore[arg-type]
                for rule in ("share_gross", "share_netted", "share_netted_both")
            }
            for symbol in INDEX_PRODUCTS
            if symbol in medians.index
        },
        "underlyings": {
            str(symbol): {
                "group": row["group"],
                "settlements": int(row["settlements"]),
                "share_gross": float(row["share_gross"]),
                "share_netted": float(row["share_netted"]),
                "share_netted_both": float(row["share_netted_both"]),
            }
            for symbol, row in medians.iterrows()
        },
    }
    run_inputs = {
        "first_date": dates.min().date().isoformat(),
        "last_date": dates.max().date().isoformat(),
        "settlements": len(dates),
        "underlyings": int(medians.shape[0]),
        "flex_series_days": len(flex),
        "ci_runs": list(inputs.ci_runs),
        "local_only": inputs.local_only,
    }
    return Result(NAME, values, hidden_gamma_macros(values, run_inputs), run_inputs, now_iso())


@ANALYSES.register(NAME)
def hidden_gamma_analysis() -> Result:
    """Hidden gamma on the chains and FLEX reports on disk, up to PANEL_END."""
    return hidden_gamma_result(load_inputs())


def load_inputs(
    raw: Path | None = None,
    ci: Path | None = None,
    *,
    local_only: bool | None = None,
    accept_ci_runs: bool | None = None,
) -> GammaInputs:
    """Read the chains (local, then each CI run), the FLEX reports and the universe.

    The CI captures are guarded as in `hidden_share_result.load_inputs`.
    """
    raw = RAW_DIR if raw is None else raw
    local_only = switch_on(LOCAL_ONLY_ENV) if local_only is None else local_only
    accept = switch_on(ACCEPT_CI_RUNS_ENV) if accept_ci_runs is None else accept_ci_runs
    runs = [] if local_only else ci_roots(CI_CAPTURES_DIR if ci is None else ci)
    names = [run.parent.name for run in runs]
    if not local_only and not accept:
        check_ci_runs(names, NAME, RESULTS_DIR)
    end = pd.Timestamp(PANEL_END)
    chains = priced_chains(
        load_chains([raw, *runs], trading_calendar(raw, end), extra=("iv",)), extra=("iv",)
    )
    chains = chains[(chains["date"] <= end) & chains["underlying_price"].notna()]
    panel = read_panel(raw, ("equity", "index"), PANEL_READ_COLUMNS, chains["date"].min(), end)
    universe = load_universe()
    groups = {
        **{s: PROGRAMME for s in (*universe.treated_single_name, *universe.treated_index_and_etf)},
        **{s: CONTROL for s in universe.control_single_name},
    }
    domain = read_results(RESULTS_DIR)["implied_validation"].values["domain"]["buckets"]
    return GammaInputs(
        chains=chains.reset_index(drop=True),
        panel=panel,
        groups={symbol.lstrip("_"): group for symbol, group in groups.items()},
        domain=frozenset((str(m), str(d)) for m, d in domain),
        ci_runs=names,
        local_only=local_only,
    )


def _mark_volatility(
    flex: pd.DataFrame,
    panel: pd.DataFrame,
    chains: pd.DataFrame,
    domain: frozenset[tuple[str, str]],
) -> dict[str, Any]:
    """Gamma from each FLEX series' own mark, where the inversion is validated."""
    styled = panel.rename(columns={"report_date": "date"})[
        [*SERIES_KEYS, "kind", "mark_price", "exercise_style"]
    ].drop_duplicates(SERIES_KEYS)
    rows = flex.merge(styled, on=SERIES_KEYS, how="left", validate="many_to_one")
    spots = chains.groupby(["date", "symbol"])["underlying_price"].median().rename("spot")
    rows = rows.join(spots, on=["date", "symbol"])
    frame = rows.rename(columns={"date": "report_date"})
    labels = buckets(frame["strike"] / frame["spot"], frame["days"])
    in_domain = [
        (str(m), str(d)) in domain
        for m, d in zip(labels["moneyness_bucket"], labels["dte_bucket"], strict=True)
    ]
    candidates = frame[np.asarray(in_domain) & frame["mark_price"].notna()]
    inverted = implied_vols_frame(candidates, rate=RATE)
    ok = inverted["iv_status"].astype(str) == InversionStatus.OK.value
    sigma = pd.Series(np.nan, index=frame.index)
    sigma.loc[inverted.index[ok]] = inverted.loc[ok, "iv"]
    gamma = black_scholes_greeks(
        frame["spot"].to_numpy(dtype=float),
        frame["strike"].to_numpy(dtype=float),
        frame["days"].to_numpy(dtype=float) / 365.0,
        sigma.fillna(1.0).to_numpy(dtype=float),
        rate=RATE,
        carry=0.0,
        is_call=True,
    ).gamma
    at_marks = pd.Series(
        dollar_gamma(gamma, frame["open_interest"], frame["spot"]), index=frame.index
    ).where(sigma.notna())
    return mark_check(flex, sigma, at_marks)


__all__ = ["NAME", "GammaInputs", "hidden_gamma_analysis", "hidden_gamma_result", "load_inputs"]
