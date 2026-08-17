#!/usr/bin/env python
"""Back-fill Global X daily holdings before they expire.

Global X serves dated holdings URLs that resolve for roughly the last two years and
404 before that. Probing on 2026-08-17 put the edge within days of exactly two years
back, which reads as a rolling retention window rather than an adoption date. If that
is right, the earliest files are expiring daily and this is a race.

Everything else in the project accumulates forward. This is the one source with
retrievable history, so it is worth grabbing in full immediately and reasoning about
afterwards.

Usage:
    scripts/backfill_globalx.py                    # all funds, full window
    scripts/backfill_globalx.py --funds qyld xyld  # subset
    scripts/backfill_globalx.py --days 90          # recent window only
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.collect.http import FetchError, build_session, fetch  # noqa: E402
from absorb.config import RAW_DIR  # noqa: E402

URL = "https://assets.globalxetfs.com/funds/holdings/{fund}_full-holdings_{day:%Y%m%d}.csv"

# Index-level covered-call and related option-overlay funds.
DEFAULT_FUNDS = ("qyld", "xyld", "ryld", "djia", "qyle", "xyle")

# Retention appears to be ~2 years; look back a little further so the true edge is
# observed rather than assumed.
DEFAULT_LOOKBACK_DAYS = 780


def destination(root: Path, fund: str, day: date) -> Path:
    return root / "globalx_holdings" / f"date={day:%Y-%m-%d}" / f"{fund.upper()}.csv"


def backfill(
    funds: tuple[str, ...], lookback_days: int, root: Path, *, overwrite: bool = False
) -> dict[str, int]:
    session = build_session()
    today = datetime.now(UTC).date()
    stats = {"saved": 0, "skipped": 0, "absent": 0, "error": 0}
    earliest: dict[str, date] = {}

    for fund in funds:
        for offset in range(lookback_days):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:  # holdings are published for trading days only
                continue

            target = destination(root, fund, day)
            if target.exists() and not overwrite:
                stats["skipped"] += 1
                continue

            try:
                result = fetch(session, URL.format(fund=fund, day=day), max_attempts=2)
            except FetchError as exc:
                # A 404 is the expected answer for a holiday or a day past the
                # retention edge, and must not be logged as a failure.
                if "404" in str(exc):
                    stats["absent"] += 1
                else:
                    stats["error"] += 1
                    logging.warning("%s %s: %s", fund, day, exc)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(result.content)
            stats["saved"] += 1
            earliest[fund] = day

        if fund in earliest:
            logging.info("%s: earliest retrieved %s", fund.upper(), earliest[fund])

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--funds", nargs="+", default=list(DEFAULT_FUNDS))
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", stream=sys.stderr
    )
    logging.info("Back-filling %s over %d days", args.funds, args.days)

    stats = backfill(tuple(args.funds), args.days, args.root, overwrite=args.overwrite)
    logging.info(
        "saved=%(saved)d skipped=%(skipped)d absent=%(absent)d error=%(error)d", stats
    )
    return 0 if stats["saved"] or stats["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
