"""Result `positions`: cleared series against positions across the market (M4).

Every report date is walked once. Its legs are grouped (`structures.group_legs`), and its
marks inverted and valued at the rate of the volatility result and at two others, with a
delta only inside the validated domain of that result. Afterwards the detector is scored
against disclosed holdings (`holdings_truth`, where the score is defined), and the worked
cases are found by their signatures and recomputed.

Under `PRECISION_RECALL_FLOOR` on either score the market-wide claim is limited: `restricted`
says so, and the section keeps to the subset the holdings speak for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.config import PANEL_END
from hidden_options.measure.holdings_truth import (
    MAX_STALENESS_BDAYS,
    floor_check,
    globalx_overlap,
    holdings_structures,
    score_against_holdings,
    score_by_date,
)
from hidden_options.measure.implied import (
    CARRY,
    RATE,
    InversionStatus,
    bucketed,
    greeks_frame,
    implied_vols_frame,
)
from hidden_options.measure.positions import (
    chance_structured_share,
    legs_from_panel,
    locate_butterfly,
    locate_collar,
    max_value,
    notional_measures,
    payoff,
    per_underlying_ratios,
    structure_shares,
)
from hidden_options.measure.positions_data import RESULT_NAME, PositionsInputs, load_inputs
from hidden_options.measure.positions_macros import positions_macros
from hidden_options.measure.structures import (
    CONTRACT_MULTIPLIER,
    GroupingConfig,
    group_legs,
)
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = RESULT_NAME
PRECISION_RECALL_FLOOR = 0.5
SENSITIVITY_RATES = (0.03, 0.05)
# The chance baseline is drawn on every CHANCE_EVERY-th report date.
CHANCE_EVERY = 5
CHANCE_SEED = 20261023
# The structured share is also read at these count tolerances, on the last date.
TOLERANCES = (0.0, 0.01, 0.10)
# The worked cases, by the signatures an earlier census described.
BUTTERFLY_UNDERLYING = "MSFT"
BUTTERFLY_MIN_WING = 50_000
COLLAR_UNDERLYING = "SPY"
COLLAR_DEEP_STRIKE = 1.87
COLLAR_SIZE = 37_500
CASE_UNDERLYINGS = (BUTTERFLY_UNDERLYING, COLLAR_UNDERLYING)
# Structure types the result names, in order; the rest are `other`.
NAMED_TYPES = (
    "synthetic",
    "risk_reversal",
    "vertical_spread",
    "butterfly",
    "three_leg",
    "collar_buffer",
)
RATIO_QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
_SIDE_COLUMNS = ["report_date", "root", "expiry", "right", "strike"]
_REPORT_KEY = ["report_date", "underlying", "expiry", "right", "strike"]


@dataclass
class _Walk:
    """What the walk over the report dates keeps."""

    daily: list[dict[str, Any]] = field(default_factory=list)
    measures: dict[float, list[pd.DataFrame]] = field(default_factory=dict)
    detected: list[pd.DataFrame] = field(default_factory=list)
    held: list[pd.DataFrame] = field(default_factory=list)
    case_rows: list[pd.DataFrame] = field(default_factory=list)
    globalx_rows: list[pd.DataFrame] = field(default_factory=list)
    chance: list[float] = field(default_factory=list)
    priced_oi: float = 0.0
    no_spot_oi: float = 0.0
    below_floor_oi: float = 0.0
    understated_oi: float = 0.0
    total_oi: float = 0.0
    floor_delta: list[pd.DataFrame] = field(default_factory=list)
    rows: int = 0
    tolerance: dict[str, float] = field(default_factory=dict)


def positions_result(inputs: PositionsInputs) -> Result:
    """The `positions` result from loaded inputs, up to the frozen PANEL_END."""
    end = pd.Timestamp(PANEL_END)
    dates = [pd.Timestamp(day) for day in inputs.dates if pd.Timestamp(day) <= end]
    holdings = inputs.holdings[pd.to_datetime(inputs.holdings["as_of"]) <= end]
    globalx = inputs.globalx[pd.to_datetime(inputs.globalx["as_of"]) <= end]
    truth = holdings_structures(holdings, dates)
    same_day = holdings_structures(holdings, dates, same_day=True)
    walk = _walk(dates, inputs, truth, same_day, globalx)
    measures = {
        rate: pd.concat(frames, ignore_index=True) for rate, frames in walk.measures.items()
    }
    ratios = per_underlying_ratios(measures[RATE])
    validation = _validation(walk, truth, same_day, globalx, dates)
    values: dict[str, Any] = {
        "settings": _settings(),
        "window": {
            "first_date": formats.iso_date(dates[0]),
            "last_date": formats.iso_date(dates[-1]),
            "dates": len(dates),
            "rows": walk.rows,
            "panel_end": formats.iso_date(end),
            "every_date": True,
        },
        "validation": validation,
        "restricted": _restricted(validation["score"]),
        "market": _market(walk),
        "ratios": _ratios(ratios, measures, walk),
        "cases": _cases(pd.concat(walk.case_rows, ignore_index=True), inputs),
    }
    run_inputs = {
        "sources": {
            "flex": "data/raw/occ_flex",
            "index_levels": "data/raw/cboe_chain, data/ci_captures/*/raw/cboe_chain",
            "bars": "data/flex_underlying_bars.parquet",
            "holdings": "data/raw/fund_holdings, data/ci_captures/*/raw/fund_holdings",
            "globalx": "data/raw/globalx_holdings",
            "domain": "results/implied_validation.json",
        },
        "ci_runs": list(inputs.ci_runs),
        "local_only": inputs.local_only,
        "panel_end": formats.iso_date(end),
        "panel_rows": walk.rows,
        "holding_rows": len(holdings),
        "spot_rows": len(inputs.spots),
    }
    return Result(NAME, values, positions_macros(values), run_inputs, now_iso())


@ANALYSES.register(NAME)
def positions_analysis() -> Result:
    """M4 on the panel, spots and holdings on disk."""
    return positions_result(load_inputs())


def _walk(
    dates: Sequence[pd.Timestamp],
    inputs: PositionsInputs,
    truth: pd.DataFrame,
    same_day: pd.DataFrame,
    globalx: pd.DataFrame,
) -> _Walk:
    walk = _Walk(measures={rate: [] for rate in (RATE, *SENSITIVITY_RATES)})
    spots = inputs.spots.assign(date=pd.to_datetime(inputs.spots["date"]))
    by_day = dict(iter(spots.groupby("date", sort=False)))
    both = pd.concat([truth, same_day], ignore_index=True)
    scored_days = set(pd.to_datetime(both["report_date"]))
    roots = set(both["root"].astype(str))
    underlyings = set(both["underlying"].astype(str))
    option_keys = globalx[["underlying", "expiry", "right", "strike"]].drop_duplicates()
    for position, day in enumerate(dates):
        rows = inputs.read_day(day).reset_index(drop=True)
        rows = rows.assign(
            expiry=pd.to_datetime(rows["expiry"]).astype("datetime64[ns]"),
            report_date=pd.to_datetime(rows["report_date"]).astype("datetime64[ns]"),
        )
        today = by_day.get(day)
        spot = {} if today is None else dict(zip(today["underlying"], today["spot"], strict=True))
        legs, table = group_legs(legs_from_panel(rows), spot)
        _tally(walk, day, rows, legs, table)
        priced = {rate: priced_rows(rows, spot, rate, inputs.domain) for rate in walk.measures}
        for rate, frame in priced.items():
            walk.measures[rate].append(
                notional_measures(rows, frame, legs, spot).assign(report_date=day)
            )
        _tally_coverage(walk, priced[RATE])
        walk.floor_delta.append(
            notional_measures(rows, with_floor_delta(priced[RATE]), legs, spot).assign(
                report_date=day
            )
        )
        if day in scored_days:
            walk.detected.append(scored_legs(legs, underlyings))
            walk.held.append(priced[RATE][priced[RATE]["root"].astype(str).isin(roots)])
        walk.case_rows.append(rows[rows["underlying"].isin(CASE_UNDERLYINGS)])
        walk.globalx_rows.append(rows.merge(option_keys)[_REPORT_KEY])
        if position % CHANCE_EVERY == 0:
            walk.chance.append(chance_structured_share(legs, seed=CHANCE_SEED + position))
        if position == len(dates) - 1:
            walk.tolerance = _tolerance_shares(legs)
    return walk


def scored_legs(legs: pd.DataFrame, underlyings: set[str]) -> pd.DataFrame:
    """One date's grouped legs the score needs: every leg of the underlyings funds hold.

    By underlying, not by root, since a structure may hold legs of more than one root.
    """
    kept: pd.DataFrame = legs[legs["underlying"].astype(str).isin(underlyings)]
    return kept


def _tolerance_shares(legs: pd.DataFrame) -> dict[str, float]:
    frozen = GroupingConfig()
    plain = legs.drop(columns=["structure_id", "structure"])
    return {
        f"{tolerance:.2f}": structure_shares(
            group_legs(plain, {}, GroupingConfig(tolerance, frozen.min_contracts, frozen.min_legs))[
                0
            ]
        )["structured"]
        for tolerance in TOLERANCES
    }


def priced_rows(
    rows: pd.DataFrame,
    spot: Mapping[str, float],
    rate: float,
    domain: frozenset[tuple[str, str]],
) -> pd.DataFrame:
    """One date's rows with their greeks, `delta_dollars` kept only in the validated domain."""
    frame = rows.assign(spot=rows["underlying"].map(dict(spot)).astype(float))
    inverted = bucketed(implied_vols_frame(frame, rate=rate, carry=CARRY))
    valued = greeks_frame(inverted, rate=rate, carry=CARRY)
    usable = (valued["iv_status"] == InversionStatus.OK.value) & in_domain(valued, domain)
    return valued.assign(in_domain=usable, delta_dollars=valued["delta_dollars"].where(usable))


