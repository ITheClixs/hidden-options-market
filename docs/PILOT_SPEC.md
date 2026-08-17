# Pilot Specification — Stage 1

**Written 2026-08-17, before any result was computed.** Thresholds are fixed here so
that the outcome cannot be rationalised after the fact.

Supersedes §25 of the research plan, whose pass criterion (4 bp, t ≥ 3.0) was built on
an undderived power figure and is unachievable — see `POWER_AND_DATA_LIMITS.md`.

## What changed and why

The original pilot tested **returns**. That was the wrong first variable.

The mechanism is that a dealer, having taken the other side of a fund's option
programme, must delta-hedge in the underlying on a schedule. If that is real, it
implies two things in order:

1. **A volume footprint.** Hundreds of millions of dollars of scheduled hedging cannot
   be transacted invisibly.
2. **A price effect.** Only if the flow is large relative to available liquidity.

The second is what the paper is about, but the first is logically prior and far better
powered. Residual log-volume noise is roughly 0.35–0.5, against 4–6% for daily returns,
so the volume test detects a proportionally much smaller footprint. If there is no
volume trace, there is certainly no price effect, and the project is in trouble
regardless of how the return test comes out.

So Stage 1 tests volume. Stage 2 tests returns, gated on Stage 1.

## Stage 1 design

**Identification: difference-in-differences around fund launch.**

Before a fund launches on underlying *i*, there is no programme and no hedging flow.
After launch there is, concentrated on option expiry dates. This gives a within-name
before/after contrast and a treated-versus-control contrast simultaneously.

- **Treated**: underlyings with a dedicated single-name option-income fund, from the
  registry. Launch dates taken from each fund's first trade date.
- **Control**: liquid names with no such fund over the sample, plus not-yet-treated
  names as the cleanest comparison group.
- **Sample**: 2 years of daily bars, free, available now.

**Outcome.** `y_{i,t} = log(dollar volume)`, residualised on name fixed effects, date
fixed effects, and `|return|` (volume mechanically tracks volatility, and failing to
absorb that would manufacture a result).

**Estimand.** The coefficient on `treated_i × post_i,t × expiry_t`, where `expiry_t`
marks standard option expiry Fridays. Day and name fixed effects absorb market-wide
and name-level variation, so the coefficient is identified off the *timing* of
excess volume within treated names after launch.

**Dose.** `fund AUM / underlying dollar ADV`, in terciles. The mechanism predicts
monotonicity; a uniform effect across dose terciles would suggest something other than
hedging.

## Pass / fail, fixed in advance

| outcome | reading |
|---|---|
| **Pass** | Top dose tercile shows ≥ 5% abnormal expiry-day volume post-launch, t ≥ 3.0 with errors clustered by date **and** by name, **and** the effect is monotone across dose terciles. |
| **Ambiguous** | Effect present but not monotone in dose, or significant only under one clustering. Investigate before proceeding; do not treat as a pass. |
| **Fail** | No effect in the top dose tercile, with the confidence interval excluding 5%. |

A fail must be reported as *bounded below the achieved MDE*, never as "no effect".
The MDE is to be computed and reported alongside the estimate whatever the result.

Expected power: with residual log-volume sd ≈ 0.4 and roughly 2,500 treated
name-expiry-days, SE ≈ 0.8%, giving an MDE near 2%. The 5% threshold therefore sits
comfortably inside detectable range, which is the point of testing volume rather than
returns.

## Falsification, run as part of Stage 1 rather than after

- **Placebo dates.** Shift the expiry flag by one week. The effect must vanish.
- **Placebo names.** Assign treated launch dates to matched control names. Must vanish.
- **Pre-trend.** Estimate the effect on the 12 months before launch. Must be flat; a
  pre-trend invalidates the design rather than qualifying it.
- **Dose randomisation.** Permute dose across treated names. Monotonicity must vanish.

## Stage 2, gated

Only if Stage 1 passes. Tests the return effect in the top dose tercile, where the
achievable MDE is roughly 20 bp. Runs on intraday data as it accumulates; the
60-day window available today is too short to be decisive on its own.

## Honest statement of what Stage 1 cannot establish

A volume footprint shows the hedging happens. It does **not** show the hedging moves
prices, and it is fully consistent with a competitive market absorbing the flow at no
cost — which is Brøgger's finding for VIX products and a live possibility here. Stage 1
is a gate on continuing, not evidence for the hypothesis.
