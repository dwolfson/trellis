"""Unit tests for MLflow tracker URI resolution and fail-fast behaviour."""

import socket
import time
from pathlib import Path

import pytest

from advisor import config as advisor_config
from advisor.config import resolve_mlflow_tracking_uri, DEFAULT_MLFLOW_TRACKING_URI
from advisor.mlflow_tracking import MLflowTracker


def _unused_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_unreachable_tracking_uri_fails_fast(monkeypatch):
    monkeypatch.setattr(advisor_config.settings, "mlflow_enable_tracking", True)
    uri = f"http://127.0.0.1:{_unused_port()}"

    start = time.monotonic()
    tracker = MLflowTracker(tracking_uri=uri, enable_resource_monitoring=False)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, f"MLflowTracker init took {elapsed:.2f}s against an unreachable URI"
    assert tracker.enabled is False
    assert tracker.tracking_uri == uri


def test_resolve_uri_env_wins(monkeypatch, tmp_path: Path):
    yaml_path = tmp_path / "advisor.yaml"
    yaml_path.write_text("observability:\n  mlflow:\n    tracking_uri: http://yaml-host:1\n")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://env-host:2")
    assert resolve_mlflow_tracking_uri(yaml_path) == "http://env-host:2"


def test_resolve_uri_yaml_over_default(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    yaml_path = tmp_path / "advisor.yaml"
    yaml_path.write_text("observability:\n  mlflow:\n    tracking_uri: http://yaml-host:1\n")
    assert resolve_mlflow_tracking_uri(yaml_path) == "http://yaml-host:1"


def test_resolve_uri_default_when_nothing_configured(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    assert resolve_mlflow_tracking_uri(tmp_path / "missing.yaml") == DEFAULT_MLFLOW_TRACKING_URI


def test_shipped_yaml_and_default_agree(monkeypatch):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    assert resolve_mlflow_tracking_uri() == DEFAULT_MLFLOW_TRACKING_URI
