"""Result `gex_map`: SPY's gamma exposure with one issuer's fund legs signed by holdings.

Specification: `docs/log/2026-11-15-gex-map-spec.md`. Inputs are SPY's listed chain for
the settlement of REPORT_DATE, OCC's FLEX report of that date, and the holdings snapshot
the `holders` result uses. The date lies after the end of the panel.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hidden_options.collect.issuer_snapshots import (
    parse_box_fund_page,
    parse_family_file,
    snapshot_folder,
)
from hidden_options.config import RAW_DIR
from hidden_options.measure.gex_map import gex_profiles, zero_level
from hidden_options.measure.hidden_gamma import MAX_IV, MIN_IV, surface_points, surface_vol
from hidden_options.measure.hidden_share_data import load_chains, priced_chains, trading_calendar
from hidden_options.measure.holders import KEY, flex_lines
from hidden_options.measure.holders_result import (
    BOX_FUND,
    BOX_FUND_PAGE,
    FAMILY_FILE,
    REPORT_DATE,
    SNAPSHOT_DATE,
)
from hidden_options.measure.implied import RATE
from hidden_options.measure.implied_data import PANEL_READ_COLUMNS, read_panel
from hidden_options.publish import formats
from hidden_options.publish.registry import ANALYSES
from hidden_options.publish.results import Result, now_iso

NAME = "gex_map"
SYMBOL = "SPY"
DROP = -0.1
READINGS = ("listed", "convention", "signed")


def gex_map_result(chain: pd.DataFrame, report: pd.DataFrame, holdings: pd.DataFrame) -> Result:
    """The figures the specification lists.

    `chain` holds SPY's priced listed series for the settlement (`priced_chains` with
    `iv`); `report` that date's FLEX report rows; `holdings` the funds' option lines.
    """
    day = pd.Timestamp(chain["date"].iloc[0])
    spot = float(chain["underlying_price"].dropna().iloc[0])
    live = chain[(chain["expiry"] > day) & (chain["open_interest"] > 0)]
    listed = live[live["iv"].between(MIN_IV, MAX_IV)]
    flex = report[
        (report["underlying"] == SYMBOL) & (report["expiry"] > day) & (report["open_interest"] > 0)
    ].reset_index(drop=True)
    sigma, _ = surface_vol(surface_points(chain), spot, day, flex)
    flex = flex.assign(sigma=sigma)
    priced = flex[np.isfinite(flex["sigma"])]

    held = flex_lines(holdings).groupby(KEY, as_index=False)["contracts"].sum()
    priced = priced.merge(held, on=KEY, how="left").fillna({"contracts": 0.0})
    share = np.minimum(1.0, priced["contracts"].abs() / priced["open_interest"])
    book = pd.concat(
        [
            pd.DataFrame(
                {
                    "source": "listed",
                    "expiry": listed["expiry"],
                    "right": listed["right"],
                    "strike": listed["strike"],
                    "open_interest": listed["open_interest"],
                    "sigma": listed["iv"],
                    "signed": 0.0,
                    "dealer_sign": 0.0,
                }
            ),
            pd.DataFrame(
                {
                    "source": "flex",
                    "expiry": priced["expiry"],
                    "right": priced["right"],
                    "strike": priced["strike"],
                    "open_interest": priced["open_interest"],
                    "sigma": priced["sigma"],
                    "signed": share,
                    "dealer_sign": -np.sign(priced["contracts"]),
                }
            ),
        ],
        ignore_index=True,
    )
    profiles = gex_profiles(book, spot=spot, as_of=day, rate=RATE)
    moves = profiles["moves"]
    at_spot, at_drop = moves.index(0.0), moves.index(DROP)
    values: dict[str, Any] = {
        "date": f"{day:%Y-%m-%d}",
        "spot": spot,
        "counts": {
            "listed_series": len(listed),
            "flex_series": len(flex),
            "flex_unpriced": int(len(flex) - len(priced)),
            "matched_series": int((share > 0).sum()),
            "matched_contracts": float(
                priced["contracts"].abs().clip(upper=priced["open_interest"]).sum()
            ),
        },
        "profiles": profiles,
        "at_spot": {name: profiles[name][at_spot] for name in READINGS},
        "at_drop": {name: profiles[name][at_drop] for name in READINGS},
        "zero": {name: zero_level(moves, profiles[name]) for name in READINGS},
        "drop": DROP,
    }
    run_inputs = {"date": values["date"], "symbol": SYMBOL, "rate": RATE}
    return Result(NAME, values, gex_map_macros(values), run_inputs, now_iso())


def gex_map_macros(values: dict[str, Any]) -> dict[str, str]:
    profiles, spot, drop = values["profiles"], values["at_spot"], values["at_drop"]
    macros = {
        "GexDate": formats.long_date(pd.Timestamp(values["date"])),
        "GexSpot": formats.decimal(values["spot"], 2),
        "GexDrop": formats.percent(-values["drop"]),
        "GexMatchedSeries": formats.count(values["counts"]["matched_series"]),
        "GexFlexUnpriced": formats.count(values["counts"]["flex_unpriced"]),
        "GexMatchedShareListed": formats.percent(profiles["matched_share_of_listed"], 1),
        "GexMatchedShareFlex": formats.percent(profiles["matched_share_of_flex"]),
        "GexSigningSpot": _bn(spot["signed"] - spot["convention"]),
        "GexSigningDrop": _bn(drop["signed"] - drop["convention"]),
    }
    for name, stem in (("listed", "Listed"), ("convention", "Convention"), ("signed", "Signed")):
        macros[f"Gex{stem}Spot"] = _bn(spot[name])
        macros[f"Gex{stem}Drop"] = _bn(drop[name])
        zero = values["zero"][name]
        macros[f"Gex{stem}Zero"] = (
            "none in range" if zero is None else formats.signed_percent(zero, 1)
        )
        macros[f"Gex{stem}ZeroLevel"] = (
            "none" if zero is None else formats.decimal(values["spot"] * (1 + zero), 0)
        )
    return macros


def _bn(value: float) -> str:
    r"""Dollars in billions to one decimal, with the sign before the dollar: `-\$1.2bn`."""
    sign = "-" if value < 0 else ""
    return f"{sign}\\${formats.decimal(abs(value) / 1e9, 1)}bn"


@ANALYSES.register(NAME)
def gex_map_analysis() -> Result:
    """SPY on REPORT_DATE, from the chains, report and snapshot on disk."""
    day = pd.Timestamp(REPORT_DATE)
    chains = load_chains(
        [RAW_DIR], trading_calendar(RAW_DIR), extra=("iv",), pattern=f"equity_{SYMBOL}.parquet"
    )
    priced = priced_chains(chains, extra=("iv",))
    chain = priced[(priced["date"] == day) & (priced["symbol"] == SYMBOL)].reset_index(drop=True)
    if chain.empty:
        raise FileNotFoundError(f"No {SYMBOL} chain for the settlement of {day:%Y-%m-%d}")
    report = read_panel(RAW_DIR, ("equity",), PANEL_READ_COLUMNS, day, day)
    folder = RAW_DIR / snapshot_folder(SNAPSHOT_DATE)
    holdings = pd.concat(
        [
            parse_family_file((folder / FAMILY_FILE).read_bytes()),
            parse_box_fund_page((folder / BOX_FUND_PAGE).read_bytes(), BOX_FUND, day),
        ],
        ignore_index=True,
    )
    return gex_map_result(chain, report, holdings)


__all__ = ["NAME", "gex_map_analysis", "gex_map_macros", "gex_map_result"]
