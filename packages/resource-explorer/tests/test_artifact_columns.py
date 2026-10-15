"""Artifacts slice 1 (DESIGN-ARTIFACTS-VIEW-AND-DOC-LINKS.md §3, §7.1; owner's go 2026-10-15):
`file_role` on every symbol and marker row, `survey_commit_sha` on every repo step run.

Both columns are additive and nullable. NULL means "extracted / run before the column existed" and a reader
says "not recorded", never a guess. Registries here are a tmp SQLite file or the throwaway Postgres test
schema (`pg_registry`); never the shared one.
"""
from __future__ import annotations

import sqlite3

import pytest

from resource_explorer.registry import Project, ProjectRegistry

NEW_COLUMNS = {
    "project_code_symbols": "file_role",
    "project_code_markers": "file_role",
    "step_runs": "survey_commit_sha",
}


def _cols(reg, table) -> set[str]:
    with reg._conn() as conn:
        return reg._get_table_columns(conn, table)


def _reg(tmp_path, name="t.db") -> ProjectRegistry:
    r = ProjectRegistry(db_path=str(tmp_path / name))
    assert str(tmp_path) in r.database_url                                   # never the shared registry
    return r


def _project(reg, slug="p", sha=""):
    reg.add(Project(slug=slug, display_name=slug, github_url=f"https://github.com/x/{slug}", description=""))
    if sha:
        reg.update_commit_sha(slug, sha)


# ── the migration ───────────────────────────────────────────────────────────────────────────────────────

def test_fresh_sqlite_has_the_columns_and_a_second_init_is_a_no_op(tmp_path):
    path = str(tmp_path / "twice.db")
    first = {t: _cols(ProjectRegistry(db_path=path), t) for t in NEW_COLUMNS}
    second = {t: _cols(ProjectRegistry(db_path=path), t) for t in NEW_COLUMNS}
    for table, col in NEW_COLUMNS.items():
        assert col in first[table], table
    assert first == second


def test_an_existing_sqlite_registry_gains_the_columns_and_its_rows_stay_null(tmp_path):
    """Simulate a registry from before the change: drop the columns, keep a row in each table, re-init."""
    from resource_explorer.ingestion.code_symbol_extractor import CodeMarker, CodeSymbol

    path = tmp_path / "old.db"
    reg = ProjectRegistry(db_path=str(path))
    _project(reg)
    reg.upsert_code_symbols("p", [CodeSymbol("p", "a.py", "python", "function", "f", "f", "()", "", 1, 2)])
    reg.upsert_code_markers("p", [CodeMarker("p", "a.py", 1, "python", "route", "fastapi", "http_api", "GET /", "f")])
    reg.record_step_run("p", "repo_symbol_extraction", "2026-10-01T00:00:00")
    con = sqlite3.connect(path)
    for table, col in NEW_COLUMNS.items():
        con.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    con.commit()
    con.close()

    again = ProjectRegistry(db_path=str(path))                                  # the migration runs
    for table, col in NEW_COLUMNS.items():
        assert col in _cols(again, table), table
        with again._conn() as conn:
            rows = [dict(r) for r in conn.execute(f"SELECT {col} FROM {table}").fetchall()]
        assert rows and all(r[col] is None for r in rows), (table, rows)   # old rows: NULL, not a guess


def test_the_migration_is_idempotent_on_postgres(pg_registry, monkeypatch):
    from resource_explorer.registry import ProjectRegistry as PR

    assert "resource_explorer_test" in pg_registry.database_url             # the throwaway schema only
    before = {t: _cols(pg_registry, t) for t in NEW_COLUMNS}
    for table, col in NEW_COLUMNS.items():
        assert col in before[table], table
    monkeypatch.setattr(PR, "_pg_schema_ready", set())                      # forget the per-process init
    again = PR(database_url=pg_registry.database_url)
    assert {t: _cols(again, t) for t in NEW_COLUMNS} == before


def test_two_processes_starting_together_both_add_the_columns_safely(pg_registry, monkeypatch):
    """Both see the columns missing; the second ADD must not fail (ADD COLUMN IF NOT EXISTS)."""
    from resource_explorer.registry import ProjectRegistry as PR

    assert "resource_explorer_test" in pg_registry.database_url
    real = PR._get_table_columns

    def blind(self, conn, table):
        cols = real(self, conn, table)
        return cols - {NEW_COLUMNS[table]} if table in NEW_COLUMNS else cols
    monkeypatch.setattr(PR, "_get_table_columns", blind)
    monkeypatch.setattr(PR, "_pg_schema_ready", set())
    again = PR(database_url=pg_registry.database_url)
    monkeypatch.setattr(PR, "_get_table_columns", real)
    for table, col in NEW_COLUMNS.items():
        assert col in _cols(again, table), table


# ── the classifier ──────────────────────────────────────────────────────────────────────────────────────

