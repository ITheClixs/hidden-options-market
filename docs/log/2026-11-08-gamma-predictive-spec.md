# Hidden gamma and next-day volatility — specification

**Written 2026-11-08, before any gamma-based estimate was computed.** The panel has been
seen in other forms: the gross-inventory null (Section 7 of the paper) and the hidden-gamma
measurement of 2026-11-07. This fixes the definitions, sample, tests and thresholds of
*this* test before the code that runs it exists.

## Why

The predictive test in the paper regresses next-day volatility on log open interest. A
review panel (2026-11-07) agreed that this measures contracts, not convexity. Most FLEX
open interest is same-strike pairs, forwards with no gamma, and the hedging channel
the paper invokes runs through gamma near spot. This test puts gamma in place of
contracts, and nets pairs out.

## Sample

- Activity dates from the first FLEX report to `PANEL_END` (2026-10-22). Underlyings are
  those of the paper's predictive sample: equity and ETF names with daily bars and at
  least 40 activity dates. Index products have no bars and stay out, as before.
- Each report for activity date T is joined to outcomes from `available_at(T)`, the next
  activity date, through `predict.panel.join_outcomes`. The lag is enforced as before.

## Gamma at T

For each FLEX series on T:
- Pair-netting first: at each root, expiry and strike, call and put open interest are
  matched and only the excess counts (`hidden_gamma.pair_netted`).
- Volatility from the series' own mark, inverted as `positions_result.priced_rows`
  inverts it. Kept only where the inversion succeeds inside a validated cell
  (`implied_validation` domain). The hidden-gamma result found gamma from marks
  within 2% of gamma from the listed surface where both exist.
- Spot: the close of T, the spot the positions result uses.
- Dollar gamma: Γ · n · 100 · S² · 0.01, the change in dollar delta for a 1% move.

Per underlying and T: netted dollar gamma `g_net`, gross `g_gross`, vendor-signed
`g_signed` (calls +, puts −, gross), and `coverage`, the share of the underlying's FLEX
open interest that has a validated volatility.

## Predictors

- **Primary:** `x_net` = g_net / ADV, where ADV is the mean dollar volume of the 20 sessions
  ending at T. This is the dollar delta a dealer holding the book would trade for a 1%
  move, as a fraction of a day's dollar volume. It is winsorised at the 1st and 99th
  percentiles of the pooled sample and standardised to unit standard deviation.
- **Secondary:** the same with g_gross (`x_gross`) and with g_signed (`x_signed`).
- An underlying-day enters only with coverage ≥ 0.5. Below that, gamma is mostly
  unpriced and the predictor is set missing, not zero. An underlying-day with no FLEX
  open interest at all has x = 0.

## Estimation

As in the paper: y_{i,t+1} = α_i + δ_t + β x_{i,t} + γ′ controls_{i,t} + ε. Controls are
rv5, rv22, abs_ret and log_dv. Errors are two-way clustered by underlying and date, with
the small-cluster correction and t critical values on the smaller cluster count.

- **Primary outcome:** `abs_ret_next`.
- **Secondary outcomes:** `oc_abs_next`, and next-session log Parkinson range,
  log(high/low).

## Tests and thresholds

- **H1 (primary).** β on `x_net` for `abs_ret_next` is different from zero: two-sided,
  α = 0.05, clustered t. The sign is not predicted. Dealers short calls to option-income
  funds would be long gamma, so β < 0; buffer structures can put them on either side.
  The estimate is reported with its MDE at 80% power, per standard deviation of `x_net`
  and as a share of mean |r|.
- **Permutation.** Within-date shuffles of `x_net` (1,000 draws, seed fixed in code), as
  the paper's permutation test. Reported beside the clustered p-value.
- **H2 (heterogeneity).** The same regression with `x_net` interacted with an indicator for
  the top tercile of each underlying's median `x_net`. Two-sided, α = 0.05.
- **Multiple testing.** H1 and H2 are the two tests of record, with Holm's adjustment
  across them. Everything else (secondary predictors, secondary outcomes, the lead
  below) is descriptive and labelled so.
- **Lead.** `x_net` dated two activity dates later. It is reported as a test of reverse
  flow (volatility moving later FLEX gamma), not as a falsification test. The review
  noted that the lead includes the session of the outcome.

## What counts as a finding

- H1 rejects after Holm: hidden gamma predicts next-day volatility, sign as estimated.
- H1 does not reject and the MDE per SD is below 2% of mean |r|: a bounded null on the
  right measure, stated with that bound.
- Otherwise: inconclusive at this sample size, stated as such.

## What would change this specification

Only a defect found in the code. Any change after an estimate has been seen is recorded
here as a dated amendment, with the estimate it changed.

## Amendment, 2026-11-08, after the estimate was seen: split adjustment

**A defect in the price data, found in review.** The provider restates a symbol's whole
bar history after a split, so stored bars were split-adjusted as of the fetch date while
OCC strikes are not. Before any split, an equity's price was off by the split's ratio
when compared with a strike: NFLX near 93 on 1 April 2025, against FLEX strikes between
855 and 1,120. Gamma at those strikes was priced against the wrong spot, and dollar
volume in the denominator was unaffected only because price and volume move inversely.
Bars are now put back on each session's basis (`collect/splits.py`, `read_bars`) before
any price meets a strike. Nothing in the specification above changes; the estimates do.

| | before | after |
|---|---|---|
| H1 β (bp per SD) | −0.38 | −0.60 |
| H1 t | −0.53 | −0.79 |
| H1 permutation p | 0.30 | 0.092 |
| H1 Holm p | 1.00 | 0.86 |
| MDE (bp per SD; share of mean \|r\|) | 2.00; 1.0% | 2.13; 1.1% |
| H2 t | 0.31 | 0.11 |
| Lead t | −4.86 | −4.93 |
| Underlying-days | 347,687 | 353,972 |

The verdict under the rule above is unchanged: a bounded null.
