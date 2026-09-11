"""The things a count counted — resource_explorer/members.py.

Members are read from the registry, not from the display-shaped results,
because those drop `detail_json` and that is where cve_scan keeps its
advisory ids. These use a fresh SQLite registry and write the rows the
readers read, so every reader is exercised against the shape it consumes.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.members import children_for, members_for
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def db(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P", github_url="https://github.com/x/p", description=""))
    return r


class TestCveMembers:
    def test_advisories_come_from_detail_json_grouped_by_package(self, db):
        db.upsert_finding("p", "cve_scan", [
            {"check_name": "java:pkg-a", "label": "high", "summary": "2 advisories for pkg-a 1.0: GHSA-1, GHSA-2",
             "detail": {"package": "pkg-a", "version": "1.0", "severity": "HIGH", "advisory_ids": ["GHSA-1", "GHSA-2"]}},
            {"check_name": "java:pkg-b", "label": "moderate", "summary": "1 advisory",
             "detail": {"package": "pkg-b", "version": "2.0", "severity": "MODERATE", "advisory_ids": ["GHSA-3"]}},
        ], surveyed_at="2026-09-01T00:00:00")
        m = members_for(db, "p", "cve_scan").to_dict()
        assert m["total"] == 3
        assert [g["name"] for g in m["groups"]] == ["pkg-a 1.0", "pkg-b 2.0"]   # severity order
        assert [x["name"] for x in m["groups"][0]["members"]] == ["GHSA-1", "GHSA-2"]
        assert m["groups"][0]["members"][0]["detail"] == "high"
        assert m["source"].endswith("detail_json")


class TestSymbolMembers:
    def test_scope_public_drops_private_and_says_it_is_inferred(self, db):
        from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol

        def sym(path, qn, kind, private):
            return CodeSymbol(resource_slug="p", file_path=path, language="python", kind=kind,
                              name=qn.split(".")[-1], qualified_name=qn, signature="", docstring="",
                              start_line=1, end_line=2, is_private=private)
        db.upsert_code_symbols("p", [
            sym("a.py", "a.public_fn", "function", False),
            sym("a.py", "a._hidden", "function", True),
            sym("b.py", "b.C", "class", False),
        ])
        pub = members_for(db, "p", "api_structure", "symbol_count", scope="public").to_dict()
        allm = members_for(db, "p", "api_structure", "symbol_count", scope="all").to_dict()
        assert pub["total"] == 2 and allm["total"] == 3
        assert pub["scope_honoured"] is True
        assert "inferred" in pub["note"]
        # files are the first level; symbols are one level down, on demand
        files = {x["name"]: x for g in pub["groups"] for x in g["members"]}
        assert set(files) == {"a.py", "b.py"}
        kids = children_for(db, "p", "api_structure", files["a.py"]["children_key"], scope="public")
        assert [k["name"] for k in kids] == ["a.public_fn"]
        kids_all = children_for(db, "p", "api_structure", files["a.py"]["children_key"], scope="all")
        assert {k["name"] for k in kids_all} == {"a.public_fn", "a._hidden"}


class TestFallbackAndScope:
    def test_unknown_analysis_falls_back_to_its_findings_with_detail(self, db):
        db.upsert_finding("p", "interface_surface", [
            {"check_name": "cli", "label": "implied", "summary": "from click", "detail": {"framework": "click"}},
            {"check_name": "http_api", "label": "implied", "summary": "from fastapi"},
        ], surveyed_at="2026-09-01T00:00:00")
        m = members_for(db, "p", "interface_surface").to_dict()
        assert m["total"] == 2 and m["groups"][0]["name"] == "implied"
        assert m["groups"][0]["members"][0]["extra"] == {"framework": "click"}
        # scope is recorded but not honoured -- the caller can see it was
        # asked for and not applied, rather than assume it was
        assert m["scope"] == "public" and m["scope_honoured"] is False

    def test_bad_scope_is_coerced_not_trusted(self, db):
        assert members_for(db, "p", "interface_surface", scope="everything").to_dict()["scope"] == "public"

    def test_children_of_an_unknown_key_is_empty_not_an_error(self, db):
        assert children_for(db, "p", "cve_scan", "nope:x") == []
