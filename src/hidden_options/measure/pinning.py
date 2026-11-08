"""Pinning at hidden strikes: the event set, the mirror-strike statistic and its inference.

Specification: `docs/log/2026-11-08-pinning-spec.md`. An event is a FLEX expiry on a
Monday-to-Thursday trading day, not a Thursday before a Friday holiday, in a name that
lists no options expiring that day. Its pin strike is the largest expiring FLEX strike
near the previous close. The statistic compares the expiry close's closeness to that
strike with its closeness to the mirror strike on the other side of the previous close,
and differences it against the same comparison on the five sessions after expiry.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

CAP = 2.0
WINDOW_SIGMAS = 2.0
MIN_CONTRACTS = 100
SIGMA_SESSIONS = 60
SIGMA_MIN = 40
# Sessions after the expiry date (negative offsets look forward). Pseudo-expiries must come
# after it: K* is chosen near the close before expiry, so sessions before it lie on a path
# that ends near K*, and would be pulled towards it by construction.
PSEUDO_OFFSETS = (-1, -2, -3, -4, -5)
BANDS = (0.25, 0.5)
EVENT_KEYS = ["underlying", "expiry"]
npt_like = Any


def listed_nonfriday(listed: pd.DataFrame, holidays: Iterable[pd.Timestamp]) -> set[str]:
    """Symbols with a listed expiry on a weekday other than Friday that is not the
    Thursday before a Friday holiday. `listed` holds `symbol` and `expiry`."""
    off = set(pd.DatetimeIndex(list(holidays)))
    expiry = pd.to_datetime(listed["expiry"])
    shifted = (expiry.dt.day_of_week == 3) & (expiry + pd.Timedelta(days=1)).isin(off)
    return set(listed.loc[(expiry.dt.day_of_week != 4) & ~shifted, "symbol"].astype(str))


def flex_only(dates: pd.DatetimeIndex, holidays: Iterable[pd.Timestamp]) -> np.ndarray:
    """Whether each date is Monday to Thursday and not a Thursday before a Friday holiday."""
    off = set(pd.DatetimeIndex(list(holidays)))
    weekday = dates.day_of_week
    shifted = (weekday == 3) & np.array([(d + pd.Timedelta(days=1)) in off for d in dates])
    return np.asarray((weekday <= 3) & ~shifted)


def with_sigma(closes: pd.DataFrame) -> pd.DataFrame:
    """`closes` (symbol, session, close) with `prev_close` and `sigma`: the standard
    deviation of daily log returns over the SIGMA_SESSIONS sessions ending the day before.

    Closes are on each session's own basis, as strikes are. With a `split_factor` column
    (`collect.splits.split_factors`), returns are taken on the adjusted basis, so a split
    is not a return, and `prev_close` is put on the basis of the session it precedes.
    """
    frame = closes.sort_values(["symbol", "session"]).reset_index(drop=True)
    if "split_factor" not in frame:
        frame["split_factor"] = 1.0
    adjusted = frame["close"] / frame["split_factor"]
    grouped = adjusted.groupby(frame["symbol"], sort=False)
    frame["prev_close"] = grouped.shift(1) * frame["split_factor"]
    returns = pd.Series(np.log(adjusted / grouped.shift(1)), index=frame.index)
    frame["sigma"] = returns.groupby(frame["symbol"], sort=False).transform(
        lambda r: r.rolling(SIGMA_SESSIONS, min_periods=SIGMA_MIN).std().shift(1)
    )
    return frame


def pin_strikes(book: pd.DataFrame, prev: pd.DataFrame) -> pd.DataFrame:
    """One pin strike per event: among the expiring strikes with at least MIN_CONTRACTS
    within WINDOW_SIGMAS of the previous close, the one with the most open interest.

    `book` holds the expiring series (underlying, expiry, strike, right, open_interest);
    `prev` each event's `prev_close` and `sigma`.
    """
    calls = book["open_interest"].where(book["right"] == "C", 0)
    strikes = (
        book.assign(call_oi=calls)
        .groupby([*EVENT_KEYS, "strike"], as_index=False)[["open_interest", "call_oi"]]
        .sum()
        .merge(prev, on=EVENT_KEYS, how="inner")
    )
    distance = np.abs(np.log(strikes["strike"] / strikes["prev_close"]))
    near = distance <= WINDOW_SIGMAS * strikes["sigma"]
    candidates = strikes[near & (strikes["open_interest"] >= MIN_CONTRACTS)]
    ordered = candidates.sort_values(
        [*EVENT_KEYS, "open_interest", "strike"], ascending=[True, True, False, True]
    )
    chosen = ordered.groupby(EVENT_KEYS, sort=False).head(1).copy()
    chosen["call_share"] = chosen["call_oi"] / chosen["open_interest"]
    return chosen.drop(columns="call_oi").reset_index(drop=True)


def closeness(
    close: npt_like, prev_close: npt_like, strike: npt_like, sigma: npt_like
) -> np.ndarray:
    """How much nearer `close` is to `strike` than to its mirror about `prev_close`, in
    sigma units, each distance capped at CAP."""
    c, p, k, s = (np.asarray(x, dtype=float) for x in (close, prev_close, strike, sigma))
    mirror = p * p / k
    to_strike = np.minimum(np.abs(np.log(c / k)) / s, CAP)
    to_mirror = np.minimum(np.abs(np.log(c / mirror)) / s, CAP)
    return np.asarray(to_mirror - to_strike)


def event_statistics(
    events: pd.DataFrame, closes: pd.DataFrame, days: pd.DatetimeIndex
) -> pd.DataFrame:
    """Per event: closeness on the expiry date, its mean over the pseudo-expiries, their
    difference D, and the banded versions. Each date's mirror is taken about the close
    of the session before it. Events missing any needed close are dropped."""
    lookup = closes.set_index(["symbol", "session"])["close"]
    position = days.get_indexer(pd.DatetimeIndex(events["expiry"]))
    reach = (position >= 1) & (position - min(PSEUDO_OFFSETS) < len(days))
    frame = events[reach].copy()
    position = position[reach]

    def close_at(offset: int) -> np.ndarray:
        keys = pd.MultiIndex.from_arrays([frame["underlying"], days[position - offset]])
        return np.asarray(lookup.reindex(keys).to_numpy(), dtype=float)

    def scores(offset: int) -> dict[str, np.ndarray]:
        c, p = close_at(offset), close_at(offset + 1)
        args = (c, p, frame["strike"].to_numpy(dtype=float), frame["sigma"].to_numpy(dtype=float))
        out = {"s": closeness(*args)}
        for band in BANDS:
            out[f"b{band}"] = _banded(*args, band)
            out[f"n{band}"] = _near(args[0], args[2], args[3], band)
        return out

    expiry = scores(0)
    pseudo = [scores(offset) for offset in PSEUDO_OFFSETS]
    for name, values in expiry.items():
        frame[f"{name}_expiry"] = values
        frame[f"{name}_pseudo"] = np.mean([p[name] for p in pseudo], axis=0)
    frame["D"] = frame["s_expiry"] - frame["s_pseudo"]
    for band in BANDS:
        frame[f"D_b{band}"] = frame[f"b{band}_expiry"] - frame[f"b{band}_pseudo"]
    needed = ["D", *(f"D_b{band}" for band in BANDS)]
    return frame.dropna(subset=needed).reset_index(drop=True)


def clustered_mean(values: pd.Series, clusters: pd.Series) -> dict[str, Any]:
    """The mean with a cluster-robust standard error (CR1) and t on G - 1 degrees of freedom.

    With fewer than two clusters there is no estimate, and every figure is None.
    """
    v = np.asarray(values, dtype=float)
    g = pd.Series(clusters).to_numpy()
    if len(set(g.tolist())) < 2:
        keys = ("mean", "std_error", "t_stat", "p_value", "mde80")
        return {**dict.fromkeys(keys), "clusters": len(set(g.tolist())), "n_obs": len(v)}
    n, mean = len(v), float(np.mean(v))
    sums = pd.Series(v - mean).groupby(pd.Series(g)).sum().to_numpy()
    groups = len(sums)
    se = float(np.sqrt(groups / (groups - 1) * np.sum(sums**2)) / n)
    t = mean / se if se > 0 else float("nan")
    p = float(2 * student_t.sf(abs(t), groups - 1))
    crit = float(student_t.ppf(0.975, groups - 1))
    return {
        "mean": mean,
        "std_error": se,
        "t_stat": t,
        "p_value": p,
        "clusters": groups,
        "n_obs": n,
        "mde80": float((crit + student_t.ppf(0.8, groups - 1)) * se),
    }


def sign_flip_p(values: pd.Series, clusters: pd.Series, *, n_draws: int, seed: int) -> float:
    """Randomisation p-value for a zero mean, flipping the sign of whole clusters."""
    sums = pd.Series(np.asarray(values, dtype=float)).groupby(pd.Series(clusters).to_numpy()).sum()
    s = sums.to_numpy()
    observed = abs(s.sum())
    rng = np.random.default_rng(seed)
    draws = np.abs((rng.choice([-1.0, 1.0], size=(n_draws, len(s))) * s).sum(axis=1))
    return float((1 + np.sum(draws >= observed)) / (n_draws + 1))


def size_terciles(stats: pd.DataFrame) -> dict[str, Any]:
    """Mean D in the top size tercile less the bottom, with an expiry-clustered error."""
    tercile = pd.qcut(stats["size"].rank(method="first"), 3, labels=False)
    sub = stats.assign(top=(tercile == 2).astype(float))[tercile.isin([0, 2])]
    x = sub["top"].to_numpy()
    y = sub["D"].to_numpy(dtype=float)
    top, bottom = y[x == 1].mean(), y[x == 0].mean()
    resid = y - np.where(x == 1, top, bottom)
    design = np.column_stack([np.ones_like(x), x])
    bread = np.linalg.inv(design.T @ design)
    scores = (
        pd.DataFrame(design * resid[:, None]).groupby(sub["expiry"].to_numpy()).sum().to_numpy()
    )
    groups = len(scores)
    cov = bread @ (scores.T @ scores) @ bread * groups / (groups - 1)
    se = float(np.sqrt(cov[1, 1]))
    diff = float(top - bottom)
    t = diff / se if se > 0 else float("nan")
    return {
        "difference": diff,
        "top": float(top),
        "bottom": float(bottom),
        "std_error": se,
        "t_stat": t,
        "p_value": float(2 * student_t.sf(abs(t), groups - 1)),
        "clusters": groups,
    }


def _near(close: np.ndarray, strike: np.ndarray, sigma: np.ndarray, band: float) -> np.ndarray:
    """1 where the close is within `band` sigma of the strike, NaN where there is no close."""
    out = (np.abs(np.log(close / strike)) <= band * sigma).astype(float)
    out[~np.isfinite(close)] = np.nan
    return np.asarray(out, dtype=float)


def _banded(
    close: np.ndarray, prev: np.ndarray, strike: np.ndarray, sigma: np.ndarray, band: float
) -> np.ndarray:
    mirror = prev * prev / strike
    near_strike = np.abs(np.log(close / strike)) <= band * sigma
    near_mirror = np.abs(np.log(close / mirror)) <= band * sigma
    out = near_strike.astype(float) - near_mirror.astype(float)
    out[~np.isfinite(close) | ~np.isfinite(prev)] = np.nan
    return np.asarray(out, dtype=float)


def simulate_worlds(
    distances: np.ndarray,
    sigmas: np.ndarray,
    clusters: np.ndarray,
    *,
    pulled: float,
    worlds: int,
    seed: int,
    alpha: float = 0.05,
) -> dict[str, float]:
    """H1 on simulated returns with the real events' structure.

    Each event keeps its pin strike's distance from the previous close (in log terms),
    its sigma and its expiry date. Expiry and pseudo-expiry returns are normal at that
    sigma, drawn independently. In a share `pulled` of events the expiry return is
    pulled halfway to the pin strike, the alternative the specification's power uses.
    Returns the share of worlds in which H1 rejects and the mean D across worlds, the
    effect that alternative implies.

    Independent normal draws give a smaller standard error than real returns, which are
    fat-tailed and move together on a date; `power_at` takes the observed one instead.
    """
    rng = np.random.default_rng(seed)
    n = len(distances)
    rejections, means = 0, []
    for _ in range(worlds):
        expiry = rng.standard_normal(n) * sigmas
        pull = rng.random(n) < pulled
        expiry = np.where(pull, 0.5 * expiry + 0.5 * distances, expiry)
        pseudo = [
            _log_closeness(rng.standard_normal(n) * sigmas, distances, sigmas)
            for _ in PSEUDO_OFFSETS
        ]
        d = _log_closeness(expiry, distances, sigmas) - np.mean(pseudo, axis=0)
        found = clustered_mean(pd.Series(d), pd.Series(clusters))
        rejections += int(found["p_value"] is not None and found["p_value"] < alpha)
        means.append(float(np.mean(d)))
    return {"rejections": rejections / worlds, "mean_effect": float(np.mean(means))}


def power_at(effect: float, std_error: float, *, clusters: int, alpha: float = 0.05) -> float:
    """Power of a two-sided t test, on `clusters` - 1 degrees of freedom, against a true
    mean of `effect` estimated with standard error `std_error`."""
    df = clusters - 1
    crit = float(student_t.ppf(1 - alpha / 2, df))
    shift = effect / std_error
    return float(student_t.sf(crit - shift, df) + student_t.cdf(-crit - shift, df))


def _log_closeness(returns: np.ndarray, distances: np.ndarray, sigmas: np.ndarray) -> np.ndarray:
    """`closeness` for log returns and log strike distances from the previous close."""
    to_strike = np.minimum(np.abs(returns - distances) / sigmas, CAP)
    to_mirror = np.minimum(np.abs(returns + distances) / sigmas, CAP)
    return np.asarray(to_mirror - to_strike)


__all__ = [
    "BANDS",
    "CAP",
    "MIN_CONTRACTS",
    "PSEUDO_OFFSETS",
    "closeness",
    "clustered_mean",
    "event_statistics",
    "flex_only",
    "listed_nonfriday",
    "pin_strikes",
    "sign_flip_p",
    "power_at",
    "simulate_worlds",
    "size_terciles",
    "with_sigma",
]
