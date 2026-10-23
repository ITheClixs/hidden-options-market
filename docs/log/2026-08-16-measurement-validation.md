# Measurement Validation — Disclosed Option Legs in Free Public Data

**Date of capture:** 2026-08-16 (single cross-sectional snapshot)
**Status:** measurement validated; **no hypothesis tested, no return result claimed**

---

## What was being checked

The project depends on observing the option positions of the derivative-income fund
complex. The anticipated obstacle (recorded as failure mode 4 in the research plan)
was that these funds transact in FLEX, which does not print on the ordinary listed
tape, so without paid data the flow would be visible only in the funds' own holdings
files and could not be independently verified.

This note records that the obstacle does not bind, and how the position is recovered.

## The fingerprint

Fund synthetic-long structures write the put leg on a **non-standard deliverable
series struck one or two cents off the round strike**. OCC's free series file reports
open interest for every series including these. Observed for MSTR, expiry 2026-10-16:

| strike | call OI | put OI | interpretation |
|---:|---:|---:|---|
| 95.00 | 46,125 | 1,746 | ordinary listed series |
| 95.00 | 7,000 | 7,000 | unrelated matched combo |
| **95.01** | **0** | **45,115** | **the fund's written put leg** |
| 95.02 | 6,620 | 6,620 | unrelated matched combo |

MSTY's published holdings for the same date list `2MSTR 261016P00095010` at
**−45,115** contracts. The match is exact.

Two signals are jointly required, and both are necessary:

1. **Offset strike** — cents component not in {00, 25, 50, 75}, marking a
   non-standard deliverable series.
2. **One-sidedness** — ≥90% of the series' open interest on a single right.

## Reconciliation result

68 underlyings, 113,610 OCC series, against 28 registered YieldMax programmes.

| | count | notional |
|---|---:|---:|
| Synthetic legs detected | 2,552 | — |
| Attributed to a registered fund | 11 | $3.6bn |
| Unattributed | 2,541 | $307bn |

Of the 11 attributed legs, **8 match the fund's disclosed contract count exactly**
(|error| ≤ 1 contract): NVDY −64,900; MSTY −45,115; AMDY −8,185; AMZY −9,360;
CONY −12,730 and −9,425; PLTY −10,890; APLY −3,865.

Three do not match exactly and the reasons are known, not mysterious:

- `MSTR 100.01` — OCC 32,366 vs disclosed 32,250 (+116). A second holder in the same
  series, or a one-day timing difference between the OCC settlement snapshot and the
  forward-dated holdings file.
- `PLTR 135.01` — OCC 14,975 vs disclosed 10,966 (+4,009). Consistent with a second
  programme on the same underlying and strike.
- `IBIT 36.95 C` — a false positive. A call-side leg matched loosely to YBIT; the
  strike is not a cent-offset and the structure is something else.

## Two corrections made during this check

Both are recorded because they changed the conclusion, and both were caught by
comparing against disclosed holdings rather than by inspection.

1. **The first detector keyed on equal call and put open interest.** That is the
   signature of a conversion, reversal, box or collar — dealer financing structures —
   not of a fund synthetic. It produced 134 "strong" candidates totalling $18bn, of
   which none were fund legs. It is retained as `find_combo_candidates` for separate
   measurement and is no longer used to identify fund flow.
2. **The first reconciler matched on (expiry, strike) without the underlying.** Every
   fund therefore matched every symbol, yielding plausible-looking nonsense such as
   MSTY attributed to INTC and NVDY to CVX. Fixed; a regression test pins it.

## What the unattributed set appears to contain

Not fund synthetics only. The largest unattributed legs fall into at least two groups:

- **Buffer / defined-outcome ETF FLEX**, e.g. `SPY 2026-09-30 765.66 C`,
  `SPY 2026-09-30 597.42 P`, `SPY 2026-10-30 579.76 P`. The irregular strikes are
  characteristic of outcome-period caps and floors struck off an index level. These
  issuers are not yet in the registry; adding them is the immediate next step.
- **Single large institutional structures**, e.g. `MSFT 2026-11-20 550.01 C` at
  200,000 contracts with 100,000-lot siblings at 510.01 and 590.01. Round sizes on one
  name and expiry look like one negotiated trade, not a fund programme.

The $307bn figure is therefore **an upper bound on a mixed population**, not a measure
of fund flow. It must not be quoted as the size of the disclosed-fund complex.

## Standing caveats

- One day, one snapshot. Nothing here speaks to returns, volatility, or the absorption
  hypothesis.
- OCC open interest is as of the prior settlement; issuer holdings files are dated
  forward one business day. The one-day offset must be handled explicitly in the panel.
- Detection thresholds (min 100 contracts, ≥90% one-sidedness) are provisional and
  were set before reconciliation, not tuned to maximise matches.

## Why this matters for the study

Independent verification of disclosed positions was not assumed to be available. It
is. Fund holdings give the intended position; OCC gives the realised open interest in
the same series; the two agree to the contract. That supports a validation the paper
can state plainly, and it opens a discovery channel for programmes absent from the
registry.
