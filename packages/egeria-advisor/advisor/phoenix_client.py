"""
Arize Phoenix / OpenTelemetry tracing for Egeria Advisor.

Ported from resource_explorer/observability/phoenix_client.py (TC-4,
BACKLOG.md) — same shape, EA's own config plumbing. Follows the
lfai/ML_LLM_Ops pattern: BeeAI spans exported over OTLP/HTTP to a Phoenix
collector.

Constructing OTLPSpanExporter does not connect, so a naive init "succeeds"
even with no collector listening and hands every later span a dead endpoint.
Measured in resource-explorer (2026-08-24): 7.89s to export ONE span against
a dead collector, retries included — paid on the traced code path, per span.
So this checks reachability once, cheaply, before instrumenting at all, and
turns itself off rather than making every traced call slower to find out
(same posture EA's own MLflow init already takes — see
mlflow_tracking.py's `_is_tracking_server_reachable`).
"""
from __future__ import annotations

import socket
from urllib.parse import urlparse

from loguru import logger

_initialized = False

#: endpoint -> reachable. Resolved once per process per endpoint; an optional
#: backend appearing mid-process is not worth re-probing for on every call.
_reachability_cache: dict[str, bool] = {}


def _is_collector_reachable(endpoint: str, timeout: float = 1.0) -> bool:
    """One cheap TCP connect, remembered for the life of the process."""
    if endpoint in _reachability_cache:
        return _reachability_cache[endpoint]
    try:
        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            _reachability_cache[endpoint] = True
            return True
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            _reachability_cache[endpoint] = True
    except OSError:
        _reachability_cache[endpoint] = False
    return _reachability_cache[endpoint]


def init_phoenix() -> None:
    """Initialize BeeAI -> Phoenix tracing. Call once at startup; safe to
    call more than once (no-ops after the first successful init)."""
    global _initialized
    if _initialized:
        return
    from advisor.config import get_full_config

    cfg = get_full_config()["observability"].phoenix
    if not cfg.enabled:
        return
    if not _is_collector_reachable(cfg.collector_endpoint):
        logger.debug(
            f"Phoenix collector not reachable at {cfg.collector_endpoint} — tracing disabled."
        )
        return
    try:
        from openinference.instrumentation.beeai import BeeAIInstrumentor
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider()
        # BatchSpanProcessor, not SimpleSpanProcessor: Simple exports
        # synchronously on every span end, so a collector that goes away
        # AFTER this init — which the reachability check above cannot
        # predict — puts its retry cost directly on whatever is being
        # traced. Batch exports on its own background thread, matching
        # design rule 4 ("observability runs in background threads — never
        # block the response").
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.collector_endpoint))
        )
        trace.set_tracer_provider(provider)
        BeeAIInstrumentor().instrument()
        _initialized = True
        logger.info(f"Phoenix tracing initialized -> {cfg.collector_endpoint}")
    except ImportError:
        logger.debug("Phoenix tracing deps not installed — tracing disabled.")
    except Exception as exc:
        logger.debug(f"Phoenix tracing init failed ({exc}) — tracing disabled.")
