"""Inputs to the implied-volatility result: listed readings, spots and style groups.

* The listed side. A Cboe chain reading belongs to a session (`chain_dates`). The one
  compared with OCC's marks is each symbol's first reading after the session's close
  shows in the feed: from 16:15 New York on the session day (the 16:00 close plus Cboe's
  fifteen-minute delay), or on a later day before the next open, as a weekend reading of
  a Friday is. Later readings carry after-hours stock prices, and Cboe computes their
  volatilities against those. Only a standard class counts (AAPL; SPX and SPXW), and
  only a series the chain gives a volatility.
* Spots. An equity's spot is its daily close from the bars. An index's is its level in
  that same chain reading, and three mini products settle on a fixed fraction of an index
  the chains carry (INDEX_FRACTIONS). Any other underlying has no spot: the Dow, MSCI and
  bitcoin indices, and FLEX classes the bars lack (adjusted deliverables among them).
* An equity's reading is used only where its stock price agrees with the close to within
  SPOT_AGREEMENT. Elsewhere Cboe's volatilities were computed against another price.
* Style groups split the validation by where the exercise style came from: OCC's class
  heading, spelled out in full or clipped by its thirty-character limit; the product
  symbol's prefix, where the heading says nothing; or the American fallback, where the
  prefix gives no answer either. Index rows are a group of their own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd

from hidden_options.config import (
    ACCEPT_CI_RUNS_ENV,
    BARS_PATH,
    CI_CAPTURES_DIR,
    LOCAL_ONLY_ENV,
    RAW_DIR,
)
from hidden_options.measure.flex_panel import exercise_style_evidence, load_panel
from hidden_options.measure.hidden_share import LISTED_INDEX_ROOTS
from hidden_options.measure.hidden_share_data import (
    check_ci_runs,
    ci_roots,
    load_chains,
    switch_on,
    trading_calendar,
)
from hidden_options.measure.implied import style_source
from hidden_options.publish.results import RESULTS_DIR

RESULT_NAME = "implied_validation"
NEW_YORK = "America/New_York"
CLOSE_MINUTES = 16 * 60
QUOTE_DELAY_MINUTES = 15
# An equity's chain reading is compared only where its price is within this of the close.
SPOT_AGREEMENT = 0.005
# Products that settle on a fixed fraction of an index whose level the chains carry.
INDEX_FRACTIONS: Mapping[str, tuple[str, float]] = MappingProxyType(
    {"XSP": ("SPX", 0.1), "XND": ("NDX", 0.01), "MRUT": ("RUT", 0.1)}
)
LISTED_COLUMNS = ("date", "symbol", "root", "expiry", "right", "strike", "iv")
SPOT_COLUMNS = ("date", "underlying", "spot", "source")
STYLE_GROUPS = ("strict", "clipped", "prefix", "fallback", "index")
BAR_COLUMNS = ("symbol", "timestamp", "close")


@dataclass(frozen=True)
class ImpliedInputs:
    """What the result is computed from, as the loaders return it.

    `panel` is the whole FLEX panel (`load_panel`), `chains` every chain row with its
    `iv` (`load_chains`), `bars` the daily bars. `ci_runs` names the CI captures read
    beside the local ones; `local_only` marks inputs read without them.
    """

    panel: pd.DataFrame
    chains: pd.DataFrame
    bars: pd.DataFrame
    ci_runs: Sequence[str] = ()
    local_only: bool = False


def load_inputs(
    raw: Path | None = None,
    ci: Path | None = None,
    bars_path: Path | None = None,
    *,
    local_only: bool | None = None,
    accept_ci_runs: bool | None = None,
) -> ImpliedInputs:
    """Read the panel, the chains (local, then each CI run) and the bars.

    The CI captures are guarded as the hidden-share result guards them: they must be
    present, and be the runs the committed result used, unless `local_only` or
    `accept_ci_runs` says otherwise (each read from its environment variable when None).
    """
    raw = RAW_DIR if raw is None else raw
    local_only = switch_on(LOCAL_ONLY_ENV) if local_only is None else local_only
    accept = switch_on(ACCEPT_CI_RUNS_ENV) if accept_ci_runs is None else accept_ci_runs
    runs = [] if local_only else ci_roots(CI_CAPTURES_DIR if ci is None else ci)
    names = [run.parent.name for run in runs]
    if not local_only and not accept:
        check_ci_runs(names, RESULT_NAME, RESULTS_DIR)
    chains = load_chains([raw, *runs], trading_calendar(raw), extra=("iv",))
    bars = pd.read_parquet(BARS_PATH if bars_path is None else bars_path, columns=list(BAR_COLUMNS))
    return ImpliedInputs(load_panel(raw), chains, bars, names, local_only)


def close_readings(chains: pd.DataFrame) -> pd.DataFrame:
    """Every row of each symbol's first reading after a session's close, `date` the session."""
    local = chains["quote_timestamp"].dt.tz_convert(NEW_YORK)
    day = local.dt.tz_localize(None).dt.normalize()
    minutes = local.dt.hour * 60 + local.dt.minute
    trading = (day == chains["session"]) & (minutes < CLOSE_MINUTES + QUOTE_DELAY_MINUTES)
    after = chains[~trading]
    first = after.groupby(["symbol", "session"])["quote_timestamp"].transform("min")
    frame = after[after["quote_timestamp"] == first]
    frame = frame.drop_duplicates(["symbol", "session", "contract"])
    readings: pd.DataFrame = frame.rename(columns={"session": "date"}).reset_index(drop=True)
    return readings


def listed_quotes(readings: pd.DataFrame) -> pd.DataFrame:
    """The standard-class series of the readings that carry a volatility."""
    roots = readings["root"].astype(str)
    symbols = readings["symbol"].astype(str)
    standard = (roots == symbols) | (roots.map(dict(LISTED_INDEX_ROOTS)) == symbols)
    iv = readings["iv"].astype(float)
    keep = standard & np.isfinite(iv) & (iv > 0)
    return readings.loc[keep, list(LISTED_COLUMNS)].reset_index(drop=True)


def equity_closes(bars: pd.DataFrame) -> pd.DataFrame:
    """Daily closes by New York session date: `date`, `symbol`, `close`."""
    session = pd.to_datetime(bars["timestamp"], utc=True).dt.tz_convert(NEW_YORK)
    return pd.DataFrame(
        {
            "date": _day(session.dt.tz_localize(None)),
            "symbol": bars["symbol"].astype(str),
            "close": bars["close"].astype(float),
        }
    )


def reading_agreement(readings: pd.DataFrame, closes: pd.DataFrame) -> pd.DataFrame:
    """Each equity reading's stock price against the close: `rel_diff`, and `agrees`."""
    prices = readings.groupby(["date", "symbol"])["underlying_price"].first().reset_index()
    prices["date"] = _day(prices["date"])
    merged = prices.merge(closes, on=["date", "symbol"], how="inner")
    merged["rel_diff"] = merged["underlying_price"] / merged["close"] - 1
    merged["agrees"] = merged["rel_diff"].abs() <= SPOT_AGREEMENT
    agreement: pd.DataFrame = merged.reset_index(drop=True)
    return agreement


