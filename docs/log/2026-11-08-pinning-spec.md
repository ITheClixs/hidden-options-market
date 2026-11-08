# Pinning at hidden strikes — specification

**Written 2026-11-08, before any expiry-date outcome was computed.** The event counts and
the power below come from the event structure (strikes, open interest, closes up to the
session before expiry) and from simulated returns. No close on an expiry date, or on a
pseudo-expiry date, has been read.

## Question

Do stocks close nearer to large FLEX strikes on the day those FLEX options expire?
Ni, Pearson and Poteshman (2005) find that stocks with listed options cluster at strikes on expiration
dates, and that the hedge rebalancing of option market makers who are net long gamma can
produce this, as Avellaneda and Lipkin (2003) model. FLEX strikes are not in the listed chain,
so a pinning effect at them would be invisible to listed-only work. It would also be an
effect of the hidden book in particular.

## Identification: FLEX-only expiries

Listed single-stock options expire on Fridays, or on the Thursday before a Friday
holiday. A few names also list Monday-to-Thursday weeklies. On a Monday-to-Thursday date
in a name without them, the only options expiring are FLEX. Pinning there cannot come
from listed open interest expiring the same day.

- **Underlyings.** Equity-class FLEX underlyings with daily bars, excluding the
  adjusted-deliverable roots. Also excluded is any name with a listed non-Friday expiry
  that is not a holiday shift, in OCC's census or in a stored Cboe chain: 31 names in the
  census, including SPY, QQQ, IWM, AAPL, MSFT, NVDA, TSLA, AMZN, META, GOOGL, AVGO, AMD,
  MU and INTC.
- **Dates.** The expiry date E is a trading day (SPY bars give the calendar), Monday to
  Thursday, and not a Thursday followed by a Friday holiday.
- **The expiring book.** Series expiring on E, read from the report of the session
  immediately before E. A series absent from that report is not counted.
- **The pin strike K\*.** The strike with the most expiring FLEX open interest, calls and
  puts summed across roots. It must carry at least 100 contracts and satisfy
  |ln(K\*/C₋₁)| ≤ 2σ. Here C₋₁ is the close of the session before E, and σ is the standard
  deviation of daily log returns over the 60 sessions ending there (at least 40 needed).
- **Bars** must exist for E and for the six sessions before it.

This leaves 2,383 events on 330 expiry dates in 499 underlyings, with a median K\* open
interest of 1,133 contracts.

## Outcome and statistic

For a date d with the previous close C_{d−1}, the mirror strike is K′ = C_{d−1}²/K\*. It
is as far from the previous close as K\*, on the other side. Closeness to a strike is
measured in σ units, capped at 2:

    s(d) = min(|ln(C_d/K′)|/σ, 2) − min(|ln(C_d/K*)|/σ, 2)

s is positive when the close is nearer K\* than its mirror.

- **Pseudo-expiries.** Closes cluster at round prices, and K\* is often round while K′ is
  not. So the same statistic is computed on the five sessions d = E−6, …, E−2 before
  expiry, with K\* held fixed and each mirror taken from that date's previous close.
- **Per-event statistic:** D = s(E) − mean over the five pseudo-dates of s(d). An
  attraction to K\* that is not specific to its expiry, round-number clustering included,
  cancels.

## Tests

- **H1 (primary).** The mean of D across events is different from zero: two-sided,
  α = 0.05, errors clustered by expiry date, t critical values with G − 1 degrees of
  freedom (G expiry dates). The predicted sign is positive (pinning). A date-level
  sign-flip randomisation test (10,000 draws, seed fixed in code) is reported beside it.
- **H2 (size).** The difference in mean D between the top and bottom terciles of book
  size, two-sided, α = 0.05. Book size is K\* open interest × 100 over the mean share
  volume of the 20 sessions ending before E. The predicted sign is positive.
- **Multiple testing.** H1 and H2 are the tests of record, with Holm's adjustment across
  them.
- **Descriptive only:**
  - the binary versions, 1{|ln(C/K)| ≤ hσ} for h = 0.25 and 0.5, treated the same way;
  - s(E) alone, without the pseudo-expiry difference;
  - the same construction on Friday FLEX expiries, where listed options also expire;
  - a split by the call share of K\* open interest.

