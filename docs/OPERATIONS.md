# Operations — scheduled capture

The snapshot sources (listed chains, fund holdings, intraday bars) cannot be recovered
once they age out, so they are accumulated daily rather than downloaded. The OCC FLEX
report is the exception: it can be backfilled with `scripts/backfill_occ_flex.py`.

## Scheduled capture

The primary collector is a `daily-capture` GitHub Actions workflow that runs at
23:30 UTC Mon–Fri in a separate private repository. It checks out this code and
stores each day as a `.tar.zst` asset on a monthly release tag (`data-YYYY-MM`)
there. The raw snapshots are vendor-sourced and are not redistributed, so this
public repository contains code and derived results only. The workflow
refuses to publish if fewer than 80% of symbols were captured.

To rebuild the panel yourself, run the collector (`absorb-collect --root data/raw`)
on your own schedule. With access to the private store, retrieve captures with:

```bash
scripts/fetch_captures.sh            # all months
scripts/fetch_captures.sh 2026-08    # one month
```

A local launchd job is available as an optional second, independent capture:

```bash
scripts/install_launchd.sh           # install or reinstall
scripts/install_launchd.sh --uninstall
```

Do not render the plist template in place — the installer writes a temporary copy so
that no machine-specific path enters version control.

## Operational notes

Scheduled workflows are disabled after 60 days of repository inactivity, so check the
schedule is still enabled after any quiet period. The local job accumulates roughly
18 MB per trading day on disk; prune `data/raw` once the corresponding release assets
are confirmed.
