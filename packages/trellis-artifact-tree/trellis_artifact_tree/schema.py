"""DDL for the containment tree.

Four tables, and the split matters:

- `artifact` carries the envelope (§10). One row per ingested thing.
- `artifact_node` carries containment. Self-referencing parent, sibling
  ordinal.
- `artifact_node_rung` carries the compression ladder as ROWS, not columns.
  Adding a rung between SUMMARY and IDENTIFIERS later is then an insert, not a
  migration -- which is why Rung's values are spaced rather than sequential.
- `artifact_node_chunk` carries leaf -> retrieval chunk references. Chunk ids
  only: the chunks and their vectors live in trellis-vectorstore, in the same
  Postgres. No foreign key across that boundary, deliberately -- the two
  packages must not learn each other's table names, and a chunk may be
  re-embedded or evicted on its own schedule.
"""
from __future__ import annotations


def _q(schema: str | None, table: str) -> str:
    return f'"{schema}"."{table}"' if schema else f'"{table}"'


def create_schema_sql(schema: str | None) -> list[str]:
    """Ordered DDL statements. Idempotent: safe to run at every startup."""
    stmts: list[str] = []
    if schema:
        stmts.append(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    stmts.append(f"""
        CREATE TABLE IF NOT EXISTS {_q(schema, 'artifact')} (
            artifact_id         TEXT PRIMARY KEY,
            source_kind         TEXT NOT NULL,
            source_id           TEXT NOT NULL,
            -- when WE read it
            fetched_at          TEXT NOT NULL,
            -- when the fact was true, per the source (Egeria's own timestamp,
            -- a commit date). Distinct from fetched_at on purpose: collapsing
            -- them loses old-fact vs stale-read, which the whole
            -- stale-but-labelled policy rests on.
            source_timestamp    TEXT NOT NULL DEFAULT '',
            source_version      TEXT NOT NULL DEFAULT '',
            -- "structural" | "generic-text". Absence of a format adapter must
            -- degrade, never block, so this records which happened and travels
            -- to the manifest and the answer's citations.
            extraction_fidelity TEXT NOT NULL DEFAULT 'structural',
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")

    stmts.append(f"""
        CREATE TABLE IF NOT EXISTS {_q(schema, 'artifact_node')} (
            node_id     TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL
                        REFERENCES {_q(schema, 'artifact')}(artifact_id)
                        ON DELETE CASCADE,
            parent_id   TEXT REFERENCES {_q(schema, 'artifact_node')}(node_id)
                        ON DELETE CASCADE,
            kind        TEXT NOT NULL,
            title       TEXT NOT NULL DEFAULT '',
            ordinal     INTEGER NOT NULL DEFAULT 0,
            span_start  INTEGER,
            span_end    INTEGER
        )""")

    stmts.append(f"""
        CREATE TABLE IF NOT EXISTS {_q(schema, 'artifact_node_rung')} (
            node_id TEXT NOT NULL
                    REFERENCES {_q(schema, 'artifact_node')}(node_id)
                    ON DELETE CASCADE,
            -- Rung's integer value, not its name: spaced so a new rung can be
            -- inserted between two existing ones without renumbering stored data.
            rung    INTEGER NOT NULL,
            text    TEXT NOT NULL,
            PRIMARY KEY (node_id, rung)
        )""")

    stmts.append(f"""
        CREATE TABLE IF NOT EXISTS {_q(schema, 'artifact_node_chunk')} (
            node_id   TEXT NOT NULL
                      REFERENCES {_q(schema, 'artifact_node')}(node_id)
                      ON DELETE CASCADE,
            -- Opaque to this package. No FK: chunks live in
            -- trellis-vectorstore and follow their own lifecycle.
            chunk_ref TEXT NOT NULL,
            PRIMARY KEY (node_id, chunk_ref)
        )""")

    stmts.append(
        f"CREATE INDEX IF NOT EXISTS artifact_node_by_artifact "
        f"ON {_q(schema, 'artifact_node')} (artifact_id)"
    )
    stmts.append(
        f"CREATE INDEX IF NOT EXISTS artifact_node_by_parent "
        f"ON {_q(schema, 'artifact_node')} (parent_id)"
    )
    return stmts
