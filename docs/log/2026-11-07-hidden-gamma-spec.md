# Hidden gamma — specification

**Written 2026-11-07, before any gamma figure was computed.** This fixes definitions, the
sample and what is reported before the code that computes them exists. The panel itself
has been seen in other forms (open interest, value, the predictive null), so this is a
specification fixed before *these* numbers, not before the data.

## Question

Dealer-gamma figures in public use ("gamma exposure", GEX) are built from listed option
chains. FLEX series are not in those chains. For the underlyings whose chains we hold,
how much option gamma does a listed-only calculation leave out, and where is it?

This is a measurement question. Open interest does not say who is long, so nothing here
is a dealer *position*; the figures are gamma *notional* under stated attribution rules.

## Sample

- Underlyings: the symbols with stored Cboe chains (equity, ETF and the three index
  products), settlements from the first chain settlement to `PANEL_END` (2026-10-22),
  the same end as every other result.
- Each settlement D pairs the FLEX report for activity date D with the listed open
  interest of settlement D and the quotes and implied volatilities of session D, dated as
  `hidden_share_data.priced_chains` dates them.
- Series expiring on or before D are out on both sides; adjusted-deliverable classes are
  out on both sides (as in `value_share`).

## Definitions

Spot S is the chain's underlying price for session D. Time to expiry τ is calendar days
to expiry over 365. Rate 0.04 and zero carry, the values the rest of the paper uses.

- **Gamma.** Black–Scholes gamma Γ(S, K, τ, σ), computed by us from σ for listed and FLEX
  series alike. The chain's own `gamma` column is not used: it is rounded to four
  decimals, which sets index-option gamma to zero.
- **Volatility.** Listed series: the chain's implied volatility. FLEX series: the listed
  surface of the same underlying and session, read at the FLEX strike and expiry:
  out-of-the-money listed quotes (calls above spot, puts below), linear in log-moneyness
  within an expiry with flat extrapolation beyond the outermost strikes, then linear in
  total variance σ²τ between the two listed expiries that bracket the FLEX expiry, flat in
  σ beyond the first and last. Robustness: σ from inverting the FLEX mark itself, on the
  validated domain of `implied.validated_domain` only.
- **Dollar gamma** of a line with open interest n: Γ · n · 100 · S² · 0.01, the change in
  dollar delta for a 1% move in the underlying.
- **Attribution rules for FLEX** (both reported, neither privileged):
  - *gross*: every contract counts at full weight;
  - *pair-netted*: at each (root, expiry, strike), the call and put open interest are
    matched and only |n_call − n_put| counts. A long call and short put at one strike is
    a forward with no gamma, which is what conversions, reversals and boxes are. A
    straddle would be understated by this rule, so pair-netted is a floor for
    conversion-like books, not a bound in general.
- **Listed comparator**: gross dollar gamma of listed series, which is what an unsigned
  listed-only total measures. A vendor-style signed figure (calls +, puts −) is reported
  as a secondary view for both sides, labelled as that convention.

## What is reported

1. Per underlying-settlement: listed dollar gamma, FLEX gross and pair-netted dollar
   gamma, and the FLEX share of the total, FLEX / (FLEX + listed), under each rule.
2. Across underlyings: the median over settlements of each underlying's share; the
   number of underlyings whose median share is at least 5%, 10% and 25%; split by the
   universe groups (programme vs control) the paper already uses.
3. Where it sits: the share of FLEX dollar gamma by days to expiry (≤ 7, 8–30, 31–90,
   > 90) and by moneyness bucket.
4. Sensitivity: the shares with σ from the FLEX marks on the validated domain; and the
   coverage, i.e. the share of FLEX open interest whose σ came from interpolation inside
   the listed surface rather than flat extrapolation.

## Expectations stated in advance

- FLEX value is mostly deep-in-the-money pairs, so pair-netting should remove most FLEX
  gamma notional. Expected: the pair-netted share is well below the gross share.
- Programme names (option-income underlyings) should carry larger shares than controls.
- Neither expectation is a pass/fail test. Whatever the figures are, they are reported.

## What would change this specification

Only a defect found in the code (a test failing, a unit wrong). Any change after a figure
has been seen is recorded here as a dated amendment, with the figure it changed.

## Amendment, 2026-11-07 (same day)

**What was seen first.** A trial run on the local captures, before any result file existed,
gave per-underlying median shares of 0.179 (gross) and 0.014 (pair-netted, FLEX side only),
over 71 underlyings and 46 settlements.

**What changed.** A methodology review pointed out that netting only the FLEX side compares a
netted numerator with a gross denominator: listed books hold conversions too. The listed
side is now also pair-netted by the same rule, and a third share is added:
`share_netted_both` = FLEX netted / (FLEX netted + listed netted). The two shares defined
above are unchanged and still reported; the new one is added beside them, not in place of
either. No threshold, filter or sample was changed.
