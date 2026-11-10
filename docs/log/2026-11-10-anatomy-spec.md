# What the FLEX market is made of (specification)

Written 2026-11-10, before the measurement below was run on the panel. It is a
measurement with no hypothesis test. It was written after an exploratory look at five
report dates, described in the next section, and that look shaped the rules.

## Why

The paper measures how large the FLEX market is and how much of its gamma survives
netting. It does not say what the market is made of. The report shows recognisable
products: box spreads, which are loans; the option packages of defined-outcome funds;
and calls and puts paired at one strike, which are forwards. Each has a fingerprint in
open interest. Counting them says how much of the market is lending and delta-one
exposure, and how much is left as outright option risk, which is the part the paper's
tests are about.

## What was seen before writing

Rough versions of the rules below were run on five report dates: 2024-12-02,
2025-06-02, 2025-12-01, 2026-06-01 and 2026-10-22. No price or volatility outcome was
involved. What was seen:

- On 2026-10-22, about $68bn of face in four-series groups that look like box spreads,
  against $22bn on 2024-12-02.
- On 2026-10-22, about $91bn of mark value in calls struck under 5% of spot that have no
  matching put, most of it in SPY.
- On 2026-10-22, about $240bn of SPX mark value at strikes where call and put open
  interest are equal.
- The series of one SPY month-end expiry, listed in full, which showed four-leg fund
  packages with equal counts and also packages whose legs share strikes with others.

The 5% threshold, the use of exact equality of counts, and the order of the categories
were chosen after that look. The figures above are not results.

## Rules

Every rule works on one report date, within one root and one expiry. The root carries
the exercise style, and the legs of one trade share it.

- **Paired strike.** A strike at which call and put open interest are equal and
  positive. That count is the strike's pair count.
- **Box.** Two paired strikes with the same pair count: four series. Its face is the
  distance between the strikes times 100 times the count. Its value at the marks is
  ((C1 − P1) − (C2 − P2)) times 100 times the count, where 1 is the lower strike.
  - When more than two paired strikes of one root and expiry share a count, they are
    matched from the outside in: lowest with highest, then the next pair inwards. With
    an odd number, the middle strike is left as a same-strike pair.
  - The alternative matching, each strike with its neighbour, gives a smaller face. Both
    are reported, and the outside-in figure is the headline.
- **Stock-leg call.** A call that is not at a paired strike and whose strike is at most
  5% of its mark plus its strike. Mark plus strike is close to spot for such a call, so
  the rule needs no price data.
- **Package leg.** Any other series whose open interest equals that of a stock-leg call
  at the same root and expiry. This includes both sides of a paired strike with that
  count.
- **Same-strike pair.** Both series of a paired strike that is in no box and is not a
  package leg.
- **Other.** Everything else.

The categories are assigned in that order, and every series with open interest gets
exactly one.

## What is reported

- **The split.** For every report date, the number of series, the open interest and the
  mark value in each category, and their shares. The paper gives the first date, the
  last date and the average over dates.
- **Box lending.** Face and value at the marks on every date, with:
  - the number of boxes;
  - the split by time to expiry (up to 1 month, 1 to 3 months, 3 to 12 months, 1 to 2
    years, over 2 years);
  - the split between SPX, SPY and everything else;
  - the share of face in European-style roots (leading digit 2 or 4);
  - the face under the neighbour matching;
  - the share of face in boxes whose upper strike is at least 1.25 times the lower.
- **The rate in OCC's marks.** For boxes with at least 7 days to expiry, the rate that
  equates value at the marks to face, weighted by face. This describes OCC's valuation
  curve. It is not a market rate; traded rates are the subject of a later entry.
- **Stock legs.** Their mark value by underlying on the last date. A stock-leg call is
  worth nearly its contracts times spot, so this is the stock exposure held through
  these calls.
- **Pairs.** The forward notional of same-strike pairs: pair count times 100 times
  (strike plus call mark less put mark).
- **Co-location.** The share of open interest in "other" that sits at a root and expiry
  with at least one stock-leg call. Fund packages whose legs share strikes with other
  packages fail the equal-count rule and land in "other"; this share bounds how much of
  "other" could be such legs.
- **Gamma.** On the domain of the `hidden_gamma` result (its underlyings and
  settlements, priced on the listed surface), the share of gross FLEX dollar gamma in
  each category.
- **Growth.** The change in box face and in stock-leg value from the first date to the
  last.

## Checks on the rules

- **Chance.** On every twentieth report date, open interest is shuffled among the
  series of each root and expiry, with a fixed seed, and the rules are run again. The
  box face and package-leg open interest found that way are the chance benchmark.
- **Outside evidence.** The box rule is checked against traded packages in Cboe's FLEX
  trade reports, and the fund categories against fund filings, in later entries with
  their own specifications.

## Reading

There is no test. The paper reports the split as it comes out. If boxes, stock legs and
same-strike pairs hold most of the mark value, the paper says that by value the hidden
market is mostly lending and delta-one exposure, and reports the share of open interest
and of gamma that remains as outright options.

## What would change this specification

Only a defect found in the code or the data. Any change after the panel figures have
been seen is recorded here as a dated amendment, with the figure it changed.
