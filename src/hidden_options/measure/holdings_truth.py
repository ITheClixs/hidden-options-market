"""Disclosed fund holdings as truth for the structure detector (M4).

Clearing is aggregate, so a holdings match can only say that a detected structure is
consistent with a disclosed holder, never that it is the holder's position. What the
holdings can test is narrow: whether series one fund holds together are grouped together.

Which holdings count
--------------------
A truth structure is what one fund holds of one underlying at one expiry, in FLEX series
only (a listed leg beside them is not on the FLEX report), when that is two legs or more.
A lone FLEX leg stays in the frame with `n_legs` 1: it can touch a detected structure but
cannot confirm one.

Every holding is keyed on its file's `as_of`, never the capture date. A file dated D shows
the settlement before D: on the issuer files the open interest of the previous report
covers every holding, and the same day's does not. So a file is set against the latest
FLEX report strictly before its `as_of` (`same_day` sets it against the report of that date
instead, as a check). A file is stale, left out and counted, when its `as_of` is more than
`max_staleness_bdays` business days behind its capture, or when no report lies within that
many business days before it.

The score, frozen before the first scored run
---------------------------------------------
Persisting positions are not independent evidence, so each distinct structure counts once,
however many dates it lasts: a date's outcome is averaged over the structure's dates, and
those averages over structures.

* A truth structure is distinct by fund, underlying, expiry and set of legs. On a date it is
  *grouped* when all its legs lie in one detected structure, and *recalled* when that
  structure's type (`structures.structure_type`) is also the type of the fund's legs.
* `recall` is the mean recalled share over distinct truth structures; `recall_grouped` the
  same without the type condition; `type_agreement` the mean, over distinct truth structures
  grouped at least once, of the share of grouped dates on which the types agree.
* A detected structure is distinct by underlying, expiry and set of legs. On a date it
  *touches* the holdings when any fund holds any of its legs. It is *consistent* when one
  fund holds at least two of its legs, and *exact* when one fund holds all of them.
* `precision` is the mean consistent share over distinct detected structures that touch;
  `precision_exact` the same for exact.
* A score with an empty denominator is 0, and a type agreement over nothing is None.

`score_by_date` scores each date alone, the per-date sampling beside the distinct count.
"""

from __future__ import annotations

import csv
import glob
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.measure.structures import structure_type

MAX_STALENESS_BDAYS = 3
TRUTH_COLUMNS = (
    "fund",
    "as_of",
    "report_date",
    "root",
    "underlying",
    "expiry",
    "right",
    "strike",
    "contracts",
    "n_legs",
    "structure",
    "truth_id",
)
_FUND_COLUMNS = (
    "fund",
    "as_of",
    "is_option",
    "option_root",
    "expiry",
    "right",
    "strike",
    "contracts",
)
_FLEX_ROOT = re.compile(r"^\d")
_PREFIX = re.compile(r"^\d+")
_GLOBALX_OPTION = re.compile(r"^([A-Z]+) US (\d{2}/\d{2}/\d{2}) ([CP])(\d+(?:\.\d+)?)$")
_GLOBALX_AS_OF = re.compile(r"as of (\d{2}/\d{2}/\d{4})")
# Strikes agree to the tenth of a cent, as OSI symbols carry them.
_STRIKE_SCALE = 1000
_PARTITION = re.compile(r"date=(\d{4}-\d{2}-\d{2})")

LegKey = tuple[pd.Timestamp, str, pd.Timestamp, str, int]


@dataclass(frozen=True)
class ValidationScore:
    """The score defined in the module docstring, and what it rests on."""

    precision: float
    recall: float
    n_truth_structures: int
    n_detected_touching: int
    type_agreement: float | None
    recall_grouped: float = 0.0
    precision_exact: float = 0.0
    n_funds: int = 0
    n_underlyings: int = 0
    n_structure_dates: int = 0
    n_detected_dates: int = 0


