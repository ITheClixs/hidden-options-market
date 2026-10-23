# Power and Data Limits — 2026-08-17

Written after establishing what price data is actually obtainable for free. It
corrects a stated figure in the research plan and changes the pilot design.

## Correction to the plan

The plan's §25 asserts that the minimum detectable roll-window effect at 80% power is
"≈ 2.5 bp", and sets a pass criterion of "|abnormal roll-window return| ≥ 4 bp with
t ≥ 3.0". **That figure was asserted, not derived, and it is wrong by roughly an order
of magnitude.** The pass criterion built on it is not achievable with any data
reachable here.

## What free price history actually exists

| interval | depth | source |
|---|---|---|
| daily | 2 years (500 bars) | Yahoo chart API, free, no auth |
| 5-minute | **60 days** | same |
| 1-minute | **7 days** | same |

Alpaca would extend this but needs credentials that are not configured, and its free
tier gives indicative rather than true quotes. Stooq is behind a JavaScript challenge.
So: **two years of intraday US equity history is not freely obtainable.** Intraday
depth must be accumulated forward, exactly like the option chains.

## Power arithmetic

MDE at 80% power, two-sided 5%, using MDE = 2.80 × σ / √N.

| design | σ | N | MDE |
|---|---:|---:|---:|
| daily close-to-close, single name | 6.0% | 2,500 | **34 bp** |
| daily, peer-adjusted | 4.0% | 2,500 | **22 bp** |
| 30-min roll window, 60d of free intraday | 1.66% | 300 | **27 bp** |
| 30-min roll window, 1 year accumulated | 1.66% | 2,600 | **9 bp** |
| 30-min window, top-dose tercile, 1 year | 1.66% | 870 | **16 bp** |

Events required at a 30-minute horizon:

| effect | events needed |
|---:|---:|
| 4 bp | 13,500 |
| 10 bp | 2,160 |
| 20 bp | 540 |
| 40 bp | 135 |

## What this means

**The 3–8 bp effect described as a "normal" outcome in the plan is not detectable with
free data on any horizon available today.** Detecting 4 bp needs ~13,500 clean
roll events; at roughly 50 single-name funds rolling weekly that is five years of
accumulation.

Three consequences.

1. **The pilot cannot be a small-effect test.** It can credibly test for an effect of
   **≥ 20 bp**, concentrated in the top dose tercile. That is the honest target, and a
   null must be reported as "bounded below ~20 bp", never as "no effect".
2. **The intraday window is where the test lives, but the 60-day free window is too
   short today** — it gives the same MDE as two years of daily data. Its value grows
   quickly with accumulation: one year of collected intraday reaches ~9 bp.
3. **An intraday underlying collector should be added to the daily capture now.** It is
   the single change that most improves the eventual test, and every day of delay is a
   permanently missing day, exactly as with the chains.

## Is the project still viable?

Yes, but the framing shifts. The plan leant on a small average effect across all
programmes. The achievable test is a **large effect in the high-dose tail** — names
where fund notional is a material share of the underlying's option and share volume
(MSTR, COIN, HOOD-type names rather than NVDA or AAPL). That is also where the theory
predicts the largest λ₀, so the design and the power constraint point the same way.

What genuinely weakens is the *absorption curve*: estimating three parameters
(λ₀, half-life, floor) per programme needs far more precision than a single pooled
mean. That should be treated as the paper's second stage, gated on the pilot finding a
detectable top-dose effect at all, rather than assumed feasible from the outset.
