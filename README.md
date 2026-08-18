# Reading the FLEX Options Market from Clearing Data

**Anonymous**

**Paper:** [`paper/known_flow.pdf`](paper/known_flow.pdf) · rebuild with `scripts/reproduce.sh`

---

## The question

FLEX options are negotiated bilaterally, cleared centrally, and absent from listed
option chains. They are about 7% of US listed options open interest and grew 45% in
2025, and are generally treated as unobservable.

They are observable at no cost. Listed strikes fall on a standard grid, so a cleared
series struck off that grid was not listed. Applying that to 682 underlyings recovers
30.9m contracts of FLEX open interest — 81% of the exchange's own published figure.

## What is in it

| structure | count | exposure | share |
|---|---:|---:|---:|
| synthetic | 458 | $57.0bn | 29.1% |
| collar / buffer | 245 | $50.5bn | 25.7% |
| vertical spread | 185 | $38.7bn | 19.7% |
| risk reversal | 123 | $19.5bn | 10.0% |
| three-leg | 116 | $17.5bn | 8.9% |
| five or more legs | 55 | $11.9bn | 6.1% |

**1,193 structures, 220 underlyings, $196bn of exposure** — against $630bn if legs are
summed naively, a 3.2× overstatement.

## The methodological point

Open interest is reported per series. A position is not a series. Conflating them
produced three errors here, with opposite signs that do not cancel:

- a butterfly counted leg by leg, credited with **49×** its maximum attainable value;
- a four-leg buffer fund counted nearly **3×** over;
- a synthetic long call struck at \$1.87 against a \$765 spot recorded at \$7m when its
  exposure is **\$2.9bn**.

Grouping legs by contract count and valuing on the underlying corrects all three.

## Verification

Detected fund-synthetic legs reconcile to daily issuer holdings **exactly, to the
contract, in 8 of 11 cases**. Two further structures were confirmed against SEC
filings. Filing-based verification is bounded by disclosure lag rather than by method:
public N-PORT is ~110 days stale and every series in the census expires after the most
recent available report.

## Layout

```
src/absorb/collect/     OCC, chains, holdings, bars, N-PORT collectors
src/absorb/measure/     flex classifier, leg grouping, gamma gap, snapshots
scripts/reproduce.sh    rebuilds every number in the paper
paper/                  LaTeX source and figures
docs/                   census, results, corrections as they happened
```

## Data policy

Every input is free and public — no WRDS, no OptionMetrics, no vendor feed.

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
