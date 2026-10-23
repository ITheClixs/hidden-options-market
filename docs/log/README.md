# Research log

The work that led to the current question, kept as it was written. The project began as
a test of how fast markets absorb a disclosed option flow, found no footprint in volume,
and became a measurement of FLEX inventory in OCC clearing data. Along the way it made
errors, retracted claims and replaced a census with an authoritative source. None of
that is deleted. Entries are not edited after the fact; the only changes since they were
written are the file names, which moved from `docs/`, and the links between entries.

Current documents are one level up: [`PREDICTIVE_RESULT.md`](../PREDICTIVE_RESULT.md) for
the result the repository is about, and [`OPERATIONS.md`](../OPERATIONS.md) for how the
data is collected. The scripts that produced the numbers below are in
[`archive/`](../../archive/README.md).

## Entries

| date | entry | what it was | what superseded it |
|---|---|---|---|
| 2026-08-16 | [measurement-validation](2026-08-16-measurement-validation.md) | Matched the fund synthetic legs seen in OCC open interest (cent-offset strike, one-sided) against issuer holdings: 8 of 11 attributed legs agree to the contract. | Stands for the fund legs it checked. As a way to find FLEX in general, the strike rule was superseded by OCC's own FLEX report (precision 0.67, recall 0.34 when scored against it; see the [README](../../README.md)). |
| 2026-08-17 | [issuer-endpoints](2026-08-17-issuer-endpoints.md) | Survey of issuer holdings endpoints, the Global X dated-URL back-fill, and the retraction of a rolling-retention claim inferred from sparse probing. | Nothing; left open. The back-fill is `scripts/backfill_globalx.py`. Innovator, First Trust, Neos and Roundhill were not resolved and nothing here collects them. |
| 2026-08-17 | [power-and-data-limits](2026-08-17-power-and-data-limits.md) | Corrected the research plan's minimum detectable effect (asserted as about 2.5 bp, roughly an order of magnitude too small) and recorded what free price history exists. | Not superseded. It changed the pilot design (next entry) and is cited from `src/hidden_options/collect/bars.py`. |
| 2026-08-17 | [pilot-spec](2026-08-17-pilot-spec.md) | Stage 1 specification written before any result: a volume difference-in-differences around fund launch, with pass and fail thresholds fixed in advance. | Run in [stage1-result](2026-08-17-stage1-result.md). Its gated Stage 2, a test on returns, was never run; the reframing decided against it. |
| 2026-08-17 | [prior-art-sweep](2026-08-17-prior-art-sweep.md) | Novelty check for the claim that the impact of a disclosed, scheduled option flow decays toward a positive floor. No competing paper found, by a sweep it states was weaker than a direct database query. | Written for the absorption-curve question, which the reframing dropped. Not re-run for the current one. |
| 2026-08-17 | [stage1-result](2026-08-17-stage1-result.md) | Stage 1 does not pass its criteria; v2 with time-varying dose and a weekday scan finds a precise null on the dose response (2026-08-18); positive controls and randomization inference follow in the same file. | Read together with the intraday test and then the reframing. Its null was later demoted from a finding to corroboration, because the hedging flow the programmes imply is below what this design could detect (see `archive/README.md`). |
| 2026-08-18 | [intraday-result](2026-08-18-intraday-result.md) | Intraday test: a dose by time-of-day specification that looks decisive and is confounded by clientele, then the identified within-name close-hour tilt, which is null on every weekday. | The reframing, the same day. |
| 2026-08-18 | [flex-census](2026-08-18-flex-census.md) | Census of US FLEX open interest found by strike signature (30.9m contracts against Cboe's 38.1m), with corrections to its own classification and notional, a rebuild by structure rather than by leg, and the limits of attribution from filings. | The OCC FLEX report itself, which lists every cleared FLEX series and makes strike-based detection unnecessary. The strike rule's precision and recall against it are in the [README](../../README.md). Within the entry, the notional figures were superseded by the exposure figures in its last sections. |
| 2026-08-18 | [reframing](2026-08-18-reframing.md) | The project's thesis after four tests found no volume footprint: a bound on absorption capacity and a free measurement method, not an absorption curve. | The next day's question, whether hidden inventory predicts the visible market, asked of the OCC FLEX panel: [`PREDICTIVE_RESULT.md`](../PREDICTIVE_RESULT.md). Its tight bound was weakened shortly after by the implied-hedging calculation (see `archive/README.md`). |

## Former names

The nine entries were moved with `git mv`, so `git log --follow` reaches their history.

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

An entry's date is the one it states in its heading or first lines: the pilot spec says
"Written 2026-08-17" and the validation note gives its date of capture. `issuer-endpoints`
states none, so its date is that of the commit that added it.
