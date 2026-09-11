"""Opening the registry must not write when there is nothing to migrate.

The 2026-09-11 annotation-type rename ran an unconditional UPDATE inside
_init_schema, before CREATE INDEX IF NOT EXISTS on the same table. Under
Postgres an UPDATE takes RowExclusiveLock even when it matches no rows, CREATE
INDEX wants ShareLock, and two processes opening the registry at once each
held the first while waiting for the second: a deadlock on every concurrent
open. Reproduced with sixteen parallel opens against the live registry —
14 of 16 deadlocked — and fixed by reading first and updating only when a
stale row exists.

SQLite has no such lock, so this asserts the *shape* the fix relies on: a
fresh registry's init issues no UPDATE against that table. If someone later
adds another unconditional write to _init_schema, this is what fails.
"""
from __future__ import annotations

from resource_explorer.registry import ProjectRegistry


def test_fresh_registry_init_issues_no_update_on_published_annotation_types(tmp_path, monkeypatch):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))

    seen: list[str] = []
    real_conn = r._conn

    class SpyCtx:
        def __init__(self, ctx): self.ctx = ctx
        def __enter__(self):
            conn = self.ctx.__enter__()
            real = conn.execute
            def spy(sql, *a, **k):
                seen.append(" ".join(str(sql).split()))
                return real(sql, *a, **k)
            conn.execute = spy
            return conn
        def __exit__(self, *a): return self.ctx.__exit__(*a)

    monkeypatch.setattr(r, "_conn", lambda: SpyCtx(real_conn()))
    r._init_schema()

    updates = [s for s in seen if s.upper().startswith("UPDATE PROJECT_PUBLISHED_ANNOTATION_TYPES")]
    assert updates == [], f"init wrote to project_published_annotation_types with nothing to migrate: {updates}"
    # and the guard read DID run, so the migration is still present
    assert any("SELECT 1 FROM project_published_annotation_types" in s for s in seen)
