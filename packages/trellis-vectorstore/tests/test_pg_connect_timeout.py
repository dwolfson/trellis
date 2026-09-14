"""PgVectorStore.connect() must bound every psycopg2.connect() it makes.

2026-09-13 :8810 incident: ThreadedConnectionPool's underlying
psycopg2.connect() hung — never returned, never raised — with Postgres
itself healthy and reachable from every other process. Nothing bounded
that call, so the worker thread that made it stayed stuck forever.
`connect_timeout` (from PgVectorStoreConfig) is threaded to both the pool
constructor and the bootstrap connection so a hung TCP/DNS/SSL negotiation
raises OperationalError instead.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trellis_vectorstore.config import PgVectorStoreConfig
from trellis_vectorstore.pg import PgVectorStore


class _FakeEmbeddings:
    def embed_texts(self, texts):
        return [[0.0] * 384 for _ in texts]

    def embed_query(self, text):
        return [0.0] * 384


def _store(connect_timeout=10):
    config = PgVectorStoreConfig(
        host="localhost", port=5442, dbname="test", user="u", password="p",
        connect_timeout=connect_timeout,
    )
    return PgVectorStore(config, metric="cosine", embeddings=_FakeEmbeddings())


class TestConnectTimeoutReachesThePool:
    def test_connect_timeout_passed_to_threaded_connection_pool(self):
        store = _store(connect_timeout=7)
        recorded = {}

        def _fake_pool(*args, **kwargs):
            recorded.update(kwargs)
            return MagicMock()

        with patch("trellis_vectorstore.pg.ThreadedConnectionPool", side_effect=_fake_pool), \
             patch("trellis_vectorstore.pg.psycopg2.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = MagicMock()
            mock_connect.return_value.__exit__.return_value = False
            store.connect()

        assert recorded.get("connect_timeout") == 7

    def test_connect_timeout_passed_to_the_bootstrap_connection(self):
        store = _store(connect_timeout=7)

        with patch("trellis_vectorstore.pg.ThreadedConnectionPool", return_value=MagicMock()), \
             patch("trellis_vectorstore.pg.psycopg2.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = MagicMock()
            mock_connect.return_value.__exit__.return_value = False
            store.connect()

        _, kwargs = mock_connect.call_args
        assert kwargs.get("connect_timeout") == 7

    def test_default_is_ten_seconds(self):
        assert PgVectorStoreConfig(
            host="h", port=1, dbname="d", user="u", password="p",
        ).connect_timeout == 10


class TestFailedConnectLeavesPoolNone:
    def test_a_raising_pool_constructor_leaves_pool_none(self):
        store = _store()
        assert store.is_connected() is False

        with patch("trellis_vectorstore.pg.ThreadedConnectionPool",
                   side_effect=Exception("boom: connect timed out")):
            with pytest.raises(Exception, match="boom"):
                store.connect()

        assert store.is_connected() is False
        assert store._pool is None

    def test_a_raising_bootstrap_connection_leaves_pool_none_and_closes_the_pool(self):
        """The pool constructor can succeed (it opens `minconn` connections
        immediately) while the separate bootstrap connect — extension/schema
        setup — still fails; that must not leave a half-open pool sitting in
        self._pool, and must not leak the connections the pool already
        opened."""
        store = _store()
        fake_pool = MagicMock()

        with patch("trellis_vectorstore.pg.ThreadedConnectionPool", return_value=fake_pool), \
             patch("trellis_vectorstore.pg.psycopg2.connect",
                   side_effect=Exception("boom: bootstrap timed out")):
            with pytest.raises(Exception, match="boom"):
                store.connect()

        assert store._pool is None
        fake_pool.closeall.assert_called_once()

    def test_retry_after_a_failed_connect_tries_again_not_reuses_a_broken_pool(self):
        store = _store()
        call_count = {"n": 0}

        def _pool_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("first attempt: connect timed out")
            return MagicMock()

        with patch("trellis_vectorstore.pg.ThreadedConnectionPool", side_effect=_pool_side_effect), \
             patch("trellis_vectorstore.pg.psycopg2.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = MagicMock()
            mock_connect.return_value.__exit__.return_value = False

            with pytest.raises(Exception, match="first attempt"):
                store.connect()
            assert store._pool is None

            store.connect()  # should retry cleanly, not raise or no-op

        assert store.is_connected() is True
        assert call_count["n"] == 2
