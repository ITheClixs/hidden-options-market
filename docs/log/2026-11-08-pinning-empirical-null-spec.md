# The pinning test's size and power on real returns (specification)

Written 2026-11-08, before any of the figures below was computed. It is a diagnostic of
the registered pinning test in [`2026-11-08-pinning-spec.md`](2026-11-08-pinning-spec.md).
That test, its sample and its verdict are unchanged.

## Why

The registered size and power come from independent normal returns. The re-review of
the listed control showed that real returns are not like that. Short-horizon reversal
gives the statistic a non-zero centre when the pin strike is fixed by the close before
expiry. A matched placebo, added after the fact, takes out that term on average. What
is still unknown is how the test behaves on real returns:

- how often it rejects when nothing expires;
- how often it detects pinning that is there.

## Design

- **Placebo dates.** For each event of the registered sample (name, expiry E, pin strike
  K\*), take the sessions E + k for k = ±10, ±12, …, ±40: 32 offsets. Keep a placebo date
  only if it meets all of the following:
  - it is a Monday to Thursday;
  - it is not a FLEX expiry of that name in the report;
  - it lies within the bars;
  - it has the closes the statistic needs.
- **Placebo strike.** On each placebo date, the strike sits at the same signed distance
  from the previous close, in daily standard deviations, as K\* sat from the close before
  E. So K = C(E+k−1) · exp(z · σ(E+k)), where z = ln(K\*/C(E−1)) / σ(E). The registered
  2σ window applies.
- **Statistic.** The registered D, with the registered clustered mean by placebo date.
  This gives one estimate per offset. Splits are handled as in the registered test.

## What is reported

- **The null distribution on real returns.** For each offset: the mean D, its clustered
  t, and whether it rejects at 5%. Summarised by:
  - the mean of the offset means (the centre);
  - their standard deviation, against the registered clustered standard error;
  - the share of offsets rejecting at 5% (the size).
- **The registered estimate against that null.** The share of offsets whose mean is at
  least as far from the centre as the registered estimate is.
- **Power on real returns.** On every offset, a share q of events (5%, 10%, 15%) has its
  placebo-date close pulled halfway to the placebo strike. This is the registered
  alternative, planted in real closes. Power is the share of offsets on which the
  registered test rejects. The pulled close also re-centres the next session's mirror, as
  a real pin would. The seed is fixed.

## Reading

This entry has no hypothesis test. Its figures replace the size and power figures from
normal draws as the description of what the registered test can see. If the size on
real returns is well above 5%, the paper says that the registered p-values are
anti-conservative. If the registered estimate is inside the bulk of the empirical null,
the paper says so.

## What would change this specification

Only a defect found in the code. Any change after a figure has been seen is recorded here
as a dated amendment.

## Result, 2026-11-08

Computed as specified, with no change after the figures were seen.

- **Offsets.** All 32 offsets have an estimate. The median is 1,502 events per offset,
  fewer than the registered 2,643, because placebo dates must fall Monday to Thursday and
  avoid the name's FLEX expiries.
- **Centre of the null:** +0.009σ.
- **Spread across offsets:** 0.032σ. Scaled to the registered sample size, that is about
  0.024σ, against the registered clustered standard error of 0.028σ. So the registered
  standard error is not too small.
- **Size at 5%:** 6.3% (2 of 32 offsets).
- **The registered estimate (−0.029σ):** 22% of offsets lie at least as far from the
  centre.
- **Power on real returns:** 28% when one event in twenty is pulled halfway to the strike,
  75% at one in ten and 97% at one in seven. These match the power at the observed
  standard error (27%, 71%, 97%).

**Reading.** On real returns the registered test is close to its nominal size at FLEX
pin-strike distances, its standard error is adequate, and its power is as reported. The
reversal term that dominates the listed control is small at these distances. The FLEX
null stands as a null with the stated power.
