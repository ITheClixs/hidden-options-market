# A Census of the US FLEX Options Market — 2026-08-18

Snapshot date 2026-08-17. Universe: 682 underlyings with listed weekly options.
486,895 cleared series, 576 million contracts of open interest.

## Why this is possible

FLEX options are negotiated bilaterally and cleared by OCC. They never print on the
consolidated tape and do not appear in listed option chains, which is why they are
generally treated as unobservable. But OCC publishes open interest for every series it
clears, FLEX included, and FLEX is separable because listed strikes fall on a standard
grid: a strike whose cents component is not 0, 25, 50 or 75 was not listed.

## Validation

The detector finds **30.9 million contracts** carrying the FLEX strike signature.
Cboe reports FLEX open interest of **38.1 million contracts** for 2025, about 7% of
total US listed options open interest.

Recovering 81% of the exchange's own figure by an independent route is the strongest
available check on the method. The shortfall is expected and in the safe direction:
FLEX struck on the standard grid cannot be detected by strike signature alone, so the
census is a lower bound.

## What is in it

| structure | series | contracts | share | notional |
|---|---:|---:|---:|---:|
| index_linked — buffer and outcome caps/floors | 3,588 | 14.5m | 47.0% | \$364bn |
| matched_combination — conversions, boxes, financing | 602 | 7.9m | 25.6% | \$148bn* |
| block — large negotiated lines | 163 | 6.1m | 19.7% | \$82bn |
| unclassified | 547 | 1.2m | 3.9% | \$10bn |
| fund_synthetic — option-income fund legs | 184 | 1.2m | 3.8% | \$25bn |

\* Notional is not economic exposure for this category. The largest single line in the
census is an SPY series struck at **10,010.01** against a spot near 765, carrying equal
call and put open interest and \$29bn of notional. It is a box spread — a financing
transaction with no directional or convex exposure. Contract counts are the safer scale
here.

Concentration is extreme: 326 of 682 underlyings carry any FLEX at all, and SPY alone
accounts for the largest share of the index-linked category.

### The categories are separable, not assumed

Each has an independent signature, and one of them can be checked against disclosure.

- **index_linked** strikes carry arbitrary decimals (SPY 765.66, 597.42) because
  defined-outcome funds strike caps and floors off an index level on the day an
  outcome period opens. **20.6% of these series expire on a month end, against 4.7%
  for every other category** — the monthly outcome-period cycle, visible in the data
  without being assumed.
- **fund_synthetic** legs are cent-offset written puts, and they reconcile to issuer
  holdings exactly, to the contract, on 8 of 11 attributed cases.
- **matched_combination** carries exactly equal call and put open interest.
- **block** lines are round lots of 100,000–200,000 contracts on standard strikes.

## Two classifier errors found and fixed

Recorded because both produced plausible-looking output.

**One-sided calls were labelled fund synthetics.** MSFT carries a ladder of
100,000–200,000 contract *call* lines at 470, 510, 525, 550.01, 575, 590.01 and 625
across three expiries — one programme, roughly \$60bn. Cent offsets on some strikes
triggered the fund-synthetic rule. But a fund synthetic writes *puts*; the rule now
requires put dominance. This moved \$45bn from `fund_synthetic` to `block` and cut the
fund-synthetic count from 624 series to 184.

**Notional was reported as if comparable across categories.** The SPY box at strike
10,010 makes that untenable. Contract counts are now reported alongside, and the
caveat is attached to the category rather than left to the reader.

## Implication for gamma measurement

Dealer-gamma measures in public use are built from listed chains and therefore exclude
all of this. Pricing the absent series with Black-Scholes at locally interpolated
implied volatility, and cancelling matched legs because a box contributes no gamma:

| | share of listed-chain gamma |
|---|---:|
| aggregate across 67 symbols | 5.5% |
| median symbol | 0.5% |
| SPY | 11.3% |
| worst cases (HON, EFA, MSFT) | 25–43% |

The omission is **concentrated, not pervasive**. For a typical name it is negligible.
For SPY — the underlying most gamma commentary is actually about — roughly one dollar
of gamma in nine is invisible.

An earlier version of this calculation reported a median of 3.6% and 16 of 65 names
above 10%. That was wrong by roughly sevenfold at the median: it priced every FLEX
strike at the chain's median implied volatility, which badly overstates gamma for
far-out-of-the-money strikes, and it counted both legs of matched combinations that in
fact cancel. Cancelling matched legs alone removes 29% of the gross figure.

## Limits

- **One day.** Everything here is a snapshot. Growth, turnover and the dynamics of
  entry and exit require the time series now accumulating.
- **Lower bound.** On-grid FLEX is undetectable by strike signature; the true market is
  larger than 30.9m contracts.
- **Categories are inferred except one.** Only `fund_synthetic` is verified against
  disclosure. The others rest on structural signatures that are strong but not proven.
- **Attribution is mostly absent.** We can name the holder for income-fund legs. For
  the \$82bn of blocks we cannot, and identifying the counterparties to a
  \$60bn MSFT programme would be a contribution in itself.

---

## Correction: the index_linked category is overstated, and its notional is wrong in both directions

Audit of 2026-08-18, prompted by finding the same class of error in the block category.

`index_linked` is 47% of the census and had not been checked for offsetting legs.
It should have been. A buffer fund is a four-leg collar, and the census counts each
leg as a separate position.

SPY at expiry 2026-09-30 carries 99 FLEX legs. One fund is directly visible in four
of them, identifiable because the contract counts match:

| strike | side | contracts | role |
|---:|---|---:|---|
| 1.87 | call | 37,507 | synthetic long |
| 765.66 | call | 37,507 | cap |
| 746.77 | put | 38,317 | floor |
| 597.42 | put | 37,540 | buffer floor |

The fund's exposure is roughly 37,500 contracts of SPY, about **\$2.87bn**. The census
credits these four legs with **\$8.02bn**, counting one fund nearly three times.

The notional metric fails in both directions at once:

- **Overstated by leg duplication.** Every buffer fund contributes four legs, so a
  category composed of them is inflated by roughly the leg count.
- **Understated on the synthetic leg.** The long call struck at \$1.87 against a spot
  of \$765 is economically \$2.9bn of exposure. Valued as strike times contracts, it
  is recorded as \$7m — three orders of magnitude too small. Deep-in-the-money calls
  used to replicate the underlying are systematically invisible to a strike-based
  notional.

The correct scale for these structures is underlying-equivalent exposure, contracts
times spot, counted once per fund rather than once per leg.

**Consequence.** The headline decomposition in the table above should not be read as
economic exposure for `index_linked` or `matched_combination`, and the \$364bn figure
for buffer structures is materially overstated. Contract counts are unaffected by the
valuation error but are still inflated by leg duplication. Re-quantifying on an
underlying-equivalent, per-fund basis is the outstanding task; until it is done, the
composition should be read as *series counts by structure type*, which is what the
detector actually establishes.

This is the third instance of the same underlying mistake — treating series
independently when they are legs of one position — after the fund-synthetic
misclassification and the MSFT butterflies. The pattern is now clear enough that any
remaining category should be assumed guilty until audited.