def with_floor_delta(priced: pd.DataFrame) -> pd.DataFrame:
    """`priced_rows` with a delta of one, in size, on every mark below the model's floor.

    Such a call has no time value left to back a volatility out of, and moves one for one
    with the underlying. Outside the validated domain, so a sensitivity and not a claim.
    """
    below = priced["iv_status"] == InversionStatus.BELOW_INTRINSIC.value
    side = priced["right"].map({"C": 1.0, "P": -1.0})
    full = side * priced["open_interest"].astype(float) * CONTRACT_MULTIPLIER * priced["spot"]
    return priced.assign(delta_dollars=priced["delta_dollars"].where(~below, full))


def in_domain(frame: pd.DataFrame, domain: frozenset[tuple[str, str]]) -> pd.Series:
    cells = pd.Series(
        list(zip(frame["moneyness_bucket"], frame["dte_bucket"], strict=True)),
        index=frame.index,
        dtype=object,
    )
    return cells.isin(domain)


def _tally(
    walk: _Walk, day: pd.Timestamp, rows: pd.DataFrame, legs: pd.DataFrame, table: pd.DataFrame
) -> None:
    shares = structure_shares(legs)
    types = {name: shares["by_type"].get(name, 0.0) for name in NAMED_TYPES}
    walk.rows += len(rows)
    walk.daily.append(
        {
            "report_date": day,
            "contracts": shares["contracts"],
            "structured": shares["structured"],
            "structures": len(table),
            "series": len(legs),
            "grouped_series": int((legs["structure_id"] >= 0).sum()),
            "other": 1.0 - sum(types.values()) if shares["structured"] else 0.0,
            **types,
        }
    )


