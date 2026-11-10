#!/usr/bin/env python
"""Fetch Cboe's daily FLEX execution reports and the Treasury yield curve beside them.

About one request per weekday for the reports. Dates already on disk are skipped, so an
interrupted run resumes; dates with no file at the source (holidays, and everything before
the archive begins on 31 March 2025) are counted as absent. The Treasury's par yield curve,
the benchmark for the rates in those trades, is fetched whole for the years covered.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from hidden_options.collect.cboe_flex_trades import backfill
from hidden_options.collect.treasury import collect_curve
from hidden_options.config import RAW_DIR

ARCHIVE_START = date(2025, 3, 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    parser.add_argument("--start", type=date.fromisoformat, default=ARCHIVE_START)
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    summary = backfill(args.start, args.end, args.root)
    logging.info("FLEX execution reports: %s", summary)
    curve = collect_curve(range(args.start.year, args.end.year + 1), args.root)
    logging.info("Treasury curve: %d dates to %s", len(curve), curve["date"].max().date())
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
