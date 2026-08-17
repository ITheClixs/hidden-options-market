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