def _tally_coverage(walk: _Walk, priced: pd.DataFrame) -> None:
    oi = priced["open_interest"].astype(float)
    walk.total_oi += float(oi.sum())
    walk.priced_oi += float(oi[priced["delta_dollars"].notna()].sum())
    walk.no_spot_oi += float(oi[priced["spot"].isna()].sum())
    below = priced["iv_status"] == InversionStatus.BELOW_INTRINSIC.value
    walk.below_floor_oi += float(oi[below].sum())
    strike_value = priced["strike"].astype(float) * oi * CONTRACT_MULTIPLIER
    walk.understated_oi += float(oi[strike_value < priced["delta_dollars"].abs()].sum())


def _settings() -> dict[str, Any]:
    return {
        "grouping": asdict(GroupingConfig()),
        "scoring_commit": "83068b6",
        "max_staleness_bdays": MAX_STALENESS_BDAYS,
        "rate": RATE,
        "carry": CARRY,
        "sensitivity_rates": list(SENSITIVITY_RATES),
        "precision_recall_floor": PRECISION_RECALL_FLOOR,
        "chance_every": CHANCE_EVERY,
        "scoring_unit": "distinct structures, each averaged over its dates",
        "tolerances": list(TOLERANCES),
    }


def _validation(
    walk: _Walk,
    truth: pd.DataFrame,
    same_day: pd.DataFrame,
    globalx: pd.DataFrame,
    dates: Sequence[pd.Timestamp],
) -> dict[str, Any]:
    detected = pd.concat(walk.detected, ignore_index=True)
    held = pd.concat(walk.held, ignore_index=True)
    report = pd.concat(walk.globalx_rows, ignore_index=True)
    multi = truth[truth["n_legs"] >= 2]
    daily = score_by_date(detected, truth)
    return {
        "score": asdict(score_against_holdings(detected, truth)),
        "same_day": asdict(score_against_holdings(detected, same_day)),
        "by_date": {
            "dates": len(daily),
            "median_precision": _pick(daily, "precision", "median"),
            "median_recall": _pick(daily, "recall", "median"),
            "low_recall": _pick(daily, "recall", "min"),
            "high_recall": _pick(daily, "recall", "max"),
        },
        "by_type": _by_type(detected, truth),
        "truth": {
            "files": truth.attrs.get("files", 0),
            "stale_files": truth.attrs.get("stale_files", 0),
            "first_as_of": formats.iso_date(pd.Timestamp(truth["as_of"].min())),
            "last_as_of": formats.iso_date(pd.Timestamp(truth["as_of"].max())),
            "funds_with_flex": int(truth["fund"].nunique()),
            "legs": len(truth),
            "single_leg_structures": int(truth.loc[truth["n_legs"] == 1, "truth_id"].nunique()),
            "types": _types(multi),
        },
        "floor": {
            "as_of_previous": floor_check(truth, held),
            "as_of_same_day": floor_check(same_day, held),
        },
        "holder_share": _holder_share(multi, held),
        "signs": _signs(multi, held),
        "globalx": globalx_overlap(globalx, report, dates),
    }


