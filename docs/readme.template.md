# The Hidden Options Market

**How much option convexity listed chains miss, and whether it moves prices.**

FLEX options are exchange options whose terms the counterparties choose. They are cleared
centrally, and they are absent from the listed option chains that most option research is
built on. They are not unobservable. The
Options Clearing Corporation publishes a free daily report of every cleared FLEX series —
root, strike, expiry, mark price and open interest — and this repository turns it into a
panel.

**In brief**

- **Size.** {{ValueEnd}} of mark value on {{PanelEnd}}. In a census of {{HiddenCensusUnderlyings}} underlyings, FLEX is at least a tenth of option open interest for {{HiddenCensusTen}}.
- **Convexity.** Across the {{GammaUnderlyings}} followed underlyings with stored listed chains, over {{GammaSettlements}} settlements, FLEX is {{GammaMedianGross}} of the median one's option gamma when every contract is counted, which listed-only gamma figures leave out. Most of it is same-strike call/put pairs, which are forwards. With those netted it is {{GammaMedianNetted}} ({{GammaMedianBoth}} if listed pairs are netted too). It stays large in SPY ({{GammaSPYNetted}} FLEX-netted) and NDX ({{GammaNDXNetted}}).
- **Does it move prices?** No effect found at daily resolution. In a test fixed in advance, netted FLEX dollar gamma does not predict next-day volatility (*t* {{GPredT}}, {{GPredDays}} underlying-days). The minimum detectable effect is {{GPredMDE}}bp per standard deviation, {{GPredMDEShare}} of mean \|*r*\|. The hedge a 1% move calls for is {{GPredMedianX}}bp of a day's dollar volume in the median case. The measure is unsigned, so books on opposite sides of an underlying could offset. Where the sign is known, in the {{GProgNames}} option-income programme names, a one-sided test leans towards dampening but is underpowered (*t* {{GProgT}}, minimum detectable effect {{GProgMDEShare}} of mean \|*r*\|).
- **Pinning?** Not detected. On {{PinEvents}} expiries, over {{PinDates}} dates, when only FLEX options expire, stocks without listed weekday expiries do not close nearer the largest FLEX strike (*t* {{PinT}}). The minimum detectable pull is {{PinMDE}}σ, but the same design finds no pinning at listed strikes on {{PinCtlDates}} monthly expirations either (net of its baseline, *t* {{PinCtlNetT}}), so this is what the design can see, not proof of absence. Both tests are unsigned: they rule out a net effect of one sign, not books on opposite sides that offset.
- **Measurement.** Treating off-grid strikes as FLEX misses {{FlexOnGridShare}} of FLEX series, and strike notional overstates delta exposure at least {{PosGrossMedian}}-fold.
- **Method.** Every number in the paper and in this README is generated from `results/*.json`, and CI checks that. The gamma measurement, the gamma test and the pinning test were each specified in a dated log entry before they were run.

![FLEX against listed open interest per underlying on {{HiddenCensusDate}}, both on log scales; coloured points are underlyings where FLEX is at least half of all open interest, squares are index products](docs/figures/hidden_share.png)

*FLEX against listed open interest per underlying on {{HiddenCensusDate}}, log scales.
Coloured: FLEX is at least half of all open interest. Squares: index products, whose
listed side comes from the Cboe chain. The {{HiddenCensusWithoutFlex}} census underlyings
with no FLEX open interest are not drawn.*

**For {{HiddenStableTen}} of the {{HiddenDailyComplete}} underlyings the collector follows
that are observed on every date ({{HiddenDailyUniverse}} in all), at least a tenth of
option open interest is FLEX, outside the listed chain, on every date.** That holds on each of the {{HiddenDailyDates}} settlements captured from
{{HiddenDailyFirst}} to {{HiddenDailyLast}} ({{HiddenDailyMissing}} of the
{{HiddenDailySpan}} in that span have no usable capture). For {{HiddenStableQuarter}} of
those underlyings ({{HiddenStableQuarterNames}}) the share is at least 25% on every date,
and for {{HiddenStableHalfNames}} at least half, counting only series that expire after
each date; with the series expiring on a date included, its lowest share is
{{HiddenRutFullLow}} ({{HiddenRutFullLowDate}}). The followed underlyings were chosen
mostly for the option-income programmes written on them: {{HiddenStableTenProgramme}} of
{{HiddenCompleteProgramme}} programme names clear 10% on every date, against
{{HiddenStableTenControl}} of {{HiddenCompleteControl}} controls. A one-date census of
{{HiddenCensusUnderlyings}} underlyings with listed weekly options, on {{HiddenCensusDate}},
gives the wider picture: the median FLEX share is {{HiddenCensusMedian}},
{{HiddenCensusTen}} underlyings are at 10% or more and {{HiddenCensusHalf}} at half or
more ({{HiddenCensusHalfNames}}).

