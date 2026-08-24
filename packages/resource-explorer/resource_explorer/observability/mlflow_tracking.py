"""Non-blocking MLflow experiment logging — runs in a background daemon thread."""
from __future__ import annotations

from resource_explorer.config import get_config
from resource_explorer.observability.reachability import endpoint_reachable


def log_query(
    query: str,
    intent: str,
    project_slug: str | None,
    response: str,
    latency_ms: int,
    collections_used: list[str],
) -> None:
    cfg = get_config().observability.mlflow
    if not cfg.enabled or not endpoint_reachable(cfg.tracking_uri):
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