def _restricted(score: Mapping[str, Any]) -> bool:
    return bool(min(score["precision"], score["recall"]) < PRECISION_RECALL_FLOOR)


def _by_type(detected: pd.DataFrame, truth: pd.DataFrame) -> dict[str, Any]:
    """Recall by the type of the fund's legs, precision by the type of the detected structure."""
    multi = truth[truth["n_legs"] >= 2]
    labels = detected["structure"].dropna().astype(str)
    names = sorted(set(multi["structure"].astype(str)) | set(labels))
    found: dict[str, Any] = {}
    for name in names:
        recall = score_against_holdings(detected, multi[multi["structure"] == name])
        keep = (detected["structure_id"] < 0) | (detected["structure"] == name)
        precision = score_against_holdings(detected[keep], truth)
        if recall.n_truth_structures or precision.n_detected_touching:
            found[name] = {
                "truth": recall.n_truth_structures,
                "recall": recall.recall if recall.n_truth_structures else None,
                "recall_grouped": recall.recall_grouped if recall.n_truth_structures else None,
                "touching": precision.n_detected_touching,
                "precision": precision.precision if precision.n_detected_touching else None,
            }
    return found


def _types(multi: pd.DataFrame) -> dict[str, int]:
    distinct = multi.drop_duplicates("truth_id")["structure"].astype(str).value_counts()
    return {str(name): int(count) for name, count in distinct.sort_index().items()}


def _holder_share(multi: pd.DataFrame, held: pd.DataFrame) -> float | None:
    """The median, over the legs funds hold in structures, of the fund's part of the open
    interest. A low one means other holders share the series, as clearing would hide."""
    joined = _joined(multi, held)
    usable = joined[joined["open_interest"] > 0]
    if usable.empty:
        return None
    shares = usable["contracts"].abs() / usable["open_interest"].astype(float)
    return float(shares.median())


