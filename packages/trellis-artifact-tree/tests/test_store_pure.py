"""Store behaviour, driven against a recording fake rather than a live Postgres.

What matters here is not that SQL executes -- that is Postgres's job -- but the
ordering and transactional guarantees the model depends on: parents inserted
before children (the parent FK is real), a wholesale replace rather than a
merge, and nothing half-written if a reparse fails partway.
"""
from __future__ import annotations

import pytest

from trellis_artifact_tree import (
    ArtifactTree,
    ArtifactTreeConfig,
    ArtifactTreeStore,
    Node,
    Provenance,
    Rung,
    create_schema_sql,
)

PROV = Provenance(source_kind="repo", source_id="amundsen", fetched_at="2026-08-27T00:00:00")


class FakeCursor:
    def __init__(self, log): self.log = log
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.log.append((" ".join(sql.split()), params))
    def fetchone(self): return None
    def fetchall(self): return []


class FakeConn:
    def __init__(self, fail_on: str | None = None):
        self.log: list[tuple[str, object]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._fail_on = fail_on

    def cursor(self):
        outer = self

        class C(FakeCursor):
            def execute(self, sql, params=None):
                flat = " ".join(sql.split())
                if outer._fail_on and outer._fail_on in flat:
                    raise RuntimeError("boom")
                outer.log.append((flat, params))

        return C(self.log)

    def commit(self): self.committed = True
    def rollback(self): self.rolled_back = True
    def close(self): self.closed = True


def store(conn: FakeConn, schema: str | None = "artifact_tree") -> ArtifactTreeStore:
    cfg = ArtifactTreeConfig(
        host="h", port=5432, dbname="d", user="u", password="p", schema=schema
    )
    return ArtifactTreeStore(cfg, connection_factory=lambda: conn)


def sample_tree() -> ArtifactTree:
    return ArtifactTree("a", PROV, (
        Node("r", "a", "document", title="README"),
        Node("s1", "a", "section", parent_id="r", ordinal=0,
             rungs={Rung.FULL: "full", Rung.SUMMARY: "sum"}, chunk_refs=("c1",)),
        Node("s1a", "a", "para", parent_id="s1", ordinal=0),
        Node("s2", "a", "section", parent_id="r", ordinal=1),
    ))


class TestWriteOrdering:
    def test_parents_are_inserted_before_children(self):
        """The parent_id FK is real, so a child inserted first fails. Breadth-
        first from the root gives the ordering, and the tree is known acyclic."""
        conn = FakeConn()
        store(conn).put(sample_tree())
        order = [
            p[0] for sql, p in conn.log
            if sql.startswith('INSERT INTO "artifact_tree"."artifact_node" (')
        ]
        assert order.index("r") < order.index("s1") < order.index("s1a")
        assert order.index("r") < order.index("s2")

    def test_delete_precedes_inserts(self):
        """A wholesale replace, not a merge: a node dropped by a reparse must
        not survive as a stale sibling."""
        conn = FakeConn()
        store(conn).put(sample_tree())
        stmts = [sql for sql, _ in conn.log]
        first_delete = next(i for i, s in enumerate(stmts) if s.startswith("DELETE"))
        first_node_insert = next(
            i for i, s in enumerate(stmts)
            if s.startswith('INSERT INTO "artifact_tree"."artifact_node" (')
        )
        assert first_delete < first_node_insert

    def test_rungs_and_chunks_written_for_their_node(self):
        conn = FakeConn()
        store(conn).put(sample_tree())
        rungs = [p for sql, p in conn.log if "artifact_node_rung" in sql and p]
        chunks = [p for sql, p in conn.log if "artifact_node_chunk" in sql and p]
        assert ("s1", int(Rung.FULL), "full") in rungs
        assert ("s1", int(Rung.SUMMARY), "sum") in rungs
        assert ("s1", "c1") in chunks


class TestTransaction:
    def test_commits_on_success(self):
        conn = FakeConn()
        store(conn).put(sample_tree())
        assert conn.committed and not conn.rolled_back and conn.closed

    def test_rolls_back_a_partial_write(self):
        """Half a tree is worse than none: orphans pointing at deleted parents
        would be found by a packer mid-compile, not at write time."""
        conn = FakeConn(fail_on='INSERT INTO "artifact_tree"."artifact_node_rung"')
        with pytest.raises(RuntimeError):
            store(conn).put(sample_tree())
        assert conn.rolled_back and not conn.committed and conn.closed


class TestSchemaQualification:
    def test_qualified_when_schema_set(self):
        conn = FakeConn()
        store(conn).create_schema()
        assert any('CREATE SCHEMA IF NOT EXISTS "artifact_tree"' in s for s, _ in conn.log)
        assert all(
            '"artifact_tree".' in s or s.startswith("CREATE SCHEMA") or s.startswith("CREATE INDEX")
            for s, _ in conn.log
        )

    def test_unqualified_when_schema_none(self):
        conn = FakeConn()
        store(conn, schema=None).create_schema()
        assert not any(s.startswith("CREATE SCHEMA") for s, _ in conn.log)
        assert not any('"artifact_tree"' in s for s, _ in conn.log)

    def test_ddl_is_idempotent_by_construction(self):
        """Run at every startup, so every statement must tolerate re-running."""
        for stmt in create_schema_sql("artifact_tree"):
            assert "IF NOT EXISTS" in stmt

    def test_get_returns_none_for_unknown_artifact(self):
        assert store(FakeConn()).get("nope") is None
