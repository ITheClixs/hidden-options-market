"""Command-line entry point: the `hidden-options` command and its subcommands."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from hidden_options.collect.backfill import DEFAULT_KINDS, backfill_flex
from hidden_options.collect.bars import refresh_flex_underlying_bars
from hidden_options.collect.lock import AlreadyRunning, single_instance
from hidden_options.collect.runner import run_daily_collection
from hidden_options.config import (
    ACCEPT_CI_RUNS_ENV,
    BARS_PATH,
    LOCAL_ONLY_ENV,
    PROJECT_ROOT,
    RAW_DIR,
    load_programmes,
    load_universe,
)
from hidden_options.measure.flex_panel import load_panel
from hidden_options.publish import check_drift, publish, registry

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

    backfill = commands.add_parser(
        "backfill-flex",
        help="download the OCC FLEX reports for a span of past dates",
        description=(
            "Download the OCC FLEX open-interest reports for every weekday in a span, "
            "skipping dates already held. OCC keeps roughly twenty months of history."
        ),
    )
    backfill.add_argument("--start", type=_iso_date, required=True, help="First date, YYYY-MM-DD")
    backfill.add_argument(
        "--end", type=_iso_date, default=None, help="Last date, YYYY-MM-DD. Default: today"
    )
    backfill.add_argument(
        "--kinds",
        nargs="+",
        choices=DEFAULT_KINDS,
        default=list(DEFAULT_KINDS),
        help="Report kinds. Default: all",
    )
    backfill.add_argument(
        "--root", type=Path, default=RAW_DIR, help=f"Output root. Default: {RAW_DIR}"
    )
    backfill.add_argument("--verbose", action="store_true", help="Debug logging")
    backfill.set_defaults(handler=_backfill_flex)

    refresh = commands.add_parser(
        "refresh-bars",
        help="re-download daily bars for the FLEX underlyings",
        description=(
            "Re-download daily bars for every equity FLEX underlying with enough activity "
            "dates, far enough back to cover the panel's first date and the trailing "
            "windows before it, and rewrite the bars file. Symbols the provider refuses "
            "are listed; symbols no longer in the set are dropped from the file."
        ),
    )
    refresh.add_argument(
        "--raw", type=Path, default=RAW_DIR, help=f"FLEX report root. Default: {RAW_DIR}"
    )
    refresh.add_argument(
        "--out", type=Path, default=BARS_PATH, help=f"Bars file. Default: {BARS_PATH}"
    )
    refresh.add_argument("--verbose", action="store_true", help="Debug logging")
    refresh.set_defaults(handler=_refresh_bars)

    results = commands.add_parser(
        "results",
        help="run the registered analyses and write results/*.json",
        description=(
            "Run every registered analysis (or one, with --only) and write its result "
            "file. The paper and README are rendered from these files."
        ),
    )
    results.add_argument("--only", metavar="NAME", help="Run only this analysis")
    results.add_argument(
        "--local-only",
        action="store_true",
        help="compute the hidden share without the CI captures; the result is marked",
    )
    results.add_argument(
        "--accept-ci-runs",
        action="store_true",
        help="compute the hidden share on the CI runs on disk even if they differ from "
        "the committed result's",
    )
    _add_root(results)
    results.set_defaults(handler=_results)

    figures = commands.add_parser(
        "figures",
        help="build the registered figures",
        description="Run every registered figure builder, or one with --only.",
    )
    figures.add_argument("--only", metavar="NAME", help="Build only this figure")
    figures.set_defaults(handler=_figures)

    publish_cmd = commands.add_parser(
        "publish",
        help="render paper/numbers.tex, paper/tables and README.md from results/",
        description=(
            "Render the paper macros, the paper tables and the README from results/ and "
            "docs/readme.template.md. Needs no raw data."
        ),
    )
    _add_root(publish_cmd)
    publish_cmd.set_defaults(handler=_publish)

    check = commands.add_parser(
        "check",
        help="fail if a generated file differs from a fresh render of results/",
        description=(
            "Re-render the generated files in memory and exit 1, listing the paths, if "
            "any committed file differs. Run `hidden-options publish` to fix it."
        ),
    )
    _add_root(check)
    check.set_defaults(handler=_check)
    return parser


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help=f"Project root holding results/, paper/ and docs/. Default: {PROJECT_ROOT}",
    )


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}") from None


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


def _backfill_flex(args: argparse.Namespace) -> int:
    """Fetch missing FLEX reports for a span. Non-zero means a request failed."""
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=LOG_FORMAT,
        stream=sys.stderr,
    )
    end = args.end or date.today()

    try:
        # The nightly collector writes the same partitions, so the two take turns.
        with single_instance(args.root / ".collector.lock"):
            summary = backfill_flex(args.start, end, args.root, tuple(args.kinds))
    except AlreadyRunning as exc:
        logging.error("%s", exc)
        return 3
    except ValueError as exc:
        logging.error("%s", exc)
        return 2

    logging.info("%s (%s to %s)", summary.describe(), args.start, end)
    if summary.absent:
        # Not published yet (or a holiday), not a fault; a later run asks again.
        logging.info("%d reports not available from the source", summary.absent)
    return 1 if summary.failed else 0


def _refresh_bars(args: argparse.Namespace) -> int:
    """Refresh the daily bars. 1 if nothing could be fetched, 2 for bad inputs."""
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=LOG_FORMAT,
        stream=sys.stderr,
    )
    try:
        summary = refresh_flex_underlying_bars(load_panel(args.raw), args.out)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2

    print(summary.describe())
    for symbol, reason in summary.failed.items():
        print(f"  failed   {symbol}: {reason}")
    if summary.dropped:
        print(f"  dropped  {', '.join(summary.dropped)}")
    for symbol, rows in summary.kept_history.items():
        print(f"  kept     {symbol}: {rows} held rows from before the fetched window")
    for symbol, rows in summary.discarded_history.items():
        print(f"  discarded {symbol}: {rows} held rows from before the fetched window")
    if summary.late_starts:
        since = f"{summary.history_start:%Y-%m-%d}"
        print(f"  starting after {since}: {', '.join(summary.late_starts)}")
    return 0


def _results(args: argparse.Namespace) -> int:
    """Run registered analyses. Exit 2 for an unknown name or a mislabelled result."""
    # The flags reach the analyses, which take no arguments, through the environment.
    if args.local_only:
        os.environ[LOCAL_ONLY_ENV] = "1"
    if args.accept_ci_runs:
        os.environ[ACCEPT_CI_RUNS_ENV] = "1"
    registry.load_registrations()
    if args.only is None and not registry.ANALYSES.select():
        print("No analyses are registered; nothing to do.")
        return 0
    try:
        written = registry.run_analyses(registry.ANALYSES, args.root / "results", args.only)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    for path in written:
        print(f"wrote {path}")
    return 0


def _figures(args: argparse.Namespace) -> int:
    """Run registered figure builders. Exit 2 for an unknown name."""
    registry.load_figure_registrations()
    if args.only is None and not registry.FIGURES.select():
        print("No figure builders are registered; nothing to do.")
        return 0
    try:
        built = registry.run_figures(registry.FIGURES, args.only)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    for name in built:
        print(f"built {name}")
    return 0


def _publish(args: argparse.Namespace) -> int:
    try:
        changed = publish(args.root)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"Cannot publish: {_describe(exc)}", file=sys.stderr)
        return 2
    for path in changed:
        print(f"updated {path}")
    if not changed:
        print("Everything is up to date.")
    return 0


def _check(args: argparse.Namespace) -> int:
    """Exit 1, listing the paths, when a generated file differs from its render."""
    try:
        drifted = check_drift(args.root)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"Cannot check: {_describe(exc)}", file=sys.stderr)
        return 2
    if not drifted:
        print("Generated files match results/.")
        return 0
    print("Generated files differ from results/:", file=sys.stderr)
    for path in drifted:
        print(f"  {path}", file=sys.stderr)
    print("Run `hidden-options publish` and commit the result.", file=sys.stderr)
    return 1


def _describe(exc: Exception) -> str:
    """KeyError wraps its message in quotes; show it plainly."""
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exit_code: int = args.handler(args)
    return exit_code


def collect_alias(argv: list[str] | None = None) -> int:
    """Entry point for the pre-rename collector command, which scheduled jobs still call.

    It forwards to `hidden-options collect` so an existing cron or workflow line keeps
    working unchanged until it is moved to the new command.
    """
    forwarded = sys.argv[1:] if argv is None else argv
    return main(["collect", *forwarded])


if __name__ == "__main__":
    raise SystemExit(main())
