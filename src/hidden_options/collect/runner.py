"""Orchestrates one daily collection pass and records an auditable manifest.

Design rule: a partial failure must never abort the run. A missing symbol-day is
unrecoverable (these are snapshot endpoints with no history), so the runner isolates
each symbol, records every outcome, and exits non-zero only if nothing was captured.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

from hidden_options.collect import bars, cboe, holdings, occ, occ_flex
from hidden_options.collect.http import build_session
from hidden_options.config import RAW_DIR, Programme, Universe


@dataclass(frozen=True)
class SymbolOutcome:
    """Immutable record of what happened to one symbol in one source."""

    source: str
    symbol: str
    status: str
    rows: int = 0
    sha256: str = ""
    detail: str = ""


def _write_frame(frame, destination: Path) -> None:
    """Write via a staging file so a crash never leaves a truncated parquet in place.

    Most sources overwrite their file the next day, but the FLEX collector treats an
    existing file as proof the date is held, so a half-written one would never be redone.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + ".partial")
    try:
        frame.to_parquet(staging, index=False, compression="zstd")
        staging.replace(destination)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def collect_cboe_chains(
    universe: Universe, as_of: datetime, root: Path
) -> tuple[SymbolOutcome, ...]:
    session = build_session()
    outcomes: list[SymbolOutcome] = []

    for symbol in universe.all_symbols:
        try:
            snapshot = cboe.fetch_chain(session, symbol)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
            outcomes.append(
                SymbolOutcome("cboe_chain", symbol, "error", detail=f"{type(exc).__name__}: {exc}")
            )
            continue

        destination = root / cboe.snapshot_partition(snapshot, as_of)
        try:
            _write_frame(snapshot.frame, destination)
        except OSError as exc:
            outcomes.append(SymbolOutcome("cboe_chain", symbol, "write_error", detail=str(exc)))
            continue

        outcomes.append(
            SymbolOutcome(
                "cboe_chain",
                symbol,
                "ok",
                rows=snapshot.n_contracts,
                sha256=snapshot.payload_sha256,
            )
        )

    return tuple(outcomes)


def collect_occ_open_interest(
    universe: Universe, as_of: datetime, root: Path
) -> tuple[SymbolOutcome, ...]:
    session = build_session()
    outcomes: list[SymbolOutcome] = []

    for symbol in universe.occ_symbols:
        try:
            snapshot = occ.fetch_open_interest(session, symbol)
        except Exception as exc:  # noqa: BLE001
            outcomes.append(
                SymbolOutcome("occ_oi", symbol, "error", detail=f"{type(exc).__name__}: {exc}")
            )
            continue

        destination = root / occ.snapshot_partition(snapshot, as_of)
        try:
            _write_frame(snapshot.frame, destination)
        except OSError as exc:
            outcomes.append(SymbolOutcome("occ_oi", symbol, "write_error", detail=str(exc)))
            continue

        outcomes.append(
            SymbolOutcome(
                "occ_oi", symbol, "ok", rows=snapshot.n_series, sha256=snapshot.payload_sha256
            )
        )

    return tuple(outcomes)


