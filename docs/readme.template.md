# The Hidden Options Market

**FLEX inventory in clearing data, and whether it predicts the visible market.**

FLEX options are negotiated bilaterally, cleared centrally, and absent from the listed
option chains that most option research is built on. They are not unobservable. The
Options Clearing Corporation publishes a free daily report of every cleared FLEX series —
root, strike, expiry, mark price and open interest — and this repository turns it into a
panel.

![FLEX open interest and mark value, {{PanelStart}} to {{PanelEnd}}](docs/figures/growth.png)

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

## Does hidden inventory predict the visible market?

A dealer on the other side of a FLEX trade hedges it in the listed market and carries the
residual convexity while the position lives. If that matters, inventory published
overnight for day *T* should say something about the underlying from day *T+1*, the first
day the report can be read.

It does not. The test covers {{PredUnderlyingDays}} underlying-days across
{{PredUnderlyings}} underlyings and {{PredDates}} activity dates, {{PredFirstDate}} to
{{PredLastDate}}, with underlying and date fixed effects, errors clustered by underlying
and by date, and controls for trailing volatility over 5 and 22 sessions, the same day's
absolute return and log dollar volume. Each report meets the returns realised from the
day it became usable, and an inventory change across a date the underlying did not report
is dropped. Index underlyings are left out: the bars come from an equity quote feed.
Coefficients and MDE80 are multiplied by 10⁴, which for |r| is basis points.

| predictor | outcome | β ×10⁴ | *t* | MDE80 ×10⁴ | permutation *p* |
|---|---|---:|---:|---:|---:|
| inventory innovation | next-day \|r\| | {{PredInnovBeta}} | {{PredInnovT}} | {{PredInnovMDE}} | {{PredInnovPermP}} |
| inventory change | next-day \|r\| | {{PredChangeBeta}} | {{PredChangeT}} | {{PredChangeMDE}} | {{PredChangePermP}} |
| near-dated share change | next-day \|r\| | {{PredNearBeta}} | {{PredNearT}} | {{PredNearMDE}} | {{PredNearPermP}} |
| put share | next-day \|r\| | {{PredPutBeta}} | {{PredPutT}} | {{PredPutMDE}} | {{PredPutPermP}} |
| inventory innovation | next-day r² | {{PredInnovSqBeta}} | {{PredInnovSqT}} | {{PredInnovSqMDE}} | {{PredInnovSqPermP}} |
| **placebo: innovation dated *after* the outcome** | next-day \|r\| | **{{PredPlaceboBeta}}** | **{{PredPlaceboT}}** | {{PredPlaceboMDE}} | {{PredPlaceboPermP}} |

![The innovation's coefficient with the predictor shuffled within dates, above the estimates and their 95% intervals](docs/figures/placebo.png)

The permutation *p* comes from {{PredPermutations}} re-estimations with the predictor
shuffled across underlyings within each date; on every row it reads the same as *t*.
The innovation sits in the middle of its shuffled distribution. The placebo, inventory
from two dates later and so dated after the outcome it is asked to predict, comes closer
to significance than any genuine predictor, at *t* = {{PredPlaceboT}}: here a *t* near two
arises without any forward information. No genuine estimate gets close; the largest
|*t*| among them, across every specification below, is {{PredMaxAbsT}}.

Longer horizons say the same: mean |r| over the next 3, 5 and 10 sessions gives
*t* = {{PredHorizonThreeT}}, {{PredHorizonFiveT}} and {{PredHorizonTenT}}. Keeping only the
tenth of underlying-days with the largest inventory changes gives *t* = {{PredDecileT}}.
The close-to-close return includes an overnight move that partly precedes the report;
the open-to-close return of the day it becomes usable gives *t* = {{PredOpenCloseT}}. The
minimum detectable effect at 80% power is {{PredInnovMDE}} basis points per log point of
innovation, {{PredMDEShare}} of the mean next-day |r| of {{PredMeanAbsRet}} basis points.

Loading the panel from later start dates moves the estimates, not the conclusion:

| panel loaded from | underlying-days | inventory innovation | placebo |
|---|---:|---:|---:|
| {{PredWindowOneStart}} (table above) | {{PredWindowOneDays}} | {{PredWindowOneBeta}} (*t* {{PredWindowOneT}}) | {{PredWindowOnePlaceboBeta}} (*t* {{PredWindowOnePlaceboT}}) |
| {{PredWindowTwoStart}} | {{PredWindowTwoDays}} | {{PredWindowTwoBeta}} (*t* {{PredWindowTwoT}}) | {{PredWindowTwoPlaceboBeta}} (*t* {{PredWindowTwoPlaceboT}}) |
| {{PredWindowThreeStart}} | {{PredWindowThreeDays}} | {{PredWindowThreeBeta}} (*t* {{PredWindowThreeT}}) | {{PredWindowThreePlaceboBeta}} (*t* {{PredWindowThreePlaceboT}}) |

Not ruled out: strike-local effects, intraday responses, and effects on the listed option
surface rather than the underlying. Each needs data that cannot be collected
retrospectively for free. The first version of this test, on a shorter panel, is kept in
[`docs/log/`](docs/log/2026-08-19-predictive-result.md).

## Two measurement results that travel

**FLEX cannot be found by its strikes.** Listed strikes sit on a grid, so an off-grid
strike looks like a FLEX tell. Scored against the OCC report over 486,895 cleared series,
that rule has precision 0.67 and recall 0.34. FLEX is routinely struck *on* the grid —
`1AAON` at \$99.00 is FLEX — so two thirds of it is invisible to any strike-based test,
and a third of what the rule flags is not FLEX at all. This project used the rule first;
the superseded census is kept as it was in
[`docs/log/2026-08-18-flex-census.md`](docs/log/2026-08-18-flex-census.md).

**A cleared series is not a position.** Open interest is reported per series, and
positions span series. Conflating them produced errors in both directions that do not
cancel:

- a butterfly counted leg by leg is credited with **49×** its maximum attainable value;
- a four-leg SPY collar is counted about **3×** over;
- a synthetic long call struck at \$1.87 against a \$765 spot is recorded as **\$7m** of
  strike notional when its exposure is **\$2.9bn**.

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
src/hidden_options/collect/occ_flex.py      OCC FLEX report: fetch, parse, validate
src/hidden_options/collect/backfill.py      fetch the FLEX reports missing for a span of dates
src/hidden_options/measure/flex_panel.py    panel assembly and inventory measures
src/hidden_options/measure/structures.py    leg grouping and valuation on the underlying
src/hidden_options/predict/                 the predictive panel, regressions and permutation test
src/hidden_options/publish/                 results/ to the paper's numbers and tables and this README
src/hidden_options/collect/                 chains, holdings, bars and N-PORT collectors
scripts/                                    scheduling, one-off back-fills, reproduce.sh
docs/                                       how the data is collected; the template for this README
docs/log/                                   superseded work and corrections, dated, as written
archive/                                    the scripts behind the log's results
```

The earlier strike-heuristic census is rebuilt by `scripts/reproduce.sh`; the write-ups
of what was tried and what replaced it are indexed in [`docs/log/`](docs/log/README.md),
and the scripts that produced them in [`archive/`](archive/README.md). Raw snapshots
from the collectors are vendor-sourced and not redistributed here; the scheduled capture
is described in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## License

MIT for the code.
