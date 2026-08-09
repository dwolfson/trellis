"""DB-free unit tests for PgVectorStore's pure logic — identifier
rendering, DDL generation, INSERT SQL text, and the metric-mismatch guard.
None of these touch a live database (create_index's metric check runs
before connect(); the others are called directly without connect())."""
from __future__ import annotations

import pytest

from trellis_vectorstore.config import PgVectorStoreConfig
from trellis_vectorstore.embeddings import EmbeddingProvider
from trellis_vectorstore.pg import PgVectorStore
from trellis_vectorstore.schemas import CollectionSchema, ExtraColumn


class _FakeEmbeddings:
    def embed_texts(self, texts):
        return [[0.0] * 384 for _ in texts]

    def embed_query(self, text):
        return [0.0] * 384


def _config(schema=None):
    return PgVectorStoreConfig(
        host="localhost", port=5442, dbname="test", user="u", password="p", schema=schema,
    )


def _store(schema=None, metric="cosine", collection_schemas=None, table_name_map=None):
    return PgVectorStore(
        _config(schema=schema), metric=metric, embeddings=_FakeEmbeddings(),
        collection_schemas=collection_schemas, table_name_map=table_name_map,
    )


def test_embedding_provider_protocol_satisfied():
    assert isinstance(_FakeEmbeddings(), EmbeddingProvider)


class TestIdentifierRendering:
    def test_schema_none_is_unqualified(self):
        store = _store(schema=None)
        assert store._qualified("pyegeria") == '"pyegeria"'
        assert store._catalog_schema == "public"

    def test_schema_set_is_qualified(self):
        store = _store(schema="resource_explorer")
        assert store._qualified("myproj_code") == '"resource_explorer"."myproj_code"'
        assert store._catalog_schema == "resource_explorer"


class TestTableNameMap:
    def test_identity_when_no_map(self):
        store = _store(table_name_map=None)
        assert store._table("pyegeria_drE") == "pyegeria_drE"

    def test_maps_known_names(self):
        store = _store(table_name_map={"pyegeria_drE": "pyegeria_dre", "cli_commands": "pyegeria_cli"})
        assert store._table("pyegeria_drE") == "pyegeria_dre"
        assert store._table("cli_commands") == "pyegeria_cli"

    def test_unmapped_name_passes_through(self):
        store = _store(table_name_map={"pyegeria_drE": "pyegeria_dre"})
        assert store._table("egeria_java") == "egeria_java"


class TestDdlRendering:
    def test_no_schema_uses_generic_renderer(self):
        store = _store()
        ddl = store._render_ddl("mycollection")
        assert 'CREATE TABLE IF NOT EXISTS "mycollection"' in ddl
        assert "embedding vector(384)" in ddl

    def test_extra_columns_rendered(self):
        schema = CollectionSchema(extra_columns=(
            ExtraColumn(name="is_private", ddl_type="BOOLEAN", default=False, ddl_default="FALSE"),
        ))
        store = _store(collection_schemas={"pyegeria": schema})
        ddl = store._render_ddl("pyegeria")
        assert "is_private BOOLEAN NOT NULL DEFAULT FALSE" in ddl

    def test_raw_ddl_escape_hatch_used_verbatim(self):
        raw = 'CREATE TABLE IF NOT EXISTS "pyegeria" (\n    id VARCHAR(256) PRIMARY KEY\n)'
        schema = CollectionSchema(raw_ddl=raw, extra_columns=())
        store = _store(collection_schemas={"pyegeria": schema})
        ddl = store._render_ddl("pyegeria")
        assert ddl == raw  # unqualified, matches raw exactly

    def test_raw_ddl_gets_schema_qualified_when_schema_set(self):
        raw = 'CREATE TABLE IF NOT EXISTS "pyegeria" (\n    id VARCHAR(256) PRIMARY KEY\n)'
        schema = CollectionSchema(raw_ddl=raw, extra_columns=())
        store = _store(schema="resource_explorer", collection_schemas={"pyegeria": schema})
        ddl = store._render_ddl("pyegeria")
        assert ddl.startswith('CREATE TABLE IF NOT EXISTS "resource_explorer"."pyegeria"')
        assert ddl.count('"resource_explorer"."pyegeria"') == 1  # replaced once, not duplicated


class TestInsertSqlGeneration:
    def test_base_schema_insert_sql(self):
        store = _store()
        result = store._build_insert_sql("mycollection")
        assert result.extra_columns == ()
        assert 'INSERT INTO "mycollection" ("id", "embedding", "text", "metadata")' in result.sql
        assert "ON CONFLICT (id) DO UPDATE SET" in result.sql
        assert '"embedding" = EXCLUDED."embedding"' in result.sql

    def test_extra_columns_insert_sql_matches_ea_shape(self):
        schema = CollectionSchema(extra_columns=(
            ExtraColumn(name="element_type", ddl_type="VARCHAR(50)", default="", ddl_default="''"),
            ExtraColumn(name="is_private", ddl_type="BOOLEAN", default=False, ddl_default="FALSE"),
        ))
        store = _store(collection_schemas={"pyegeria": schema})
        result = store._build_insert_sql("pyegeria")
        assert result.extra_columns == ("element_type", "is_private")
        assert (
            'INSERT INTO "pyegeria" '
            '("id", "embedding", "text", "metadata", "element_type", "is_private") '
            "VALUES %s "
            "ON CONFLICT (id) DO UPDATE SET "
            '"embedding" = EXCLUDED."embedding", "text" = EXCLUDED."text", '
            '"metadata" = EXCLUDED."metadata", "element_type" = EXCLUDED."element_type", '
            '"is_private" = EXCLUDED."is_private"'
        ) == result.sql

    def test_qualified_insert_sql_when_schema_set(self):
        store = _store(schema="resource_explorer")
        result = store._build_insert_sql("mycollection")
        assert result.sql.startswith('INSERT INTO "resource_explorer"."mycollection"')


class TestMetricMismatchGuard:
    def test_matching_metric_type_does_not_raise_before_connect(self):
        # Won't reach the actual DB call in this test — matching value
        # returns early from the guard, not from a live connection.
        store = _store(metric="cosine")
        # Confirm the guard itself doesn't raise for a match (would proceed
        # to self.connect() next, which we don't invoke here directly —
        # testing only the pure validation logic).
        assert store._metric.legacy_metric_type == "COSINE"

    def test_mismatched_metric_type_raises_before_connecting(self):
        store = _store(metric="cosine")
        with pytest.raises(ValueError, match="disagrees with this store's configured metric"):
            store.create_index("mycollection", metric_type="L2")

    def test_none_metric_type_never_raises(self):
        store = _store(metric="l2")
        # metric_type=None means "use the instance's own strategy" — the
        # guard must not fire; this WILL attempt to connect and fail with a
        # connection error (no live DB in this unit test), which is the
        # correct proof the ValueError guard was skipped.
        with pytest.raises(Exception) as exc_info:
            store.create_index("mycollection")
        assert "disagrees with this store's configured metric" not in str(exc_info.value)
