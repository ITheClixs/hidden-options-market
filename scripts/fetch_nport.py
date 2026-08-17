#!/usr/bin/env python
"""Fetch per-fund net assets from N-PORT and cache them.

Roughly 200 SEC requests, so results are written per fund as they arrive and existing
funds are skipped on re-run. An interrupted run resumes rather than starting over.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.collect.http import build_session, fetch  # noqa: E402
from absorb.collect.nport import (  # noqa: E402
    TICKER_MAP_URL,
    fetch_report,
    list_accessions,
    to_frame,
)
from absorb.config import RAW_DIR, load_programmes  # noqa: E402


def ticker_map(session) -> dict[str, tuple[int, str]]:
    payload = json.loads(fetch(session, TICKER_MAP_URL).content)
    idx = {field: i for i, field in enumerate(payload["fields"])}
    return {row[idx["symbol"]]: (row[idx["cik"]], row[idx["seriesId"]]) for row in payload["data"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    parser.add_argument("--refresh", action="store_true", help="refetch funds already cached")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    out_dir = args.root / "nport" / "by_fund"
    out_dir.mkdir(parents=True, exist_ok=True)

    session = build_session()
    mapping = ticker_map(session)

    for programme in load_programmes():
        if programme.underlying.startswith("_"):
            continue
        target = out_dir / f"{programme.fund}.parquet"
        if target.exists() and not args.refresh:
            continue

        located = mapping.get(programme.fund)
        if not located:
            logging.warning("%s: no SEC series mapping", programme.fund)
            continue

        cik, series_id = located
        try:
            accessions = list_accessions(session, series_id)
        except Exception as exc:  # noqa: BLE001
            logging.warning("%s: filing index failed (%s)", programme.fund, exc)
            continue

        reports = []
        for accession in accessions:
            try:
                reports.append(
                    fetch_report(session, cik, accession, fund=programme.fund, series_id=series_id)
                )
            except Exception as exc:  # noqa: BLE001
                logging.warning("%s %s: %s", programme.fund, accession, type(exc).__name__)

        if reports:
            to_frame(reports).to_parquet(target, index=False)
            logging.info("%s: %d reports", programme.fund, len(reports))

    files = sorted(out_dir.glob("*.parquet"))
    if not files:
        logging.error("no N-PORT data collected")
        return 1

    combined = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    combined = combined.sort_values(["fund", "report_date"]).reset_index(drop=True)
    combined.to_parquet(args.root / "nport" / "net_assets.parquet", index=False)
    logging.info("combined %d reports across %d funds", len(combined), combined.fund.nunique())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