def load_fund_holdings(roots: Sequence[Path]) -> pd.DataFrame:
    """The option rows of every fund file under `roots`, with `capture_date` from its folder."""
    paths = [
        path
        for root in roots
        for path in sorted(glob.glob(str(root / "fund_holdings/date=*/*.parquet")))
    ]
    if not paths:
        names = ", ".join(str(root) for root in roots)
        raise FileNotFoundError(f"No fund holdings under {names}/fund_holdings")
    frames = []
    for path in paths:
        rows = pd.read_parquet(path, columns=list(_FUND_COLUMNS))
        found = _PARTITION.search(path)
        if found is None:
            raise ValueError(f"{path} is not in a date=YYYY-MM-DD folder")
        capture = pd.Timestamp(found.group(1)).to_datetime64()
        frames.append(rows[rows["is_option"]].assign(capture_date=capture))
    held = pd.concat(frames, ignore_index=True).drop(columns="is_option")
    return held.assign(
        as_of=pd.to_datetime(held["as_of"]).astype("datetime64[ns]"),
        expiry=pd.to_datetime(held["expiry"]).astype("datetime64[ns]"),
        capture_date=held["capture_date"].astype("datetime64[ns]"),
    )


def holdings_structures(
    holdings: pd.DataFrame,
    flex_dates: Sequence[pd.Timestamp],
    *,
    max_staleness_bdays: int = MAX_STALENESS_BDAYS,
    same_day: bool = False,
) -> pd.DataFrame:
    """One row per FLEX leg a fund holds on a report date, in TRUTH_COLUMNS.

    `attrs` carries `files` (distinct fund and `as_of` pairs holding options) and
    `stale_files` (those left out). See the module docstring for both rules.
    """
    flex = holdings[holdings["option_root"].astype(str).str.match(_FLEX_ROOT)]
    files = _files(holdings, flex_dates, max_staleness_bdays, same_day)
    fresh = files[~files["stale"]]
    kept = flex.merge(fresh[["fund", "as_of", "report_date", "capture_date"]], how="inner")
    kept = kept.drop_duplicates(["fund", "as_of", "option_root", "expiry", "right", "strike"])
    kept = kept[kept["contracts"] != 0]
    truth = _with_ids(kept) if len(kept) else pd.DataFrame(columns=list(TRUTH_COLUMNS))
    truth.attrs = {"files": len(files), "stale_files": int(files["stale"].sum())}
    return truth


def _files(
    holdings: pd.DataFrame, flex_dates: Sequence[pd.Timestamp], limit: int, same_day: bool
) -> pd.DataFrame:
    """Each fund and `as_of`: its latest capture, its report date, and whether it is stale.

    A capture is the file as first seen, so a file is judged by the capture nearest its
    `as_of`, and read from the latest one, which holds the same rows. A row without a
    capture date is judged by its report date alone.
    """
    frame = holdings.assign(capture_date=_capture_dates(holdings))
    keys = ["fund", "as_of"]
    grouped = frame.groupby(keys, sort=True)["capture_date"]
    files = grouped.agg(["min", "max"]).reset_index()
    files = files.rename(columns={"max": "capture_date"})
    as_of = files["as_of"].to_numpy(dtype="datetime64[D]")
    reports = np.sort(pd.DatetimeIndex(list(flex_dates)).to_numpy(dtype="datetime64[D]"))
    positions = np.searchsorted(reports, as_of, side="right" if same_day else "left") - 1
    has_report = positions >= 0
    report_days = np.where(has_report, reports[np.maximum(positions, 0)], np.datetime64("NaT", "D"))
    behind_capture = np.busday_count(as_of, files["min"].to_numpy(dtype="datetime64[D]")) > limit
    usable = reports[np.maximum(positions, 0)] if len(reports) else as_of
    behind_report = np.busday_count(usable, as_of) > limit
    return files.assign(
        report_date=pd.to_datetime(report_days).astype("datetime64[ns]"),
        stale=behind_capture | behind_report | ~has_report,
    )[[*keys, "capture_date", "report_date", "stale"]]


