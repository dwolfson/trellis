from __future__ import annotations

from trellis_vectorstore.schemas import CollectionSchema, ExtraColumn, render_create_table_sql


def test_render_base_schema_no_extra_columns():
    sql = render_create_table_sql('"mycollection"', (), embedding_dim=384)
    assert 'CREATE TABLE IF NOT EXISTS "mycollection"' in sql
    assert "id        VARCHAR(256) PRIMARY KEY" in sql
    assert "embedding vector(384) NOT NULL" in sql
    assert "text      TEXT         NOT NULL" in sql
    assert "metadata  JSONB        NOT NULL DEFAULT '{}'" in sql
    # No extra columns rendered
    assert sql.count("DEFAULT") == 1  # just metadata's default


def test_render_with_extra_columns():
    cols = (
        ExtraColumn(name="is_private", ddl_type="BOOLEAN", default=False, ddl_default="FALSE"),
        ExtraColumn(name="class_name", ddl_type="VARCHAR(200)", default="", ddl_default="''"),
    )
    sql = render_create_table_sql('"pyegeria"', cols, embedding_dim=384)
    assert "is_private BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "class_name VARCHAR(200) NOT NULL DEFAULT ''" in sql


def test_render_respects_embedding_dim():
    sql = render_create_table_sql('"x"', (), embedding_dim=768)
    assert "vector(768)" in sql


def test_nullable_extra_column_omits_not_null():
    cols = (ExtraColumn(name="note", ddl_type="TEXT", default=None, ddl_default="NULL", nullable=True),)
    sql = render_create_table_sql('"x"', cols, embedding_dim=384)
    assert "note TEXT DEFAULT NULL" in sql
    assert "note TEXT NOT NULL" not in sql


def test_collection_schema_defaults_to_empty():
    schema = CollectionSchema()
    assert schema.extra_columns == ()
    assert schema.raw_ddl is None


def test_collection_schema_is_frozen():
    schema = CollectionSchema()
    try:
        schema.raw_ddl = "x"  # type: ignore[misc]
        assert False, "should have raised"
    except Exception:
        pass