def usable_listed(readings: pd.DataFrame, agreement: pd.DataFrame) -> pd.DataFrame:
    """`listed_quotes` less the equity readings whose price disagrees with the close."""
    listed = listed_quotes(readings)
    off = agreement.loc[~agreement["agrees"], ["date", "symbol"]]
    key = pd.MultiIndex.from_arrays([_day(listed["date"]), listed["symbol"].astype(str)])
    drop = key.isin(pd.MultiIndex.from_frame(off.astype({"symbol": str})))
    return listed[~drop].reset_index(drop=True)


def spot_table(readings: pd.DataFrame, closes: pd.DataFrame) -> pd.DataFrame:
    """Spots by date and underlying, with their `source`: bars, chain or fraction."""
    equity = pd.DataFrame(
        {"date": closes["date"], "underlying": closes["symbol"], "spot": closes["close"]}
    ).assign(source="bars")
    indices = readings[readings["symbol"].isin(set(LISTED_INDEX_ROOTS.values()))]
    read = indices.groupby(["date", "symbol"])["underlying_price"].first().reset_index()
    levels = pd.DataFrame(
        {
            "date": _day(read["date"]),
            "underlying": read["symbol"].astype(str),
            "spot": read["underlying_price"].astype(float),
        }
    ).assign(source="chain")
    minis = []
    for mini, (parent, fraction) in INDEX_FRACTIONS.items():
        base = levels[levels["underlying"] == parent]
        minis.append(base.assign(underlying=mini, spot=base["spot"] * fraction, source="fraction"))
    spots = pd.concat([equity, levels, *minis], ignore_index=True)
    twice = spots.duplicated(["date", "underlying"])
    if twice.any():
        name = spots.loc[twice, "underlying"].iloc[0]
        raise ValueError(f"{name} has a spot from more than one source")
    table: pd.DataFrame = spots[list(SPOT_COLUMNS)]
    return table


def with_spots(rows: pd.DataFrame, spots: pd.DataFrame) -> pd.DataFrame:
    """`rows` with the `spot` of their underlying on their report date (NaN if none)."""
    table = pd.Series(
        spots["spot"].to_numpy(dtype=float),
        index=pd.MultiIndex.from_arrays([_day(spots["date"]), spots["underlying"].astype(str)]),
    )
    key = pd.MultiIndex.from_arrays([_day(rows["report_date"]), rows["underlying"].astype(str)])
    return rows.assign(spot=table.reindex(key).to_numpy())


def overlap_dates(panel: pd.DataFrame, readings: pd.DataFrame) -> list[pd.Timestamp]:
    """FLEX report dates on which most chains were read after the close.

    Most means more than half the symbols the readings ever cover. A date with a stray
    reading or two (a pre-open capture of one symbol) would bring in a day whose index
    rows have no level to be priced against.
    """
    flex = set(_day(pd.Series(panel["report_date"].unique())))
    per_date = readings.groupby(_day(readings["date"]))["symbol"].nunique()
    covered = per_date[2 * per_date > readings["symbol"].nunique()]
    return sorted(pd.Timestamp(day) for day in set(covered.index) & flex)


def style_groups(panel: pd.DataFrame) -> pd.Series:
    """Where an equity row's exercise style comes from: `strict` or `clipped` for a heading
    that spells the style out or is cut off partway through it, `prefix` for one read
    from the product symbol, `fallback` for one assumed; `index` for index rows."""
    codes, headings = pd.factorize(panel["class_name"])
    read = [exercise_style_evidence(heading)[1] for heading in headings]
    evidence = np.array([*read, "none"], dtype=object)[codes]
    source = style_source(panel).to_numpy()
    groups = np.where(evidence == "none", source, evidence).astype(object)
    groups[(panel["kind"] == "index").to_numpy()] = "index"
    return pd.Series(groups, index=panel.index, dtype=object)


def _day(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values).astype("datetime64[ns]").dt.normalize()


__all__ = [
    "INDEX_FRACTIONS",
    "RESULT_NAME",
    "SPOT_AGREEMENT",
    "STYLE_GROUPS",
    "ImpliedInputs",
    "close_readings",
    "equity_closes",
    "listed_quotes",
    "load_inputs",
    "overlap_dates",
    "reading_agreement",
    "spot_table",
    "style_groups",
    "usable_listed",
    "with_spots",
]
