# Does hidden inventory predict the visible market? — 2026-08-19

The question the project was pointed at:

> Can hidden institutional derivative inventory, observable through clearing, predict
> the future evolution of the visible market?

**Answer, at daily frequency with per-underlying inventory: no.** The finding is a
well-powered null with a placebo that fails identically, which is what makes it a
result rather than an absence of one.

## Design

FLEX positions are negotiated bilaterally and cleared. OCC reports open interest for
activity date $T$, published overnight, so an observer has it on $T+1$. A dealer taking
the other side hedges in the listed market and retains the residual convexity for the
life of the position. If that is material, inventory at $T$ should inform behaviour
from $T+1$.

Timing is enforced, not assumed: every predictor is measured at $T$ or earlier, every
outcome strictly after $T$.

$$y_{i,t+1} = \alpha_i + \delta_t + \beta\,\text{flex}_{i,t} + \text{controls}_{i,t} + \varepsilon$$

Underlying and date fixed effects, errors two-way clustered, controls for trailing
realised volatility at 5 and 22 days, same-day absolute return, and log dollar volume.

Panel: **58,014 underlying-days, 281 underlyings, 231 activity dates**, 2025-09-16 to
2026-08-17.

## Result

| predictor | outcome | β | t | MDE80 |
|---|---|---:|---:|---:|
| inventory innovation | next-day \|return\| | −0.00030 | −1.37 | 0.00062 |
| inventory change | next-day \|return\| | −0.00016 | −0.40 | 0.00115 |
| near-dated share change | next-day \|return\| | +0.00081 | +0.58 | 0.00390 |
| put share | next-day \|return\| | −0.00189 | −1.73 | 0.00307 |
| inventory innovation | next-day return² | −0.00003 | −0.81 | 0.00011 |
| **placebo: future inventory** | next-day \|return\| | **−0.00032** | **−1.37** | 0.00065 |

Longer horizons are weaker still: mean absolute return over the next 3, 5 and 10 days
gives $t = -0.88$, $-0.59$, $-0.12$. Restricting to the top decile of inventory changes
— large creations and extinguishments only — gives $t = -0.71$ next day.

## Why the placebo settles it

The placebo uses inventory dated *after* the outcome it is asked to predict. It cannot
carry information by construction. It returns $\beta = -0.00032$ at $t = -1.37$ against
the genuine predictor's $-0.00030$ at $t = -1.37$ — the same coefficient and the same
statistic to two decimal places.

Whatever associates inventory with volatility runs equally well backwards in time,
which is the signature of a common factor moving both, not of information flowing from
one to the other. Without the placebo the marginal $t = -1.37$, and the $t = -1.95$ it
showed on a smaller panel, would have been reportable as suggestive.

## Power

MDE at 80% power is roughly 0.0006 in absolute return, against a typical daily absolute
return near 0.02 in this cross-section. Relative effects of 3–5% would be detected. The
null bounds the effect below that, and should be stated as a bound rather than as an
absence.

## What is not ruled out

Three things, and they matter.

**Strike-local effects.** Inventory is aggregated to the underlying here. If a dealer's
hedging response is concentrated at the strikes it transacted, aggregation averages it
away. Testing that retrospectively needs historical strike-level listed implied
volatility, which is not obtainable free; it requires forward accumulation.

**Intraday.** Daily bars cannot see a hedging response that completes within a session.

**Option-market outcomes.** The test predicts the underlying. The more natural target is
the listed option surface, since that is where a dealer lays off risk. That test needs
the same historical surface data.

The honest statement is therefore narrow: per-underlying FLEX inventory does not
predict next-day or next-fortnight realised volatility in the underlying, to a
resolution of a few percent, over eleven months.