FIXTURE_ROLES = {
    # Python
    "testgen/api/app.py": "core",
    "testgen/__init__.py": "core",
    "tests/unit/test_api.py": "test",
    "testgen/conftest.py": "test",
    "proto/service_pb2.py": "generated",
    "proto/service_pb2_grpc.py": "generated",
    "build/lib/testgen/app.py": "generated",
    ".venv/lib/python3.12/site-packages/fastapi/app.py": "vendored",
    "vendor/requests/api.py": "vendored",
    "vendor/requests/tests/test_api.py": "vendored",                      # somebody else's tests
    "docs/conf.py": "docs",
    "docs/examples/app.py": "docs",
    # Java
    "src/main/java/org/x/Api.java": "core",
    "src/main/java/org/x/doc/DocBuilder.java": "core",                     # a package called doc is code
    "src/test/java/org/x/ApiTest.java": "test",
    "module/src/main/java/org/x/ApiIT.java": "test",
    "target/generated-sources/annotations/org/x/Api_.java": "generated",
    "module/generated/org/x/Model.java": "generated",
    "documentation/samples/Sample.java": "docs",
    # JavaScript
    "web/static/app.js": "core",
    "web/static/app.test.js": "test",
    "web/src/__tests__/app.js": "test",
    "web/src/util.spec.ts": "test",
    "web/static/vendor.min.js": "generated",
    "web/dist/bundle.js": "generated",
    "node_modules/react/index.js": "vendored",
    "web/node_modules/lodash/lodash.js": "vendored",
    "web/api.generated.ts": "generated",
    # Go
    "pkg/api/server.pb.go": "generated",
    "pkg/api/server.go": "core",
    "pkg/api/server_test.go": "test",
}


@pytest.mark.parametrize("path,role", sorted(FIXTURE_ROLES.items()))
def test_the_classifier_labels_each_fixture_file(path, role):
    from resource_explorer.ingestion.file_role import FILE_ROLES, classify_file_role

    assert role in FILE_ROLES
    assert classify_file_role(path) == role


def test_the_classifier_agrees_with_is_test_path_for_own_code():
    """One rule for tests: outside vendored/generated, role == test exactly when is_test_path says so."""
    from resource_explorer.ingestion.file_role import classify_file_role
    from resource_explorer.ingestion.test_paths import is_test_path

    for path, role in FIXTURE_ROLES.items():
        if role in ("vendored", "generated"):
            continue
        assert (classify_file_role(path) == "test") == is_test_path(path), path


# ── extraction writes file_role ─────────────────────────────────────────────────────────────────────────

APP_PY = '''
from fastapi import APIRouter
router = APIRouter()

@router.get("/token")
def get_token():
    return 1
'''
TEST_PY = '''
def test_token():
    assert True
'''
JAVA = '''
@RestController
public class Api {
    @GetMapping("/x")
    public String x() { return ""; }
}
'''
JS = "function render() { return 1; }\n"


