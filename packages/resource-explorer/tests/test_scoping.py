"""Tests for scoping.py (D5/D6 repo scope-narrowing funnel plan,
docs/repo-scope-narrowing-funnel.md) — the shared path-prefix filter helpers
used by every corpus-shaped repo surveyor."""
from __future__ import annotations

from resource_explorer.surveyors.scoping import path_matches_scope, sql_scope_filter


class TestPathMatchesScope:
    def test_empty_scope_matches_everything(self):
        assert path_matches_scope("any/path.py", "") is True
        assert path_matches_scope("", "") is True

    def test_exact_file_match(self):
        assert path_matches_scope("src/mod.py", "src/mod.py") is True

    def test_folder_prefix_match(self):
        assert path_matches_scope("src/mod.py", "src") is True
        assert path_matches_scope("src/nested/mod.py", "src") is True

    def test_no_match_for_sibling_or_partial_name(self):
        assert path_matches_scope("srcother/mod.py", "src") is False
        assert path_matches_scope("other/mod.py", "src") is False

    def test_no_match_for_unrelated_file(self):
        assert path_matches_scope("src/mod.py", "src/other.py") is False


class TestSqlScopeFilter:
    def test_empty_scope_returns_no_filter(self):
        sql, params = sql_scope_filter("")
        assert sql == ""
        assert params == ()

    def test_non_empty_scope_returns_parameterized_fragment(self):
        sql, params = sql_scope_filter("src")
        assert sql == " AND (file_path = ? OR file_path LIKE ?)"
        assert params == ("src", "src/%")

    def test_custom_column_name(self):
        sql, params = sql_scope_filter("schema1", column="table_schema")
        assert "table_schema = ?" in sql
        assert "table_schema LIKE ?" in sql
        assert params == ("schema1", "schema1/%")

    def test_never_string_interpolates_scope_locator(self):
        # Malicious-looking locator must stay in params, never in the SQL text.
        sql, params = sql_scope_filter("'; DROP TABLE x; --")
        assert "DROP TABLE" not in sql
        assert params[0] == "'; DROP TABLE x; --"
