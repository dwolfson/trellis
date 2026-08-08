#!/bin/bash
# Launch the Egeria Advisor web UI.
#
# Always serves plain HTTP on $ADVISOR_HTTP_PORT (default 8880). Additionally
# serves HTTPS on $ADVISOR_HTTPS_PORT (default 8881) when ADVISOR_SSL_CERTFILE
# and ADVISOR_SSL_KEYFILE are set in .env and both files exist -- otherwise
# HTTPS is silently skipped (HTTP-only, e.g. plain local dev).
#
# uvicorn serves exactly one scheme per process, so "both HTTP and HTTPS" means
# two uvicorn processes sharing the same FastAPI app, not one process doing both.
#
# Usage: scripts/run_web.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# Load .env into this shell (same values advisor.config.settings would see)
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

HOST="${ADVISOR_BIND_HOST:-0.0.0.0}"
HTTP_PORT="${ADVISOR_HTTP_PORT:-8880}"
HTTPS_PORT="${ADVISOR_HTTPS_PORT:-8881}"

PIDS=()
cleanup() {
    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

uvicorn advisor.web.app:app --host "$HOST" --port "$HTTP_PORT" &
PIDS+=("$!")
echo "HTTP  → http://${HOST}:${HTTP_PORT} (pid ${PIDS[-1]})"

if [ -n "${ADVISOR_SSL_CERTFILE:-}" ] && [ -n "${ADVISOR_SSL_KEYFILE:-}" ] \
   && [ -f "${ADVISOR_SSL_CERTFILE}" ] && [ -f "${ADVISOR_SSL_KEYFILE}" ]; then
    uvicorn advisor.web.app:app --host "$HOST" --port "$HTTPS_PORT" \
        --ssl-certfile "$ADVISOR_SSL_CERTFILE" --ssl-keyfile "$ADVISOR_SSL_KEYFILE" &
    PIDS+=("$!")
    echo "HTTPS → https://${HOST}:${HTTPS_PORT} (pid ${PIDS[-1]})"
else
    echo "HTTPS → not started (set ADVISOR_SSL_CERTFILE and ADVISOR_SSL_KEYFILE in .env to enable)"
fi

wait