def _capture_dates(holdings: pd.DataFrame) -> pd.Series:
    if "capture_date" not in holdings.columns:
        return pd.to_datetime(holdings["as_of"])
    return pd.to_datetime(holdings["capture_date"]).fillna(pd.to_datetime(holdings["as_of"]))


def _with_ids(kept: pd.DataFrame) -> pd.DataFrame:
    frame = kept.rename(columns={"option_root": "root"})
    frame = frame.assign(underlying=frame["root"].astype(str).str.replace(_PREFIX, "", regex=True))
    frame = frame.sort_values(["fund", "as_of", "root", "expiry", "right", "strike"])
    records: list[pd.DataFrame] = []
    for (fund, _, underlying, expiry), legs in frame.groupby(
        ["fund", "as_of", "underlying", "expiry"], sort=True
    ):
        signature = ",".join(
            f"{root}:{right}:{_strike_key(strike)}"
            for root, right, strike in zip(legs["root"], legs["right"], legs["strike"], strict=True)
        )
        records.append(
            legs.assign(
                n_legs=len(legs),
                structure=structure_type(
                    list(legs["right"]),
                    legs["strike"].to_numpy(),
                    legs["contracts"].abs().to_numpy(),
                ),
                truth_id=f"{fund}|{underlying}|{pd.Timestamp(str(expiry)):%Y-%m-%d}|{signature}",
            )
        )
    truth: pd.DataFrame = pd.concat(records, ignore_index=True)[list(TRUTH_COLUMNS)]
    return truth


def score_against_holdings(legs_with_ids: pd.DataFrame, truth: pd.DataFrame) -> ValidationScore:
    """The score of a detector's legs (`report_date`, `root`, `expiry`, `right`, `strike`,
    `contracts`, `structure_id`) against `holdings_structures`. Defined in the module docstring.
    """
    detected = legs_with_ids[legs_with_ids["structure_id"] >= 0]
    keys = _leg_keys(detected)
    days = pd.to_datetime(detected["report_date"]).to_numpy()
    ids = detected["structure_id"].to_numpy()
    members: dict[tuple[Any, int], list[int]] = defaultdict(list)
    placed: dict[LegKey, tuple[Any, int]] = {}
    for row, (key, day, sid) in enumerate(zip(keys, days, ids, strict=True)):
        members[(day, int(sid))].append(row)
        placed[key] = (day, int(sid))
    holders = _holders(truth)
    types = _StructureTypes(detected, members)

    recalled, grouped_share, agreement, structure_dates = _recall(truth, placed, types)
    consistent, exact, n_dates = _precision(keys, members, placed, holders, detected)
    multi = truth[truth["n_legs"] >= 2] if len(truth) else truth
    return ValidationScore(
        precision=_mean(consistent),
        recall=_mean(recalled),
        n_truth_structures=len(recalled),
        n_detected_touching=len(consistent),
        type_agreement=float(np.mean(agreement)) if agreement else None,
        recall_grouped=_mean(grouped_share),
        precision_exact=_mean(exact),
        n_funds=int(multi["fund"].nunique()) if len(multi) else 0,
        n_underlyings=int(multi["underlying"].nunique()) if len(multi) else 0,
        n_structure_dates=structure_dates,
        n_detected_dates=n_dates,
    )


class _StructureTypes:
    """The type of each detected structure, computed once and only if asked for."""

    def __init__(self, detected: pd.DataFrame, members: dict[tuple[Any, int], list[int]]) -> None:
        self._rights = detected["right"].to_numpy(dtype=object)
        self._strikes = detected["strike"].to_numpy(dtype=float)
        self._sizes = detected["contracts"].to_numpy(dtype=float)
        self._members = members
        self._known: dict[tuple[Any, int], str] = {}

    def of(self, structure: tuple[Any, int]) -> str:
        if structure not in self._known:
            rows = self._members[structure]
            self._known[structure] = structure_type(
                list(self._rights[rows]), self._strikes[rows], self._sizes[rows]
            )
        return self._known[structure]


