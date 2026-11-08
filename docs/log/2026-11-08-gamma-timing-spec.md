# Gamma test: predetermined inputs, an implied-volatility control, and the lead (specification)

Written 2026-11-08, before any of the estimates below was computed. It adds robustness
rows to the gamma test of [`2026-11-08-gamma-predictive-spec.md`](2026-11-08-gamma-predictive-spec.md)
and changes nothing in that test of record: its sample, H1, H2, Holm adjustment and verdict stay as they are.

## Why

A review of the gamma test (methodology round 2, W2) points out that the registered predictor
`x_net` at activity date T uses three inputs that each move with volatility:

- the spot, the close of T;
- each series' implied volatility at T, where gamma near the money falls as volatility rises;
- the dollar volume of the twenty sessions ending at T.

The controls (|r_T|, rv5, rv22) take out part of that link, not all of it. Implied
volatility forecasts realised volatility beyond them and is not a control. The link pushes
β negative, so it could hide amplification or manufacture dampening. The paper also calls
the large negative lead coefficient "mechanical" without showing it.

## Rows, all descriptive robustness, none a test of record

All rows use the regression, controls, fixed effects, clustering, outcome (`abs_ret_next`),
standardisation (winsorised 1/99, divided by the standard deviation on the sample) and the
coverage rule (at least half of the underlying's live FLEX open interest priced) of the
registered test.

- **R1, predetermined pricing.** Open interest of report T, pair-netted as registered,
  each series priced with the gamma and spot it had at T−1. That gamma comes from the
  series' own mark at T−1, inside a validated cell. A series not priced at T−1 counts as
  unpriced, and coverage is recomputed on that basis. Scaled by the mean dollar volume of
  the twenty sessions ending at T−1. Every input except open interest is fixed before T.
  Open interest of report T is what the registered test uses.
- **R2, implied-volatility control.** The registered `x_net`, with one more control: the
  log of the underlying's open-interest-weighted mean implied volatility at T over its
  priced FLEX series. It is known at T's close.
- **R3, both.** R1's predictor with R2's control.
- **R4, the lead at fixed pricing.** Open interest of report T+2 (the registered lead's
  date), each series priced with its gamma and spot at T, scaled by dollar volume ending at
  T. Series not priced at T count as unpriced. Only open interest moves between T and T+2.

Each row reports β per standard deviation, its clustered t and p, and its MDE at 80% power.
Each is set next to the registered H1 and lead rows.

## What would count as what

These rows are read against the following, fixed now.

- **R1 to R3.**
  - The registered H1 does not reject. If none of R1 to R3 rejects at α = 0.05 (two-sided,
    clustered), the bounded null stands with its mechanical link checked.
  - If any of them rejects, the paper says that the null does not survive predetermined
    inputs, and gives the sign. That outcome is a robustness failure, not a finding: the
    test of record is unchanged.
- **R4.**
  - If |t| < 2, the lead's large negative coefficient comes from re-pricing: spot, IV and
    ADV moving with volatility. The paper then says so as a result.
  - If R4 stays below −2, the "mechanical" reading is not supported, since open interest
    itself falls after volatile days. The paper then states that instead.

## Data rules

- A series is the same across dates if root, expiry, right and strike agree. Pair-netting
  is done within each report date, as registered.
- If an underlying has a split ex-date between the pricing date and the open-interest
  date, its underlying-day is dropped from R1 and R4. Its strikes and spot would be on
  different bases.
- Spots are on each session's own basis (`collect.splits.read_bars`), as in the
  registered test. Returns and dollar volume are on the adjusted basis.

## What would change this specification

Only a defect found in the code. Any change after an estimate has been seen is recorded
here as a dated amendment, with the estimate it changed.