def collect_fund_holdings(
    programmes: tuple[Programme, ...], as_of: datetime, root: Path
) -> tuple[SymbolOutcome, ...]:
    """Capture each programme's daily holdings file.

    Issuers overwrite these files in place, so a missed day is unrecoverable. Every
    programme is attempted regardless of earlier failures.
    """
    session = build_session()
    outcomes: list[SymbolOutcome] = []

    for programme in programmes:
        try:
            snapshot = holdings.fetch_holdings(session, programme.fund, programme.url_template)
        except Exception as exc:  # noqa: BLE001
            outcomes.append(
                SymbolOutcome(
                    "fund_holdings",
                    programme.fund,
                    "error",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        destination = root / holdings.snapshot_partition(snapshot, as_of)
        try:
            _write_frame(snapshot.frame, destination)
        except OSError as exc:
            outcomes.append(
                SymbolOutcome("fund_holdings", programme.fund, "write_error", detail=str(exc))
            )
            continue

        outcomes.append(
            SymbolOutcome(
                "fund_holdings",
                programme.fund,
                "ok",
                rows=snapshot.n_positions,
                sha256=snapshot.payload_sha256,
                detail=f"{snapshot.n_option_legs} option legs, as_of={snapshot.as_of}",
            )
        )

    return tuple(outcomes)


def collect_underlying_bars(
    universe: Universe,
    as_of: datetime,
    root: Path,
    *,
    interval: str = "5m",
    lookback: str = "1mo",
) -> tuple[SymbolOutcome, ...]:
    """Capture intraday bars for every underlying.

    Free intraday history is shallow and ages out, so depth has to be accumulated.
    The fetched window overlaps heavily with what is already held: the redundancy is
    cheap and lets a missed run repair itself rather than leaving a permanent hole.
    """
    session = build_session()
    outcomes: list[SymbolOutcome] = []
    source = f"bars_{interval}"

    for symbol in universe.all_symbols:
        # Index pseudo-symbols use a different convention upstream ("_SPX" -> "^SPX").
        request_symbol = f"^{symbol.lstrip('_')}" if symbol.startswith("_") else symbol
        try:
            snapshot = bars.fetch_bars(
                session, request_symbol, interval=interval, lookback=lookback
            )
        except Exception as exc:  # noqa: BLE001
            outcomes.append(
                SymbolOutcome(source, symbol, "error", detail=f"{type(exc).__name__}: {exc}")
            )
            continue

        destination = root / bars.snapshot_partition(snapshot, as_of)
        try:
            _write_frame(snapshot.frame, destination)
        except OSError as exc:
            outcomes.append(SymbolOutcome(source, symbol, "write_error", detail=str(exc)))
            continue

        outcomes.append(
            SymbolOutcome(
                source,
                symbol,
                "ok",
                rows=snapshot.n_bars,
                sha256=snapshot.payload_sha256,
                detail=f"{snapshot.first_timestamp} to {snapshot.last_timestamp}",
            )
        )

    return tuple(outcomes)


def _weekdays(end: date, lookback_days: int) -> list[date]:
    """Weekdays in ``[end - lookback_days, end]``, newest first."""
    days = (end - timedelta(days=offset) for offset in range(lookback_days + 1))
    return [day for day in days if day.weekday() < 5]


def _store_flex_report(report: occ_flex.FlexReport, root: Path) -> SymbolOutcome:
    """File a report under its own activity date, never under the date it was asked for."""
    symbol = f"{report.kind}:{report.report_date:%Y-%m-%d}"
    destination = root / occ_flex.snapshot_path(report)
    try:
        _write_frame(report.frame, destination)
    except OSError as exc:
        return SymbolOutcome("flex", symbol, "write_error", detail=str(exc))
    return SymbolOutcome(
        "flex",
        symbol,
        "ok",
        rows=report.n_series,
        sha256=report.payload_sha256,
        detail=f"{report.class_totals_matched}/{report.class_totals_checked} class totals match",
    )


def _collect_flex_report(
    session: requests.Session, day: date, kind: str, root: Path
) -> tuple[SymbolOutcome, ...]:
    symbol = f"{kind}:{day:%Y-%m-%d}"
    try:
        report = occ_flex.fetch_report(session, day, kind)
    except occ_flex.FlexReportAbsent as exc:
        return (SymbolOutcome("flex", symbol, "absent", detail=str(exc)),)
    except Exception as exc:  # noqa: BLE001 - one bad report must not stop the run
        return (SymbolOutcome("flex", symbol, "error", detail=f"{type(exc).__name__}: {exc}"),)

    if report.report_date == day:
        return (_store_flex_report(report, root),)

    # OCC answered with another day's report. It is never filed under the requested
    # date (that would enter one settlement twice as two stable days); under its own
    # date it is a good capture if that date is not already held.
    outcomes = [
        SymbolOutcome(
            "flex",
            symbol,
            "absent",
            detail=f"OCC answered with the report for {report.report_date:%Y-%m-%d}",
        )
    ]
    if not (root / occ_flex.snapshot_path(report)).exists():
        outcomes.append(_store_flex_report(report, root))
    return tuple(outcomes)


def collect_occ_flex(
    as_of: datetime,
    root: Path,
    *,
    lookback_days: int = 7,
    session: requests.Session | None = None,
) -> tuple[SymbolOutcome, ...]:
    """Capture the OCC FLEX open-interest reports for every weekday in the window.

    OCC publishes the report for activity date T overnight, so a run at the close of T
    usually finds T not out yet. Unlike the snapshot sources this is recoverable (OCC
    keeps ~20 months), so the window re-asks for any date still missing and a later run
    catches up. A date already on disk is not fetched again; "absent" (not published,
    a holiday, or OCC answering with a different day) is an ordinary outcome, not an error.
    """
    http = session or build_session()
    outcomes: list[SymbolOutcome] = []

    for day in _weekdays(as_of.date(), lookback_days):
        for kind in occ_flex.REPORT_KINDS:
            if (root / occ_flex.snapshot_path_for(day, kind)).exists():
                continue
            outcomes.extend(_collect_flex_report(http, day, kind, root))

    return tuple(outcomes)


def write_manifest(outcomes: tuple[SymbolOutcome, ...], as_of: datetime, root: Path) -> Path:
    """Persist the run log. The manifest is the audit trail for data provenance."""
    destination = root / "manifests" / f"{as_of:%Y-%m-%d}T{as_of:%H%M%S}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)

    ok = [o for o in outcomes if o.status == "ok"]
    summary = {
        "captured_at_utc": as_of.isoformat(),
        "n_attempted": len(outcomes),
        "n_ok": len(ok),
        "n_failed": len(outcomes) - len(ok),
        "total_rows": sum(o.rows for o in ok),
        "outcomes": [asdict(o) for o in outcomes],
    }
    destination.write_text(json.dumps(summary, indent=2))
    return destination


def _sweep_up(
    outcomes: tuple[SymbolOutcome, ...],
    universe: Universe,
    programmes: tuple[Programme, ...],
    timestamp: datetime,
    root: Path,
) -> tuple[SymbolOutcome, ...]:
    """Retry whatever failed, once, at the end of the run.

    Long sequential passes over multi-megabyte endpoints draw throttling, so late
    symbols fail for reasons unrelated to the symbol. Because a missed capture cannot
    be recovered later, a second attempt after the burst has subsided is worth more
    than any amount of in-loop retrying.

    An absent FLEX report is not a failure and is not retried: asking again within the
    same run cannot change OCC's answer. A FLEX request that errors is not retried here
    either, because the next run's lookback window asks for it again.
    """
    failed = {(o.source, o.symbol) for o in outcomes if o.status not in ("ok", "absent")}
    if not failed:
        return outcomes

    retry_universe = Universe(
        treated_single_name=tuple(s for src, s in failed if src == "cboe_chain"),
        treated_index_and_etf=(),
        control_single_name=(),
    )
    retry_occ = Universe(
        treated_single_name=tuple(s for src, s in failed if src == "occ_oi"),
        treated_index_and_etf=(),
        control_single_name=(),
    )
    retry_programmes = tuple(p for p in programmes if ("fund_holdings", p.fund) in failed)

    repaired: tuple[SymbolOutcome, ...] = ()
    if retry_programmes:
        repaired += collect_fund_holdings(retry_programmes, timestamp, root)
    if retry_universe.all_symbols:
        repaired += collect_cboe_chains(retry_universe, timestamp, root)
    if retry_occ.all_symbols:
        repaired += collect_occ_open_interest(retry_occ, timestamp, root)

    # Later outcome for a given key wins, so a successful retry supersedes the failure.
    merged: dict[tuple[str, str], SymbolOutcome] = {(o.source, o.symbol): o for o in outcomes}
    for outcome in repaired:
        merged[(outcome.source, outcome.symbol)] = outcome
    return tuple(merged.values())


def run_daily_collection(
    universe: Universe,
    programmes: tuple[Programme, ...] = (),
    *,
    root: Path | None = None,
    as_of: datetime | None = None,
    sources: tuple[str, ...] = ("holdings", "cboe", "occ", "bars", "flex"),
    sweep_up: bool = True,
) -> tuple[SymbolOutcome, ...]:
    """Run every enabled source once, retry failures, and write a manifest.

    Holdings run first: they are the only source with no upstream history at all.
    """
    target_root = root or RAW_DIR
    timestamp = as_of or datetime.now(UTC)

    outcomes: tuple[SymbolOutcome, ...] = ()
    if "holdings" in sources and programmes:
        outcomes += collect_fund_holdings(programmes, timestamp, target_root)
    if "cboe" in sources:
        outcomes += collect_cboe_chains(universe, timestamp, target_root)
    if "occ" in sources:
        outcomes += collect_occ_open_interest(universe, timestamp, target_root)
    if "flex" in sources:
        outcomes += collect_occ_flex(timestamp, target_root)
    if "bars" in sources:
        outcomes += collect_underlying_bars(universe, timestamp, target_root, interval="5m")
        outcomes += collect_underlying_bars(
            universe, timestamp, target_root, interval="1d", lookback="2y"
        )

    if sweep_up:
        outcomes = _sweep_up(outcomes, universe, programmes, timestamp, target_root)

    write_manifest(outcomes, timestamp, target_root)
    return outcomes


__all__ = [
    "SymbolOutcome",
    "collect_cboe_chains",
    "collect_fund_holdings",
    "collect_occ_flex",
    "collect_underlying_bars",
    "collect_occ_open_interest",
    "run_daily_collection",
    "write_manifest",
]
