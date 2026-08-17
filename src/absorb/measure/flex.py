"""Classification of FLEX option positions visible in clearing data.

Background
----------
FLEX options are bilaterally negotiated and then cleared. They are, by construction,
option demand that chose *not* to execute in the lit market, and they do not print on
the consolidated tape. They are widely treated as unobservable.

They are not. The Options Clearing Corporation publishes open interest for every
series it clears, FLEX included, and FLEX series are distinguishable from listed ones
because listed strikes fall on a standard grid. A strike whose cents component is not
0, 25, 50 or 75 is not a listed strike.

What makes this useful rather than merely curious is that the *structures* built from
FLEX leave different fingerprints, so the population can be decomposed rather than
reported as one undifferentiated total.

Taxonomy
--------
``fund_synthetic``
    A one- or two-cent offset from a round strike, with open interest concentrated on
    one right. Single-name option-income funds write the put leg of their synthetic
    long this way; the cent offset keeps the series from being netted against the
    listed one at clearing. Verified against issuer disclosure.

``matched_combination``
    Call and put open interest exactly equal in the same series. This is the signature
    of a conversion, reversal or box — dealer financing and carry structures, not
    directional positions.

``index_linked``
    A strike with an arbitrary decimal (for example 765.66) rather than a cent offset,
    typically on an index ETF at a month-end expiry. Defined-outcome and buffer funds
    strike their caps and floors at levels derived from an index value on the day the
    outcome period opens, which produces exactly this.

``block``
    One-sided open interest at a round contract count on a standard-looking strike,
    large enough that it is likely a single negotiated trade rather than an
    accumulation.

``unclassified``
    Everything else. Reported rather than forced into a category.

The classifier is deliberately conservative: it assigns a label only when a signature
is clear, and the residual is reported as residual.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Cents values that occur on ordinary listed strike grids.
STANDARD_CENTS = frozenset({0, 25, 50, 75})
# Cent offsets used to keep a non-standard-deliverable series distinct from the listed one.
SYNTHETIC_OFFSET_CENTS = frozenset({1, 2, 3, 10, 20, 30})

REQUIRED_COLUMNS = frozenset(
    {"symbol", "expiry", "strike", "call_open_interest", "put_open_interest"}
)

CENSUS_COLUMNS = (
    "symbol",
    "expiry",
    "strike",
    "call_open_interest",
    "put_open_interest",
    "total_open_interest",
    "notional",
    "cents",
    "one_sidedness",
    "category",
)


@dataclass(frozen=True)
class ClassifierConfig:
    """Thresholds for FLEX classification.

    `min_open_interest` keeps near-empty series out of the census; with tens of
    thousands of series even a small false-positive rate would dominate the counts.
    """

    min_open_interest: int = 100
    one_sided_threshold: float = 0.90
    block_min_contracts: int = 10_000
    block_round_lot: int = 1_000


def strike_cents(strike: float) -> int:
    """Cents component of a strike, as an integer 0-99."""
    return int(round(round(float(strike), 2) * 100)) % 100


def is_flex_strike(strike: float) -> bool:
    """True when a strike is off the standard listed grid."""
    return strike_cents(strike) not in STANDARD_CENTS


def classify(row: pd.Series, config: ClassifierConfig) -> str:
    """Assign one structural category to a series."""
    call = float(row["call_open_interest"])
    put = float(row["put_open_interest"])
    total = call + put
    if total < config.min_open_interest:
        return "below_threshold"

    cents = strike_cents(row["strike"])
    dominant = max(call, put)
    one_sided = dominant / total if total else 0.0

    # Matched legs are checked first: an exact equality is a strong signature and
    # would otherwise be misread as a weakly one-sided position.
    if call == put and call > 0:
        return "matched_combination"

    if one_sided >= config.one_sided_threshold:
        # A fund synthetic is a *written put*. Requiring the put side to dominate
        # matters: without it, a one-sided call ladder at cent-offset strikes is
        # misread as a fund leg. An observed MSFT programme of 100,000-200,000
        # contract call lines was labelled this way before the condition was added.
        if cents in SYNTHETIC_OFFSET_CENTS and put > call:
            return "fund_synthetic"
        if cents not in STANDARD_CENTS:
            return "index_linked"
        if dominant >= config.block_min_contracts and dominant % config.block_round_lot == 0:
            return "block"

    return "unclassified"


def build_census(
    open_interest: pd.DataFrame, config: ClassifierConfig | None = None
) -> pd.DataFrame:
    """Classify every series and return the FLEX census.

    Listed series on the standard grid are retained only when they are large round
    blocks, since those are negotiated too; everything else on-grid is ordinary
    listed activity and out of scope.
    """
    cfg = config or ClassifierConfig()
    missing = REQUIRED_COLUMNS - set(open_interest.columns)
    if missing:
        raise ValueError(f"open_interest frame is missing columns: {sorted(missing)}")

    if open_interest.empty:
        return pd.DataFrame(columns=list(CENSUS_COLUMNS))

    frame = open_interest.copy()
    call = frame["call_open_interest"].astype(float)
    put = frame["put_open_interest"].astype(float)

    frame["total_open_interest"] = call + put
    frame["notional"] = frame["total_open_interest"] * 100 * frame["strike"]
    frame["cents"] = frame["strike"].map(strike_cents)
    total = frame["total_open_interest"].replace(0, np.nan)
    frame["one_sidedness"] = (pd.concat([call, put], axis=1).max(axis=1) / total).fillna(0.0)
    frame["category"] = frame.apply(lambda r: classify(r, cfg), axis=1)

    keep = frame["category"].isin(
        {"fund_synthetic", "index_linked", "matched_combination", "block", "unclassified"}
    )
    off_grid_or_block = (frame["cents"].map(lambda c: c not in STANDARD_CENTS)) | (
        frame["category"] == "block"
    )
    result = frame.loc[keep & off_grid_or_block, list(CENSUS_COLUMNS)]
    return result.sort_values("notional", ascending=False).reset_index(drop=True)


def summarise(census: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the census by category.

    Notional is reported but should not be read as economic exposure for
    ``matched_combination``. Boxes and conversions are routinely struck far from spot
    purely to transport cash --- the largest single line observed is an SPY series at
    a strike of 10,010 against a spot near 765, carrying \\$29bn of notional and no
    directional or convex exposure whatever. Contract counts are the safer scale for
    that category.
    """
    if census.empty:
        return pd.DataFrame(
            columns=["category", "series", "contracts_m", "notional_bn", "share_contracts"]
        )

    grouped = (
        census.groupby("category")
        .agg(
            series=("strike", "size"),
            contracts_m=("total_open_interest", lambda x: x.sum() / 1e6),
            notional_bn=("notional", lambda x: x.sum() / 1e9),
        )
        .reset_index()
    )
    grouped["share_contracts"] = grouped["contracts_m"] / grouped["contracts_m"].sum()
    return grouped.sort_values("contracts_m", ascending=False).reset_index(drop=True)


__all__ = [
    "CENSUS_COLUMNS",
    "STANDARD_CENTS",
    "SYNTHETIC_OFFSET_CENTS",
    "ClassifierConfig",
    "build_census",
    "classify",
    "is_flex_strike",
    "strike_cents",
    "summarise",
]
