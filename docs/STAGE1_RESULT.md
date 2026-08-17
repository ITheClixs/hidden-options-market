# Stage 1 Result — 2026-08-17

Run against the thresholds fixed in `PILOT_SPEC.md` before any estimation.

Panel: 64,553 observations, 52 names (25 treated, 27 control), 1,253 trading days,
2021-08-19 to 2026-08-17. Outcome is log dollar volume with name and date fixed
effects and `|return|` as a control. Errors two-way clustered on name and date.

## Estimates

| specification | β (post × Friday) | se | t | p | 95% CI | MDE80 |
|---|---:|---:|---:|---:|---|---:|
| **all treated** | +0.0289 | 0.0163 | 1.77 | 0.082 | [−0.004, +0.062] | 0.047 |
| dose low | +0.0355 | 0.0142 | 2.51 | 0.017 | [+0.007, +0.064] | 0.041 |
| dose mid | +0.0178 | 0.0175 | 1.02 | 0.316 | [−0.018, +0.053] | 0.051 |
| dose high | +0.0298 | 0.0404 | 0.74 | 0.466 | [−0.052, +0.112] | 0.117 |
| placebo: Thursday | −0.0023 | 0.0121 | −0.19 | 0.851 | [−0.027, +0.022] | 0.035 |
| pre-trend: 6m pre-launch | −0.0087 | 0.0290 | −0.30 | 0.766 | [−0.067, +0.049] | 0.083 |

## Verdict against the pre-registered criteria

**Does not pass.**

The criterion required ≥5% abnormal Friday volume in the top dose tercile at t ≥ 3.0,
*and* monotonicity across dose terciles. Neither holds. The top tercile gives +3.0%
at t = 0.74, and the ordering across terciles is low > high > mid — no dose response
at all.

Under the spec's own definitions this sits between "ambiguous" and "fail": the dose
pattern is absent, but the top tercile's interval [−5.2%, +11.2%] does not exclude 5%,
so the hypothesis is not *rejected* there either. It is underpowered, with an MDE of
11.7% against a 5% target, because that tercile holds only about eight names.

## What is genuinely informative

**The placebos are clean.** Shifting the event to Thursday gives −0.2% (t = −0.19),
and the six months before launch give −0.9% (t = −0.30). The design is not
manufacturing effects, so the weak result is a property of the data rather than of the
specification. That is worth as much as the main estimate.

**The pooled effect is suggestive but not more.** +2.9% extra Friday volume at
p = 0.082 is the kind of number that becomes whatever the analyst wants it to be. It is
not evidence for the mechanism.

**The absent dose response is the most damaging finding.** If dealers were hedging
programme flow, names where the programme is large relative to turnover should show
the largest footprint. They do not. Taken at face value this is evidence against the
mechanism, and it is the result the project has to answer.

## Two measurement weaknesses that could produce exactly this pattern

Before treating the dose result as decisive, both need fixing, because each degrades
precisely the dose sort that failed.

1. **Dose is measured with today's net assets applied to five years of history.**
   These funds grew by orders of magnitude over their lives; a fund that is large now
   was small at launch. Applying a current cross-sectional figure retroactively is
   close to a random re-labelling for the early part of each sample. The N-PORT
   quarterly net-asset series (seven points per fund) fixes this and already exists.

2. **The roll day is assumed to be Friday and was never verified.** Weekly option
   expiry is Friday, but whether these funds transact then, the day before, or on
   Monday is an empirical question that the daily holdings series answers directly.
   If the true roll is systematically off Friday, the estimand is diluted toward zero
   by construction.

Neither weakness is an excuse for the result. Both were avoidable and should have been
resolved before running, and the honest position is that Stage 1 is inconclusive on the
mechanism rather than that the mechanism is disproved.

## What this does not say

It does not say option-income funds have no market footprint. It says that at daily
frequency, with a Friday proxy for the roll and a static dose measure, no dose-ordered
Friday volume effect above roughly 4–12% is detectable. The mechanism could still
operate intraday, on a different day, or at a magnitude below this resolution.

## Next

- Rebuild dose from the N-PORT quarterly net-asset series rather than a single
  current value.
- Identify actual roll days from the holdings series instead of assuming Friday.
- Re-run. If the dose response is still absent with both fixed, that is a real finding
  and should be written up as one.

---

# Stage 1 v2 — 2026-08-18

Both measurement weaknesses fixed. Dose now steps with the N-PORT reported net-asset
series (226 reports across 23 funds, 2023-01 to 2026-04) instead of a single current
figure, and every weekday is estimated rather than assuming Friday.

The fix mattered: MSTY's reported net assets ran $437m (Jul-2024) → $5,747m (Jul-2025)
→ $726m (today). Applying today's figure across five years was not a mild
approximation.

## Dose actually spans three orders of magnitude

Peak fund AUM over the underlying's median daily dollar volume:

| symbol | peak | median | peak AUM $m | ADV $m |
|---|---:|---:|---:|---:|
| MSTR | 5.72 | 1.27 | 5,747 | 1,004 |
| COIN | 1.02 | 0.44 | 1,455 | 1,427 |
| HOOD | 0.89 | 0.47 | 252 | 282 |
| SMCI | 0.41 | 0.15 | 338 | 825 |
| GDX | 0.36 | 0.13 | 283 | 789 |
| MRNA / MARA | 0.27 | 0.15 | 115 / 125 | 425 / 469 |
| NVDA | 0.08 | 0.05 | 1,910 | 23,635 |
| AAPL | 0.014 | 0.008 | 155 | 11,098 |
| DIS | 0.005 | 0.005 | 5 | 1,049 |

Seven of 23 names reach a peak above 0.25; two exceed 1.0. At its peak MSTY held 5.7
times MSTR's entire daily dollar turnover. This is the variation a dose-response test
needs, and it is present.

## Result: a precise null on the mechanism

| weekday | level β | t | **dose-response β** | t | MDE80 |
|---|---:|---:|---:|---:|---:|
| Mon | −0.0133 | −1.25 | +0.0033 | +0.46 | 0.020 |
| Tue | −0.0129 | −1.64 | +0.0059 | +0.87 | 0.019 |
| Wed | −0.0045 | −0.49 | −0.0018 | −0.24 | 0.021 |
| Thu | +0.0013 | +0.11 | −0.0039 | −0.52 | 0.021 |
| Fri | +0.0288 | +1.95 | −0.0035 | −0.40 | 0.025 |

**No dose response on any day.** Every coefficient sits within ±0.006 with an MDE
near 0.020 per log unit of dose. Log dose spans about 7 units across the sample, so
the test would resolve a total spread of roughly 14% of volume across the full dose
range. It finds nothing.

This is not the underpowered cell of v1. It is a tight zero.

## Reading it

**The Friday level effect survives but is not the mechanism.** +2.9% (t = 1.95) is the
same figure as v1 and it is the only day that stands out. But it does not scale with
programme size, and a hedging footprint must. A flow proportional to fund AUM cannot
produce an effect identical for a fund at 0.5% of daily volume and one at 570%. Post-
launch attention, index or screener inclusion, or simple noise all fit better.

**For the largest names the test has real power.** MSTY at median dose held 1.27 days
of MSTR turnover. Even a delta change of a few percent of notional at each roll would
be several percent of a day's volume, comfortably above a 2% MDE. The absence is
informative there, not merely inconclusive.

## Honest limitations

- **Daily aggregation.** Hedging spread across a session could be diluted in a daily
  total. The intraday collector now accumulating is the direct answer, and until it
  has depth this null is about daily volume, not about intraday footprint.
- **The dose-permutation falsification did not run.** Permuting dose at name level
  collapsed the regressor and the two-way clustered variance failed to be positive
  definite. It is recorded as not run rather than passed.
- **Roll timing is still inferred, not observed.** Scanning all five weekdays is
  better than assuming Friday, but if the roll is spread across days or keyed to
  expiry cycles rather than weekdays, a weekday design dilutes it.

## What this means for the project

The central mechanism — a scheduled dealer hedging footprint that scales with
programme size — does not appear in daily volume, with adequate power and across
three orders of magnitude of dose. That is the second consecutive test to find no
dose relationship, and the first that was well powered.

The honest position is that the mechanism is now in doubt, not merely unproven. Two
routes remain and they should be pursued in this order:

1. **Intraday.** Accumulate the 5-minute panel and re-run the roll-window test. This
   is the one place a real footprint could hide from a daily test.
2. **Observed roll dates.** The daily holdings series now being collected will show
   exactly when each fund transacts, removing the last inference from the design.

If both come back null, the finding is that a large, fully disclosed, mechanically
scheduled option programme leaves no measurable footprint in its underlying — which
is a publishable result about market absorption, and closer to Brøgger's VIX
conclusion than to the paper originally envisaged.

---

# Positive controls and randomization inference — 2026-08-18

Added because a null is worthless without evidence the design can detect anything.

## Positive controls (same estimator, same panel)

| control | β | t |
|---|---:|---:|
| \|return\| → volume | +10.6806 | +9.40 |
| triple witching × ever_treated | −0.3297 | −4.65 |
| monthly opex × ever_treated | −0.1221 | −3.13 |

The design detects volatility-driven volume and option-expiry effects at |t| = 3 to 9.
It reports the programme dose effect at |t| < 1. The null is a property of the flow,
not of the machinery.

Note the sign on the expiry controls: treated names show *less* relative volume on
expiry days than controls. That is the same clientele composition effect seen
intraday — controls are mega-caps with large index-driven expiry activity — and is not
itself a finding about programmes.

## Randomization inference

Dose permuted across the 25 treated names, 300 draws, re-estimating each time. This
avoids relying on the clustered standard error at all.

```
actual dose-response beta : -0.00348
permutation mean / sd     : -0.00008 / 0.01144
permutation 2.5 / 97.5    : -0.02317 / +0.02011
two-sided permutation p   : 0.773
```

The estimate sits at the 37th percentile of its own null. The permutation sd (0.0114)
is close to the clustered standard error, so the parametric inference was not
materially optimistic.

This replaces the falsification recorded earlier as "did not run".
