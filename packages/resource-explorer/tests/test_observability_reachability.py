"""Optional observability backends must turn themselves off, not slow everything down.

Both MLflow and Phoenix default to enabled, pointing at a localhost port, and
both degrade badly rather than quickly when nothing is listening. Measured
2026-08-24:

  * mlflow.set_experiment() retries six times with exponential backoff while
    holding mlflow's global _experiment_lock. This hung CI's integration step
    until the job timeout killed it, reporting only "The operation was
    canceled" — pytest-timeout is what turned that into a named stack.
  * An OTLP SimpleSpanProcessor exports synchronously on span end: 7.89s for a
    single span against a dead collector, on the traced code path. With
    BatchSpanProcessor the same ten spans cost 0.000s there.

Neither reproduced on a developer machine, because MLflow really does run on
localhost:5025 here. That is the same shape as the platform-split uvloop pin
and the uncached embedding model — things that work everywhere they are
developed and nowhere else.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

from resource_explorer.observability import reachability


@pytest.fixture(autouse=True)
def _clear_cache():
    reachability.reset_cache()
    yield
    reachability.reset_cache()


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


class TestEndpointReachable:
    def test_a_listening_port_is_reachable(self, listening_port):
        assert reachability.endpoint_reachable(f"http://127.0.0.1:{listening_port}") is True

    def test_a_dead_port_is_not(self):
        assert reachability.endpoint_reachable("http://127.0.0.1:9") is False

    def test_a_dead_port_resolves_fast(self):
        """The whole point: finding out must be cheap. Anything approaching the
        1s timeout here would mean the check itself is the new problem."""
        start = time.time()
        reachability.endpoint_reachable("http://127.0.0.1:9")
        assert time.time() - start < 1.0

    def test_a_file_store_needs_no_server(self):
        """MLflow against a local file:// store is perfectly usable with nothing
        listening anywhere — refusing it would disable a working setup."""
        assert reachability.endpoint_reachable("file:///tmp/mlruns") is True
        assert reachability.endpoint_reachable("/tmp/mlruns") is True

    def test_the_result_is_cached(self, listening_port):
        url = f"http://127.0.0.1:{listening_port}"
        reachability.endpoint_reachable(url)
        # Second call must not re-probe — patch the connect to prove it.
        import unittest.mock as mock
        with mock.patch("socket.create_connection", side_effect=AssertionError("re-probed")):
            assert reachability.endpoint_reachable(url) is True


class TestBackendsAreGated:
    def test_mlflow_skips_when_unreachable(self, monkeypatch):
        from resource_explorer.observability import mlflow_tracking

        monkeypatch.setattr(mlflow_tracking, "endpoint_reachable", lambda *_a, **_k: False)

        def _boom(*_a, **_k):
            raise AssertionError("mlflow was touched despite an unreachable server")

        monkeypatch.setitem(__import__("sys").modules, "mlflow", type("M", (), {
            "set_tracking_uri": staticmethod(_boom),
            "set_experiment": staticmethod(_boom),
        })())
        mlflow_tracking.log_query(query="q", intent="i", resource_slug=None,
                                  response="r", latency_ms=1, collections_used=[])

    def test_phoenix_skips_when_unreachable(self, monkeypatch):
        from resource_explorer.observability import phoenix_client

        monkeypatch.setattr(phoenix_client, "_initialized", False)
        monkeypatch.setattr(phoenix_client, "endpoint_reachable", lambda *_a, **_k: False)
        phoenix_client.init_phoenix()
        assert phoenix_client._initialized is False, (
            "init_phoenix must not mark itself initialized against a dead collector — "
            "doing so hands every later span an endpoint that costs seconds to fail"
        )
