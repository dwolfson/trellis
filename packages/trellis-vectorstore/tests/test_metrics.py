from __future__ import annotations

import math

import pytest

from trellis_vectorstore.metrics import COSINE, L2, METRICS, MetricStrategy, resolve_metric


def test_cosine_strategy_shape():
    assert COSINE.distance_op == "<=>"
    assert COSINE.index_ops == "vector_cosine_ops"
    assert COSINE.score_fn(0.0) == 1.0
    assert COSINE.score_fn(0.5) == 0.5


def test_l2_strategy_shape():
    assert L2.distance_op == "<->"
    assert L2.index_ops == "vector_l2_ops"
    assert L2.score_fn(0.0) == pytest.approx(1.0)
    assert L2.score_fn(1.0) == pytest.approx(math.exp(-1.0))


def test_resolve_metric_by_string_case_insensitive():
    assert resolve_metric("cosine") is COSINE
    assert resolve_metric("COSINE") is COSINE
    assert resolve_metric("l2") is L2


def test_resolve_metric_passthrough_strategy():
    assert resolve_metric(COSINE) is COSINE


def test_resolve_metric_unknown_raises():
    with pytest.raises(ValueError, match="Unknown metric"):
        resolve_metric("manhattan")


def test_metrics_registry_is_immutable():
    with pytest.raises(TypeError):
        METRICS["new"] = COSINE  # type: ignore[index]


def test_metric_strategy_is_frozen():
    with pytest.raises(Exception):
        COSINE.name = "not cosine"  # type: ignore[misc]