## Power, from simulated returns on these events

Normal returns at each event's σ, with five pseudo-dates. In a share q of events the
expiry return is pulled halfway to K\*. Power of H1 at α = 0.05 is about 0.04 at q = 0
(size), 0.11 at q = 0.05, 0.49 at q = 0.10 and 0.83 at q = 0.15. The test can find
attraction in roughly one event in seven, not in one in twenty. The minimum detectable
mean D is reported from the estimated standard error (2.8 × SE).

## What counts as a finding

- H1 rejects after Holm with a positive sign: FLEX-only expiries pin to the hidden strike.
- H1 rejects with a negative sign: closes are pushed away from K\* on expiry, consistent
  with dealers short gamma at those strikes. This is reported as such.
- Otherwise: no pinning detectable at this power, stated with the MDE.

## What would change this specification

Only a defect found in the code. Any change after an outcome has been seen is recorded
here as a dated amendment, with the estimate it changed.

## Amendment, 2026-11-08, before any outcome was read

**1. The pseudo-expiries move to the five sessions after expiry, E+1 to E+5.** A test on
simulated returns with no pinning rejected at p < 10⁻⁷, which exposed a defect in the
design above. K\* is chosen near the close of E−1. The sessions E−6 to E−2 lie on the
path that ends at that close, so their closes are drawn towards K\* by construction. That
biases the pseudo-expiry term up and D down.

The sessions after expiry carry no such bias: their returns are independent of how K\*
was chosen. The FLEX book at K\* has expired by then, and the five sessions still catch
attraction to K\* that is not specific to its expiry, round-number clustering included.
Each pseudo-date's mirror is taken about the close of the session before it. Bars must
exist for E−1 to E+5.

Over 60 simulated null worlds the corrected test rejects at 1.7% for a nominal 5%. The
power figures above came from independent pseudo-draws and are unaffected.

**2. Clarification of K\*.** The event count above was computed by choosing K\* among the
strikes that pass both filters, at least 100 contracts and within 2σ, not by choosing the
largest strike first and then applying the filters. That is the rule.

## Amendment, 2026-11-08, after the outcome was seen: split adjustment, sample, power

**1. A defect in the price data, found in review.** Stored bars were split-adjusted as
of the fetch date; OCC strikes are not. Before a split, the previous close, σ's scale
and the distance to K\* were all off by the split's ratio, so pin strikes of split names
failed the 2σ filter or were measured against the wrong price. Bars are now put back on
each session's basis (`collect/splits.py`, `read_bars`). The design is unchanged; the
sample and the estimates change.

| | before | after |
|---|---|---|
| Events (expiry dates; names) | 2,324 (326; 494) | 2,709 (326; 498) |
| H1 mean D (σ) | −0.017 | −0.031 |
| H1 t | −0.62 | −1.16 |
| H1 sign-flip p | 0.54 | 0.25 |
| H1 Holm p | 1.00 | 0.50 |
| MDE (σ) | 0.076 | 0.074 |
| H2 t | 0.58 | 1.05 |

The finding under the rule above is unchanged: no pinning detectable at this power.

**2. Event count.** The 2,383 events on 330 dates above were counted on the split-adjusted
bars and before requiring bars through E+5; on corrected bars with that requirement the
sample is 2,709 events on 326 dates.

**3. Excluded names: 32, not 31.** The count above was taken on OCC's census alone. The
rule also uses the stored Cboe chains, which add GDX. The code applied the rule as
written; only the count in the text was short.

**4. Power, now computed in the repository.** The power figures above were computed
outside the repository and cannot be reproduced exactly. The result now carries its own
(`simulate_worlds`, `power_at`): the same alternative, on the corrected events. Over 1,000
null worlds the test rejects in 6.1% at a nominal 5%. Independent normal returns give a
standard error of about 0.021σ, below the observed 0.026σ, so power is reported at the
observed standard error: 26% when one event in twenty is pulled halfway to K\*, 75% at one
in ten and 97% at one in seven (39%, 92% and 100% on the simulated standard error). The
statement above, that the test can find attraction in about one event in seven and not in
one in twenty, stands.
