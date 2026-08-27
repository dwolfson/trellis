#!/usr/bin/env bash
# Stops exactly what scripts/prefect_up.sh started (tracked via .prefect-run/*.pid).
# Does nothing to a Prefect server/worker that script didn't start itself.
set -euo pipefail

cd "$(dirname "$0")/.."  # packages/resource-explorer/
STATE_DIR=".prefect-run"

_stop() {
  local name="$1"
  local pidfile="$STATE_DIR/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    kill "$(cat "$pidfile")"
    echo "✓ Stopped $name (pid $(cat "$pidfile"))"
  else
    echo "- $name not running (or not started by prefect_up.sh)"
  fi
  rm -f "$pidfile"
}

_stop worker
_stop server