OCC's series search and its FLEX report count the same FLEX open interest twice, and they
agree to the contract on {{HiddenReconAgreeing}} of {{HiddenReconSymbolDates}}
symbol-dates. Valued at the report's marks and at listed mid quotes (Cboe's theoretical
value where a quote is one-sided or crossed, {{HiddenValueTheo}} of listed open interest),
FLEX holds {{HiddenValueLow}}–{{HiddenValueHigh}} of the followed underlyings' option
value, against {{HiddenValueOpenInterestLow}}–{{HiddenValueOpenInterestHigh}} of their open
interest. The gap is mostly deep in-the-money legs and call and put lines paired at the
same strike: on {{HiddenValueCompositionDate}}, {{HiddenValueIntrinsic}} of the
{{HiddenValueFlexTotal}} of FLEX value on these underlyings is intrinsic and {{HiddenValuePaired}} sits in
paired lines. One {{HiddenLineSymbol}} {{HiddenLineRight}} series, {{HiddenLineOpenInterest}}
contracts struck at {{HiddenLineStrike}} and paired with {{HiddenLineOppositeOpenInterest}}
{{HiddenLineOpposite}} contracts at the same strike, is marked at {{HiddenLineValue}},
against {{HiddenLineListed}} for every listed {{HiddenLineSymbol}} option together.

## The FLEX market over {{PanelMonths}} months

| | {{PanelStart}} | {{PanelEnd}} |
|---|---:|---:|
| Open interest | {{OIStart}}m contracts | **{{OIEnd}}m contracts** |
| Mark value | {{ValueStart}} | **{{ValueEnd}}** |

{{PanelDates}} activity dates, {{PanelUnderlyings}} underlyings,
{{PanelSeriesDaysMillions}}m series-days. A one-break fit dates the turn in growth to
{{BreakMonth}}; averaged over a monthly expiry cycle, open interest stays in its
pre-break band of {{OIFlatLow}}–{{OIFlatHigh}}m contracts through the cycle ending
{{FlatBandEnd}}, and the latest cycle averages {{OICycleLatest}}m, {{GrowthMultiple}} times
the pre-break mean of {{OIFlatLevel}}m. The latest quarter added only {{OIQuarterChange}}.
The sawtooth in the chart is the expiry cycle: of the ten largest one-day falls in open
interest, {{DropsOnExpiry}} land on a monthly expiry or the activity date after it, where
only {{ExpiryWindowShare}} of day-to-day changes do. On the last date, {{SeriesEnd}}
series across {{UnderlyingsEnd}} underlyings: the ten largest underlyings hold
{{TopTenShare}} of open interest, {{WithinSixtyShare}} expires within sixty days,
{{OverOneYear}} is more than a year from expiry (up from {{OverOneYearStart}} on the first
date), and {{CallShare}} is calls.

## How much gamma do listed chains leave out?

Gamma figures in public use are built from listed chains, and FLEX is not in them. Pricing
listed and FLEX series on one listed volatility surface over {{GammaSettlements}} settlements
({{GammaStart}} to {{GammaEnd}}, {{GammaUnderlyings}} underlyings) gives the following FLEX
shares of total dollar gamma:

| FLEX attribution | Median underlying | Pooled | SPX | SPY | NDX |
|---|---:|---:|---:|---:|---:|
| Gross | {{GammaMedianGross}} | {{GammaPooledGross}} | {{GammaSPXGross}} | {{GammaSPYGross}} | {{GammaNDXGross}} |
| Same-strike pairs netted, FLEX side | {{GammaMedianNetted}} | {{GammaPooledNetted}} | {{GammaSPXNetted}} | {{GammaSPYNetted}} | {{GammaNDXNetted}} |
| Same-strike pairs netted, both sides | {{GammaMedianBoth}} | {{GammaPooledBoth}} | {{GammaSPXBoth}} | {{GammaSPYBoth}} | {{GammaNDXBoth}} |

FLEX gamma is not deep in the money: {{GammaNearMoneyGross}} of it sits within 5% of spot.
Gamma from the FLEX marks, where their inversion is validated ({{GammaMarkShare}} of open
interest), is {{GammaMarkRatio}} times gamma from the listed surface. Specification:
[`docs/log/2026-11-07-hidden-gamma-spec.md`](docs/log/2026-11-07-hidden-gamma-spec.md).

## Does hidden inventory predict the visible market?

