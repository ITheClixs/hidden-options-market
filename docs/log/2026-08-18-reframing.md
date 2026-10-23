# Reframing — 2026-08-18

The original question asked how fast markets absorb a newly created, fully disclosed
mechanical option flow, and expected to measure an absorption curve with a positive
floor. Four tests have now looked for the footprint that curve presupposes. It is not
there. This records what the project becomes.

## What the evidence supports

| test | identified | result |
|---|---|---|
| Daily volume DiD, N-PORT dose, weekday scan | yes | dose response within ±0.006, MDE 0.020 per log unit |
| Intraday close-hour tilt, within-name | yes | null on all five weekdays |
| Randomization inference on dose | yes | p = 0.773, 37th percentile of the null |
| Intraday dose × time-of-day | **no** | strong pattern, confounded by clientele |

And, critically, the same estimator on the same panel detects known effects:

| positive control | β | t |
|---|---:|---:|
| \|return\| → volume | +10.68 | +9.40 |
| triple witching × treated | −0.330 | −4.65 |
| monthly opex × treated | −0.122 | −3.13 |

A design that sees option-expiry and volatility effects at |t| = 3 to 9, and sees the
programme dose effect at |t| < 1, is not a design that is simply too blunt.

## The revised thesis

> A cohort of option-writing programmes grew to hold, in the largest case, 5.7 times
> its underlying's entire daily dollar turnover. Their positions, strikes, expiries and
> roll calendars are public daily. Their trades are mechanical and uninformed. Yet
> across three orders of magnitude of programme size, they leave no measurable
> footprint in the underlying's volume — daily or intraday — while the same estimator
> detects option-expiry effects in the same panel.

That is a statement about market absorption capacity, and it is close to Brøgger's
conclusion for leveraged VIX products: predictable uninformed flow is absorbed by
liquidity provision that organises around it. The contribution here is that the flow
is far larger relative to its market, disclosed in far more detail, and the bound is
tight rather than an unrejected null.

## What the paper contributes

**1. A free, reproducible measurement of disclosed derivative positioning.**
Fund holdings give the intended position; OCC series open interest gives the realised
one; the two reconcile to the contract on 8 of 11 attributed legs. The FLEX synthetic
leg, which was expected to be invisible without paid data, is identifiable from its
cent-offset strike and one-sided open interest. Every input is free. This survives
regardless of the hypothesis and is the piece most likely to be reused.

**2. A tight bound where the literature has assumptions.**
The dealer-gamma literature and its practitioner counterpart assume hedging flows move
underlyings. This measures one large, cleanly identified case and bounds the volume
footprint near zero.

**3. A worked example of a confound that looks like a result.**
The unidentified intraday specification produced a monotone profile with |t| > 3 and
the wrong sign for the mechanism. It is reported alongside its refutation. Given how
much of this literature rests on cross-sectional dose sorts, that is worth documenting.

## Honest assessment of the ceiling

This is a smaller paper than the one planned. It is a bound and a method, not a
discovered phenomenon, and it produces no alpha. It will not carry the citation
profile sketched in the original plan, and the "absorption curve with a positive floor"
framing should be dropped rather than salvaged — there is no curve to fit if the
level is zero.

What it is: defensible, well identified, honestly powered, fully reproducible from
free data, and true. Suitable for a focused empirical note rather than a flagship.

## What continues, at no cost

The collectors run daily and require nothing. They accumulate the two things that
could still change the answer:

1. **Intraday depth.** 60 sessions today; a year reaches an MDE near 9 bp on returns.
2. **Observed roll dates.** The holdings series will show exactly when each fund
   transacts, removing the last inference in the design.

Re-run both tests quarterly. If a footprint appears with observed roll dates and a
year of intraday, the original question is live again. If not, the bound tightens and
the paper gets stronger as a null.

## Immediate next steps

1. Freeze the current results as a pre-results note with the positive controls and the
   randomization inference included — these are what make the null credible.
2. Extend the measurement layer to the buffer/defined-outcome issuers already visible
   in the unattributed OCC legs, since the method section is the durable contribution.
3. Leave the return tests unrun. With no volume footprint and an MDE near 20 bp, a
   return test now would be underpowered and uninformative.
