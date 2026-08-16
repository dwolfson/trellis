"""Distance-metric strategies for vector search.

The distance operator and the score-conversion formula must never be set
independently — a store built with the cosine operator but scored with the
L2 formula (or vice versa) would produce numbers that look plausible but
mean nothing. Binding them into one frozen dataclass, registered in an
immutable mapping, makes that mismatch structurally impossible rather than
a discipline problem.

Resource Explorer and Egeria Advisor made different, deliberate choices
here — RE uses cosine (its min_score threshold semantics were calibrated
against Milvus's COSINE/FLAT setup; switching to L2 would silently change
what "score >= threshold" means). EA uses L2. Neither is "more correct" —
PgVectorStore.__init__ takes `metric` as a required keyword argument with
no default specifically so a new store can never silently inherit the
wrong one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping


@dataclass(frozen=True)
class MetricStrategy:
    name: str                 # "cosine" | "l2"
    distance_op: str          # pgvector operator: "<=>" | "<->"
    index_ops: str            # HNSW opclass: "vector_cosine_ops" | "vector_l2_ops"
    score_fn: Callable[[float], float]
    # The pre-extraction string vocabulary each app's create_index() used
    # ("COSINE" | "L2") — kept only so an explicitly-passed metric_type can
    # be compared against the instance's own strategy (see pg.py).
    legacy_metric_type: str


# Cosine distance operator <=> ranges [0, 2]; converted to a
# Milvus-COSINE-compatible similarity score in [-1, 1] via 1 - distance —
# Resource Explorer's existing min_score thresholds were calibrated against
# exactly this conversion under Milvus, before the pgvector migration.
COSINE = MetricStrategy(
    name="cosine", distance_op="<=>", index_ops="vector_cosine_ops",
    score_fn=lambda d: 1.0 - d, legacy_metric_type="COSINE",
)

# L2 (Euclidean) distance operator <->, unbounded above; converted to a
# (0, 1] similarity score via exponential decay — Egeria Advisor's existing
# convention, unrelated to RE's cosine/Milvus calibration.
L2 = MetricStrategy(
    name="l2", distance_op="<->", index_ops="vector_l2_ops",
    score_fn=lambda d: math.exp(-d), legacy_metric_type="L2",
)

METRICS: Mapping[str, MetricStrategy] = MappingProxyType({"cosine": COSINE, "l2": L2})


def resolve_metric(metric: "str | MetricStrategy") -> MetricStrategy:
    if isinstance(metric, MetricStrategy):
        return metric
    try:
        return METRICS[metric.lower()]
    except KeyError:
        raise ValueError(f"Unknown metric {metric!r} — must be one of {sorted(METRICS)}") from None
