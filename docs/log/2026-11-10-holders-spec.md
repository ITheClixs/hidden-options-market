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

## Result, 2026-11-10

Computed as specified, with no change after the figures were seen.

- **The funds.** The file holds 173 funds with option lines and $36.4bn of net assets
  among them. Their true stock legs are worth $22.1bn at the funds' prices.
- **Matching.** 730 FLEX lines from 168 funds. 99.2% of the lines and 98.0% of the
  contracts are in OCC's report of 2026-11-09, as 720 series. The funds hold a median
  98% of a series' open interest, at least 95% of it in 59% of the series, and 91% of
  the open interest of all the series taken together.
- **The stock-leg rule** finds every true stock leg (100% by contracts).
- **The package rule** finds 58% of true package legs by contracts. The rest have a
  count in the report that differs from their stock leg's, because several funds share
  the strike.
- **How much of each category these funds are.** 34% of the report's stock-leg open
  interest and 31% of its package-leg open interest.
- **Sign by design.** 96.0% of true package legs, by contracts, are held on the side
  the design predicts: 100% of upper puts, 98.9% of calls and 90.4% of lower puts.
- **The dealer's side in gamma**, as the change in dollar delta for a 1% move. Every
  matched package leg was priced.
  - All underlyings: dealer long $1,477m, dealer short $853m, net long $623m. The
    vendor convention gives a net of $40m and signs 14% of the legs' gross gamma wrongly.
  - SPY: long $1,210m, short $702m, net long $508m, against $85m under the convention.
    The legs are 16% of SPY's gross FLEX gamma on the date.
  - The legs are 28% of gross FLEX gamma in EFA, 36% in EEM, 11% in IWM and 8% in QQQ.
- **The box.** The BOXX fund holds 14,902 contracts of the SPY 10.01/10,010.01 box of
  December 2026 on the lending side: $14.9bn of face, 92% of that box's open interest
  and 21% of the $69.9bn of box face the anatomy rules find on the date. It is short a
  QQQ box of $0.45bn. The anatomy rules classify its SPY box as a box.

**Reading.** For this issuer's funds on this date the stock-leg rule is exact, the
package rule finds a little over half of the legs, and the design predicts the side of
96% of them. The dealer opposite these funds is net long gamma, and the convention that
signs every put as dealer-short misses most of that. One fund is the lender in the
largest box. None of this is known for other issuers or other dates.

## Added 2026-11-10, after the figures above were seen

A profile of the dealer's net gamma in the matched SPY legs across spot levels, from 15%
below the report date's spot to 15% above, with each leg's volatility held at the value
its mark implies. It is another view of the same legs and changes no figure above.

- With the disclosed sides the net is positive at every level above a fall of about 6%,
  between −$54m and zero from there to a fall of about 13%, and positive again below.
- Under the vendor convention the net turns negative just below spot and reaches about
  −$900m at a fall of 13%.
- At 10% below spot: −$52m with the disclosed sides, −$846m under the convention.

The convention reads these funds as a large source of dealer short gamma in a fall. The
holdings say there is almost none, because the dealer who is short the upper puts is
long the lower ones. The profile holds volatility fixed and covers one issuer on one
date.