def _recall(
    truth: pd.DataFrame, placed: dict[LegKey, tuple[Any, int]], types: _StructureTypes
) -> tuple[list[float], list[float], list[float], int]:
    """Per distinct truth structure: the recalled share, the grouped share and, for those
    grouped at least once, the share of grouped dates on which the types agree."""
    if truth.empty:
        return [], [], [], 0
    multi = truth[truth["n_legs"] >= 2]
    recalled: list[float] = []
    grouped_shares: list[float] = []
    agreement: list[float] = []
    structure_dates = 0
    for _, structure in multi.groupby("truth_id", sort=True):
        hits = grouped = dates = 0
        for _, legs in structure.groupby(["fund", "report_date"], sort=False):
            dates += 1
            found = {placed.get(key) for key in _leg_keys(legs)}
            if len(found) != 1 or None in found:
                continue
            grouped += 1
            home = next(iter(found))
            hits += types.of(home) == legs["structure"].iloc[0]  # type: ignore[arg-type]
        structure_dates += dates
        recalled.append(hits / dates)
        grouped_shares.append(grouped / dates)
        if grouped:
            agreement.append(hits / grouped)
    return recalled, grouped_shares, agreement, structure_dates


def _precision(
    keys: list[LegKey],
    members: dict[tuple[Any, int], list[int]],
    placed: dict[LegKey, tuple[Any, int]],
    holders: dict[LegKey, set[str]],
    detected: pd.DataFrame,
) -> tuple[list[float], list[float], int]:
    """Per distinct detected structure that touches: the consistent and exact shares."""
    touched = {placed[key] for key in holders if key in placed}
    underlyings = detected["underlying"].to_numpy(dtype=object)
    outcomes: dict[tuple[Any, ...], list[tuple[bool, bool]]] = defaultdict(list)
    for structure in touched:
        rows = members[structure]
        legs = [keys[row] for row in rows]
        counts = Counter(fund for leg in legs for fund in holders.get(leg, ()))
        most = max(counts.values())
        distinct = (underlyings[rows[0]], tuple(sorted(leg[1:] for leg in legs)))
        outcomes[distinct].append((most >= 2, most == len(legs)))
    consistent = [float(np.mean([one[0] for one in dates])) for dates in outcomes.values()]
    exact = [float(np.mean([one[1] for one in dates])) for dates in outcomes.values()]
    return consistent, exact, len(touched)


