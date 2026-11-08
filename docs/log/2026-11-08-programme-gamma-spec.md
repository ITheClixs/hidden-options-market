# A signed gamma test: the option-income programme names (specification)

Written 2026-11-08, before any estimate on this subsample was computed. It is a new test,
separate from the registered gamma test of
[`2026-11-08-gamma-predictive-spec.md`](2026-11-08-gamma-predictive-spec.md), which stays as it is.

## Why

The registered predictor is unsigned. Dealers who are long gamma would dampen moves and
dealers who are short gamma would amplify them, so a pooled slope can be zero while both
effects are present (methodology review round 2, W3). A subsample where the sign of the
book is known in advance can be tested one-sided.

The collector's universe file (`configs/universe.json`, in the repository's first commit
of 16 August 2026, when collection began) fixes 34 single names, chosen for the
option-income programmes written on them and not for anything in the FLEX data. A synthetic covered-call fund
in these names holds a long call and a short put at one strike, which is synthetic stock,
and writes a call above it. Pair-netting removes the same-strike pair, so what remains of
the fund's book is the written call. The dealer on the other side is long it, and so long
gamma. Holdings disclosed by funds of this kind (Section 5.2 of the paper) are mostly such
pairs, which is why the netted remainder is the part that carries a sign.

The hypothesis is therefore that hedging by dealers who are long this gamma dampens
next-day moves: β < 0.

## Test

- **Sample.** The rows of the registered gamma test's sample (outcome, controls and
  `x_net` present) whose symbol is one of the 34 programme single names in
  `configs/universe.json` (`treated_single_name`). Names with no rows in the sample drop out;
  the number left is reported.
- **Predictor.** The registered `x_net`, standardised as registered on the full sample,
  so β is in the registered units: per standard deviation of the full sample.
- **Regression.** `abs_ret_next` on `x_net` and the registered controls, with underlying
  and date fixed effects, on the subsample alone.
- **H (one-sided).** β < 0 at α = 0.05.
- **Inference.** With about 34 clusters, the clustered t is not reliable. The p-value is
  from a wild cluster restricted bootstrap: clustered by underlying, with Rademacher weights,
  the null β = 0 imposed, and 9,999 draws at a fixed seed. The statistic is the t-ratio with
  standard errors clustered one way by underlying. The fixed effects are re-applied to every
  bootstrap outcome. The two-way clustered t is reported beside it, as in the registered test.
- **MDE.** At 80% power, one-sided α = 0.05: (1.645 + 0.842) times the one-way clustered
  standard error. It is reported per standard deviation and as a share of mean |r| on the
  subsample.

This is the only test of record in this entry. It is not pooled with the registered H1
and H2 for Holm's adjustment; the paper reports it as a separate, sign-identified test.

## Descriptive only

- The same regression on the 27 control single names in the universe file. They were chosen
  as liquid names without such programmes, and no sign is predicted for them.
- The subsample estimate priced at T−1 (`x_pre` of
  [`2026-11-08-gamma-timing-spec.md`](2026-11-08-gamma-timing-spec.md)).

## What counts as what

- The bootstrap p is below 0.05 and β < 0: a sign-identified finding. Hidden gamma held
  long by dealers in programme names predicts calmer next days. It is stated with its
  magnitude against the MDE.
- Otherwise, if the MDE is below 2% of mean |r| on the subsample: a bounded null on the
  signed channel, stated with that bound.
- Otherwise: inconclusive at this sample size.
- A positive estimate is not a finding under a one-sided test. Its t is reported.

## What would change this specification

Only a defect found in the code. Any change after an estimate has been seen is recorded
here as a dated amendment, with the estimate it changed.

## Amendment, 2026-11-08, after the outcome was read: the assumption fails

**Outcome under the rule above.** β = −7.29 bp per SD, t −0.82, wild cluster bootstrap
p 0.22. The MDE is 9.4% of mean |r|, so the test is inconclusive.

**A check of the identifying assumption, added after that outcome** (result
`programme_book`). The collector keeps the daily holdings of 24 programme funds. Over the
45 dates they cover up to the panel end:

- **Written calls are listed.** 0% of the funds' written-call contracts are FLEX.
- **Short puts are FLEX.** 100% of their short puts are FLEX, and 54% of those sit
  opposite a FLEX long call at the same strike, which pair-netting removes.
- **The funds hold little of the netted book.** Their netted FLEX book is 4.5% of the
  netted FLEX open interest in the 34 names, and that open interest is 79% calls.

So "the netted remainder is the funds' written calls" is false for the funds the data
show. The test is not sign-identified, and the paper reports that.

The holdings come from one fund family, and other programmes' FLEX use may differ.
Nothing here can recover the sign of the netted book in these names.
