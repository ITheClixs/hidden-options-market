# FLEX box rates against listed SPX box rates on the same dates (specification)

Written 2026-11-17, before any listed box rate was computed. It follows
[`2026-11-10-box-rates-spec.md`](2026-11-10-box-rates-spec.md), whose traded FLEX box
rates have been seen, including their amendment to settlement days. It has no hypothesis
test.

## Why

The traded spread of FLEX boxes over Treasuries has been set beside a quote-based estimate
from listed SPX options. That estimate was published for other months, and over the
months it covers FLEX boxes traded well below it. The 2026-11-15 review asked for a
like-for-like comparison: on the same dates and at the same maturities, does a lender
earn more or less in a FLEX box than the rate implied by listed SPX quotes? The answer
says where a large lender such as the BOXX fund gets paid, and whether FLEX boxes are a
cheaper or dearer way to borrow against the index.

## Data

- **Listed.** SPX's listed chains (roots SPX and SPXW, both European) for every session
  from the first stored capture to 2026-10-22, the end of the panel. Quotes are the
  latest read of each session, as the paper's gamma section reads them (`priced_chains`).
- **FLEX.** The box trades of the box-rate result with 7 days to one year to expiry (its
  headline sample), traded on those sessions.

## The listed box rate

For each session and each listed expiry, take the strikes that have both a call and a put
with a positive bid and an ask at or above it, within 20% of spot. Put-call parity for
European options says that the call mid less the put mid is
S·e^(−qT) − K·e^(−rT). An ordinary least-squares regression of call mid less put mid on
the strike has slope −e^(−rT). The listed box rate is −ln(−slope) / T, with T in years of
settlement-to-settlement days, as for FLEX boxes:
- the premium settles on the business day after the session;
- the payoff settles on the business day after expiry.

An expiry is used if it has at least 10 such strikes, a negative slope, and a rate inside
−5% to 25%.

## Matching

For each FLEX box trade, the listed box rate of its trade date at its settlement days is
read off the session's curve. The curve is linear in days between listed expiries and
flat beyond the first and last. A trade whose date has no listed curve is left out and
counted.

## What is reported

- **Matched trades.** Their count and face.
- **The difference, FLEX traded rate less listed rate.**
  - Median with its interquartile range, and the face-weighted mean.
  - A 95% interval from resampling trade dates (2,000 draws, fixed seed).
  - Split by FLEX underlying: SPX, SPY and other.
- **The listed box rate over Treasuries.** On the same matched points, the median and
  face-weighted mean of the listed rate less the Treasury benchmark used for FLEX boxes,
  as a check against the quote-based literature.
- **Fit quality.** The median number of strikes and the median R² of the parity
  regressions used.

## Reading

There is no test. A positive difference means FLEX box lenders earned more than listed
SPX quotes imply on the same day and maturity, and the paper says so. A negative one
means they earned less. The comparison covers about two months of overlap and says
nothing about other periods. Listed rates come from quotes at the close, while FLEX rates
come from trades during the day.

## What would change this specification

Only a defect found in the code or the data. Any change after a figure has been seen is
recorded here as a dated amendment.
