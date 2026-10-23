"""Command-line entry point: the `hidden-options` command and its subcommands."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from hidden_options.collect.lock import AlreadyRunning, single_instance
from hidden_options.collect.runner import run_daily_collection
from hidden_options.config import RAW_DIR, load_programmes, load_universe

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hidden-options",
        description="Collect and measure OCC FLEX clearing data.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    collect = commands.add_parser(
        "collect",
        help="capture one daily snapshot of free option-chain and open-interest data",
        description="Capture one daily snapshot of free option-chain and open-interest data.",
    )
    collect.add_argument(
        "--sources",
        default="holdings,cboe,occ,bars,flex",
        help="Comma-separated sources (holdings, cboe, occ, bars, flex). Default: all",
    )
    collect.add_argument(
        "--root", type=Path, default=RAW_DIR, help=f"Output root. Default: {RAW_DIR}"
    )
    collect.add_argument(
        "--universe", type=Path, default=None, help="Override universe config path"
    )
    collect.add_argument("--funds", type=Path, default=None, help="Override fund registry path")
    collect.add_argument("--verbose", action="store_true", help="Debug logging")
    collect.set_defaults(handler=_collect)
    return parser


def _collect(args: argparse.Namespace) -> int:
    """Run one collection pass. Exit codes are the contract with the scheduler."""
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
    absent = [o for o in outcomes if o.status == "absent"]
    failed = [o for o in outcomes if o.status not in ("ok", "absent")]
    logging.info(
        "Captured %d/%d snapshots (%d rows)", len(ok), len(outcomes), sum(o.rows for o in ok)
    )
    if absent:
        # Not published yet (or a holiday), not a fault; the next run asks again.
        logging.info("%d reports not available from the source yet", len(absent))
    for outcome in failed:
        logging.warning(
            "%s %s: %s %s", outcome.source, outcome.symbol, outcome.status, outcome.detail
        )

    if not ok:
        logging.error("No snapshots captured; treating run as failed")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


def collect_alias(argv: list[str] | None = None) -> int:
    """Entry point for the pre-rename collector command, which scheduled jobs still call.

    It forwards to `hidden-options collect` so an existing cron or workflow line keeps
    working unchanged until it is moved to the new command.
    """
    forwarded = sys.argv[1:] if argv is None else argv
    return main(["collect", *forwarded])


if __name__ == "__main__":
    raise SystemExit(main())
