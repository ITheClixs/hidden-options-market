"""Detect fund synthetic-long positions in OCC series-level open interest.

Background
----------
Single-name option-income funds do not hold the stock. They build a *synthetic long*
— long a call and short a put at the same expiry — and write calls against it. Both
legs are FLEX, so neither prints on the ordinary listed tape, and the flow was
expected to be invisible without paid data.

It is not invisible. OCC publishes open interest for every series for free, and the
put leg carries a distinctive fingerprint.

The fingerprint
---------------
The written put is issued on a *non-standard deliverable* series struck one or two
cents away from the round strike, so it cannot be confused or auto-exercised against
the listed series. Observed for MSTR on 2026-08-16::

    strike   call_oi   put_oi
     95.00     46125     1746     <- listed series
     95.01         0    45115     <- the fund's written put leg
     95.02      6620     6620     <- an unrelated combo at an offset strike

The 95.01 series matches the fund's disclosed -45,115 contracts exactly. The same
pattern reproduces across issuers and underlyings (IBIT 35.01, MARA 11.51,
TSLA 310.01, XOM 155.01, SNOW 260.01, PYPL 50.01 …).

Two signals therefore identify the leg, and both are needed:

1. **Offset strike** — the cents component is not a standard increment
   (not 0, 25, 50 or 75). This is what marks the series as non-standard deliverable.
2. **One-sidedness** — essentially all open interest sits on one right, because the
   series exists only to carry that leg.

An earlier version of this module keyed on *equal* call and put open interest. That
is the signature of a conversion/reversal or other combo, not of a fund synthetic,
and it produced a large, mostly irrelevant candidate set. It is retained below as
``find_combo_candidates`` because those structures are real dealer positions worth
measuring separately — but it is not the fund detector.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Cent values that appear on ordinary listed strikes ($0.50, $1, $2.50, $5 grids,
# plus quarter strikes on low-priced names).
_STANDARD_CENTS = frozenset({0, 25, 50, 75})

_REQUIRED_OI_COLUMNS = frozenset(
    {"symbol", "expiry", "strike", "call_open_interest", "put_open_interest"}
)
_REQUIRED_HOLDINGS_COLUMNS = frozenset(
    {"fund", "option_root", "expiry", "strike", "right", "contracts", "is_option"}
)

LEG_COLUMNS = (
    "symbol",
    "expiry",
    "strike",
    "leg_right",
    "leg_open_interest",
    "opposite_open_interest",
    "one_sidedness",
    "is_offset_strike",
)


@dataclass(frozen=True)
class DetectionConfig:
    """Tunables for synthetic-leg detection.

    `min_open_interest` suppresses coincidences in near-empty series.
    `min_one_sidedness` is the share of the series' open interest that must sit on a
    single right; 0.9 admits a leg that has accumulated a little opposing interest.
    """

    min_open_interest: int = 100
    min_one_sidedness: float = 0.9
    require_offset_strike: bool = True


def _require_columns(frame: pd.DataFrame, required: frozenset[str], name: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{name} frame is missing columns: {sorted(missing)}")


def is_offset_strike(strike: float) -> bool:
    """True when a strike sits off the standard listing grid (a FLEX indicator)."""
    cents = round(round(float(strike), 2) * 100) % 100
    return cents not in _STANDARD_CENTS


def _empty(columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def find_synthetic_legs(
    open_interest: pd.DataFrame, config: DetectionConfig | None = None
) -> pd.DataFrame:
    """Identify one-sided open interest on non-standard-deliverable series.

    Returns one row per candidate leg, never mutating the input. ``leg_right`` is the
    side carrying the position: ``P`` for the written put of a synthetic long.
    """
    cfg = config or DetectionConfig()
    _require_columns(open_interest, _REQUIRED_OI_COLUMNS, "open_interest")

    if open_interest.empty:
        return _empty(LEG_COLUMNS)

    frame = open_interest.copy()
    call = frame["call_open_interest"].astype(float)
    put = frame["put_open_interest"].astype(float)

    frame["leg_right"] = ["P" if p >= c else "C" for c, p in zip(call, put, strict=True)]
    frame["leg_open_interest"] = pd.concat([call, put], axis=1).max(axis=1)
    frame["opposite_open_interest"] = pd.concat([call, put], axis=1).min(axis=1)
    total = frame["leg_open_interest"] + frame["opposite_open_interest"]
    frame["one_sidedness"] = (frame["leg_open_interest"] / total.replace(0, pd.NA)).fillna(0.0)
    frame["is_offset_strike"] = frame["strike"].map(is_offset_strike)

    keep = (frame["leg_open_interest"] >= cfg.min_open_interest) & (
        frame["one_sidedness"] >= cfg.min_one_sidedness
    )
    if cfg.require_offset_strike:
        keep &= frame["is_offset_strike"]

    result = frame.loc[keep, list(LEG_COLUMNS)]
    return result.sort_values("leg_open_interest", ascending=False).reset_index(drop=True)


def find_combo_candidates(
    open_interest: pd.DataFrame, config: DetectionConfig | None = None
) -> pd.DataFrame:
    """Identify series with matched call and put open interest.

    These are conversions, reversals, boxes and collars rather than fund synthetics.
    Measured separately because they are genuine dealer inventory, but they must not
    be conflated with disclosed fund flow.
    """
    cfg = config or DetectionConfig()
    _require_columns(open_interest, _REQUIRED_OI_COLUMNS, "open_interest")

    if open_interest.empty:
        return _empty(("symbol", "expiry", "strike", "paired_open_interest", "is_offset_strike"))

    frame = open_interest.copy()
    matched = frame["call_open_interest"] == frame["put_open_interest"]
    big = frame["call_open_interest"] >= cfg.min_open_interest

    result = frame.loc[matched & big].copy()
    result["paired_open_interest"] = result["call_open_interest"]
    result["is_offset_strike"] = result["strike"].map(is_offset_strike)
    return (
        result[["symbol", "expiry", "strike", "paired_open_interest", "is_offset_strike"]]
        .sort_values("paired_open_interest", ascending=False)
        .reset_index(drop=True)
    )


def underlying_from_root(root: object) -> str | None:
    """Strip the non-standard-deliverable prefix from an option root ('2MSTR' -> 'MSTR')."""
    if root is None or (isinstance(root, float) and pd.isna(root)):
        return None
    return str(root).lstrip("0123456789").strip() or None


def reconcile_with_holdings(
    legs: pd.DataFrame, holdings: pd.DataFrame, *, strike_tolerance: float = 0.05
) -> pd.DataFrame:
    """Attribute detected legs to the funds that disclose them.

    Matching requires the **underlying**, the expiry, a strike within tolerance, and
    the same right with the correct sign (a written put leg must correspond to a
    negative disclosed put position). Omitting the underlying check silently matches
    every fund to every symbol, which is wrong in a way that looks plausible.

    Legs with no disclosed counterpart are retained with nulls: those are the
    discovery channel, since they indicate a programme not yet in the registry.
    """
    _require_columns(holdings, _REQUIRED_HOLDINGS_COLUMNS, "holdings")

    if legs.empty:
        return legs.assign(matched_fund=None, disclosed_contracts=None)

    option_legs = holdings[holdings["is_option"].fillna(False)].copy()
    option_legs["underlying"] = option_legs["option_root"].map(underlying_from_root)

    matched_fund: list[str | None] = []
    disclosed: list[float | None] = []

    for leg in legs.itertuples():
        # A written leg is negative in the fund's book; a held leg is positive.
        hit = option_legs[
            (option_legs["underlying"] == leg.symbol)
            & (option_legs["expiry"] == leg.expiry)
            & (option_legs["right"] == leg.leg_right)
            & ((option_legs["strike"] - leg.strike).abs() <= strike_tolerance)
        ]
        if len(hit):
            best = hit.iloc[(hit["contracts"].abs() - leg.leg_open_interest).abs().argsort()[:1]]
            matched_fund.append(str(best["fund"].iloc[0]))
            disclosed.append(float(best["contracts"].iloc[0]))
        else:
            matched_fund.append(None)
            disclosed.append(None)

    return legs.assign(matched_fund=matched_fund, disclosed_contracts=disclosed)


__all__ = [
    "LEG_COLUMNS",
    "DetectionConfig",
    "find_combo_candidates",
    "find_synthetic_legs",
    "is_offset_strike",
    "reconcile_with_holdings",
    "underlying_from_root",
]
