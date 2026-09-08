"""Phoenix tracing must turn itself off, not slow everything down.

Mirrors resource-explorer's tests/test_observability_reachability.py
(TC-4/BACKLOG.md) — same failure mode, EA's own reachability helper. An
OTLP SimpleSpanProcessor exports synchronously on span end: measured in
resource-explorer at 7.89s for a single span against a dead collector. This
never reproduces on a developer machine where Phoenix happens to be running,
which is exactly why it has to be tested rather than just observed.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

from advisor import phoenix_client


@pytest.fixture(autouse=True)
def _clear_cache():
    phoenix_client._reachability_cache.clear()
    phoenix_client._initialized = False
    yield
    phoenix_client._reachability_cache.clear()
    phoenix_client._initialized = False


@pytest.fixture
def listening_port():
    """A real socket, so "reachable" means reachable rather than mocked."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    threading.Thread(target=lambda: srv.accept(), daemon=True).start()
    yield port
    srv.close()


class TestCollectorReachable:
    def test_a_listening_port_is_reachable(self, listening_port):
        assert phoenix_client._is_collector_reachable(f"http://127.0.0.1:{listening_port}") is True

    def test_a_dead_port_is_not(self):
        assert phoenix_client._is_collector_reachable("http://127.0.0.1:9") is False

    def test_a_dead_port_resolves_fast(self):
        """The whole point: finding out must be cheap."""
        start = time.time()
        phoenix_client._is_collector_reachable("http://127.0.0.1:9")
        assert time.time() - start < 1.0

    def test_the_result_is_cached(self, listening_port):
        url = f"http://127.0.0.1:{listening_port}"
        phoenix_client._is_collector_reachable(url)
        import unittest.mock as mock
        with mock.patch("socket.create_connection", side_effect=AssertionError("re-probed")):
            assert phoenix_client._is_collector_reachable(url) is True


class TestInitPhoenixIsGated:
    def test_skips_when_disabled(self, monkeypatch):
        from advisor.config import get_full_config

        cfg = get_full_config()
        cfg["observability"].phoenix.enabled = False
        monkeypatch.setattr("advisor.config.get_full_config", lambda *a, **k: cfg)

        phoenix_client.init_phoenix()
        assert phoenix_client._initialized is False

    def test_skips_when_unreachable(self, monkeypatch):
        from advisor.config import get_full_config

        cfg = get_full_config()
        cfg["observability"].phoenix.enabled = True
        monkeypatch.setattr("advisor.config.get_full_config", lambda *a, **k: cfg)
        monkeypatch.setattr(phoenix_client, "_is_collector_reachable", lambda *_a, **_k: False)

        phoenix_client.init_phoenix()
        assert phoenix_client._initialized is False, (
            "init_phoenix must not mark itself initialized against a dead collector — "
            "doing so hands every later span an endpoint that costs seconds to fail"
        )

    def test_initializes_when_enabled_and_reachable(self, listening_port, monkeypatch):
        from advisor.config import get_full_config

        cfg = get_full_config()
        cfg["observability"].phoenix.enabled = True
        cfg["observability"].phoenix.collector_endpoint = f"http://127.0.0.1:{listening_port}/v1/traces"
        monkeypatch.setattr("advisor.config.get_full_config", lambda *a, **k: cfg)

        phoenix_client.init_phoenix()
        assert phoenix_client._initialized is True

    def test_is_idempotent(self, listening_port, monkeypatch):
        """A second call after a successful init must not re-instrument."""
        from advisor.config import get_full_config

        cfg = get_full_config()
        cfg["observability"].phoenix.enabled = True
        cfg["observability"].phoenix.collector_endpoint = f"http://127.0.0.1:{listening_port}/v1/traces"
        monkeypatch.setattr("advisor.config.get_full_config", lambda *a, **k: cfg)

        phoenix_client.init_phoenix()
        assert phoenix_client._initialized is True

        def _boom(*_a, **_k):
            raise AssertionError("re-instrumented on a second call")

        monkeypatch.setattr("advisor.config.get_full_config", _boom)
        phoenix_client.init_phoenix()  # must return early on the _initialized guard, never reach _boom