def _signs(multi: pd.DataFrame, held: pd.DataFrame) -> dict[str, Any]:
    """How the all-long netting reads a structure whose signs a fund discloses.

    For each distinct structure with every leg priced on a date, the fund's own net delta
    (its signed contracts) beside what the netting rule gives on the same contracts, and
    beside the gross delta of those contracts.
    """
    joined = _joined(multi, held)
    joined = joined[joined["delta_dollars"].notna()]
    if joined.empty:
        return {"structures": 0, "rule_over_signed": None, "signed_over_gross": None}
    base = joined["delta"] * CONTRACT_MULTIPLIER * joined["spot"]
    frame = joined.assign(
        signed=base * joined["contracts"],
        all_long=base * joined["contracts"].abs(),
        gross=(base * joined["contracts"]).abs(),
        legs_priced=1,
    )
    per_date = frame.groupby(["truth_id", "report_date"], sort=True).agg(
        signed=("signed", "sum"),
        all_long=("all_long", "sum"),
        gross=("gross", "sum"),
        legs_priced=("legs_priced", "sum"),
        n_legs=("n_legs", "first"),
    )
    per_date = per_date[(per_date["legs_priced"] == per_date["n_legs"]) & (per_date["signed"] != 0)]
    if per_date.empty:
        return {"structures": 0, "rule_over_signed": None, "signed_over_gross": None}
    medians = (
        pd.DataFrame(
            {
                "rule": per_date["all_long"].abs() / per_date["signed"].abs(),
                "signed": per_date["signed"].abs() / per_date["gross"],
            }
        )
        .groupby("truth_id")
        .median()
    )
    return {
        "structures": len(medians),
        "rule_over_signed": float(medians["rule"].median()),
        "signed_over_gross": float(medians["signed"].median()),
    }


def _joined(multi: pd.DataFrame, held: pd.DataFrame) -> pd.DataFrame:
    columns = [*_SIDE_COLUMNS, "open_interest", "delta", "delta_dollars", "spot"]
    report = held[columns].drop_duplicates(_SIDE_COLUMNS)
    joined: pd.DataFrame = multi.merge(report, on=_SIDE_COLUMNS)
    return joined


def _market(walk: _Walk) -> dict[str, Any]:
    daily = pd.DataFrame(walk.daily)
    structured = daily["structured"].astype(float)
    last = daily.iloc[-1]
    return {
        "structured_mean": float(structured.mean()),
        "structured_first": float(structured.iloc[0]),
        "structured_last": float(structured.iloc[-1]),
        "structured_min": float(structured.min()),
        "structured_max": float(structured.max()),
        "chance_mean": float(np.mean(walk.chance)),
        "chance_dates": len(walk.chance),
        "structures_last": int(last["structures"]),
        "series_last": int(last["series"]),
        "grouped_series_last": int(last["grouped_series"]),
        "types_mean": {name: float(daily[name].mean()) for name in (*NAMED_TYPES, "other")},
        "tolerance_last": dict(walk.tolerance),
    }


def _ratios(
    ratios: pd.DataFrame, measures: Mapping[float, pd.DataFrame], walk: _Walk
) -> dict[str, Any]:
    base = measures[RATE]
    floor = per_underlying_ratios(pd.concat(walk.floor_delta, ignore_index=True))
    covered = float((base["covered_oi_share"] * base["open_interest"]).sum())
    total = float(base["open_interest"].sum())
    return {
        "underlyings": len(ratios),
        "rule": _distribution(ratios["ratio"]),
        "gross": _distribution(ratios["gross_ratio"]),
        "market": _pooled(base),
        "structured_by_underlying": _share_across(base),
        "coverage": {
            "covered_share": covered / total if total else None,
            "priced_share": walk.priced_oi / walk.total_oi if walk.total_oi else None,
            "no_spot_share": walk.no_spot_oi / walk.total_oi if walk.total_oi else None,
            "outside_share": 1 - covered / total if total else None,
        },
        "legs": {
            "understated_share": walk.understated_oi / walk.priced_oi if walk.priced_oi else None,
            "below_floor_share": walk.below_floor_oi / walk.total_oi if walk.total_oi else None,
        },
        "floor_delta": _distribution(floor["ratio"]),
        "floor_delta_gross": _distribution(floor["gross_ratio"]),
        "rates": {
            f"{rate:.2f}": _distribution(per_underlying_ratios(measures[rate])["ratio"])
            for rate in SENSITIVITY_RATES
        },
        "rates_gross": {
            f"{rate:.2f}": _distribution(per_underlying_ratios(measures[rate])["gross_ratio"])
            for rate in SENSITIVITY_RATES
        },
        "by_underlying": [
            {
                "symbol": str(row.underlying),
                "ratio": float(row.ratio),  # type: ignore[arg-type]
                "gross_ratio": float(row.gross_ratio),  # type: ignore[arg-type]
            }
            for row in ratios.itertuples()
        ],
    }


