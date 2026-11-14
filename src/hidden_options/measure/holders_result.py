"""Result `holders`: the product rules and the dealer's side against issuer holdings.

Specification: `docs/log/2026-11-10-holders-spec.md`. One snapshot: Innovator's all-funds
holdings file and the BOXX fund page captured on SNAPSHOT_DATE, against OCC's FLEX report
of REPORT_DATE, the activity date before it. The date lies after the end of the panel.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from hidden_options.collect.issuer_snapshots import (
    parse_box_fund_page,
    parse_family_file,
    snapshot_folder,
)
from hidden_options.config import RAW_DIR
from hidden_options.measure.anatomy import classify
from hidden_options.measure.holders import (
    KEY,
    box_positions,
    category_shares,
    dealer_gamma,
    design_agreement,
    flex_lines,
    gamma_profile,
    match,
    matching,
    rule_recall,
    spots_from_stock_legs,
    with_roles,
)
from hidden_options.measure.holders_macros import holders_macros
from hidden_options.measure.implied import RATE, greeks_frame, implied_vols
from hidden_options.measure.implied_data import PANEL_READ_COLUMNS, read_panel
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "holders"
SNAPSHOT_DATE = date(2026, 11, 10)
REPORT_DATE = date(2026, 11, 9)
CONTRACT_MULTIPLIER = 100
BOX_FUND = "BOXX"
PROFILE_UNDERLYING = "SPY"
FAMILY_FILE = "innovator_xt_holdings.csv"
BOX_FUND_PAGE = "alphaarchitect_boxx.html"


def holders_result(family: pd.DataFrame, box_fund: pd.DataFrame, report: pd.DataFrame) -> Result:
    """The figures the specification lists.

    `family` and `box_fund` hold option lines in `issuer_snapshots.HOLDING_COLUMNS`;
    `report` is one date's FLEX report with its exercise styles, as `read_panel` gives it.
    """
    anatomy = classify(report)
    series = anatomy.series
    lines = with_roles(flex_lines(family))
    found = match(lines, series)
    spots = spots_from_stock_legs(series)
    priced = greeks_frame(implied_vols(report, spots, rate=RATE), rate=RATE)
    gamma = priced[[*KEY, "gamma", "spot", "open_interest", "underlying"]]
    legs = found[(found["role"] == "package_leg") & found["open_interest"].notna()]
    with_gamma = legs.merge(gamma[[*KEY, "gamma"]], on=KEY, how="left")["gamma"].notna()

    stock = lines[lines["role"] == "stock_leg"]
    per_fund = family.drop_duplicates("fund")
    values: dict[str, Any] = {
        "file_date": f"{pd.Timestamp(family['as_of'].iloc[0]):%Y-%m-%d}",
        "report_date": f"{pd.Timestamp(report['report_date'].iloc[0]):%Y-%m-%d}",
        "family": {
            "funds": int(family["fund"].nunique()),
            "net_assets": float(per_fund["net_assets"].sum()),
            "stock_leg_value": float(
                (stock["contracts"] * stock["price"]).sum() * CONTRACT_MULTIPLIER
            ),
        },
        "matching": matching(found),
        "rule_recall": rule_recall(found),
        "category_shares": category_shares(found, series),
        "design": design_agreement(found),
        "priced_share": float(with_gamma.mean()) if len(legs) else 0.0,
        "spots": {name: spots[name] for name in sorted(spots)},
        "dealer_gamma": dealer_gamma(found, gamma),
        "dealer_gamma_package": dealer_gamma(found[found["role"] == "package_leg"], gamma),
        "coverage": _coverage(found, gamma),
        "profile": _profile(found, priced),
        "box": _box(box_fund, anatomy.boxes, series),
    }
    run_inputs = {
        "file_date": values["file_date"],
        "report_date": values["report_date"],
        "family_lines": len(family),
        "box_fund_lines": len(box_fund),
    }
    return Result(NAME, values, holders_macros(values), run_inputs, now_iso())


def _coverage(found: pd.DataFrame, gamma: pd.DataFrame) -> dict[str, Any]:
    """How much of the matched holdings could be priced. A series is priced where its
    underlying has a spot from a stock-leg call and its mark inverts. Stock legs are left
    out: a call struck at a few percent of spot has no gamma to speak of, and its mark
    often sits below the model's floor. Added after the first figures, when the dealer's
    gamma turned out to leave some funds out."""
    present = found[found["open_interest"].notna() & (found["role"] != "stock_leg")]
    usable = gamma.loc[gamma["gamma"].notna(), KEY].assign(priced=True)
    flagged = present.merge(usable, on=KEY, how="left")
    priced = flagged["priced"].fillna(False).to_numpy(dtype=bool)
    size = flagged["contracts"].abs().to_numpy(float)
    funds = flagged["fund"].to_numpy()
    missing = flagged.loc[~priced, "underlying"].dropna().unique()
    return {
        "priced_contracts_share": float(size[priced].sum() / size.sum()) if size.sum() else 0.0,
        "funds": int(len(set(funds))),
        "priced_funds": int(len(set(funds[priced]))),
        "unpriced_underlyings": sorted(str(name) for name in missing),
        "package_share_of_priced": float(
            size[priced & (flagged["role"] == "package_leg").to_numpy()].sum() / size[priced].sum()
        )
        if size[priced].sum()
        else 0.0,
    }


def _profile(found: pd.DataFrame, priced: pd.DataFrame) -> dict[str, Any]:
    """The dealer's net gamma in the matched legs of PROFILE_UNDERLYING across spot
    levels, and the moves from spot at which it changes sign. Not in the specification:
    added after its figures were seen, as another view of the same legs."""
    profile = gamma_profile(found, priced, PROFILE_UNDERLYING, rate=RATE)
    moves, dealer = profile["moves"], profile["dealer"]
    flips = [
        (moves[i] + moves[i + 1]) / 2
        for i in range(len(dealer) - 1)
        if (dealer[i] < 0) != (dealer[i + 1] < 0)
    ]
    return {"underlying": PROFILE_UNDERLYING, **profile, "flips": flips}


def _box(box_fund: pd.DataFrame, boxes: pd.DataFrame, series: pd.DataFrame) -> dict[str, Any]:
    """The box fund's lending and borrowing, its largest lent box against that box's open
    interest, and its lent face against all box face the anatomy rules find."""
    positions = box_positions(flex_lines(box_fund))
    lent = positions[positions["side"] == "lent"].sort_values("face", ascending=False)
    borrowed = positions[positions["side"] == "borrowed"]
    market = float(boxes["face"].sum())
    out: dict[str, Any] = {
        "lent_face": float(lent["face"].sum()),
        "borrowed_face": float(borrowed["face"].sum()),
        "lent_contracts": float(lent["contracts"].iloc[0]) if len(lent) else 0.0,
        "market_face": market,
        "share_of_box_face": float(lent["face"].sum() / market) if market else 0.0,
        "share_of_its_box": 0.0,
        "its_box_is_a_box": False,
    }
    if len(lent):
        top = lent.iloc[0]
        line = series[
            (series["root"] == top["root"])
            & (series["expiry"] == top["expiry"])
            & (series["strike"] == top["lower"])
            & (series["right"] == "C")
        ]
        if len(line):
            out["share_of_its_box"] = float(top["contracts"] / line["open_interest"].iloc[0])
            out["its_box_is_a_box"] = bool(line["category"].iloc[0] == "box")
    return out


@ANALYSES.register(NAME)
def holders_analysis() -> Result:
    """The check on the snapshot held under RAW_DIR."""
    folder = RAW_DIR / snapshot_folder(SNAPSHOT_DATE)
    report_day = pd.Timestamp(REPORT_DATE)
    family = parse_family_file((folder / FAMILY_FILE).read_bytes())
    box_fund = parse_box_fund_page((folder / BOX_FUND_PAGE).read_bytes(), BOX_FUND, report_day)
    report = read_panel(RAW_DIR, ("equity", "index"), PANEL_READ_COLUMNS, report_day, report_day)
    return holders_result(family, box_fund, report)


__all__ = ["NAME", "REPORT_DATE", "SNAPSHOT_DATE", "holders_analysis", "holders_result"]
