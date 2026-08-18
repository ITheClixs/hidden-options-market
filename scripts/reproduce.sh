#!/usr/bin/env bash
# Rebuild every number in the paper from free public sources.
#
# Nothing here requires credentials, a subscription, or an account. Runtime is
# dominated by ~1,000 polite HTTP requests and is roughly 30-45 minutes from cold.
#
#   scripts/reproduce.sh          full rebuild
#   scripts/reproduce.sh --quick  skip collection, rebuild analysis from existing captures

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY=.venv/bin/python
[[ -x "$PY" ]] || { echo "run: uv venv && uv pip install -e '.[dev]'" >&2; exit 127; }

if [[ "${1:-}" != "--quick" ]]; then
  echo "==> 1/5  OCC clearing data for the optionable universe (~682 symbols)"
  ABSORB_REQUEST_SPACING=0.12 $PY scripts/flex_census.py

  echo "==> 2/5  listed chains, fund holdings and bars for the study universe"
  $PY -m absorb.cli --root data/raw

  echo "==> 3/5  fund net assets from N-PORT"
  ABSORB_REQUEST_SPACING=0.2 $PY scripts/fetch_nport.py
fi

echo "==> 4/5  census, structures and spots"
$PY - <<'PYEOF'
import glob, json, logging, pandas as pd
logging.basicConfig(level=logging.ERROR)
from absorb.collect.http import build_session, fetch
from absorb.measure.flex import build_census, detect_multileg, summarise
from absorb.measure.structures import group_structures

occ = pd.concat([pd.read_parquet(f) for f in glob.glob("data/raw/occ_census/*.parquet")],
                ignore_index=True).drop_duplicates(
                    subset=["symbol", "product_symbol", "expiry", "strike"])
census = detect_multileg(build_census(occ))
census.to_parquet("data/flex_census.parquet", index=False)

session = build_session()
spots = {}
for sym in sorted(census.symbol.unique()):
    try:
        meta = json.loads(fetch(session,
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
            params={"interval": "1d", "range": "5d"}, max_attempts=2).content
        )["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        if price:
            spots[sym] = float(price)
    except Exception:
        pass
pd.Series(spots, name="spot").to_frame().to_parquet("data/spots.parquet")

structures = group_structures(census, spots)
structures.to_parquet("data/flex_structures.parquet", index=False)

print(f"  FLEX series          {len(census):,}")
print(f"  FLEX contracts       {census.total_open_interest.sum()/1e6:.1f}m")
print(f"  structures           {len(structures):,} across {structures.symbol.nunique()} underlyings")
print(f"  exposure             ${structures.exposure.sum()/1e9:,.0f}bn")
print(f"  naive leg notional   ${census.notional.sum()/1e9:,.0f}bn")
print(f"  overstatement        {census.notional.sum()/structures.exposure.sum():.1f}x")
print(summarise(census).round(3).to_string(index=False))
PYEOF

echo "==> 5/5  figures and paper"
$PY scripts/make_figures.py
( cd paper && tectonic known_flow.tex >/dev/null 2>&1 && echo "  paper/known_flow.pdf rebuilt" )
echo "done."