**On gamma.** The test regresses next-day absolute returns on pair-netted FLEX dollar gamma, scaled by
twenty-session dollar volume, with underlying and date fixed effects and two-way
clustering. It was fixed in advance in
[`docs/log/2026-11-08-gamma-predictive-spec.md`](docs/log/2026-11-08-gamma-predictive-spec.md).
The coefficient is {{GPredBeta}}bp per standard deviation (*t* {{GPredT}}, permutation *p*
{{GPredPermP}}, Holm *p* {{GPredHolm}}) on {{GPredDays}} underlying-days. The minimum
detectable effect is {{GPredMDE}}bp, {{GPredMDEShare}} of mean |*r*|, which the rule fixed in
advance calls {{GPredVerdict}}. Netted gamma dated two activity dates later is negative
(*t* {{GPredLeadT}}), and priced at the first date's spot, implied volatilities and
volume, so that only open interest moves, it is not (*t* {{GPredLeadFixedT}}): a large
move re-prices the book, carrying spot away from the strikes. The same re-pricing could
bias the test itself, so rows fixed in
[`docs/log/2026-11-08-gamma-timing-spec.md`](docs/log/2026-11-08-gamma-timing-spec.md)
before they were run price it on the day before (*t* {{GPredPreT}}) and add an
implied-volatility control (*t* {{GPredIvT}}). Neither finds an effect. In the
{{GProgNames}} option-income programme names, where netting leaves the funds' written calls and
dealers are long their gamma, a one-sided test fixed in
[`docs/log/2026-11-08-programme-gamma-spec.md`](docs/log/2026-11-08-programme-gamma-spec.md)
gives {{GProgBeta}}bp per standard deviation (*t* {{GProgT}}, wild cluster bootstrap *p*
{{GProgWildP}}). Its minimum detectable effect is {{GProgMDE}}bp, {{GProgMDEShare}} of mean
\|*r*\|, so the test is {{GProgVerdict}}.

**At hidden strikes.** Most listed options expire on Fridays, but FLEX options can expire on any weekday. A
Monday-to-Thursday FLEX expiry in a name that lists no option expiring that day is a date
on which only FLEX expires. On {{PinEvents}} such expiries ({{PinDates}} dates,
{{PinUnderlyings}} names), the test compares the close's distance to the largest expiring
FLEX strike with its distance to the mirror strike on the other side of the previous
close. It then subtracts the same comparison on the five sessions after expiry. The
result is {{PinMean}}σ (*t* {{PinT}}, sign-flip *p* {{PinFlipP}}), with a minimum
detectable effect of {{PinMDE}}σ. Large books do no better than small ones (*t*
{{PinSizeT}}). Specification and its pre-outcome amendment:
[`docs/log/2026-11-08-pinning-spec.md`](docs/log/2026-11-08-pinning-spec.md).
As a positive control, fixed in
[`docs/log/2026-11-08-pinning-control-spec.md`](docs/log/2026-11-08-pinning-control-spec.md),
the same statistic at the nearest listed strike on {{PinCtlDates}} monthly expirations
({{PinCtlEvents}} events) finds no pinning: {{PinCtlMean}}σ (*t* {{PinCtlT}}), against a
baseline of {{PinCtlPlaceboMean}}σ on ordinary sessions, so {{PinCtlNetMean}}σ net (*t*
{{PinCtlNetT}}). The design does not detect listed pinning in this panel, so the FLEX null
reads as not detected, not absent.

**On contracts.** The original, cruder test regresses on open interest instead. A dealer on the other side of a FLEX trade hedges it in the listed market and carries the
residual convexity while the position lives. If that matters, inventory published
overnight for day *T* should say something about the underlying from day *T+1*, the first
day the report can be read.

It does not. The test covers {{PredUnderlyingDays}} underlying-days across
{{PredUnderlyings}} underlyings and {{PredDates}} activity dates, {{PredFirstDate}} to
{{PredLastDate}}, with underlying and date fixed effects, errors clustered by underlying
and by date, and controls for trailing volatility over 5 and 22 sessions, the same day's
absolute return and log dollar volume. Each report meets the returns realised from the
day it became usable, and an inventory change across a date the underlying did not report
is dropped. Bars are fetched by the equity report's tickers, so index underlyings are left
out (a bare index symbol names another security, or none). Of the {{PredQualifying}}
equity names with at least {{PredQualifyingDates}} activity dates, {{PredNoBars}} have
symbols the bar provider does not serve. OCC adjusted-deliverable roots, option classes
renamed with a digit after a corporate action changed their deliverable (`GME1`), account
for {{PredNoBarsAdjusted}}; share-class spellings such as `BRKB` for
{{PredNoBarsShareClass}}; other tickers, delisted and renamed names among them, for
{{PredNoBarsOther}}. Coefficients and MDE80 are multiplied by 10⁴, which for |r| is basis
points.

