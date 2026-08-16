#!/usr/bin/env bash
# Download captured days from the GitHub Releases store into ./data/raw.
#
# Captures are published as one asset per trading day under a monthly release tag
# (data-YYYY-MM). This pulls them back down and unpacks them, so a fresh clone can
# reconstruct the full panel with one command.
#
# Usage:
#   scripts/fetch_captures.sh                 # every month available
#   scripts/fetch_captures.sh 2026-08         # one month
#   scripts/fetch_captures.sh 2026-08 2026-09 # several

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="${PROJECT_DIR}/tmp/captures"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required: https://cli.github.com" >&2
  exit 127
fi

if [[ $# -gt 0 ]]; then
  months=("$@")
else
  mapfile -t months < <(
    gh release list --limit 200 |
      awk '{print $1}' |
      grep '^data-' |
      sed 's/^data-//' |
      sort
  )
fi

if [[ ${#months[@]} -eq 0 ]]; then
  echo "No capture releases found." >&2
  exit 1
fi

mkdir -p "${STAGING}" "${PROJECT_DIR}/data/raw"

for month in "${months[@]}"; do
  tag="data-${month}"
  echo "==> ${tag}"
  rm -rf "${STAGING:?}/${month}"
  mkdir -p "${STAGING}/${month}"

  if ! gh release download "${tag}" --dir "${STAGING}/${month}" --pattern '*.tar.zst' --clobber; then
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
