#!/usr/bin/env python
"""Fetch Cboe's daily FLEX execution reports and store them by trade date.

About one request per weekday. Dates already on disk are skipped, so an interrupted run
resumes; dates with no file at the source (holidays, and everything before the archive
begins around April 2025) are counted as absent.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from hidden_options.collect.cboe_flex_trades import backfill
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
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