def _share_across(base: pd.DataFrame) -> dict[str, Any]:
    """Each underlying's median structured share across dates, summarised across them."""
    shares = base.groupby("underlying")["structured_oi_share"].median()
    return {
        "n": len(shares),
        "median": float(shares.median()),
        "at_least_half": float((shares >= 0.5).mean()),
    }


def _distribution(values: pd.Series) -> dict[str, Any]:
    clean = values[np.isfinite(values.to_numpy(dtype=float))].astype(float)
    if clean.empty:
        return {"n": 0, "quantiles": {}, "below_one": None, "above_one": None}
    return {
        "n": len(clean),
        "quantiles": {f"{q:.2f}": float(clean.quantile(q)) for q in RATIO_QUANTILES},
        "below_one": float((clean < 1).mean()),
        "above_one": float((clean > 1).mean()),
        "above_ten": float((clean > 10).mean()),
        "below_tenth": float((clean < 0.1).mean()),
        "low": float(clean.min()),
        "high": float(clean.max()),
    }


def _pooled(base: pd.DataFrame) -> dict[str, Any]:
    """The whole market on each date, then the median date."""
    columns = [
        "strike_notional",
        "mark_value",
        "strike_notional_priced",
        "delta_exposure",
        "gross_delta",
    ]
    per_date = base.groupby("report_date", sort=True)[columns].sum()
    usable = per_date[per_date["delta_exposure"] > 0]
    over_net = usable["strike_notional_priced"] / usable["delta_exposure"]
    over_gross = usable["strike_notional_priced"] / usable["gross_delta"]
    netting = (usable["gross_delta"] / usable["delta_exposure"]).map(np.log) / over_net.map(np.log)
    last = per_date.iloc[-1]
    return {
        "strike_over_delta": float(over_net.median()),
        "strike_over_gross": float(over_gross.median()),
        "strike_over_mark": float((per_date["strike_notional"] / per_date["mark_value"]).median()),
        "netting_share_of_gap": float(netting.median()),
        "last_strike_notional": float(last["strike_notional"]),
        "last_mark_value": float(last["mark_value"]),
        "last_strike_priced": float(last["strike_notional_priced"]),
        "last_delta_exposure": float(last["delta_exposure"]),
        "last_gross_delta": float(last["gross_delta"]),
    }


def _cases(rows: pd.DataFrame, inputs: PositionsInputs) -> dict[str, Any]:
    return {"butterfly": _butterfly(rows, inputs), "collar": _collar(rows, inputs)}


def _spot_on(inputs: PositionsInputs, underlying: str, day: pd.Timestamp) -> float | None:
    spots = inputs.spots
    found = spots[(pd.to_datetime(spots["date"]) == day) & (spots["underlying"] == underlying)]
    return float(found["spot"].iloc[0]) if len(found) else None


def _butterfly(rows: pd.DataFrame, inputs: PositionsInputs) -> dict[str, Any] | None:
    case = locate_butterfly(rows, BUTTERFLY_UNDERLYING, min_wing=BUTTERFLY_MIN_WING)
    if case is None:
        return None
    day = case["report_date"]
    today = rows[(rows["report_date"] == day) & (rows["underlying"] == case["underlying"])]
    grouped, _ = group_legs(legs_from_panel(today), {})
    legs = case["legs"]
    return {
        "report_date": formats.iso_date(day),
        "underlying": case["underlying"],
        "spot": _spot_on(inputs, case["underlying"], day),
        "lines": case["lines"],
        "expiries": [formats.iso_date(pd.Timestamp(e)) for e in case["expiries"]],
        "strike_notional": case["strike_notional"],
        "max_value": case["max_value"],
        "overstatement": case["overstatement"],
        "wings_grouped": _wing_pairs(grouped, legs),
        "legs": _leg_records(legs),
    }


