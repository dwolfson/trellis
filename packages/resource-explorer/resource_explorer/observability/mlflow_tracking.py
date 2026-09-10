"""Non-blocking MLflow experiment logging — runs in a background daemon thread."""
from __future__ import annotations

import logging

from resource_explorer.config import get_config
from resource_explorer.observability.reachability import endpoint_reachable

log = logging.getLogger(__name__)


def _usage_metrics(usage: dict | None) -> tuple[dict, dict]:
    """(metrics, params) for one `llm_usage.LlmUsage.as_dict()`, or ({}, {}).

    MLflow splits numbers from strings, and the split matters for reading these
    back: token counts are metrics so they aggregate, while `llm_usage_complete`
    and the model list are params so they filter. A run whose usage is a floor
    rather than a measurement must be *excludable* by query, which is what
    `llm_usage_complete` is for — see `llm_usage`'s three-state docstring.

    `llm_uncounted_calls` is logged as a metric even though it is usually zero,
    deliberately: a metric absent from a run is indistinguishable from a metric
    that was zero, and this is precisely the number a reader needs in order to
    trust the total.
    """
    if not usage:
        return {}, {}
    metrics = {
        k: v for k, v in usage.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    params = {"llm_usage_complete": usage.get("llm_usage_complete", True),
              "llm_models": ",".join(usage.get("llm_models") or []) or "none"}
    return metrics, params


def log_query(
    query: str,
    intent: str,
    resource_slug: str | None,
    response: str,
    latency_ms: int,
    collections_used: list[str],
    usage: dict | None = None,
) -> None:
    """One RAG query. `usage` is `llm_usage.LlmUsage.as_dict()` when the caller
    scoped the call — optional, because a cache hit makes no LLM call at all and
    logging zeros for it would put a free answer in the same population as a
    paid one."""
    cfg = get_config().observability.mlflow
    if not cfg.enabled or not endpoint_reachable(cfg.tracking_uri):
        return
    try:
        import mlflow
        mlflow.set_tracking_uri(cfg.tracking_uri)
        mlflow.set_experiment(cfg.experiment_name)
        usage_metrics, usage_params = _usage_metrics(usage)
        with mlflow.start_run():
            mlflow.log_params({
                "intent": intent,
                "project_slug": resource_slug or "all",
                "collections_count": len(collections_used),
                **usage_params,
            })
            mlflow.log_metrics({
                "latency_ms": latency_ms,
                # Characters, not tokens — kept because it predates token
                # accounting and some history is keyed on it, but it is NOT a
                # cost measure and llm_completion_tokens is the one to read.
                "response_length": len(response),
                **usage_metrics,
            })
    except Exception:
        pass  # never block the response path


def log_run_usage(run_id: str, kind: str, usage: dict, *,
                  slug: str = "", analysis_id: str = "") -> None:
    """One queued run's LLM cost — the per-run attribution the funnel-cost
    spec's §1 wanted and wall time could not give it.

    A separate experiment from `log_query`'s: a run and a chat query are
    different populations with different denominators, and pooling them would
    make "median cost per run" quietly include every chat message. Named off the
    configured experiment so a from-scratch environment does not need a second
    setting.

    Called from the worker thread that ran the handler, not from a callback —
    the usage scope is a ContextVar and only code running under it can read it.
    """
    # The config read and the reachability probe are INSIDE the try, unlike
    # log_query above. This function is called from the run worker on a path
    # where the run has already succeeded, so it must be incapable of raising —
    # a caller that has to wrap it in its own try/except becomes a
    # broad-except/log-only/value-returning site itself, which is what the
    # silent-success ratchet correctly flagged the first version for.
    try:
        cfg = get_config().observability.mlflow
        if not cfg.enabled or not endpoint_reachable(cfg.tracking_uri):
            return
        import mlflow
        mlflow.set_tracking_uri(cfg.tracking_uri)
        mlflow.set_experiment(f"{cfg.experiment_name}-runs")
        metrics, params = _usage_metrics(usage)
        with mlflow.start_run(run_name=f"{kind}:{analysis_id or slug or run_id}"):
            mlflow.log_params({
                "run_id": run_id,
                "kind": kind,
                "project_slug": slug or "unknown",
                "analysis_id": analysis_id or "none",
                **params,
            })
            if metrics:
                mlflow.log_metrics(metrics)
    except Exception:
        # Swallowed — a metrics sink must never fail a run that already
        # succeeded — but RECORDED. A silently-dropped sink is how MLflow can
        # sit "enabled" and empty for weeks with nothing to say it stopped;
        # this file's other writer has been bare-`pass` since it was written
        # and that is the shape to move away from, not to copy.
        log.debug("could not record llm usage for run %s (%s)", run_id, kind,
                  exc_info=True)
