"""Orchestrates one daily collection pass and records an auditable manifest.

Design rule: a partial failure must never abort the run. A missing symbol-day is
unrecoverable (these are snapshot endpoints with no history), so the runner isolates
each symbol, records every outcome, and exits non-zero only if nothing was captured.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from absorb.collect import cboe, holdings, occ
from absorb.collect.http import build_session
from absorb.config import RAW_DIR, Programme, Universe


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
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(destination, index=False, compression="zstd")


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
    """
    failed = {(o.source, o.symbol) for o in outcomes if o.status != "ok"}
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
    sources: tuple[str, ...] = ("holdings", "cboe", "occ"),
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

    if sweep_up:
        outcomes = _sweep_up(outcomes, universe, programmes, timestamp, target_root)

    write_manifest(outcomes, timestamp, target_root)
    return outcomes


__all__ = [
    "SymbolOutcome",
    "collect_cboe_chains",
    "collect_fund_holdings",
    "collect_occ_open_interest",
    "run_daily_collection",
    "write_manifest",
]
