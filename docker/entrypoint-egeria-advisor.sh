#!/usr/bin/env bash
# Entrypoint for trellis/egeria-advisor. Dispatches on the first arg to a
# process role, mapped onto egeria-advisor's existing [project.scripts]
# (packages/egeria-advisor/pyproject.toml): egeria-advisor-web,
# egeria-advisor, egeria-advisor-plans. Everything after the role is passed
# through to the underlying command untouched.
#
# EA has no `worker` or `tui` role today (docs/runtime-architecture-plan.md
# §2/§5 sequencing brings the worker-role pattern to EA only after it is
# proven in resource-explorer, and EA has no Textual TUI at all) — those
# names are accepted here so the failure is a clear message instead of
# "command not found", not because the role exists.
set -euo pipefail

ROLE="${1:-web}"
[ $# -gt 0 ] && shift

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8880}"

run_web() {
    local help_text=""
    help_text="$(egeria-advisor-web --help 2>&1 || true)"
    local args=(--host "$HOST" --port "$PORT")
    # egeria-advisor-web defaults --reload/--no-reload to reload ON (dev
    # ergonomics) — a container image should not watch the filesystem for
    # changes by default; force --no-reload unless explicitly overridden.
    if [ "${RELOAD:-0}" = "1" ] || [ "${RELOAD:-}" = "true" ]; then
        args+=(--reload)
    else
        args+=(--no-reload)
    fi
    exec egeria-advisor-web "${args[@]}" "$@"
}

run_cli() {
    exec egeria-advisor "$@"
}

run_plans() {
    exec egeria-advisor-plans "$@"
}

run_unsupported() {
    local role="$1"
    echo "[entrypoint] role '$role' does not exist in egeria-advisor today." >&2
    case "$role" in
        worker)
            echo "The worker role (background loops) is planned for EA after it lands in" >&2
            echo "resource-explorer first — see docs/runtime-architecture-plan.md, Sequencing step 5." >&2
            ;;
        tui)
            echo "egeria-advisor has no Textual TUI; use 'cli' for the interactive REPL" >&2
            echo "(egeria-advisor's Click CLI has a one-shot query mode, a REPL and an agent REPL)." >&2
            ;;
    esac
    exit 1
}

case "$ROLE" in
    web)   run_web "$@" ;;
    cli)   run_cli "$@" ;;
    plans) run_plans "$@" ;;
    worker|tui) run_unsupported "$ROLE" ;;
    *)
        echo "Unknown role '$ROLE'." >&2
        echo "Usage: docker run ... trellis/egeria-advisor:local {web|cli|plans} [args...]" >&2
        exit 1
        ;;
esac
