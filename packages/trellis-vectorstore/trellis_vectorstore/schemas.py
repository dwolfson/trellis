"""Per-collection schema — extra scalar columns beyond the uniform base
four (id, embedding, text, metadata), keyed by canonical (post-name-map)
table name.

Resource Explorer has no extra columns anywhere — every collection uses
the uniform base schema, so RE's PgVectorStore adapter passes no
collection_schemas at all. Egeria Advisor has two collections (pyegeria,
pyegeria_cli) with extra scalar columns denormalized out of the JSONB
metadata blob for fast filtered queries (e.g. WHERE is_private = true) —
these were previously hardcoded module-level constants
(_TABLE_DDL/_EXTRA_COLUMNS/_COL_DEFAULTS in advisor/vector_store_pg.py),
now expressed as real constructor-time configuration instead.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtraColumn:
    name: str
    ddl_type: str          # e.g. "VARCHAR(200)", "BOOLEAN"
    default: object        # Python-side value used when a row's metadata lacks this key
    ddl_default: str       # SQL literal for the DDL, e.g. "''" or "FALSE"
    nullable: bool = False


@dataclass(frozen=True)
class CollectionSchema:
    extra_columns: tuple[ExtraColumn, ...] = ()
    # Transitional escape hatch (migration Phase 3/5): when set, this exact
    # CREATE TABLE statement is used verbatim instead of rendering DDL from
    # extra_columns — lets a cutover reproduce an app's exact existing DDL
    # byte-for-byte on day one, with zero DDL-generation risk, while the
    # generic renderer is proven equivalent (via an information_schema
    # comparison, not string diffing — Postgres doesn't persist DDL
    # whitespace) before this field is dropped in a follow-up. extra_columns
    # must still be declared alongside raw_ddl — it's still needed for
    # INSERT/upsert column ordering and defaults, which raw_ddl says
    # nothing about.
    raw_ddl: str | None = None


def render_create_table_sql(qualified_name: str, extra_columns: tuple[ExtraColumn, ...], embedding_dim: int) -> str:
    """Generic DDL renderer — used when a CollectionSchema has no raw_ddl
    override. Produces the base four columns plus any declared extras."""
    lines = [
        "id        VARCHAR(256) PRIMARY KEY",
        f"embedding vector({embedding_dim}) NOT NULL",
        "text      TEXT         NOT NULL",
        "metadata  JSONB        NOT NULL DEFAULT '{}'",
    ]
    for col in extra_columns:
        null_clause = "" if col.nullable else " NOT NULL"
        lines.append(f"{col.name} {col.ddl_type}{null_clause} DEFAULT {col.ddl_default}")
    body = ",\n        ".join(lines)
    return f'CREATE TABLE IF NOT EXISTS {qualified_name} (\n        {body}\n    )'