def score_by_date(legs_with_ids: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """The score of each report date alone: `report_date`, `precision`, `recall`, and the
    `n_truth_structures` and `n_detected_touching` each rests on."""
    records = []
    legs_day = pd.to_datetime(legs_with_ids["report_date"])
    truth_day = pd.to_datetime(truth["report_date"])
    for day in sorted(truth_day.unique()):
        score = score_against_holdings(legs_with_ids[legs_day == day], truth[truth_day == day])
        records.append(
            {
                "report_date": pd.Timestamp(day),
                "precision": score.precision,
                "recall": score.recall,
                "n_truth_structures": score.n_truth_structures,
                "n_detected_touching": score.n_detected_touching,
            }
        )
    return pd.DataFrame(records)


def floor_check(truth: pd.DataFrame, report: pd.DataFrame) -> dict[str, int]:
    """How many held legs are on the report of their date, and how many of those have open
    interest of at least the fund's contracts: what fixes which report a file shows."""
    table = {
        key: oi
        for key, oi in zip(_leg_keys(report), report["open_interest"].to_numpy(), strict=True)
    }
    found = covered = 0
    for key, held in zip(_leg_keys(truth), truth["contracts"].abs().to_numpy(), strict=True):
        if key in table:
            found += 1
            covered += table[key] >= held
    return {"legs": len(truth), "found": found, "covered": covered}


def load_globalx_options(raw: Path) -> pd.DataFrame:
    """The option lines of the Global X files: all of them are `SPX US 03/21/25 C6085`."""
    records = []
    for path in sorted(glob.glob(str(raw / "globalx_holdings/date=*/*.csv"))):
        records.extend(_globalx_file(Path(path)))
    columns = ["fund", "as_of", "underlying", "expiry", "right", "strike", "contracts"]
    return pd.DataFrame(records, columns=columns)


def _globalx_file(path: Path) -> list[dict[str, Any]]:
    with path.open(errors="ignore", newline="") as handle:
        rows = list(csv.reader(handle))
    stated = next(
        (m for row in rows[:3] for m in [_GLOBALX_AS_OF.search(",".join(row))] if m), None
    )
    if stated is None:
        return []
    as_of = pd.to_datetime(stated.group(1), format="%m/%d/%Y")
    found = []
    for row in rows:
        match = _GLOBALX_OPTION.match(row[2]) if len(row) >= 6 else None
        if match:
            found.append(
                {
                    "fund": path.stem,
                    "as_of": as_of,
                    "underlying": match.group(1),
                    "expiry": pd.to_datetime(match.group(2), format="%m/%d/%y"),
                    "right": match.group(3),
                    "strike": float(match.group(4)),
                    "contracts": float(row[5].replace(",", "")),
                }
            )
    return found


def globalx_overlap(
    options: pd.DataFrame, report: pd.DataFrame, flex_dates: Sequence[pd.Timestamp]
) -> dict[str, int]:
    """What the Global X files can offer the validation: their legs that sit on the FLEX
    report of the settlement before the file's date, and holdings with more than one leg."""
    reports = np.sort(pd.DatetimeIndex(list(flex_dates)).to_numpy(dtype="datetime64[ns]"))
    as_of = options["as_of"].to_numpy(dtype="datetime64[ns]")
    positions = np.searchsorted(reports, as_of, side="left") - 1
    dated = options[positions >= 0].assign(report_date=reports[positions[positions >= 0]])
    on_report = dated.merge(
        report[["report_date", "underlying", "expiry", "right", "strike"]].drop_duplicates(),
        on=["report_date", "underlying", "expiry", "right", "strike"],
    )
    held = options.groupby(["fund", "as_of", "underlying", "expiry"]).size()
    return {
        "funds": int(options["fund"].nunique()),
        "fund_dates": int(options[["fund", "as_of"]].drop_duplicates().shape[0]),
        "legs": len(options),
        "legs_on_flex_report": len(on_report),
        "multi_leg_holdings": int((held >= 2).sum()),
    }


def _holders(truth: pd.DataFrame) -> dict[LegKey, set[str]]:
    holders: dict[LegKey, set[str]] = defaultdict(set)
    if truth.empty:
        return holders
    for key, fund in zip(_leg_keys(truth), truth["fund"], strict=True):
        holders[key].add(str(fund))
    return holders


def _leg_keys(frame: pd.DataFrame) -> list[LegKey]:
    days = pd.to_datetime(frame["report_date"]).to_numpy(dtype="datetime64[ns]")
    expiries = pd.to_datetime(frame["expiry"]).to_numpy(dtype="datetime64[ns]")
    strikes = np.rint(frame["strike"].to_numpy(dtype=float) * _STRIKE_SCALE).astype(np.int64)
    return list(
        zip(
            days.tolist(),
            frame["root"].astype(str).tolist(),
            expiries.tolist(),
            frame["right"].astype(str).tolist(),
            strikes.tolist(),
            strict=True,
        )
    )


def _strike_key(strike: float) -> int:
    return round(float(strike) * _STRIKE_SCALE)


def _mean(values: Sequence[float]) -> float:
    return float(np.mean(values)) if len(values) else 0.0


__all__ = [
    "MAX_STALENESS_BDAYS",
    "TRUTH_COLUMNS",
    "ValidationScore",
    "floor_check",
    "globalx_overlap",
    "holdings_structures",
    "load_fund_holdings",
    "load_globalx_options",
    "score_against_holdings",
    "score_by_date",
]
