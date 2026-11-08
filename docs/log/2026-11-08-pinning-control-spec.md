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

## Amendment, 2026-11-08, after the outcome was read: the result, and a baseline

**Outcome under the rule above.** The control rejects with D < 0: −0.024σ, t −2.56,
sign-flip p 0.016, on 37,672 events over 34 monthly expirations in 1,433 names. Under the
rule this is reported as such and is not a control. The design does not detect listed
pinning in this panel. The paper drops "do not pin" and says "not detected".

**A baseline, found while reading it.** It was added as a diagnostic, not a test. The same
construction on ordinary Monday-to-Thursday sessions, when nothing standard expires, gives
D = −0.006σ (t −2.43, 558 dates). D should average zero there, and it does not: s on the
day itself is near zero, while s over the following five sessions is slightly positive.
Closes drift towards the round strike chosen the day before. So the post-expiry
differencing carries a small negative bias when K\* is a round number. Monthly
expirations net of that baseline give −0.018σ (t −1.85, the two standard errors combined
as independent), not distinguishable from zero at 5%. The result carries both figures
(`control.placebo`, `control.less_placebo`).

The registered FLEX test is not changed. Its K\* is the FLEX strike with the most open
interest, often round too, so a bias of that order may sit in its estimate. That is small
next to its MDE of 0.078σ, and its sign would push the estimate away from pinning.

## Amendment 2, 2026-11-08: a matched placebo replaces the ordinary-day baseline

A re-review found that the ordinary-day baseline does not explain the negative D, and is
not the right comparison either.

- **Strikes are not the cause.** Random off-grid strikes at the same distances give
  about the same negative D. So the bias does not come from round strikes. It comes from
  the design: K\* is fixed by the close of E−1, while each pseudo-date's mirror is
  re-centred on the close before it. Short-horizon reversal pulls later closes back
  towards the E−1 close, and so towards any K\* near it.
- **The independence assumption is unsafe.** The ordinary-day baseline is a different
  sample, and its standard error was combined with the control's as if the two were
  independent. They share names and overlapping windows.
- **The statistic's centre.** It is centred on zero only for serially independent returns.

The diagnostic is now matched to each event. Placebo strikes sit at C(E−1)·exp(±|d|), at
the pin strike's distance |d| on each side. Their closeness on the expiry date cancels
exactly, so their mean D is the design's own term for that event. D net of it is
reported per event, with the registered inference. It is a post-hoc diagnostic, labelled
so in the paper. The control's registered outcome, above, stands.

On the 34 monthly expirations:
- the matched placebo is −0.016σ;
- the control net of it is −0.007σ (t −1.64, sign-flip p 0.11);
- the MDE is 0.013σ, since pairing removes the common noise.

On the FLEX events of the registered test, the matched placebo is +0.001σ. Net of it,
the FLEX estimate is −0.031σ (t −1.14), so the registered estimate is not materially
biased by this term. The superseded comparison against ordinary sessions (t −1.85) is no
longer reported.
