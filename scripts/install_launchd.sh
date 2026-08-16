#!/usr/bin/env bash
# Install (or reinstall) the local launchd capture job on macOS.
#
# The plist in this directory is a template containing REPLACE_WITH_PROJECT_DIR.
# Rendering it in place would bake a machine-specific absolute path into a tracked
# file, so this script renders to a temporary copy and installs that, leaving the
# template untouched.
#
# The local job is optional and redundant with the GitHub Actions capture. It is
# worth having as a second, independent capture of sources that cannot be
# back-filled, but it is not the primary collector.
#
# Usage:
#   scripts/install_launchd.sh            # install or reinstall
#   scripts/install_launchd.sh --uninstall

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="${PROJECT_DIR}/scripts/local.absorb.collect.plist"
LABEL="local.absorb.collect"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "launchd is macOS-only. On Linux use cron or a systemd timer." >&2
  exit 1
fi

unload_if_present() {
  if launchctl list | grep -q "${LABEL}"; then
    launchctl unload -w "${TARGET}" 2>/dev/null || true
  fi
}

if [[ "${1:-}" == "--uninstall" ]]; then
  unload_if_present
  rm -f "${TARGET}"
  echo "Removed ${LABEL}"
  exit 0
fi

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "Template not found at ${TEMPLATE}" >&2
  exit 1
fi

if [[ ! -x "${PROJECT_DIR}/.venv/bin/absorb-collect" ]]; then
  echo "absorb-collect not installed. Run: uv venv && uv pip install -e '.[dev]'" >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${PROJECT_DIR}/logs"

rendered="$(mktemp -t absorb-plist)"
trap 'rm -f "${rendered}"' EXIT
sed "s|REPLACE_WITH_PROJECT_DIR|${PROJECT_DIR}|g" "${TEMPLATE}" >"${rendered}"

if ! plutil -lint "${rendered}" >/dev/null; then
  echo "Rendered plist is malformed; not installing." >&2
  exit 1
fi

unload_if_present
cp "${rendered}" "${TARGET}"
launchctl load -w "${TARGET}"

echo "Installed ${LABEL}"
launchctl list | grep "${LABEL}" || true
echo
echo "Schedule is 23:15 local time, Mon-Fri. That is 17:15 US Eastern from a"
echo "Central European machine in both summer and winter. Adjust the"
echo "StartCalendarInterval entries in the template if you are in another zone."
echo "Logs: ${PROJECT_DIR}/logs/"
