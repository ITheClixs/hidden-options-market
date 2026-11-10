# The price of box lending, from traded packages (specification)

Written 2026-11-10, before the trade reports were collected or any rate was computed on
them. It is a measurement with no hypothesis test. It follows
[`2026-11-10-anatomy-spec.md`](2026-11-10-anatomy-spec.md), which counts box spreads in
open interest.

## Why

Open interest says how much box lending is outstanding. It does not say at what rate.
OCC's marks imply a rate, but a mark is OCC's valuation, not a price anyone paid. Cboe
publishes every FLEX execution on its exchange, with time, price, size and a flag for
legs of a multi-leg order. A box spread traded as one order appears there as four legs
with one timestamp, and its net price is the amount lent.

## What was seen before writing

Two of the daily files, 2025-06-02 and 2026-10-22, were opened to learn the layout.
What was seen:

- the columns: time, price, size, root, expiry, right, strike and a spread flag;
- that every execution appears twice;
- thirteen box packages in the two files, with rates near 4.45% to 4.8%;
- that files exist from about April 2025 and not before.

No benchmark rate was set beside those trades.

## Data

- **Trades.** Cboe's daily "FLEX trade reports" for its options exchange, from the
  first file available to 2026-10-22, the end of the panel. SPX FLEX trades only on
  Cboe. FLEX on equities and ETFs also trades on other exchanges, which these files do
  not cover.
- **Benchmark.** The US Treasury's daily par yield curve.
- **Marks.** OCC's FLEX report of the trade date, already in the panel.

## Rules

- **Executions.** Identical rows are one execution reported from both sides. A row seen
  m times counts as m/2 executions, rounded up.
- **Box trade.** Among rows flagged as legs of a spread, a group with one timestamp,
  root, expiry and size that consists of exactly four legs: a call and a put at each of
  two strikes. Its price is (C1 − P1) − (C2 − P2), where 1 is the lower strike. Its face
  is the distance between the strikes times 100 times the size.
  - A group with the same timestamp, root, expiry and size that has two or more strikes
    carrying both rights but is not exactly such a box is not resolved into boxes. That
    covers more than two such strikes, extra legs, and a leg at more than one price.
    Such groups are counted. (Wording widened on 2026-11-10 while the code was written,
    before any file beyond the two named above was read: the first version named only
    the case of more than two strikes.)
  - A box executed several times at one instant, each leg equally often, counts with
    that multiple of its size.
- **Rate.** The continuously compounded rate that discounts the distance between the
  strikes to the price over the calendar days from trade date to expiry, on a 365-day
  year.
- **Rate sample.** Box trades with at least 7 days to expiry and a positive price.
  Rates outside −5% to 25% are treated as errors, dropped and counted.
- **Benchmark rate.** The Treasury curve of the trade date at the box's maturity:
  - each published maturity is converted to continuous compounding, as a simple yield
    up to six months and as a semiannual yield from one year;
  - between published maturities the converted rates are interpolated linearly in days;
  - below one month the one-month rate is used.
  A trade date with no curve takes the previous business day's.
- **Spread.** The box rate less the benchmark rate.

## What is reported

- **The sample.** Files, executions, box trades, their face, and how many groups were
  not resolved or dropped.
- **The spread.** Face-weighted mean, median and interquartile range of the spread:
  - for boxes of 7 days to one year, which is the headline, because a Treasury bill
    yield is a zero rate there;
  - by maturity: 7 days to 1 month, 1 to 3 months, 3 to 12 months, 1 to 2 years, over 2
    years. Beyond one year the benchmark is a par yield, so those spreads are
    approximate;
  - for SPX, SPY and everything else;
  - by calendar month, with the traded face of the month.
- **A standard error.** For the headline mean, clustered by trade date.
- **Marks against trades.** For each box trade whose four series are in OCC's report of
  the trade date, the rate implied by the marks less the traded rate. Face-weighted
  mean and median.
- **The open-interest rule against trades.** Of the box face found in open interest on
  the last report date, the share at a root, expiry and pair of strikes that traded as
  a box package in the files.

## Reading

There is no test. The spread is described as it comes out. A positive spread is what
the literature on box rates finds in quoted prices; the paper says how large it is in
these traded prices and how it varies with maturity.

## What would change this specification

Only a defect found in the code or the data. Any change after a rate has been seen is
recorded here as a dated amendment, with the figure it changed.

## Result, 2026-11-10

Computed as specified. One defect was fixed before any figure was produced: a day with no
box trade returned an empty table that broke the joining of days; such days are now
skipped when the days are joined.

- **Sample.** 391 files from 2025-03-31 to 2026-10-22, with 499,633 executions. The
  files of 2025-11-12 and 2026-04-13 were published with a header and no rows.
  1,359 box trades with $158.5bn of face. 8 groups were not resolved. Dropped from the
  rate sample: 29 with under 7 days to run, 9 without a positive price, 14 with a rate
  out of range. Every remaining trade had a benchmark.
- **Headline, 7 days to one year.** 1,099 trades on 369 dates, $146.6bn of face. The
  face-weighted mean spread over the Treasury curve is 35.8bp (standard error 4.9bp),
  the median 38.7bp, the interquartile range 24.8bp to 49.3bp. The traded rate averages
  4.25% against 3.89% for the benchmark.
- **By maturity (face-weighted mean, median).** 7 days to 1 month: 30.8bp, 38.9bp.
  1 to 3 months: 34.5bp, 35.3bp. 3 to 12 months: 39.7bp, 41.2bp. 1 to 2 years: 31.4bp,
  28.5bp. Over 2 years: −42.1bp, 24.6bp, on 83 trades with a standard error of 57bp.
- **By underlying, up to one year.** SPX 40.3bp, SPY 39.2bp, everything else 30.9bp.
- **By month.** The median runs from about 20bp in spring 2025 to 40bp to 45bp in 2026.
  Traded face peaks in the last month of each quarter.
- **Marks against trades.** 1,304 of 1,307 trades have all four series in OCC's report
  of the trade date. The rate in the marks is 35bp below the traded rate on average and
  42bp below at the median: OCC's marks value a box at about the Treasury rate.
- **The open-interest rule against trades.** 41% of the box face found in open interest
  on 2026-10-22 ($27.5bn of $67.9bn) is at a root, expiry and pair of strikes that
  traded as a box package in the files.

**Diagnostics added after these figures were seen.** They are not part of the
specification.

- The face-weighted mean of June 2025 is −5.9bp against a median of 7.2bp. It comes from
  one roll on 2025-06-06, a QQQ box of 24 days and a SPY box of 105 days traded seconds
  apart in near-equal size. The two legs of a roll are priced together, so the rate of
  each alone is loose. Medians do not move with it: by trade size, the median spread is
  between 36bp and 42bp in every band from under $1m to over $1bn of face.
- Of the $40.3bn of open-interest box face not seen trading as a package, $27.7bn is in
  boxes of 100 to 1,000 contracts, mostly SPX strike pairs at uneven levels such as
  3673.53 and 7729.26. Those look like two forwards struck at index levels of different
  dates whose counts match, which pays a fixed amount at expiry as a box does but need
  not have been lent as one. The largest untraded box is 2SPY 100/1200 of December 2026
  ($2.6bn).

**Reading.** Box spreads on Cboe traded about 36bp above Treasuries of the same
maturity. The figure for box positions in open interest is an upper bound on lending
done through boxes; the part confirmed by traded packages since April 2025 is 41% of it.
