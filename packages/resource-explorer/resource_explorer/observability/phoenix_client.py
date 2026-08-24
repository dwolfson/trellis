"""Arize Phoenix / OpenTelemetry tracing — follows lfai/ML_LLM_Ops pattern."""
from __future__ import annotations

from resource_explorer.config import get_config
from resource_explorer.observability.reachability import endpoint_reachable

_initialized = False


def init_phoenix() -> None:
    """Initialize BeeAI → Phoenix tracing. Call once at startup."""
    global _initialized
    if _initialized:
        return
    cfg = get_config().observability.phoenix
    if not cfg.enabled:
        return
    # Constructing OTLPSpanExporter does not connect, so this init used to
    # "succeed" with no collector listening and hand every later span a dead
    # endpoint. Measured 2026-08-24: 7.89s to export ONE span against a dead
    # collector, retries included — paid on the traced code path, per span.
    if not endpoint_reachable(cfg.collector_endpoint):
        return
    try:
        from openinference.instrumentation.beeai import BeeAIInstrumentor
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider()
        # BatchSpanProcessor, not SimpleSpanProcessor: Simple exports
        # synchronously on every span end, so a collector that goes away AFTER
        # this init — which the reachability check above cannot predict — puts
        # its retry cost directly on whatever is being traced. Batch exports on
        # its own background thread, which is what rule 4 ("observability runs
        # in background threads — never block the response") actually requires.
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.collector_endpoint))
        )
        trace.set_tracer_provider(provider)
        BeeAIInstrumentor().instrument()
        _initialized = True
    except ImportError:
        pass  # Phoenix not installed — tracing disabled silently
    except Exception:
        pass  # Phoenix not running — tracing disabled silently
