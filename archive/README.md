# Archive

The scripts that produced the results in the [research log](../docs/log/README.md),
kept so those results can be reproduced and checked. They are not maintained. They are
linted but not type-checked, and nothing in the package imports them.

They use `hidden_options.*` directly, so `pip install -e .` is all the setup they need.
Run them from the repository root; paths such as `data/raw` and `configs/` are relative
to it. They read the collected data and live endpoints as they stood in August 2026, so
a re-run on today's data will not return the log's figures: the 60-day intraday window,
in particular, has moved on.

| script | reproduces | notes |
|---|---|---|
| `run_stage1.py` | [stage1-result](../docs/log/2026-08-17-stage1-result.md), first section: the Stage 1 volume difference-in-differences, run against the thresholds fixed in [pilot-spec](../docs/log/2026-08-17-pilot-spec.md). | Defines the panel builders that the next two scripts import. |
| `run_stage1_v2.py` | [stage1-result](../docs/log/2026-08-17-stage1-result.md), "Stage 1 v2": dose from the N-PORT net-asset series and a scan of all five weekdays. | Needs the output of `scripts/fetch_nport.py`. It imports `run_stage1`, so the two files stay together. Its dose-permutation check is the one the entry records as not run. |
| `run_intraday.py` | [intraday-result](../docs/log/2026-08-18-intraday-result.md), first specification: dose by time-of-day, the one the entry shows to be confounded by clientele. | Also imports `run_stage1`. The within-name close-hour test the entry treats as identified is not in this script. |
| `flex_census.py` | [flex-census](../docs/log/2026-08-18-flex-census.md), first section: collects OCC series open interest for every optionable symbol. | The census itself is built from that output in step 4 of `scripts/reproduce.sh`. |
| `verify_attribution.py` | [flex-census](../docs/log/2026-08-18-flex-census.md), "Attribution": searches EDGAR for each predicted strike and opens every candidate N-PORT filing to read the position. | Reads `data/flex_census.parquet`, which `scripts/reproduce.sh` writes. |
| `implied_hedging.py` | No log entry quotes it. It sizes the rehedge the income programmes imply from their disclosed legs, and bears on the volume tests in [stage1-result](../docs/log/2026-08-17-stage1-result.md) and [intraday-result](../docs/log/2026-08-18-intraday-result.md). | See below. |

## What the log does not contain

Some results in the log have no committed script: the positive controls and
randomization inference at the end of the Stage 1 entry (the commit that recorded them
changed only documents), and the within-name close-hour test in the intraday entry.
Their numbers are as reported in the log and cannot be regenerated from this repository.

## The calculation that came after the tests

`implied_hedging.py` should have been run before the volume tests, and was run after
them. A fund's synthetic long is a forward by put-call parity and carries no gamma, so
the dealer hedges it once and does not rebalance it; only the written call overlay
generates rebalancing, and it is written as spreads. Notional is attached to the part of
the position that produces no ongoing flow.

The message of commit `76f79d3`, which records its result, gives a rehedge of 0.00% to
0.65% of daily dollar volume for a 1% move across 24 programmes, median 0.09%, against a
minimum detectable effect about an order of magnitude larger, and concludes that the
volume nulls are corroboration rather than a test of the hedging mechanism. The tight
bound claimed in the [reframing](../docs/log/2026-08-18-reframing.md), written half an
hour earlier, should be read with that in mind. The figures are quoted from the commit
message; the script needs the collected holdings and chains, which are not in this
repository, and has not been re-run for this archive.
