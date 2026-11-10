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
  - A group with the same timestamp, root, expiry and size but more than two strikes
    carrying both rights is not resolved into boxes. Such groups are counted.
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
