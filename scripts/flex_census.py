#!/usr/bin/env python
"""Collect OCC series open interest across the optionable universe and build the
FLEX census.

FLEX positions are bilaterally negotiated, never print on the tape, and are widely
treated as unobservable. They are visible in clearing data, and this assembles the
first broad picture of them we are aware of.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.collect.http import build_session  # noqa: E402
from absorb.collect.occ import fetch_open_interest  # noqa: E402
from absorb.config import RAW_DIR  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=Path, default=Path("configs/optionable_universe.txt"))
    parser.add_argument("--root", type=Path, default=RAW_DIR)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    out = args.root / "occ_census"
    out.mkdir(parents=True, exist_ok=True)

    symbols = [s.strip() for s in args.symbols.read_text().split() if s.strip()]
    if args.limit:
        symbols = symbols[: args.limit]

    session = build_session()
    done = failed = 0
    for i, symbol in enumerate(symbols, 1):
        target = out / f"{symbol}.parquet"
        if target.exists():
            done += 1
            continue
        try:
            snapshot = fetch_open_interest(session, symbol)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        snapshot.frame.to_parquet(target, index=False)
        done += 1
        if i % 50 == 0:
            logging.info("%d/%d symbols (%d failed)", i, len(symbols), failed)

    logging.info("collected %d symbols, %d failed", done, failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
