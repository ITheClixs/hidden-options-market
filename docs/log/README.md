# Research log

The work that led to the current question, kept as it was written. The project began as
a test of how fast markets absorb a disclosed option flow, found no footprint in volume,
and became a measurement of FLEX inventory in OCC clearing data. Along the way it made
errors, retracted claims and replaced a census with an authoritative source. None of
that is deleted. Entries are not edited after the fact; the only changes since they were
written are the file names, which moved from `docs/`, the links between entries, and one
cleanup on 2026-11-07: `prior-art-sweep` dropped a numeric "race-risk" estimate that had
no stated basis and restated its verdict line in plain words. Its findings are unchanged.

The current results are in the paper and the [README](../../README.md), generated from
`results/`; [`OPERATIONS.md`](../OPERATIONS.md) says how the data is collected. The
scripts that produced the numbers below are in [`archive/`](../../archive/README.md).

## Entries

| date | entry | what it was | what superseded it |
|---|---|---|---|
| 2026-08-16 | [measurement-validation](2026-08-16-measurement-validation.md) | Matched the fund synthetic legs seen in OCC open interest (cent-offset strike, one-sided) against issuer holdings: 8 of 11 attributed legs agree to the contract. | Stands for the fund legs it checked. As a way to find FLEX in general, the strike rule was superseded by OCC's own FLEX report (its precision and recall are in the [README](../../README.md)). |
| 2026-08-17 | [issuer-endpoints](2026-08-17-issuer-endpoints.md) | Survey of issuer holdings endpoints, the Global X dated-URL back-fill, and the retraction of a rolling-retention claim inferred from sparse probing. | Nothing; left open. The back-fill is `scripts/backfill_globalx.py`. Innovator, First Trust, Neos and Roundhill were not resolved and nothing here collects them. |
| 2026-08-17 | [power-and-data-limits](2026-08-17-power-and-data-limits.md) | Corrected the research plan's minimum detectable effect (asserted as about 2.5 bp, roughly an order of magnitude too small) and recorded what free price history exists. | Not superseded. It changed the pilot design (next entry) and is cited from `src/hidden_options/collect/bars.py`. |
| 2026-08-17 | [pilot-spec](2026-08-17-pilot-spec.md) | Stage 1 specification written before any result: a volume difference-in-differences around fund launch, with pass and fail thresholds fixed in advance. | Run in [stage1-result](2026-08-17-stage1-result.md). Its gated Stage 2, a test on returns, was never run; the reframing decided against it. |
| 2026-08-17 | [prior-art-sweep](2026-08-17-prior-art-sweep.md) | Novelty check for the claim that the impact of a disclosed, scheduled option flow decays toward a positive floor. No competing paper found, by a sweep it states was weaker than a direct database query. | Written for the absorption-curve question, which the reframing dropped. Not re-run for the current one. |
| 2026-08-17 | [stage1-result](2026-08-17-stage1-result.md) | Stage 1 does not pass its criteria; v2 with time-varying dose and a weekday scan finds a precise null on the dose response (2026-08-18); positive controls and randomization inference follow in the same file. | Read together with the intraday test and then the reframing. Its null was later demoted from a finding to corroboration, because the hedging flow the programmes imply is below what this design could detect (see `archive/README.md`). |
| 2026-08-18 | [intraday-result](2026-08-18-intraday-result.md) | Intraday test: a dose by time-of-day specification that looks decisive and is confounded by clientele, then the identified within-name close-hour tilt, which is null on every weekday. | The reframing, the same day. |
| 2026-08-18 | [flex-census](2026-08-18-flex-census.md) | Census of US FLEX open interest found by strike signature (30.9m contracts against Cboe's 38.1m), with corrections to its own classification and notional, a rebuild by structure rather than by leg, and the limits of attribution from filings. | The OCC FLEX report itself, which lists every cleared FLEX series and makes strike-based detection unnecessary. The strike rule's precision and recall against it are in the [README](../../README.md). Within the entry, the notional figures were superseded by the exposure figures in its last sections. |
| 2026-08-18 | [reframing](2026-08-18-reframing.md) | The project's thesis after four tests found no volume footprint: a bound on absorption capacity and a free measurement method, not an absorption curve. | The next day's question, whether hidden inventory predicts the visible market, asked of the OCC FLEX panel: [predictive-result](2026-08-19-predictive-result.md). Its tight bound was weakened shortly after by the implied-hedging calculation (see `archive/README.md`). |
| 2026-08-19 | [predictive-result](2026-08-19-predictive-result.md) | The first test of whether per-underlying FLEX inventory predicts the underlying's next-day volatility, on the shorter panel then on disk: a null, with a placebo dated after the outcome that matched the genuine estimate. | The same test rebuilt in code on the full panel, with gap-safe changes, outcomes joined on the date each report became usable, and permutation inference; its numbers are in the paper's predictive section and the README. |

| 2026-11-07 | [hidden-gamma-spec](2026-11-07-hidden-gamma-spec.md) | Specification, written before any figure, of how much option gamma a listed-only calculation leaves out: gamma from one listed surface for both sides, two attribution rules for FLEX (gross, pair-netted). | Done: result `hidden_gamma`, paper Section 6. |
| 2026-11-08 | [gamma-predictive-spec](2026-11-08-gamma-predictive-spec.md) | Specification, written before any estimate, of the predictive test on pair-netted FLEX dollar gamma scaled by dollar volume, in place of open interest: two tests of record with Holm's adjustment, MDE per standard deviation. | Done: result `gamma_predictive`, paper Section 7.1, a bounded null (amended after the estimate: bars un-split-adjusted, verdict unchanged). |
| 2026-11-08 | [pinning-spec](2026-11-08-pinning-spec.md) | Specification, written before any expiry-date close was read, of a pinning test at the largest FLEX strike on dates when only FLEX options expire: a mirror-strike statistic differenced against five pseudo-expiries, clustered by expiry date, with the power simulated in advance. | Done: result `pinning`, paper Section 7.2, no pinning (amended before any outcome: pseudo-expiries after the expiry date; amended after: bars un-split-adjusted, power computed in the repository, finding unchanged). |
| 2026-11-08 | [gamma-timing-spec](2026-11-08-gamma-timing-spec.md) | Specification, written before any estimate, of robustness rows for the gamma test: pricing at T−1, an implied-volatility control, both, and the lead at fixed pricing, with the reading of each fixed in advance. | Done: rows in result `gamma_predictive` and Table tab:gamma-pred; none rejects, and the lead at fixed pricing is null, so the lead was re-pricing. |
| 2026-11-08 | [programme-gamma-spec](2026-11-08-programme-gamma-spec.md) | Specification, written before any estimate on the subsample, of a one-sided test in the 34 option-income programme names, where the netted FLEX book is the funds' written calls and dealers are long its gamma: β < 0, wild cluster restricted bootstrap by underlying. | Done: result `gamma_predictive` (`programme`), paper Section 7.1; the estimate is negative but the test is inconclusive (MDE 9.4% of mean \|r\|); amended after: the funds' holdings contradict the sign assumption (result `programme_book`). |
| 2026-11-08 | [pinning-control-spec](2026-11-08-pinning-control-spec.md) | Specification, written before any expiry close in it was read, of a positive control for the pinning test: the registered statistic at the nearest coarse listed strike on standard monthly expirations, with the reading fixed in advance. | Done: the control finds no pinning (D < 0; net of an ordinary-day baseline, t −1.85), so the FLEX null reads as not detected; amended after the outcome: a matched placebo shows the negative sign is the design's under return reversal (net −0.007σ, t −1.64); the FLEX estimate is unaffected. |
| 2026-11-08 | [pinning-empirical-null-spec](2026-11-08-pinning-empirical-null-spec.md) | Specification, written before any figure in it, of the pinning test's size and power on real returns: each event moved to placebo dates in its own name, with pins planted in real closes. | Done: size 6.3% on real returns, power 28/75/97% at one event in 20/10/7, the registered estimate inside the null (22% of placebo dates as far out). |
| 2026-11-10 | [anatomy-spec](2026-11-10-anatomy-spec.md) | Specification, written after an exploratory look at five report dates and before the panel was measured, of what the FLEX market is made of: box spreads, the stock-leg calls and packages of defined-outcome funds, same-strike pairs and the rest, by open interest, value and gamma. | Done: result `anatomy`; by value 77% of the market is box legs, stock-leg calls and same-strike pairs; box face $22bn to $68bn. |
| 2026-11-10 | [box-rates-spec](2026-11-10-box-rates-spec.md) | Specification, written before the trade reports were collected, of the rate at which box spreads trade in Cboe's FLEX execution reports, against the Treasury curve and against OCC's marks. | Done: result `box_rates`; 1,099 box trades of up to a year at 36bp over Treasuries (standard error 5bp); OCC's marks sit 35bp below traded rates; 41% of open-interest box face confirmed by traded packages. |
| 2026-11-10 | [holders-spec](2026-11-10-holders-spec.md) | Specification, written before any holding was matched, of a check of the product rules and of the dealer's side against the holdings two issuers disclose on one date: Innovator's defined-outcome funds and the BOXX fund. | Open. |

## Former names

The ten entries were moved with `git mv`, so `git log --follow` reaches their history.

| entry | was |
|---|---|
| measurement-validation | `docs/MEASUREMENT_VALIDATION.md` |
| issuer-endpoints | `docs/ISSUER_ENDPOINTS.md` |
| power-and-data-limits | `docs/POWER_AND_DATA_LIMITS.md` |
| pilot-spec | `docs/PILOT_SPEC.md` |
| prior-art-sweep | `docs/PRIOR_ART_SWEEP.md` |
| stage1-result | `docs/STAGE1_RESULT.md` |
| intraday-result | `docs/INTRADAY_RESULT.md` |
| flex-census | `docs/FLEX_CENSUS.md` |
| reframing | `docs/REFRAMING.md` |
| predictive-result | `docs/PREDICTIVE_RESULT.md` |

An entry's date is the one it states in its heading or first lines: the pilot spec says
"Written 2026-08-17" and the validation note gives its date of capture. `issuer-endpoints`
states none, so its date is that of the commit that added it.
