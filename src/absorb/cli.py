"""Command-line entry point for the daily collector."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from absorb.collect.lock import AlreadyRunning, single_instance
from absorb.collect.runner import run_daily_collection
from absorb.config import RAW_DIR, load_programmes, load_universe

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="absorb-collect",
        description="Capture one daily snapshot of free option-chain and open-interest data.",
    )
    parser.add_argument(
        "--sources",
        default="holdings,cboe,occ,bars",
        help="Comma-separated sources (holdings, cboe, occ, bars). Default: all",
    )
    parser.add_argument(
        "--root", type=Path, default=RAW_DIR, help=f"Output root. Default: {RAW_DIR}"
    )
    parser.add_argument("--universe", type=Path, default=None, help="Override universe config path")
    parser.add_argument("--funds", type=Path, default=None, help="Override fund registry path")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=LOG_FORMAT,
        stream=sys.stderr,
    )

    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())

    try:
        universe = load_universe(args.universe)
        programmes = load_programmes(args.funds) if "holdings" in sources else ()
    except (FileNotFoundError, ValueError) as exc:
        logging.error("Cannot load configuration: %s", exc)
        return 2

    logging.info(
        "Collecting %s for %d symbols and %d programmes",
        sources,
        len(universe.all_symbols),
        len(programmes),
    )

    try:
        with single_instance(args.root / ".collector.lock"):
            outcomes = run_daily_collection(universe, programmes, root=args.root, sources=sources)
    except AlreadyRunning as exc:
        # Concurrent runs draw throttling from the free endpoints and can race on the
        # same partition file, so a second instance declines rather than competing.
        logging.error("%s", exc)
        return 3

    ok = [o for o in outcomes if o.status == "ok"]
    failed = [o for o in outcomes if o.status != "ok"]
    logging.info(
        "Captured %d/%d snapshots (%d rows)", len(ok), len(outcomes), sum(o.rows for o in ok)
    )
    for outcome in failed:
        logging.warning(
            "%s %s: %s %s", outcome.source, outcome.symbol, outcome.status, outcome.detail
        )

    if not ok:
        logging.error("No snapshots captured; treating run as failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
