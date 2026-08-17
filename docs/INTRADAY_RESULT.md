# Intraday Test — 2026-08-18

The remaining place a hedging footprint could hide from a daily test.

Data: 60 sessions of 5-minute bars, 52 names, 13 half-hour bins, 40,560 bin
observations. This is the full free intraday depth available; it cannot be extended
backwards, only accumulated forward.

## Design problem, and how it was handled

Every programme in the sample launched before this 60-day window opens, so there is no
pre/post variation inside it and the Stage 1 difference-in-differences collapses.

The first attempt identified from dose × time-of-day across names, with name and
date × bin fixed effects. It produced a strong, monotone pattern:

| bin | β | t |
|---|---:|---:|
| 09:30 | +0.0351 | +1.35 |
| 12:00 | ref | |
| 15:00 | −0.0424 | **−3.52** |
| 15:30 | −0.0951 | **−3.20** |

Higher-dose names are open-weighted and close-underweighted, monotonically across the
session, with two coefficients past |t| > 3.

**This is not the mechanism, and it is the wrong sign for it.** Hedging predicts
*more* close volume in high-dose names, not less. The pattern is a confound: dose is
mechanically correlated with what kind of stock the underlying is. The high-dose names
are MSTR, COIN, HOOD, SMCI, MARA — retail-heavy and open-weighted. The low-dose names
are AAPL, MSFT, NVDA, META — mega-caps with large closing auctions. With dose
time-invariant inside the window, dose × bin cannot be separated from any name
characteristic × bin. The specification is not identified, and the result is reported
here only because it looks convincing and is not.

## The identified test

Restricting to the within-name contrast removes it. Outcome is the logit share of the
day's dollar volume falling in the final hour, with name and date fixed effects, so
each name's average intraday shape is absorbed and identification comes from whether a
name tilts *more* to the close on some weekdays than others, scaled by dose.

| weekday | β | t | MDE80 |
|---|---:|---:|---:|
| Mon | −0.0137 | −1.44 | 0.027 |
| Tue | +0.0041 | +0.37 | 0.031 |
| Wed | +0.0272 | +2.19 | 0.035 |
| Thu | +0.0018 | +0.16 | 0.032 |
| Fri | −0.0209 | −1.30 | 0.046 |

**Null on every day.** Wednesday is nominally the largest at t = 2.19, but this is one
of five tests and the Bonferroni threshold is about 2.8. Nothing survives.

Power is reasonable rather than excellent: at a mean close-hour share of 0.237, an MDE
of 0.03 in logit units is about 0.54 percentage points of daily volume per log unit of
dose, so roughly 3.8 points across the sample's full dose range.

## Where the evidence now stands

Three tests, none supporting the mechanism:

| test | identified? | result |
|---|---|---|
| Daily volume DiD, static dose (v1) | yes | no dose response, underpowered top cell |
| Daily volume DiD, N-PORT dose, weekday scan (v2) | yes | **precise null**, MDE 2% per log unit |
| Intraday close tilt, within-name | yes | null on all five weekdays |
| Intraday dose × time-of-day | **no** | strong pattern, confounded by clientele |

The two well-identified, adequately powered tests both find nothing, and the only
striking result came from the one specification that is not identified.

## Honest limitations

- 60 sessions is short. The panel grows daily and this should be re-run quarterly.
- Roll timing is still inferred from weekday rather than observed. The holdings series
  now accumulating will fix this, and it is the last inference in the design.
- The close-hour window is a guess at where hedging would concentrate. A dealer could
  hedge continuously, which would leave no tilt while still moving prices.

## Assessment

The mechanism as originally framed — a scheduled dealer hedging footprint scaling with
programme size — is not visible in daily volume, and is not visible in the intraday
volume shape once the design is identified. Both tests had enough power to see effects
well below what a programme holding several times its underlying's daily turnover
should generate.

This does not prove absence. It does mean the project should stop looking for the
footprint in volume and decide between two honest paths: accumulate intraday depth and
observed roll dates for one more attempt, or reframe around the finding that a large,
fully disclosed, mechanically scheduled option programme is absorbed without a
detectable trace.
