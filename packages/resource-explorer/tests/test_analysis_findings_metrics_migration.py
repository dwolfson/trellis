"""Migration test for the analysis-kind extensibility redesign's D3 forward
migration: project_security_findings/project_documentation_findings/
project_data_profile_snapshots/project_api_structure_snapshots (Phase B's
four per-kind tables) -> the two generic project_analysis_findings/
project_analysis_metrics tables, guarded on "the new table is still empty."

Seeds representative rows directly into the four old tables (bypassing the
new upsert_finding()/upsert_metric() functions, simulating pre-existing
Phase B production data), then opens a second ProjectRegistry against the
same db file to trigger _init_schema()'s one-time migration, and confirms
the new generic tables end up with equivalent, correctly-kind-tagged rows —
and that the old tables are left untouched (soak-period retrieval still
works).
"""
from __future__ import annotations

from resource_explorer.registry import Project, ProjectRegistry


def _seed_project(registry, slug="myproj"):
    registry.add(Project(
        slug=slug, display_name="My Project",
        github_url=f"https://github.com/test/{slug}", description="",
    ))


class TestForwardMigration:
    def test_migrates_security_and_documentation_findings(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        registry = ProjectRegistry(db_path=db_path)
        _seed_project(registry)

        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_security_findings "
                "(project_slug, surveyed_at, check_name, status, summary, detail_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("myproj", "2026-01-01T00:00:00", "license", "pass", "License: MIT", None),
            )
            conn.execute(
                "INSERT INTO project_documentation_findings "
                "(project_slug, surveyed_at, finding_type, label, confidence, detail_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("myproj", "2026-01-01T00:00:00", "quality_score", "Partial", 70, None),
            )

        # Re-opening against the same file re-triggers _init_schema()'s
        # guarded one-time migration (new tables still empty at this point).
        registry2 = ProjectRegistry(db_path=db_path)

        sec = registry2.query_findings("myproj", "security_hygiene")
        assert len(sec) == 1
        assert sec[0]["check_name"] == "license"
        assert sec[0]["label"] == "pass"
        assert sec[0]["summary"] == "License: MIT"

        doc = registry2.query_findings("myproj", "documentation")
        assert len(doc) == 1
        assert doc[0]["check_name"] == "quality_score"
        assert doc[0]["label"] == "Partial"
        assert doc[0]["confidence"] == 70

        # Old tables untouched (soak period — not dropped).
        with registry2._conn() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM project_security_findings"
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM project_documentation_findings"
            ).fetchone()[0] == 1

    def test_migrates_data_profile_and_api_structure_snapshots(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        registry = ProjectRegistry(db_path=db_path)
        _seed_project(registry)

        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_data_profile_snapshots "
                "(project_slug, surveyed_at, total_files, total_size_bytes, format_breakdown_json) "
                "VALUES (?, ?, ?, ?, ?)",
                ("myproj", "2026-01-01T00:00:00", 3, 1000, '{"csv": 3}'),
            )
            conn.execute(
                "INSERT INTO project_api_structure_snapshots "
                "(project_slug, surveyed_at, symbol_count, by_language_json, relationship_count) "
                "VALUES (?, ?, ?, ?, ?)",
                ("myproj", "2026-01-01T00:00:00", 12, '{"python": 12}', 2),
            )

        registry2 = ProjectRegistry(db_path=db_path)

        dp = registry2.query_metrics("myproj", "data_profile")
        assert dp["total_files"] == 3
        assert dp["total_size_bytes"] == 1000
        assert dp["detail"] == {"csv": 3}

        api = registry2.query_metrics("myproj", "api_structure")
        assert api["symbol_count"] == 12
        assert api["relationship_count"] == 2
        assert api["detail"] == {"python": 12}

        # Old tables untouched (soak period — not dropped).
        with registry2._conn() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM project_data_profile_snapshots"
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM project_api_structure_snapshots"
            ).fetchone()[0] == 1

    def test_does_not_re_migrate_once_generic_tables_have_rows(self, tmp_path):
        """Guard is on 'new table empty', not per-row — once real writes go
        through upsert_finding()/upsert_metric(), reopening the registry
        must not re-copy old rows a second time."""
        db_path = str(tmp_path / "test.db")
        registry = ProjectRegistry(db_path=db_path)
        _seed_project(registry)

        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_security_findings "
                "(project_slug, surveyed_at, check_name, status, summary, detail_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("myproj", "2026-01-01T00:00:00", "license", "pass", "License: MIT", None),
            )

        registry2 = ProjectRegistry(db_path=db_path)
        assert len(registry2.query_findings("myproj", "security_hygiene")) == 1

        # A fresh real write via the new generic function...
        registry2.upsert_finding(
            "myproj", "security_hygiene",
            [{"check_name": "ci_config", "label": "gap", "summary": ""}],
            surveyed_at="2026-02-01T00:00:00",
        )

        # ...and reopening again must not duplicate the originally-migrated row.
        registry3 = ProjectRegistry(db_path=db_path)
        all_rows = registry3.query_findings_history_raw("myproj", "security_hygiene")
        license_rows = [r for r in all_rows if r["check_name"] == "license"]
        assert len(license_rows) == 1
