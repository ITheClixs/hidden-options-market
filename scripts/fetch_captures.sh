#!/usr/bin/env bash
# Download captured days from the private GitHub Releases store into ./data/raw.
#
# Captures are published as one asset per trading day under a monthly release tag
# (data-YYYY-MM) in a private repository, because the raw snapshots are
# vendor-sourced and not redistributable. Access to that repository is required;
# set KFA_DATA_REPO to use a different store. This pulls them back down and unpacks
# them, so a fresh clone can reconstruct the full panel with one command.
#
# Usage:
#   scripts/fetch_captures.sh                 # every month available
#   scripts/fetch_captures.sh 2026-08         # one month
#   scripts/fetch_captures.sh 2026-08 2026-09 # several
#
# With --ci-captures the same archives are kept apart instead, for the hidden-share
# analysis, which reads each CI run beside the local captures and checks them against
# each other: every archive is unpacked into its own data/ci_captures/<run date>/raw,
# keeping only the series-search open interest and the Cboe chains, and data/raw is not
# touched. Runs already unpacked are left as they are.
#   scripts/fetch_captures.sh --ci-captures             # every month available
#   scripts/fetch_captures.sh --ci-captures 2026-09     # one month

set -euo pipefail

mode="merge"
if [[ "${1:-}" == "--ci-captures" ]]; then
  mode="ci"
  shift
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="${PROJECT_DIR}/tmp/captures"
DATA_REPO="${KFA_DATA_REPO:-ITheClixs/known-flow-alpha-data}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required: https://cli.github.com" >&2
  exit 127
fi

if [[ $# -gt 0 ]]; then
  months=("$@")
else
  # Month releases are tagged data-YYYY-MM. The store also holds a flex-archive release
  # (the OCC FLEX reports, see docs/OPERATIONS.md); it is not a month and is left out.
  mapfile -t months < <(
    gh release list -R "${DATA_REPO}" --limit 200 --json tagName --jq '.[].tagName' |
      grep -E '^data-[0-9]{4}-[0-9]{2}$' |
      sed 's/^data-//' |
      sort
  )
fi

if [[ ${#months[@]} -eq 0 ]]; then
  echo "No capture releases found." >&2
  exit 1
fi

if [[ "${mode}" == "ci" ]]; then
  CI_DIR="${CI_CAPTURES_DIR:-${PROJECT_DIR}/data/ci_captures}"
  ARCHIVES="${CI_DIR}/archives"
  mkdir -p "${ARCHIVES}"
  for month in "${months[@]}"; do
    echo "==> data-${month}"
    gh release download "data-${month}" -R "${DATA_REPO}" --dir "${ARCHIVES}" \
      --pattern '*.tar.zst' --skip-existing || echo "    no assets for data-${month}" >&2
  done
  for archive in "${ARCHIVES}"/*.tar.zst; do
    [[ -e "${archive}" ]] || continue
    name="$(basename "${archive}" .tar.zst)"
    run="${name##*-raw-}"
    if [[ ! "${run}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
      echo "    ${name}: no run date in the name, skipped" >&2
      continue
    fi
    [[ -d "${CI_DIR}/${run}/raw" ]] && continue
    # The archives come from outside this repository: refuse absolute or parent paths.
    if zstd -dc "${archive}" | tar -tf - | grep -qE '^/|(^|/)\.\.(/|$)'; then
      echo "    ${name}: unsafe paths, skipped" >&2
      continue
    fi
    partial="${CI_DIR}/${run}.partial"
    rm -rf "${partial}"
    mkdir -p "${partial}"
    zstd -dc "${archive}" | tar -xf - -C "${partial}"
    find "${partial}/raw" -mindepth 1 -maxdepth 1 \
      ! -name occ_open_interest ! -name cboe_chain -exec rm -rf {} +
    mv "${partial}" "${CI_DIR}/${run}"
    echo "    ${run}"
  done
  echo
  echo "CI runs present: $(find "${CI_DIR}" -mindepth 1 -maxdepth 1 -type d -name '20*' | wc -l)"
  exit 0
fi

mkdir -p "${STAGING}" "${PROJECT_DIR}/data/raw"

for month in "${months[@]}"; do
  tag="data-${month}"
  echo "==> ${tag}"
  rm -rf "${STAGING:?}/${month}"
  mkdir -p "${STAGING}/${month}"

  if ! gh release download "${tag}" -R "${DATA_REPO}" --dir "${STAGING}/${month}" --pattern '*.tar.zst' --clobber; then
    echo "    no assets for ${tag}, skipping" >&2
    continue
  fi

  for archive in "${STAGING}/${month}"/*.tar.zst; do
    [[ -e "${archive}" ]] || continue
    # Archives contain a top-level 'raw/' directory; unpack into data/ to merge by
    # date partition. Existing days are overwritten, which is intended: a re-run of
    # the same day supersedes the earlier partial capture.
    tar --use-compress-program="zstd -d" -xf "${archive}" -C "${PROJECT_DIR}/data"
    echo "    $(basename "${archive}")"
  done
done

echo
echo "Days present:"
find "${PROJECT_DIR}/data/raw/cboe_chain" -maxdepth 1 -type d -name 'date=*' 2>/dev/null |
  sed 's/.*date=//' | sort | tr '\n' ' '
echo
