# Who holds the fund packages and the largest box (specification)

Written 2026-11-10, before any holding was matched to the FLEX report. It is a check of
the product rules in [`2026-11-10-anatomy-spec.md`](2026-11-10-anatomy-spec.md) against
what two issuers disclose, and a first signed reading of a part of the book. It has no
hypothesis test.

## Why

The product split reads boxes and fund packages from counts. It cannot say who holds
them or which side. Issuers publish their funds' holdings daily, with signed quantities.
Where a FLEX series belongs to a fund, the fund's side is known and the dealer's is the
opposite.

The plan was to use SEC N-PORT filings, which cover every registered fund. The SEC
refuses requests that carry no contact address, and none is configured, so that part
waits. This entry uses issuer files instead. It covers one date and two issuers, and it
says so wherever a figure is read.

## What was seen before writing

- Innovator's file of all its funds' holdings, dated 2026-11-10: its columns, 179 funds,
  768 option lines, and the four option lines of one fund (BJAN), which are a long call
  struck at 6.83, a long put, a short put below it and a short call above.
- The holdings table on the BOXX fund page of the same day: a long SPY box at 10.01 and
  10,010.01 expiring 2026-12-18 with 14,902 contracts a leg, and a short QQQ box of 453.
- Nothing was matched to the FLEX report, and no rule was scored.

## Data

- **Fund holdings.** Innovator's all-funds holdings file and the BOXX page, both
  captured on 2026-11-10 and kept with the raw data. Quantities are signed: a short
  position is negative.
- **The report.** OCC's FLEX report of 2026-11-09, the last activity date before the
  date on the holdings. It is after the end of the panel; the panel is not extended.
- An option line of a fund is a FLEX line when its root begins with a digit. It matches
  a report series on root, expiry, right and strike.

## What is reported

- **Matching.** Of the funds' FLEX lines, the share found in the report, by lines and by
  contracts. For the series found, the funds' summed contracts as a share of open
  interest: the median, and the share of series where it is at least 95%. A FLEX series
  is bespoke, so this share should be near one.
- **The stock-leg rule.** A fund's *true stock leg* is a long FLEX call whose strike is
  at most 5% of its own price plus its strike, on the fund's price, not OCC's mark. Of
  true stock legs, by contracts, the share the anatomy rules call a stock-leg call on
  the report.
- **The package rule.** A fund's *true package legs* are its other FLEX option lines at
  a root and expiry where it holds a true stock leg. Of them, by contracts, the share
  the rules call a package leg.
- **How much of each category these funds are.** Of the report's open interest in
  stock-leg calls and in package legs, the share in series these funds hold.
- **Sign by design.** The design of a defined-outcome fund predicts each leg's side:
  long the stock leg; among its puts at that root and expiry, long the highest strike
  and short the rest; short every other call. Of true package legs, by contracts, the
  share whose disclosed side agrees.
- **The dealer's side in gamma.** Each matched fund line priced from OCC's mark of the
  report date, with the method of the paper's pricing section. The spot of an underlying
  is the mark plus the strike of its stock-leg call nearest to expiry. The dealer's
  position is the opposite of the fund's. Per underlying and in all:
  - dealer-long, dealer-short and net dollar gamma in the legs these funds hold;
  - the share of the underlying's gross FLEX gamma on that date that those legs are;
  - the net under the convention gamma vendors apply (dealers long calls, short puts),
    and the share of the legs' gross gamma that the convention signs wrongly.
- **The box.** The BOXX fund's box positions: face lent and face borrowed. Its long
  box's contracts as a share of that box's open interest, and its lent face as a share
  of all box face the anatomy rules find on the report date.

## Reading

There is no test. The check covers one issuer of defined-outcome funds and one box fund
on one date. It does not say what other issuers hold, and it cannot say how any figure
moved over the panel. If the rules and the design signs agree with the holdings, the
paper says so for these funds and uses the design signs nowhere else.

## What would change this specification

Only a defect found in the code or the data. Any change after a figure has been seen is
recorded here as a dated amendment.
