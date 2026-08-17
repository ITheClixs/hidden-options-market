#!/usr/bin/env python
"""Back-fill Global X daily holdings.

Global X serves dated holdings URLs, the only source found so far with retrievable
history — everything else in the project accumulates forward only.

History runs from 2024-07-03, an edge shared by all four funds. An earlier reading
called this a rolling two-year retention window with files expiring daily; that was
wrong. It was inferred from probes that happened to land on a market holiday and on
scattered missing days inside the covered range. A single boundary common to four
independently-managed funds points to an asset-host adoption date instead.

Roughly 190 dates inside the range are genuinely absent (holidays plus gaps), so a
404 is an expected answer rather than a failure.

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

# History begins 2024-07-03; look back beyond that so the edge is observed rather
# than assumed, and so a future extension of the archive is picked up automatically.
DEFAULT_LOOKBACK_DAYS = 850


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
    logging.info("saved=%(saved)d skipped=%(skipped)d absent=%(absent)d error=%(error)d", stats)
    return 0 if stats["saved"] or stats["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
