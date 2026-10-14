"""ODS reader: RE's registry, read side only.

Opens the store itself read-only (SQLite `mode=ro`; Postgres `default_transaction_read_only`), and does
NOT construct RE's ProjectRegistry, whose constructor runs migrations: a library that reads must not
be able to change the schema. Every query is a SELECT; the guard below refuses anything else.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator


class OdsUnreadable(Exception):
    """The registry could not be read; the cause is the message."""


def normalize_slug(slug: str) -> str:
    return slug.replace("-", "_").lower()   # the same rule as ProjectRegistry._normalize_slug


class OdsReader:
    def __init__(self, url: str):
        self.url = url
        self._is_pg = url.startswith("postgresql")

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        try:
            if self._is_pg:
                import psycopg2
                import psycopg2.extras
                conn = psycopg2.connect(self.url)
                conn.set_session(readonly=True, autocommit=True)
                cur_factory = psycopg2.extras.RealDictCursor
            else:
                path = self.url.removeprefix("sqlite:///")
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                cur_factory = None
        except Exception as exc:  # noqa: BLE001
            raise OdsUnreadable(f"could not open the registry: {exc}") from exc
        try:
            yield conn, cur_factory
        finally:
            conn.close()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Run one SELECT with `?` placeholders. Raises OdsUnreadable when the store cannot answer."""
        if not sql.lstrip().lower().startswith("select"):
            raise ValueError("the ODS reader runs SELECT statements only")
        try:
            with self._conn() as (conn, factory):
                if self._is_pg:
                    cur = conn.cursor(cursor_factory=factory)
                    cur.execute(sql.replace("?", "%s"), params)
                else:
                    cur = conn.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except OdsUnreadable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OdsUnreadable(f"the registry did not answer: {exc}") from exc

    # ── the curation record, as RE writes it ──

    def commit_proofs(self, slug: str) -> list[dict]:
        rows = self.query(
            "SELECT id, node_kind, schema_name, table_name, proof, element_guid, read_at, detail_json "
            "FROM catalogue_commit_proofs WHERE database_slug = ? ORDER BY id", (normalize_slug(slug),))
        for r in rows:
            try:
                r["detail"] = json.loads(r.pop("detail_json") or "{}")
            except (ValueError, TypeError):
                r["detail"] = {}
        return rows

    def catalogue_scope_events(self, slug: str) -> list[dict]:
        return self.query(
            "SELECT id, node_kind, schema_name, table_name, choice, action, source, proposal_rule, changed_at "
            "FROM catalogue_scope_events WHERE database_slug = ? ORDER BY id", (normalize_slug(slug),))

    def resource_scope_events(self, resource_type: str, slug: str) -> list[dict]:
        return self.query(
            "SELECT id, locator, kind, choice, action, source, proposal_rule, changed_at "
            "FROM resource_scope_events WHERE resource_type = ? AND resource_slug = ? ORDER BY id",
            (resource_type, normalize_slug(slug)))

    def outbox_status_counts(self, entity_type: str, slug: str) -> dict[str, list[int]]:
        """status -> outbox row ids, for one resource."""
        out: dict[str, list[int]] = {}
        for r in self.query("SELECT id, status FROM egeria_outbox WHERE entity_type = ? AND entity_slug = ? ORDER BY id",
                            (entity_type, normalize_slug(slug))):
            out.setdefault(r["status"], []).append(r["id"])
        return out

    # ── row_count_snapshot results, as RE stores them ──

    def row_count_snapshots(self, slug: str, limit: int = 2) -> list[dict]:
        """The latest `limit` row_count_snapshot results for a database, newest first:
        `[{"surveyed_at", "source", "tables": [{schema_name, table_name, table_type, row_count, state}]}]`.

        A snapshot is one survey's `database_tables` rows (the rows RE's `row_count_snapshot` analysis reads),
        keyed by (surveyed_at, source). A survey RE marked invalid (`database_surveys.invalid_at`, the false-zero
        rule) is not a snapshot. A survey that stored no table rows measured no row counts, so it is not one either.
        """
        s = normalize_slug(slug)
        runs = self.query(
            "SELECT t.surveyed_at AS surveyed_at, t.source AS source FROM database_tables t "
            "WHERE t.database_slug = ? AND NOT EXISTS (SELECT 1 FROM database_surveys d "
            "  WHERE d.database_slug = t.database_slug AND d.surveyed_at = t.surveyed_at "
            "  AND d.source = t.source AND d.invalid_at IS NOT NULL) "
            "GROUP BY t.surveyed_at, t.source ORDER BY t.surveyed_at DESC, t.source LIMIT ?", (s, int(limit)))
        out = []
        for run in runs:
            tables = self.query(
                "SELECT schema_name, table_name, table_type, row_count, state FROM database_tables "
                "WHERE database_slug = ? AND surveyed_at = ? AND source = ? ORDER BY schema_name, table_name",
                (s, run["surveyed_at"], run["source"]))
            out.append({"surveyed_at": run["surveyed_at"], "source": run["source"], "tables": tables})
        return out

    def registry_view(self):
        """A read-only stand-in for ProjectRegistry (needs the optional `re` extra; see registry_view.py)."""
        from trellis_analytics.readers.registry_view import RegistryReadView
        return RegistryReadView(self.url)
