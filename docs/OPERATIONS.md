# Operations — scheduled capture

Most of what is collected cannot be recovered once it ages out, so it is accumulated
daily rather than downloaded. One source is the exception.

| source | what it captures | recoverable later? |
|---|---|---|
| `holdings` | issuer fund holdings files | no, issuers overwrite them in place |
| `cboe` | listed option chains | no, only the current chain is served |
| `occ` | OCC series open interest | no, only the current state is served |
| `bars` | underlying price bars | only a shallow window |
| `flex` | OCC FLEX open-interest report, equity and index classes | yes, OCC keeps about twenty months |

The `flex` source runs with the others every night. Each run asks for every weekday of
the last seven days it does not yet hold and files each report under the activity date
the report states, not the date it was fetched. OCC publishes overnight, so a run at the
close of day *T* usually finds *T* not out yet and a later run catches up. The same
report can also be backfilled by hand:

```bash
hidden-options backfill-flex --start YYYY-MM-DD   # skips dates already held
```

Because OCC keeps only about twenty months, the reports already collected are archived
(see [The FLEX archive](#the-flex-archive)).

## Scheduled capture

There are two collectors. Either one runs `hidden-options collect`, all five sources.

**Primary: the `daily-capture` workflow.** A GitHub Actions workflow in the private
repository `ITheClixs/known-flow-alpha-data`, at 23:30 UTC Monday to Friday. It checks
out this code, runs the collector, and stores each day as a `.tar.zst` asset on a
monthly release tag (`data-YYYY-MM`) in that repository. It refuses to publish if fewer
than 80% of the snapshots were captured, and it can be started by hand, choosing which
sources to run. The raw snapshots are vendor-sourced and are not redistributed, so this
public repository contains code and derived results only.

**Secondary: the `local.hidden-options.collect` launchd job.** An optional second,
independent capture on a Mac, which runs `scripts/collect_daily.sh` at 23:15 local time,
Monday to Friday. Local time is chosen to land after the US close from a Central
European machine; adjust the schedule in the plist for another zone.

```bash
scripts/install_launchd.sh           # install or reinstall
scripts/install_launchd.sh --uninstall
```

Do not render the plist template in place — the installer writes a temporary copy so
that no machine-specific path enters version control. The job logs to `logs/`.

To rebuild the panel yourself, run the collector (`hidden-options collect --root data/raw`)
on your own schedule.

## Getting the captures back

With access to the private store:

```bash
scripts/fetch_captures.sh            # all months
scripts/fetch_captures.sh 2026-08    # one month
```

With no argument the script lists the store's releases and takes those tagged
`data-YYYY-MM`. The `flex-archive` release is not a month and is left out; it is
restored separately, below.

The hidden-share analysis reads each CI run on its own, beside the local captures, and
checks the two against each other, so it needs the runs kept apart rather than merged.
`scripts/fetch_captures.sh --ci-captures` (optionally with months) unpacks every run into
`data/ci_captures/<run date>/raw`, keeping only the series-search open interest and the
Cboe chains, and leaves `data/raw` alone. `hidden-options results` refuses to compute the
hidden share without that folder, or with other runs than the committed result used;
`--local-only` computes without them and marks the result, `--accept-ci-runs` accepts the
runs on disk.

## The FLEX archive

The `flex-archive` release in the same private store holds the OCC FLEX reports as
collected, one `flex-YYYY-MM.tar.zst` per activity month from December 2024 to August
2026, with a `SHA256SUMS` file. OCC will not serve those dates again once they age out,
so these are the copies of record. To restore them:

```bash
gh release download flex-archive -R ITheClixs/known-flow-alpha-data --dir tmp/flex-archive
(cd tmp/flex-archive && shasum -a 256 -c SHA256SUMS)    # every line must say OK
for archive in tmp/flex-archive/flex-*.tar.zst; do
  tar --use-compress-program="zstd -d" -xf "$archive" -C data/raw
done
```

## Operational notes

Scheduled workflows are disabled after 60 days of repository inactivity, so check the
schedule is still enabled after any quiet period. The local job accumulates roughly
18 MB per trading day on disk; prune `data/raw` once the corresponding release assets
are confirmed. After any multi-day absence of the local machine, check the manifests in
`data/raw/manifests/` for gaps: launchd runs a missed job once on wake, but not one
missed while the machine stayed off past the next slot.
