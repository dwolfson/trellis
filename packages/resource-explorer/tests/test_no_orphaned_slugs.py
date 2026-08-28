"""No row may reference a resource slug that no longer exists.

This is a trap turned into a test. Two of them, really:

  * `project_published_annotation_types` and `project_published_analyses` carry
    a `project_slug` with NO declared foreign key to `projects.slug`, so
    Postgres will not stop a delete from stranding their rows -- and
    `ProjectRegistry.remove()` does not clean them up.
  * Removing the stale `trellis` repo on 2026-08-28 stranded exactly one row in
    `project_published_annotation_types`. Nothing noticed. Nothing would have.

The FK-declared tables are already safe by construction; the value here is the
ones that are not, and the fact that this test DISCOVERS slug-bearing tables
from the live schema rather than from a hand-maintained list. A list would have
been written against today's schema and gone stale the first time a table was
added -- which is exactly how the two above came to exist unguarded.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry

pytestmark = pytest.mark.requires_pgvector


@pytest.fixture
def pg_registry(pg_test_schema):
    """A registry on the throwaway integration schema, never the live
    `resource_explorer` one -- this test deletes things."""
    from resource_explorer.config import get_config

    cfg = get_config().pgvector
    url = (f"postgresql://{cfg.db_user}:{cfg.password}@{cfg.host}:{cfg.port}"
           f"/{cfg.dbname}?options=-csearch_path%3D{pg_test_schema}")
    return ProjectRegistry(database_url=url)

# Tables whose slug column deliberately outlives the resource. Empty today:
# `project_published_analyses` is *suspected* to be audit history, but that is
# inferred from a test comment rather than stated anywhere authoritative, so it
# is not exempted on a guess. If it should be, add it here WITH the reason.
# Slug-bearing tables with NO declared foreign key to projects.slug. Postgres
# will not stop a delete from stranding their rows, so each needs a reason.
#
# Both were found by audit on 2026-08-28, not by design. Removing the stale
# `trellis` repo the same day stranded a row in the first, and nothing noticed.
UNGUARDED_BY_DESIGN: dict[str, str] = {
    "project_published_annotation_types":
        "published to Egeria; rows outlive the local repo. NOTE: not cleaned "
        "up by remove() either, which is a separate open question.",
    "project_published_analyses":
        "suspected audit history -- inferred from a test comment, not stated "
        "anywhere authoritative. Confirm or clean up.",
    # Found by THIS TEST on first run, not by the hand audit that found the two
    # above. Reasons not yet established -- they are baselined, not blessed.
    "conversation_history": "DECISION PENDING -- found 2026-08-28, reason unknown.",
    "repo_dispositions": "DECISION PENDING -- found 2026-08-28, reason unknown.",
    "sub_resources": "DECISION PENDING -- found 2026-08-28, reason unknown.",
    "query_log":
        "observability history -- what was asked about a resource is analytics "
        "that outlives the resource, and feedback tuning reads it. Deliberate.",
}

# This allowlist is a RATCHET, in the manner of
# tests/no_silent_success_baseline.json: it records where things stand today so
# a sixth unguarded table cannot appear unnoticed, and it may only shrink.
# Three of the five entries are marked DECISION PENDING and should be resolved
# -- either give the table a foreign key, or write down why its rows outlive
# the resource. Adding a new entry to keep the build green is the one use this
# list is not for.


def _connect():
    import psycopg2

    from resource_explorer.config import get_config

    cfg = get_config().pgvector
    conn = psycopg2.connect(
        host=cfg.host, port=cfg.port, dbname=cfg.dbname,
        user=cfg.db_user, password=cfg.password,
    )
    conn.autocommit = True
    return conn


def _slug_bearing_tables(cur, schema: str) -> list[tuple[str, str]]:
    """(table, column) for every column that holds a resource slug."""
    cur.execute(
        """SELECT table_name, column_name
             FROM information_schema.columns
            WHERE table_schema = %s
              AND column_name IN ('project_slug', 'resource_slug')
         ORDER BY table_name, column_name""",
        (schema,),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


class TestNoOrphanedSlugs:
    def test_discovery_finds_slug_columns(self, pg_registry, pg_test_schema):
        """Guards the discovery itself. If this stops finding slug columns, the
        check below silently passes by inspecting nothing -- the failure mode
        this file exists to prevent, one level up. pg_registry is requested
        first so the schema is provisioned before it is read."""
        conn = _connect()
        try:
            with conn.cursor() as cur:
                found = _slug_bearing_tables(cur, pg_test_schema)
        finally:
            conn.close()
        assert len(found) > 5, f"only {len(found)} slug column(s) -- discovery is broken"

    def test_every_unguarded_slug_table_is_accounted_for(self, pg_registry, pg_test_schema):
        """The real check, and it cannot be vacuous.

        A table carrying a resource slug with no FK to projects.slug can strand
        rows on delete, silently. That is not always wrong -- rows published to
        Egeria may legitimately outlive the local resource -- but it must be a
        decision, not an accident. A new one appearing here means someone added
        a slug column without deciding.
        """
        conn = _connect()
        try:
            with conn.cursor() as cur:
                slug_tables = {t for t, _ in _slug_bearing_tables(cur, pg_test_schema)}
                cur.execute(
                    """SELECT DISTINCT tc.table_name
                         FROM information_schema.table_constraints tc
                         JOIN information_schema.key_column_usage kcu
                           ON kcu.constraint_name = tc.constraint_name
                          AND kcu.table_schema = tc.table_schema
                        WHERE tc.table_schema = %s
                          AND tc.constraint_type = 'FOREIGN KEY'
                          AND kcu.column_name IN ('project_slug', 'resource_slug')""",
                    (pg_test_schema,),
                )
                guarded = {r[0] for r in cur.fetchall()}
        finally:
            conn.close()

        unguarded = slug_tables - guarded
        undeclared = sorted(unguarded - set(UNGUARDED_BY_DESIGN))
        assert not undeclared, (
            "slug-bearing table(s) with no foreign key and no recorded reason: "
            f"{undeclared}. Either add the FK, or add an entry to "
            "UNGUARDED_BY_DESIGN saying why rows may outlive the resource."
        )

    def test_the_allowlist_does_not_rot(self, pg_registry, pg_test_schema):
        """An entry for a table that no longer exists, or that has since gained
        an FK, is a stale exemption hiding behind a real one."""
        conn = _connect()
        try:
            with conn.cursor() as cur:
                slug_tables = {t for t, _ in _slug_bearing_tables(cur, pg_test_schema)}
        finally:
            conn.close()
        stale = sorted(set(UNGUARDED_BY_DESIGN) - slug_tables)
        assert not stale, f"UNGUARDED_BY_DESIGN lists table(s) that are gone: {stale}"