def _fixture_repo(root):
    files = {
        "testgen/api/app.py": APP_PY,
        "tests/test_api.py": TEST_PY,
        "docs/examples/app.py": APP_PY,
        "proto/svc_pb2.py": "class Svc:\n    pass\n",
        "src/main/java/org/x/Api.java": JAVA,
        "src/test/java/org/x/ApiTest.java": JAVA,
        "web/static/app.js": JS,
        "web/static/app.test.js": JS,
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def test_the_extractor_stamps_file_role_on_symbols_and_markers():
    from resource_explorer.ingestion.code_symbol_extractor import CodeSymbolExtractor

    ex = CodeSymbolExtractor()
    syms = ex.extract("tests/test_api.py", TEST_PY, "p", "python")
    assert syms and {s.file_role for s in syms} == {"test"}
    marks = ex.extract_markers("docs/examples/app.py", APP_PY, "p", "python")
    assert marks and {m.file_role for m in marks} == {"docs"}


def test_survey_extraction_writes_file_role_on_every_symbol_and_marker_row(tmp_path):
    from resource_explorer.surveyors.sub_surveyors.symbol_extraction import SymbolExtractionSurveyor

    reg = _reg(tmp_path)
    _project(reg)
    root = tmp_path / "repo"
    _fixture_repo(root)
    SymbolExtractionSurveyor(reg.get("p"), reg, str(root)).run()

    with reg._conn() as conn:
        syms = [dict(r) for r in conn.execute(
            "SELECT file_path, file_role FROM project_code_symbols WHERE project_slug = 'p'").fetchall()]
        marks = [dict(r) for r in conn.execute(
            "SELECT file_path, file_role FROM project_code_markers WHERE project_slug = 'p'").fetchall()]
    by_file = {r["file_path"]: r["file_role"] for r in syms}
    assert syms and all(r["file_role"] is not None for r in syms)
    assert by_file["testgen/api/app.py"] == "core"
    assert by_file["tests/test_api.py"] == "test"
    assert by_file["docs/examples/app.py"] == "docs"
    assert by_file["proto/svc_pb2.py"] == "generated"
    assert by_file["src/main/java/org/x/Api.java"] == "core"
    assert by_file["src/test/java/org/x/ApiTest.java"] == "test"
    assert by_file["web/static/app.js"] == "core"
    assert by_file["web/static/app.test.js"] == "test"
    roles = {r["file_path"]: r["file_role"] for r in marks}
    assert marks and all(r["file_role"] is not None for r in marks)
    assert roles == {"testgen/api/app.py": "core", "docs/examples/app.py": "docs",
                     "src/main/java/org/x/Api.java": "core"}


def test_a_re_extraction_overwrites_the_role(tmp_path):
    from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol

    reg = _reg(tmp_path)
    _project(reg)
    s = CodeSymbol("p", "a.py", "python", "function", "f", "f", "()", "", 1, 2)
    reg.upsert_code_symbols("p", [s])
    s.file_role = "core"
    reg.upsert_code_symbols("p", [s])
    with reg._conn() as conn:
        assert [dict(r)["file_role"] for r in conn.execute("SELECT file_role FROM project_code_symbols").fetchall()] == ["core"]


# ── the survey run records its commit ───────────────────────────────────────────────────────────────────

def _step_shas(reg):
    with reg._conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT slug, entity_type, step_key, survey_commit_sha FROM step_runs ORDER BY id").fetchall()]


def test_a_repo_step_run_stores_the_commit_it_surveyed(tmp_path):
    reg = _reg(tmp_path)
    _project(reg, "p", sha="3606859c0ffee")
    reg.record_step_run("p", "repo_symbol_extraction", "2026-10-15T10:00:00")
    assert _step_shas(reg)[0]["survey_commit_sha"] == "3606859c0ffee"


def test_through_the_observer_path_too(tmp_path):
    from resource_explorer.surveyors import step_cost_observer

    reg = _reg(tmp_path)
    _project(reg, "p", sha="abc123")
    obs = step_cost_observer.Observation(step_key="repo_symbol_extraction", elapsed=0.1, connects=0,
                                       declared_fetch="download", declared_compute="medium")
    step_cost_observer.record(reg, "p", obs, "2026-10-15T10:00:00")
    assert [r["survey_commit_sha"] for r in _step_shas(reg)] == ["abc123"]


def test_no_known_commit_and_non_repo_runs_store_null(tmp_path):
    reg = _reg(tmp_path)
    _project(reg, "nosha")                                                 # never fetched: last_commit_sha ''
    reg.record_step_run("nosha", "repo_symbol_extraction", "2026-10-15T10:00:00")
    reg.record_step_run("db1", "db_columns", "2026-10-15T10:00:00", entity_type="database")
    assert [r["survey_commit_sha"] for r in _step_shas(reg)] == [None, None]


def test_a_later_fetch_does_not_rewrite_an_earlier_run(tmp_path):
    reg = _reg(tmp_path)
    _project(reg, "p", sha="old")
    reg.record_step_run("p", "repo_symbol_extraction", "2026-10-14T10:00:00")
    reg.update_commit_sha("p", "new")
    reg.record_step_run("p", "repo_symbol_extraction", "2026-10-15T10:00:00")
    assert [r["survey_commit_sha"] for r in _step_shas(reg)] == ["old", "new"]


# ── readers say "not recorded" for NULL ─────────────────────────────────────────────────────────────────

def test_the_labels_say_not_recorded_for_null():
    from resource_explorer.artifact_provenance import NOT_RECORDED, commit_label, role_label

    assert NOT_RECORDED == "not recorded"
    assert role_label(None) == "role not recorded"
    assert role_label("test") == "test"
    assert commit_label(None) == "commit not recorded"
    assert commit_label("") == "commit not recorded"
    assert commit_label("3606859c0ffee1234567") == "commit 3606859c0ffe"


def test_the_symbol_drill_down_shows_role_and_commit_or_not_recorded(tmp_path):
    from resource_explorer import members
    from resource_explorer.artifact_provenance import extraction_commit
    from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol

    reg = _reg(tmp_path)
    _project(reg)
    old = CodeSymbol("p", "a.py", "python", "function", "old_f", "old_f", "()", "", 1, 2)   # role NULL
    new = CodeSymbol("p", "a.py", "python", "function", "new_f", "new_f", "()", "", 3, 4)
    new.file_role = "core"
    reg.upsert_code_symbols("p", [old, new])

    rows = {r["name"]: r["detail"] for r in members._symbols_in_file(reg, "p", "a.py", "all", 50)}
    assert rows["old_f"] == "function · role not recorded"
    assert rows["new_f"] == "function · core"

    assert extraction_commit(reg, "p") is None                             # no extraction run recorded
    assert "commit not recorded" in members._symbol_members(reg, "p", "all", 50).note
    reg.record_step_run("p", "repo_symbol_extraction", "2026-10-15T10:00:00")  # run with no known sha
    assert "commit not recorded" in members._symbol_members(reg, "p", "all", 50).note
    reg.update_commit_sha("p", "3606859c0ffee1234567")
    reg.record_step_run("p", "repo_symbol_extraction", "2026-10-15T11:00:00")
    assert extraction_commit(reg, "p") == "3606859c0ffee1234567"
    assert "extracted at commit 3606859c0ffe" in members._symbol_members(reg, "p", "all", 50).note
