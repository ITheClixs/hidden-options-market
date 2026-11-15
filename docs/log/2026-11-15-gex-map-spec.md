# What signed fund legs do to SPY's gamma exposure (specification)

Written 2026-11-15, before any of the figures below was computed. It follows the holders
check in [`2026-11-10-holders-spec.md`](2026-11-10-holders-spec.md). That check's own
figures, including a profile of the dealer's gamma in the matched SPY lines across price
levels, have been seen. The listed SPY chain of the same date has not been priced, and
no figure below has been computed. It has no hypothesis test.

## Why

The holders check found that the sign convention behind gamma-exposure (GEX) figures,
applied to one issuer's fund legs, gets their sign wrong in a fall. A desk reads GEX for
the whole underlying, not for a few legs. The 2026-11-15 review panel asked where that
lands. What is SPY's GEX on the date? How much do FLEX series add to it under the
convention? How much does signing the issuer's legs by their disclosed side change it,
at spot and at other price levels? And where is the level at which the net changes sign?

## Data

- **Listed.** SPY's listed chain for the settlement of 2026-11-09. Open interest comes
  from the chain read after that settlement, and quotes and implied volatilities from
  the latest read of that session, as the gamma section of the paper reads them
  (`priced_chains`).
- **FLEX.** OCC's FLEX report of 2026-11-09, SPY roots.
- **Holdings.** The holdings snapshot of 2026-11-10 used by the holders check (Innovator's
  all-funds file and the BOXX page). Its FLEX lines are matched to the report on root,
  expiry, right and strike.

## Pricing

- **Model.** Black–Scholes gamma at the paper's rate of 4% and no dividends.
- **Spot.** The listed chain's underlying price for the session.
- **Volatility.** A listed series is priced at its own quoted implied volatility. A FLEX
  series is priced at the listed surface's volatility at its strike and expiry, read as
  the paper's gamma section reads it. Every volatility is held fixed as the price level
  moves.
- **Price levels.** From 15% below spot to 15% above, in steps of 0.5%.
- **Units.** Dollar gamma for a 1% move, Γ·n·100·S²·0.01, at each level S.
- Series expiring on or before the date are out. So is a listed series without a usable
  implied volatility, as in the gamma section.

## Three readings

1. **Listed only, under the convention.** Calls count positive, puts negative.
2. **Listed and FLEX, under the convention.** Every FLEX SPY series is added, signed the
   same way.
3. **Listed and FLEX, with disclosed sides where known.** As in reading 2, except that
   each matched fund line counts with the side opposite the fund's, in proportion to the
   fund's contracts. The rest of that series, and every unmatched series, stays under the
   convention.

## What is reported

- **Each reading.** The net at spot and at 10% below spot.
- **The zero-gamma level.** The price level closest to spot at which the net changes
  sign, by linear interpolation between grid points; none if it does not change sign in
  the range.
- **The change from signing.** Reading 3 less reading 2, at spot and at 10% below.
- **Size.** The matched fund lines' gross gamma at spot, as a share of the listed gross
  gamma at spot, and as a share of all FLEX gross gamma at spot.
- **A figure.** The three readings across price levels.

## Reading

There is no test. Readings 1 and 2 are what a vendor reports and what it would report if
it included FLEX. Reading 3 changes only the legs whose side is disclosed, so it is still
a convention everywhere else. If the change from signing is small against reading 1, the
paper says the holdings correct a small part of SPY's GEX. If it moves the net or the
zero-gamma level materially, the paper says so. Either way the comparison covers one
issuer on one date.

## What would change this specification

Only a defect found in the code or the data. Any change after a figure has been seen is
recorded here as a dated amendment.