| predictor | outcome | β ×10⁴ | *t* | MDE80 ×10⁴ | clustered *p* | permutation *p* |
|---|---|---:|---:|---:|---:|---:|
| inventory innovation | next-day \|r\| | {{PredInnovBeta}} | {{PredInnovT}} | {{PredInnovMDE}} | {{PredInnovClusterP}} | {{PredInnovPermP}} |
| inventory change | next-day \|r\| | {{PredChangeBeta}} | {{PredChangeT}} | {{PredChangeMDE}} | {{PredChangeClusterP}} | {{PredChangePermP}} |
| near-dated share change | next-day \|r\| | {{PredNearBeta}} | {{PredNearT}} | {{PredNearMDE}} | {{PredNearClusterP}} | {{PredNearPermP}} |
| put share | next-day \|r\| | {{PredPutBeta}} | {{PredPutT}} | {{PredPutMDE}} | {{PredPutClusterP}} | {{PredPutPermP}} |
| inventory innovation | next-day r² | {{PredInnovSqBeta}} | {{PredInnovSqT}} | {{PredInnovSqMDE}} | {{PredInnovSqClusterP}} | {{PredInnovSqPermP}} |
| **lead: innovation dated *after* the outcome** | next-day \|r\| | **{{PredPlaceboBeta}}** | **{{PredPlaceboT}}** | {{PredPlaceboMDE}} | {{PredPlaceboClusterP}} | {{PredPlaceboPermP}} |