def _wing_pairs(grouped: pd.DataFrame, legs: pd.DataFrame) -> int:
    """At how many of the expiries the detector groups the two wings together."""
    calls = grouped[grouped["right"] == "C"]
    pairs = 0
    for expiry, signed in legs.groupby("expiry"):
        wings = set(signed.loc[signed["contracts"] > 0, "strike"].astype(float))
        here = calls[(calls["expiry"] == expiry) & calls["strike"].astype(float).isin(wings)]
        ids = set(here["structure_id"])
        pairs += len(ids) == 1 and -1 not in ids
    return pairs


def _collar(rows: pd.DataFrame, inputs: PositionsInputs) -> dict[str, Any] | None:
    case = locate_collar(rows, COLLAR_UNDERLYING, deep_strike=COLLAR_DEEP_STRIKE, size=COLLAR_SIZE)
    if case is None:
        return None
    day, underlying = case["report_date"], case["underlying"]
    spot = _spot_on(inputs, underlying, day)
    legs = case["legs"]
    priced = priced_rows(legs, {underlying: spot} if spot else {}, RATE, inputs.domain)
    signed = _collar_signs(priced)
    strike_notional = float((legs["strike"] * legs["open_interest"]).sum() * CONTRACT_MULTIPLIER)
    size = float(legs["open_interest"].median())
    today = rows[(rows["report_date"] == day) & (rows["underlying"] == underlying)]
    grouped, _ = group_legs(legs_from_panel(today), {})
    keys = legs[["expiry", "right", "strike"]]
    ids = set(grouped.merge(keys, on=["expiry", "right", "strike"])["structure_id"])
    top = max_value(signed)
    return {
        "report_date": formats.iso_date(day),
        "expiry": formats.iso_date(case["expiry"]),
        "underlying": underlying,
        "spot": spot,
        "size": size,
        "strike_notional": strike_notional,
        "max_value": top,
        "spot_exposure": None if spot is None else size * CONTRACT_MULTIPLIER * spot,
        "overstatement": strike_notional / top,
        "detected_as_one": len(ids) == 1 and -1 not in ids,
        "legs": _leg_records(signed),
        "floor_at_expiry": float(payoff(signed, np.array([0.0]))[0]),
        "deep_call": _deep_call(priced, spot),
    }


def _collar_signs(priced: pd.DataFrame) -> pd.DataFrame:
    """The buffer construction: long the deep call and the higher put, short the rest."""
    calls = priced["right"] == "C"
    low_call = priced.loc[calls, "strike"].min()
    high_put = priced.loc[~calls, "strike"].max()
    long_leg = (calls & (priced["strike"] == low_call)) | (~calls & (priced["strike"] == high_put))
    size = priced["open_interest"].astype(float)
    return pd.DataFrame(
        {
            "right": priced["right"],
            "strike": priced["strike"].astype(float),
            "contracts": size.where(long_leg, -size),
            "expiry": priced["expiry"],
        }
    )


def _deep_call(priced: pd.DataFrame, spot: float | None) -> dict[str, Any]:
    calls = priced[priced["right"] == "C"]
    row = calls.sort_values("strike").iloc[0]
    size = float(row["open_interest"])
    notional = float(row["strike"]) * size * CONTRACT_MULTIPLIER
    usable = bool(row["in_domain"])
    delta = float(row["delta"]) if usable else None
    exposure = None if spot is None else size * CONTRACT_MULTIPLIER * spot * (delta or 1.0)
    return {
        "strike": float(row["strike"]),
        "contracts": size,
        "mark": float(row["mark_price"]),
        "iv_status": str(row["iv_status"]),
        "in_domain": usable,
        "delta": delta,
        "strike_notional": notional,
        "exposure": exposure,
        "ratio": None if exposure is None else exposure / notional,
    }


def _leg_records(legs: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "expiry": formats.iso_date(pd.Timestamp(str(leg.expiry))),
            "right": str(leg.right),
            "strike": float(leg.strike),  # type: ignore[arg-type]
            "contracts": float(leg.contracts),  # type: ignore[arg-type]
        }
        for leg in legs.itertuples()
    ]


def _pick(frame: pd.DataFrame, column: str, how: str) -> float | None:
    return float(frame[column].agg(how)) if len(frame) else None
