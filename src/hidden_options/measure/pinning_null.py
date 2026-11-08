"""The pinning test's size and power on real returns.

Specification: `docs/log/2026-11-08-pinning-empirical-null-spec.md`. The size and power the
registered test reports come from independent normal returns. Here each event of the
registered sample is moved to placebo dates in its own name, where nothing expires, with
its pin strike at the same distance from the previous close in daily standard
deviations. The registered statistic on those dates is its null on real returns.
Planting the registered alternative in those real closes gives its power.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from hidden_options.measure.pinning import (
    WINDOW_SIGMAS,
    clustered_mean,
    event_statistics,
    straddles_split,
)

OFFSETS = (*range(-40, -9, 2), *range(10, 41, 2))
SHARES = (0.05, 0.10, 0.15)
ALPHA = 0.05


def placebo_events(
    stats: pd.DataFrame,
    closes: pd.DataFrame,
    days: pd.DatetimeIndex,
    *,
    offset: int,
    flex_expiries: set[tuple[str, pd.Timestamp]],
) -> pd.DataFrame:
    """The events of `stats` moved `offset` sessions, kept on Monday to Thursday dates that
    are not a FLEX expiry of the name, with the strike at the same distance in sigmas."""
    position = days.get_indexer(pd.DatetimeIndex(stats["expiry"])) + offset
    inside = (position >= 0) & (position < len(days))
    frame = stats.loc[inside, ["underlying", "expiry", "strike", "prev_close", "sigma"]]
    target = days[position[inside]]
    z = np.log(frame["strike"].to_numpy(float) / frame["prev_close"].to_numpy(float)) / frame[
        "sigma"
    ].to_numpy(float)
    moved = pd.DataFrame(
        {
            "underlying": frame["underlying"].to_numpy(),
            "expiry": target,
            "z": z,
            "source_expiry": frame["expiry"].to_numpy(),
        }
    )
    at = closes.rename(columns={"symbol": "underlying", "session": "expiry"})[
        ["underlying", "expiry", "prev_close", "sigma"]
    ]
    moved = moved.merge(at, on=["underlying", "expiry"], how="inner").dropna(
        subset=["prev_close", "sigma"]
    )
    weekday = pd.DatetimeIndex(moved["expiry"]).day_of_week < 4
    clear = ~pd.Series(
        list(zip(moved["underlying"], moved["expiry"], strict=True)), index=moved.index
    ).isin(flex_expiries)
    moved = moved[weekday & clear & (np.abs(moved["z"]) <= WINDOW_SIGMAS)]
    moved = moved.assign(strike=moved["prev_close"] * np.exp(moved["z"] * moved["sigma"]))
    return pd.DataFrame(moved.drop(columns="z").reset_index(drop=True))


def planted(
    closes: pd.DataFrame, events: pd.DataFrame, *, share: float, rng: np.random.Generator
) -> pd.DataFrame:
    """`closes` with the close on the expiry date of a random `share` of `events` pulled
    halfway, in logs, to the event's strike. A new frame."""
    out = closes.copy()
    chosen = events[rng.random(len(events)) < share]
    keys = pd.MultiIndex.from_frame(out[["symbol", "session"]])
    rows = keys.get_indexer(pd.MultiIndex.from_arrays([chosen["underlying"], chosen["expiry"]]))
    found = rows >= 0
    values = out["close"].to_numpy(dtype=float, copy=True)
    values[rows[found]] = np.sqrt(values[rows[found]] * chosen["strike"].to_numpy(float)[found])
    out["close"] = values
    return out


def empirical_null(
    stats: pd.DataFrame,
    closes: pd.DataFrame,
    days: pd.DatetimeIndex,
    flex_expiries: set[tuple[str, pd.Timestamp]],
    *,
    offsets: Iterable[int] = OFFSETS,
    shares: Sequence[float] = SHARES,
    seed: int = 0,
    observed: float | None = None,
) -> dict[str, Any]:
    """The registered statistic on placebo dates, and with planted pins, per offset."""
    rng = np.random.default_rng(seed)
    rows, hits, skipped = [], {f"{q:.2f}": 0 for q in shares}, 0
    for offset in offsets:
        events = placebo_events(stats, closes, days, offset=offset, flex_expiries=flex_expiries)
        found = _estimate(events, closes, days)
        if found["mean"] is None:  # fewer than two placebo dates: no estimate
            skipped += 1
            continue
        rows.append({"offset": offset, **found})
        for q in shares:
            pinned = _estimate(events, planted(closes, events, share=q, rng=rng), days)
            hits[f"{q:.2f}"] += int(pinned["p_value"] is not None and pinned["p_value"] < ALPHA)
    means = np.array([r["mean"] for r in rows], dtype=float)
    centre = float(np.mean(means))
    out: dict[str, Any] = {
        "offsets": rows,
        "centre": centre,
        "spread": float(np.std(means, ddof=1)) if len(means) > 1 else float("nan"),
        "size": float(np.mean([r["p_value"] < ALPHA for r in rows])),
        "median_events": float(np.median([r["n_obs"] for r in rows])),
        "skipped_offsets": skipped,
        "power": {key: hit / len(rows) for key, hit in hits.items()},
    }
    if observed is not None:
        out["observed_share"] = float(np.mean(np.abs(means - centre) >= abs(observed - centre)))
    return out


def _estimate(events: pd.DataFrame, closes: pd.DataFrame, days: pd.DatetimeIndex) -> dict[str, Any]:
    found = event_statistics(events, closes, days)
    found = found[~straddles_split(found, closes, days)]
    keep = ("mean", "std_error", "t_stat", "p_value", "n_obs", "clusters")
    estimate = clustered_mean(found["D"], found["expiry"])
    return {key: estimate[key] for key in keep}


__all__ = ["OFFSETS", "SHARES", "empirical_null", "placebo_events", "planted"]
