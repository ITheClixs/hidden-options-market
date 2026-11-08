# A positive control for the pinning test: listed strikes on monthly expirations (specification)

Written 2026-11-08, before any expiry-date close in this design was read. It adds a
control to the pinning test of [`2026-11-08-pinning-spec.md`](2026-11-08-pinning-spec.md)
and changes nothing in that test.

## Why

The pinning test finds no attraction to the largest FLEX strike on dates when only FLEX
expires. The methodology review (round 2, W1) asks whether the design could have found
pinning at all. The statistic is a capped continuous distance difference, and pinning is a
local effect at the close. Its Friday row, where listed options also expire, uses the
FLEX strike and is null too. A control is needed that runs the identical statistic where
pinning is documented: listed strikes at standard monthly expirations
(Ni, Pearson and Poteshman 2005).

## Why the nearest coarse listed strike

Listed open interest by strike is stored only from 13 August 2026, three monthly
expirations before the panel ends. So the strike with the most listed open interest can't
be the pin strike over the panel. The control uses the strike nearest the previous close
on a coarse standard grid instead: multiples of $2.50 for a previous close below $25, of
$5 from $25 to $200, and of $10 above $200. Every optionable name lists those strikes at
its monthly expiration, since finer grids contain them. The nearest strike is the measure
of the pinning literature. Round strikes attract closes on any day, so the pseudo-expiry
differencing, which subtracts the same comparison on the five sessions after expiry, is
the part of the design that matters here.

## Events

- **Expiries.** The standard monthly expiration: the third Friday of each month, or the
  session before it when that Friday is a holiday. Only expiries with closes for E−1
  through E+5 count, and only those with σ from 40 or more of the 60 sessions before.
- **Names.** Every equity symbol in the bars, with a previous close of at least $5.
- **Pin strike.** K\* is the coarse-grid strike nearest the close of E−1. It is kept if it
  lies within 2σ, as in the registered test. Ties go to the lower strike.
- **Splits.** An event with a split between E−1 and E+5 is dropped. σ and closes are on
  the bases of the registered test.

## Statistic and inference

The registered statistic, unchanged: D = s(E) minus the mean of s over E+1 to E+5, where s
is closeness to K\* against its mirror about the previous close, capped at 2σ. The
inference also follows the test: a mean with standard errors clustered by expiry date,
t on G−1 degrees of freedom, and a sign-flip randomisation over expiry dates (10,000
draws, fixed seed). The MDE is at 80% power.

- **Control (the one test in this entry).** Mean D > 0 on monthly expirations,
  two-sided, α = 0.05.
- **Descriptive.**
  - The same construction on Fridays that are not monthly expirations, when weekly
    listed options expire in some names.
  - The banded versions at 0.25σ and 0.5σ.

## What counts as what

- **The control rejects with D > 0.** The design detects listed pinning. The FLEX null is
  then read against the control's estimate: the FLEX book is either too small or not
  hedged in the way that pins.
- **The control does not reject.** The design does not detect listed pinning in this panel
  either. The paper then says so, and drops any claim that stocks "do not pin" to FLEX
  strikes. What is left is: not detected, by a design that detects none at listed strikes.
- **The control rejects with D < 0.** This is reported as such. It is not a control.

## What would change this specification

Only a defect found in the code. Any change after an outcome has been seen is recorded
here as a dated amendment, with the estimate it changed.
