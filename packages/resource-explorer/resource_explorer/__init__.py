"""Resource Explorer — multi-agent RAG reference implementation for GitHub projects."""

import os

# Guard against the ephemeral-Prefect-server leak found 2026-09-04 (13
# orphaned `prefect.server.api.server:create_app` subprocess servers, days
# old, reparented to launchd). Root cause: Prefect's own client starts an
# ephemeral in-process subprocess server whenever
# PREFECT_SERVER_EPHEMERAL_ENABLED is true (Prefect's shipped default
# profile sets it true) and no PREFECT_API_URL is reachable — and nothing
# shuts that subprocess down. Set here, at package import time, rather than
# only in surveyors/prefect_adapter.py, because more than one module under
# this package imports `prefect` directly (e.g. web/routes/prefect_status.py
# imports `prefect.client.orchestration` on its own, independent of
# prefect_adapter.py's import order) — this is the one place guaranteed to
# run before any of them. See PrefectConfig.enabled's docstring in config.py
# and prefect_adapter.py for the full explanation.
# setdefault() so an operator who deliberately wants ephemeral-server
# behavior can still override it via their own environment.
os.environ.setdefault("PREFECT_SERVER_EPHEMERAL_ENABLED", "false")

__version__ = "0.1.0"
