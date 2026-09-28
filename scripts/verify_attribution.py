#!/usr/bin/env python
"""Verify structural signatures against fund disclosure.

The taxonomy assigns categories from structure alone. This checks those assignments
against N-PORT filings, which played no part in constructing them.

A search hit is not a verification. Strike values recur across underlyings, and EDGAR
full-text cannot conjoin underlying, strike and expiry, so every candidate filing is
opened and the position read. A case counts as verified only when the filing contains
an option on the right underlying, at the right strike, with the predicted side.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from absorb.config import USER_AGENT  # noqa: E402

UA = {"User-Agent": USER_AGENT}
FTS = "https://efts.sec.gov/LATEST/search-index?q={q}&forms=NPORT-P"
DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml"

# Only off-grid decimals are searchable: round strikes return the ten-thousand-hit
# ceiling and identify nothing.
SEARCHABLE_CENTS = set(range(1, 100)) - {25, 50, 75}


def _get(url: str, timeout: int = 45) -> str:
    return (
        urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
        .read()
        .decode("utf-8", "replace")
    )


def candidates(strike: float, limit: int = 8) -> list[tuple[str, str, str]]:
    """(display name, cik, accession) for filings mentioning this strike."""
    try:
        payload = json.loads(_get(FTS.format(q=urllib.parse.quote(f'"{strike:g}"'))))
    except Exception:
        return []
    if payload.get("hits", {}).get("total", {}).get("value", 0) > 5000:
        return []  # a value this common identifies nothing
    out = []
    for hit in payload.get("hits", {}).get("hits", [])[:limit]:
        source = hit["_source"]
        names = source.get("display_names") or ["?"]
        out.append(
            (
                names[0].split("  (CIK")[0],
                source["ciks"][0].lstrip("0"),
                hit["_id"].split(":")[0].replace("-", ""),
            )
        )
    return out


def confirm(cik: str, accession: str, symbol: str, strike: float, right: str):
    """Return (series name, title, balance) if the filing holds the position."""
    try:
        document = _get(DOC.format(cik=cik, acc=accession), timeout=90)
    except Exception:
        return None
    series = re.search(r"<seriesName>(.*?)</seriesName>", document)
    pattern = re.compile(
        rf"<title>([^<]*\b{re.escape(symbol)}\b[^<]*{re.escape(f'{strike:g}')}[^<]*)</title>"
        r".*?<balance>([-\d.]+)</balance>",
        re.S,
    )
    match = pattern.search(document)
    if not match:
        return None
    title, balance = match.group(1).strip(), float(match.group(2))
    if right == "P" and balance >= 0:
        return None
    if right == "C" and balance == 0:
        return None
    return (series.group(1) if series else "?", title, balance)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-cases", type=int, default=25)
    parser.add_argument("--out", type=Path, default=Path("data/attributions.parquet"))
    args = parser.parse_args(argv)

    census = pd.read_parquet("data/flex_census.parquet")
    census = census[census["cents"].isin(SEARCHABLE_CENTS)]

    targets = []
    for category, predicted_right in [("fund_synthetic", "P"), ("index_linked", "C")]:
        subset = census[census["category"] == category]
        subset = subset[
            subset["put_open_interest" if predicted_right == "P" else "call_open_interest"] > 0
        ]
        targets.append(
            subset.nlargest(args.max_cases // 2, "total_open_interest").assign(
                predicted_right=predicted_right
            )
        )
    targets = pd.concat(targets, ignore_index=True)

    rows = []
    for target in targets.itertuples():
        found = None
        for name, cik, accession in candidates(target.strike):
            hit = confirm(cik, accession, target.symbol, target.strike, target.predicted_right)
            time.sleep(0.25)
            if hit:
                found = (name, *hit)
                break
        rows.append(
            {
                "symbol": target.symbol,
                "expiry": target.expiry,
                "strike": target.strike,
                "category": target.category,
                "predicted_right": target.predicted_right,
                "verified": found is not None,
                "filer": found[0] if found else None,
                "series": found[1] if found else None,
                "title": found[2] if found else None,
                "balance": found[3] if found else None,
            }
        )
        status = "OK " if found else "-- "
        detail = f"{found[1][:52]} {found[3]:+,.0f}" if found else "no confirming filing"
        print(f"{status}{target.symbol:6s} {target.strike:>9g} {target.category:16s} {detail}")

    frame = pd.DataFrame(rows)
    frame.to_parquet(args.out, index=False)
    verified = frame["verified"].sum()
    print(f"\nverified {verified} of {len(frame)} attempted")
    for category, group in frame.groupby("category"):
        print(f"  {category:18s} {group.verified.sum()}/{len(group)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
