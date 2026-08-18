#!/usr/bin/env python
"""Download the OCC FLEX open-interest panel.

OCC retains roughly twenty months of daily FLEX reports. This is the enabling asset
for any question about whether hidden institutional inventory predicts the visible
market, and unlike the snapshot sources elsewhere in this project it can be obtained
retrospectively.

Files are stored under the report's own activity date, never the capture date.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.collect.http import FetchError, build_session  # noqa: E402
from absorb.collect.occ_flex import FlexReportError, fetch_report, snapshot_path  # noqa: E402
from absorb.config import RAW_DIR  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-12-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    parser.add_argument("--kinds", nargs="+", default=["equity", "index"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)

    session = build_session()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    saved = absent = failed = skipped = 0
    day = end

    while day >= start:
        if day.weekday() < 5:
            for kind in args.kinds:
                try:
                    stub = f"occ_flex/date={day:%Y-%m-%d}/{kind}.parquet"
                except Exception:  # noqa: BLE001
                    continue
                target = args.root / stub
                if target.exists():
                    skipped += 1
                    continue
                try:
                    report = fetch_report(session, day, kind)
                except FlexReportError:
                    absent += 1
                    continue
                except (FetchError, Exception) as exc:  # noqa: BLE001
                    failed += 1
                    logging.warning("%s %s: %s", day, kind, type(exc).__name__)
                    continue

                out = args.root / snapshot_path(report)
                out.parent.mkdir(parents=True, exist_ok=True)
                report.frame.to_parquet(out, index=False)
                saved += 1
                if report.class_totals_matched != report.class_totals_checked:
                    logging.warning(
                        "%s %s: %d/%d class totals reconcile",
                        day,
                        kind,
                        report.class_totals_matched,
                        report.class_totals_checked,
                    )
        day -= timedelta(days=1)
        if saved and saved % 60 == 0:
            logging.info(
                "saved=%d absent=%d skipped=%d failed=%d (at %s)",
                saved,
                absent,
                skipped,
                failed,
                day,
            )

    logging.info("saved=%d absent=%d skipped=%d failed=%d", saved, absent, skipped, failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
