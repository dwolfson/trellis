"""Non-blocking MLflow experiment logging — runs in a background daemon thread."""
from __future__ import annotations

import socket
from urllib.parse import urlparse

from resource_explorer.config import get_config

#: Tri-state, resolved once per process: None = not yet checked.
_TRACKING_REACHABLE: bool | None = None


def _reachable(tracking_uri: str, timeout: float = 1.0) -> bool:
    """Is the tracking server actually there? Checked once, then remembered.

    mlflow.set_experiment() does not fail fast when it is not. It retries
    through urllib3 (six attempts with exponential backoff) *while holding
    mlflow's global _experiment_lock*, so an absent server costs minutes per
    call rather than an immediate error. The `except Exception: pass` below is
    annotated "never block the response path" and does not achieve that on its
    own — it catches the failure only after all the retries are spent.

    This is not theoretical. CI's integration step hung on exactly this on
    2026-08-24 and was killed by the job timeout; the stack showed a daemon
    thread parked in `with _experiment_lock` under a run of
    "Retrying (Retry(total=6..2))" warnings. It never showed up locally because
    a real MLflow server runs on localhost:5025 on this machine — the same
    local-vs-CI divergence class as the platform-split uvloop pin.

    Same posture as tests/conftest.py's _pgvector_reachable/_egeria_reachable:
    one cheap connect, cached, and the feature turns itself off rather than
    degrading everything around it.
    """
    global _TRACKING_REACHABLE
    if _TRACKING_REACHABLE is not None:
        return _TRACKING_REACHABLE
    try:
        parsed = urlparse(tracking_uri)
        if parsed.scheme in ("", "file") or not parsed.hostname:
            # A local file:// store needs no server and is always usable.
            _TRACKING_REACHABLE = True
            return True
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            _TRACKING_REACHABLE = True
    except Exception:
        _TRACKING_REACHABLE = False
    return _TRACKING_REACHABLE


def log_query(
    query: str,
    intent: str,
    project_slug: str | None,
    response: str,
    latency_ms: int,
    collections_used: list[str],
) -> None:
    cfg = get_config().observability.mlflow
    if not cfg.enabled or not _reachable(cfg.tracking_uri):
        return
    try:
        import mlflow
        mlflow.set_tracking_uri(cfg.tracking_uri)
        mlflow.set_experiment(cfg.experiment_name)
        with mlflow.start_run():
            mlflow.log_params({
                "intent": intent,
                "project_slug": project_slug or "all",
                "collections_count": len(collections_used),
            })
            mlflow.log_metrics({
                "latency_ms": latency_ms,
                "response_length": len(response),
            })
    except Exception:
        pass  # never block the response path
