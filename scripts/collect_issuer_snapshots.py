#!/usr/bin/env python
"""Capture today's issuer holdings snapshots: Innovator's all-funds file and the BOXX page.

Both are overwritten in place by their issuers, so a day not captured is gone. The raw
payloads are stored under `issuer_snapshots/date=YYYY-MM-DD/`; a file already held is left
alone.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from hidden_options.collect.http import build_session
from hidden_options.collect.issuer_snapshots import collect_snapshots
from hidden_options.config import RAW_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    outcomes = collect_snapshots(build_session(), date.today(), args.root)
    for name, outcome in outcomes.items():
        logging.info("%s %s", name, outcome)
    return 1 if any(outcome.startswith("failed") for outcome in outcomes.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
