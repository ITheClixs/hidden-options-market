#!/usr/bin/env bash
# Daily capture of free option-chain, open-interest and fund-holdings snapshots.
#
# These upstream sources are snapshots with no history: issuers overwrite holdings
# files in place and the quote/OI endpoints serve only the current state. A day that
# is not captured is gone permanently, which is why this runs unattended and logs
# every outcome rather than failing fast.
#
# Intended schedule: once per trading day after the close (see launchd plist).

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/collect_$(date +%Y-%m-%d).log"
CLI="${PROJECT_DIR}/.venv/bin/hidden-options"

mkdir -p "${LOG_DIR}"

if [[ ! -x "${CLI}" ]]; then
  echo "$(date -u +%FT%TZ) FATAL hidden-options not found at ${CLI}" >>"${LOG_FILE}"
  exit 127
fi

echo "$(date -u +%FT%TZ) starting collection" >>"${LOG_FILE}"
"${CLI}" collect --root "${PROJECT_DIR}/data/raw" >>"${LOG_FILE}" 2>&1
status=$?
echo "$(date -u +%FT%TZ) finished with exit ${status}" >>"${LOG_FILE}"

# Deliberately exit 0 on partial failure: a run that captured most symbols is far
# more valuable than a retry storm, and the manifest records exactly what was missed.
exit 0
