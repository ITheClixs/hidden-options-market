# The Half-Life of a Known Flow

## How Fast Do Option Markets Absorb Newly Created, Fully Disclosed Mechanical Demand?

**Anonymous**

**Status — pre-data.** Collection infrastructure only. No hypothesis has been
tested and no result is claimed.

---

## The question

When a new option-writing programme is born on a named underlying at a known date —
the launch of an options-income, covered-call, or defined-outcome ETF — its demand is
uninformed, calendar-scheduled, and publicly disclosed in daily holdings from day one.
Competitive liquidity provision says such demand should not move prices. It does.

This project asks how fast that gap closes:

> Does the price impact of a newly created, fully disclosed, calendar-scheduled option
> flow decay toward **zero** or toward a **strictly positive risk-bearing floor**, at
> what half-life, and is the residual exploitable net of realistic costs?

The object being estimated, per programme, is

```
λ(a) = λ∞ + (λ0 − λ∞) · exp(−a / h)
```

where `a` is programme age, `λ0` is impact at birth, `h` is the absorption half-life,
and `λ∞` is the equilibrium floor. Roughly 700 independent programme births since 2019
make this the first setting in which the formation of a sunshine-trading equilibrium
can be watched rather than inferred.

Why the floor need not be zero: a dealer absorbing an option position retains an
*unhedgeable* residual (jump risk, vol-of-vol, discrete hedging). Competitive entry
drives the rent to zero but not the risk premium.

## Why the answer matters either way

- **λ0 > λ∞ > 0 with finite h** — publicly known mechanical inefficiencies are absorbed
  at a finite, measurable rate, and the half-life is the shelf-life of any such edge.
- **λ0 ≈ λ∞ ≈ 0** — option markets absorb disclosed mechanical supply essentially
  instantly, bounding a widely asserted volatility-amplification channel to near zero.

Both are results. Neither is "the model did not work."

## Data policy

**Every input is free and public.** No WRDS, no OptionMetrics, no paid vendor feed.
The stated aim is that any reader can rebuild the entire dataset at zero cost.

| Source | What it gives | Access |
|---|---|---|
| Cboe delayed quotes CDN | Full option chain per symbol: bid/ask **with sizes**, IV, greeks, volume, open interest | Free, unauthenticated |
| OCC series search | Authoritative per-series open interest and position limits | Free, unauthenticated |
| Issuer daily ETF holdings | Exact strikes, expiries, contract counts held by each programme | Free |
| SEC EDGAR N-PORT | Position-level fund derivatives with counterparty, from Oct 2019 | Free |
| SEC EDGAR N-CEN / 485BPOS | Fund launch dates and prospectus roll calendars | Free |

Because the quote-bearing sources are **snapshot** endpoints with no history, a missing
day is unrecoverable. The collector therefore runs daily and isolates per-symbol
failures so one bad symbol never costs a whole capture.

## Layout

```
configs/universe.json      treated and control underlyings
src/absorb/config.py       paths, endpoints, tunables
src/absorb/collect/http.py shared session, retry, pacing
src/absorb/collect/cboe.py option chain snapshots
src/absorb/collect/occ.py  series-level open interest
src/absorb/collect/runner.py  one daily pass + audit manifest
src/absorb/cli.py          entry point
tests/                     parser and runner tests
```

## Usage

```bash
uv venv && uv pip install -e ".[dev]"

# one capture of everything
.venv/bin/absorb-collect

# a single source, to a scratch root
.venv/bin/absorb-collect --sources cboe --root /tmp/absorb-check

# tests
.venv/bin/pytest
```

Output is Parquet partitioned by capture date, plus a JSON manifest per run recording
row counts and a SHA-256 of every raw payload.

## Scheduled capture

The primary collector is the `daily-capture` GitHub Actions workflow, which runs at
23:30 UTC Mon–Fri and publishes each day as a `.tar.zst` asset on a monthly release
tag (`data-YYYY-MM`). Release assets do not count against repository size, so the
capture is stored at full fidelity rather than trimmed. The workflow refuses to
publish if fewer than 80% of symbols were captured.

Retrieve captures on any machine:

```bash
scripts/fetch_captures.sh            # all months
scripts/fetch_captures.sh 2026-08    # one month
```

A local launchd job is available as an optional second, independent capture:

```bash
scripts/install_launchd.sh           # install or reinstall
scripts/install_launchd.sh --uninstall
```

Do not render the plist template in place — the installer writes a temporary copy so
that no machine-specific path enters version control.

Two operational notes. Scheduled workflows are disabled after 60 days of repository
inactivity, so check the schedule is still enabled after any quiet period. And the
local job accumulates roughly 18 MB per trading day on disk; prune `data/raw` once
the corresponding release assets are confirmed.

## License

MIT for the code. Any preprint is released separately under CC BY 4.0.