![The innovation's coefficient with the predictor shuffled within dates, above the estimates and their 95% intervals](docs/figures/placebo.png)

The permutation *p* comes from {{PredPermutations}} re-estimations with the predictor
shuffled across underlyings within each date, which treats underlyings as exchangeable
within a date. Among the genuine predictors the smallest permutation *p* is
{{PredMinGenuinePermP}} and the smallest clustered *p* {{PredMinGenuineClusterP}}. The
lead row is inventory from two dates later. Its change includes contracts created
during the outcome's own session, so it is a test of reverse flow, volatility moving
later inventory, and not a placebo; its clustered *p* is {{PredPlaceboClusterP}}. The
largest |*t*| among the genuine estimates, across every specification below, is
{{PredMaxAbsT}}.

Longer horizons say the same: mean |r| over the next 3, 5 and 10 sessions gives
*t* = {{PredHorizonThreeT}}, {{PredHorizonFiveT}} and {{PredHorizonTenT}}. Keeping only the
tenth of underlying-days with the largest inventory changes gives *t* = {{PredDecileT}}.
The close-to-close return includes an overnight move that partly precedes the report;
the open-to-close return of the day it becomes usable gives *t* = {{PredOpenCloseT}}. The
minimum detectable effect at 80% power is {{PredInnovMDE}} basis points per log point of
innovation, {{PredMDEShare}} of the mean next-day |r| of {{PredMeanAbsRet}} basis points.

Loading the panel from later start dates moves the estimates, not the conclusion:

| panel loaded from | underlying-days | inventory innovation | lead |
|---|---:|---:|---:|
| {{PredWindowOneStart}} (table above) | {{PredWindowOneDays}} | {{PredWindowOneBeta}} (*t* {{PredWindowOneT}}) | {{PredWindowOnePlaceboBeta}} (*t* {{PredWindowOnePlaceboT}}) |
| {{PredWindowTwoStart}} | {{PredWindowTwoDays}} | {{PredWindowTwoBeta}} (*t* {{PredWindowTwoT}}) | {{PredWindowTwoPlaceboBeta}} (*t* {{PredWindowTwoPlaceboT}}) |
| {{PredWindowThreeStart}} | {{PredWindowThreeDays}} | {{PredWindowThreeBeta}} (*t* {{PredWindowThreeT}}) | {{PredWindowThreePlaceboBeta}} (*t* {{PredWindowThreePlaceboT}}) |

Not ruled out: strike-local effects, intraday responses, and effects on the listed option
surface rather than the underlying. Each needs data that cannot be collected
retrospectively for free. The first version of this test, on a shorter panel, is kept in
[`docs/log/`](docs/log/2026-08-19-predictive-result.md).

## Two measurement results that travel

**FLEX cannot be found by its strikes.** Listed strikes sit on a grid of whole dollars,
halves and quarters, so an off-grid strike looks like a FLEX tell. OCC's series search
marks every FLEX product with a leading digit, so the rule can be scored: over the
{{CensusSeries}} series with open interest in the {{HiddenCensusDate}} census, it has
precision {{RulePrecision}} and recall {{RuleRecall}}. FLEX is routinely struck *on* the
grid: {{FlexDollarShare}} of FLEX series sit on a whole dollar, the largest of them
`{{RuleExampleProduct}}` at {{RuleExampleStrike}} with {{RuleExampleOpenInterest}}. So
{{FlexOnGridShare}} of FLEX series, and {{FlexOnGridOpenInterest}} of FLEX open interest,
are invisible to any strike-based test, and {{RuleFalseShare}} of what the rule flags is
listed. This project used the rule first; the superseded census is kept as it was in
[`docs/log/2026-08-18-flex-census.md`](docs/log/2026-08-18-flex-census.md).

**A cleared series is not a position.** Open interest is reported per series, and positions
span series. On an average date {{PosStructuredMean}} of FLEX open interest sits in groups of
series with near-equal counts at one expiry, against {{PosChance}} when the counts are dealt at
random. Scored against disclosed fund holdings, with the settings frozen first, that grouping
recalls {{PosRecall}} of {{PosTruth}} held structures with precision {{PosPrecision}}. The test
rests on {{PosFunds}} of one family, where in the median held leg the fund holds
{{PosHolderShare}} of the open interest, and almost entirely on same-strike pairs; a match means consistent with a disclosed
holder, no more. On the {{PosCovered}} of open interest with a validated delta, the median
underlying's strike notional, across {{PosRatioUnderlyings}} underlyings, is at least
{{PosGrossMedian}} times its delta exposure, whatever the signs of the legs. Counting every leg as long gives
{{PosRatioMedian}}, a reading that is neither a floor nor a ceiling and that overstates the
ratio on the same-strike pairs funds disclose. On single
positions, recomputed from the report:

- a butterfly's strike notional is **{{PosButterflyTimes}}×** its maximum value;
- a four-leg SPY collar is counted about **{{PosCollarTimes}}×** over;
- a call struck at {{PosDeepStrike}} is recorded as **{{PosDeepNotional}}** of strike notional
  when its exposure is **{{PosDeepExposure}}**.

## Run it

Python 3.11+. Every input is free: no WRDS, no OptionMetrics, no vendor feed, no account.

```bash
uv venv && uv pip install -e '.[dev,paper]'
.venv/bin/pytest

# the OCC FLEX report, equity and index classes, for every date OCC still serves
.venv/bin/hidden-options backfill-flex --start 2024-12-02

# daily bars for the FLEX underlyings, far enough back for the trailing controls
.venv/bin/hidden-options refresh-bars

# results, figures, the generated paper numbers and this README, then the PDF
make all
```

Every downloaded report is checked against the per-class totals it carries and stored
under its own activity date, not the date it was fetched. OCC publishes overnight, so a
capture taken during a session returns the previous settlement; partitioning by fetch
date would enter one settlement twice as two suspiciously stable days. The numbers in this
README and the paper are rendered from `results/` by `make publish`, and `make check`
fails if any of them differs from its result file.

## Layout

```
src/hidden_options/collect/occ_flex.py        OCC FLEX report: fetch, parse, validate
src/hidden_options/collect/backfill.py        fetch the FLEX reports missing for a span of dates
src/hidden_options/measure/flex_panel.py      panel assembly and inventory measures
src/hidden_options/measure/hidden_share*.py   how much of each options market is FLEX
src/hidden_options/measure/identification*.py why a strike rule cannot find FLEX
src/hidden_options/measure/structures.py      leg grouping and valuation on the underlying
src/hidden_options/measure/holdings_truth.py  fund holdings as truth for the grouping, and its score
src/hidden_options/measure/positions*.py      series against positions across the market
src/hidden_options/predict/                   the predictive panel, regressions and permutation test
src/hidden_options/publish/                   results/ to the paper's numbers and tables and this README
src/hidden_options/collect/                   chains, holdings, bars and N-PORT collectors
scripts/                                      scheduling, one-off back-fills, reproduce.sh
docs/                                         how the data is collected; the template for this README
docs/log/                                     superseded work and corrections, dated, as written
archive/                                      the scripts behind the log's results
```

The earlier strike-heuristic census is rebuilt by `scripts/reproduce.sh`; the write-ups
of what was tried and what replaced it are indexed in [`docs/log/`](docs/log/README.md),
and the scripts that produced them in [`archive/`](archive/README.md). Raw snapshots
from the collectors are vendor-sourced and not redistributed here; the scheduled capture
is described in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## License

MIT for the code.
