"""Arize Phoenix / OpenTelemetry tracing — follows lfai/ML_LLM_Ops pattern."""
from __future__ import annotations

from resource_explorer.config import get_config

_initialized = False


def init_phoenix() -> None:
    """Initialize BeeAI → Phoenix tracing. Call once at startup."""
    global _initialized
    if _initialized:
        return
    cfg = get_config().observability.phoenix
    if not cfg.enabled:
        return
    try:
        from openinference.instrumentation.beeai import BeeAIInstrumentor
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        provider = TracerProvider()
        provider.add_span_processor(
            SimpleSpanProcessor(OTLPSpanExporter(endpoint=cfg.collector_endpoint))
        )
        trace.set_tracer_provider(provider)
        BeeAIInstrumentor().instrument()
        _initialized = True
    except ImportError:
        pass  # Phoenix not installed — tracing disabled silently
    except Exception:
        pass  # Phoenix not running — tracing disabled silently
