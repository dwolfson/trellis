"""`egeria_interfaces` — which Egeria view services a repository consumes, and
its Dr.Egeria usage, both zero-fetch (project owner's "Cataloguing in layers"
decision, 2026-09-14).

`project_code_symbols` records only symbol DEFINITIONS — no import
statements, no call/instantiation sites (verified against `registry.py`
before this module was built). The tests here pin the honest consequence:
matches are a lower bound derived from signature/return-type/base-class text,
never claimed as a full count, and a repo with no pyegeria dependency reads
`nothing_found`.
"""
from __future__ import annotations

import textwrap

import pytest

from resource_explorer.surveyors import egeria_interfaces as ei


@pytest.fixture(autouse=True)
def _fresh():
    ei.clear_cache()
    yield
    ei.clear_cache()


def _write_mapping(tmp_path, body: str):
    p = tmp_path / "m.yaml"
    p.write_text(textwrap.dedent(body))
    return p


class TestTheMappingIsValidatedLoudly:
    def test_the_real_mapping_loads(self):
        entries = ei.load_mapping()
        assert len(entries) >= 20
        assert any(e.client_class == "ClassificationExplorer" for e in entries)

    def test_unknown_keys_are_rejected(self, tmp_path):
        p = _write_mapping(tmp_path, """
            client_classes:
              - client_class: X
                servcie: foo
        """)
        with pytest.raises(ei.EgeriaViewServiceMappingError, match="unknown keys"):
            ei.load_mapping(p)

    def test_missing_client_class_is_rejected(self, tmp_path):
        p = _write_mapping(tmp_path, """
            client_classes:
              - module: foo
        """)
        with pytest.raises(ei.EgeriaViewServiceMappingError, match="no client_class"):
            ei.load_mapping(p)

    def test_duplicate_client_class_is_rejected(self, tmp_path):
        p = _write_mapping(tmp_path, """
            client_classes:
              - client_class: X
                view_service: A
              - client_class: X
                view_service: B
        """)
        with pytest.raises(ei.EgeriaViewServiceMappingError, match="listed twice"):
            ei.load_mapping(p)

    def test_a_class_with_no_view_service_loads_as_unmapped(self, tmp_path):
        p = _write_mapping(tmp_path, """
            client_classes:
              - client_class: SomeHelper
                module: helper
        """)
        entries = ei.load_mapping(p)
        assert entries[0].view_service is None


class TestAssessGatesOnPyegeriaDeclared:
    def test_no_pyegeria_dependency_is_nothing_found(self):
        a = ei.assess(pyegeria_declared=False, code_symbol_rows=[{"signature": "ClassificationExplorer"}],
                      inherits_from_rows=[], file_inventory_paths=[])
        assert a.state == ei.NOTHING_FOUND
        assert a.view_services == []
        assert "No pyegeria dependency" in a.headline()


class TestClientClassMatching:
    def _mapping(self):
        return (ei.ViewServiceClient("ClassificationExplorer", "classification_explorer",
                                     "Classification Explorer", "classification-explorer"),
                ei.ViewServiceClient("GlossaryManager", "glossary_manager",
                                     "Glossary Manager", "glossary-manager"))

    def test_a_signature_mentioning_a_client_class_matches(self):
        rows = [{"qualified_name": "Foo.bar", "signature": "(self, client: ClassificationExplorer)",
                 "return_type": "", "file_path": "foo.py"}]
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=rows, inherits_from_rows=[],
                      file_inventory_paths=[], mapping=self._mapping())
        assert len(a.view_services) == 1
        assert a.view_services[0].view_service == "Classification Explorer"
        assert a.view_services[0].client_classes == ["ClassificationExplorer"]

    def test_a_substring_that_is_not_a_whole_identifier_does_not_match(self):
        rows = [{"qualified_name": "Foo.bar", "signature": "(self, x: MyClassificationExplorerSubclass)",
                 "return_type": "", "file_path": "foo.py"}]
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=rows, inherits_from_rows=[],
                      file_inventory_paths=[], mapping=self._mapping())
        assert a.view_services == []

    def test_a_return_type_match_is_also_counted(self):
        rows = [{"qualified_name": "make_client", "signature": "()", "return_type": "GlossaryManager",
                 "file_path": "foo.py"}]
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=rows, inherits_from_rows=[],
                      file_inventory_paths=[], mapping=self._mapping())
        assert a.view_services[0].view_service == "Glossary Manager"

    def test_inheritance_from_a_client_class_is_counted_as_base_class_evidence(self):
        rels = [{"source_name": "MyExplorer.__class__", "target_name": "ClassificationExplorer"}]
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=[], inherits_from_rows=rels,
                      file_inventory_paths=[], mapping=self._mapping())
        assert a.view_services[0].client_matches[0].evidence[0]["matched_field"] == "base_class"

    def test_two_client_classes_for_the_same_view_service_are_aggregated(self):
        mapping = (ei.ViewServiceClient("AssetCatalog", "asset_catalog", "Asset Catalog", "asset-catalog"),
                  ei.ViewServiceClient("RegisteredInfo", "registered_info", "Asset Catalog", "asset-catalog",
                                       shares_path_with="AssetCatalog"))
        rows = [
            {"qualified_name": "a", "signature": "(c: AssetCatalog)", "return_type": "", "file_path": "a.py"},
            {"qualified_name": "b", "signature": "(c: RegisteredInfo)", "return_type": "", "file_path": "b.py"},
        ]
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=rows, inherits_from_rows=[],
                      file_inventory_paths=[], mapping=mapping)
        assert len(a.view_services) == 1
        assert a.view_services[0].client_classes == ["AssetCatalog", "RegisteredInfo"]

    def test_an_unmapped_client_class_is_named_not_dropped(self):
        mapping = (ei.ViewServiceClient("SomeHelper", "helper", None, None),)
        rows = [{"qualified_name": "a", "signature": "(c: SomeHelper)", "return_type": "", "file_path": "a.py"}]
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=rows, inherits_from_rows=[],
                      file_inventory_paths=[], mapping=mapping)
        assert a.view_services == []
        assert a.unmapped_client_classes == ["SomeHelper"]

    def test_no_matches_still_reads_checked_not_nothing_found(self):
        """pyegeria IS declared, but no symbol text happens to match — this is
        a real zero of a different kind than 'pyegeria is absent'."""
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=[], inherits_from_rows=[],
                      file_inventory_paths=[], mapping=self._mapping())
        assert a.state == ei.CHECKED
        assert a.view_services == []


class TestDrEgeriaEvidence:
    def test_paths_under_dr_egeria_are_counted(self):
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=[], inherits_from_rows=[],
                      file_inventory_paths=["docs/dr-egeria/create-term.md", "README.md"],
                      mapping=())
        assert a.dr_egeria_doc_paths == ["docs/dr-egeria/create-term.md"]

    def test_command_shaped_filenames_produce_a_family_guess(self):
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=[], inherits_from_rows=[],
                      file_inventory_paths=["docs/dr-egeria/create-term.md"], mapping=())
        assert len(a.dr_egeria_families) == 1
        assert a.dr_egeria_families[0].name == "create_term"
        assert a.dr_egeria_families[0].basis == "filename_guess"

    def test_a_non_command_shaped_filename_produces_no_family(self):
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=[], inherits_from_rows=[],
                      file_inventory_paths=["docs/dr-egeria/README.md"], mapping=())
        assert a.dr_egeria_families == []
        assert a.dr_egeria_doc_paths == ["docs/dr-egeria/README.md"]


class TestFindingsShape:
    def test_coverage_row_confidence_reflects_nothing_found(self):
        a = ei.assess(pyegeria_declared=False, code_symbol_rows=[], inherits_from_rows=[],
                      file_inventory_paths=[])
        cov = [r for r in a.as_findings() if r["check_name"] == "coverage"][0]
        assert cov["confidence"] == 100
        assert cov["label"] == ei.NOTHING_FOUND

    def test_a_view_service_row_never_claims_full_confidence(self):
        mapping = (ei.ViewServiceClient("ClassificationExplorer", "classification_explorer",
                                        "Classification Explorer", "classification-explorer"),)
        rows = [{"qualified_name": "a", "signature": "(c: ClassificationExplorer)",
                "return_type": "", "file_path": "a.py"}]
        a = ei.assess(pyegeria_declared=True, code_symbol_rows=rows, inherits_from_rows=[],
                      file_inventory_paths=[], mapping=mapping)
        vs_row = [r for r in a.as_findings() if r["check_name"] == "view_service"][0]
        assert vs_row["confidence"] < 100, "a lower-bound signal must never read as fully confident"


# ── the surveyor, against the real registry ─────────────────────────────────

class TestTheSurveyor:
    @pytest.fixture
    def slug(self, request):
        import re
        return "ei_" + re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:48]

    @pytest.fixture
    def reg(self, pg_registry, slug):
        from resource_explorer.registry import Project
        pg_registry.add(Project(slug=slug, display_name=slug, github_url=f"https://github.com/x/{slug}"))
        return pg_registry

    def _run(self, reg, slug):
        from resource_explorer.surveyors.sub_surveyors.egeria_interfaces import EgeriaInterfacesSurveyor
        return EgeriaInterfacesSurveyor(project=reg.get(slug), registry=reg).run()

    def test_no_pyegeria_dependency_is_nothing_found_not_never_run(self, reg, slug):
        anns = self._run(reg, slug)
        # Not "coverage": that check_name belongs to the normal path's own
        # coverage annotation, and two annotations sharing a check_name with
        # no item_key collide on publish (test_annotation_check_names). This
        # branch says "nothing to assess" — pyegeria isn't even declared.
        assert len(anns) == 1 and anns[0].check_name == "nothing_to_assess"
        assert anns[0].json_properties.get("state") == ei.NOTHING_FOUND
        rows = reg.query_findings(slug, "egeria_interfaces")
        assert rows and rows[0]["label"] == ei.NOTHING_FOUND

    def test_pyegeria_declared_with_a_matching_symbol_publishes_a_view_service(self, reg, slug):
        reg.upsert_dependencies(slug, [
            {"dep_name": "pyegeria", "dep_version": "5.4", "dep_type": "runtime",
             "ecosystem": "python", "source_file": "pyproject.toml"},
        ])
        with reg._conn() as conn:
            conn.execute(
                "INSERT INTO project_code_symbols (project_slug, file_path, language, kind, name, "
                "qualified_name, signature, docstring, summary, start_line, end_line) "
                "VALUES (?, 'foo.py', 'python', 'function', 'connect', 'connect', "
                "'(server: ClassificationExplorer)', '', '', 1, 2)", (slug,),
            )
        anns = self._run(reg, slug)
        assert {a.check_name for a in anns} == {"view_service", "coverage"}
        vs_ann = [a for a in anns if a.check_name == "view_service"][0]
        assert vs_ann.item_key == "Classification Explorer"

        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _egeria_interfaces_headline, _egeria_interfaces_results)
        res = _egeria_interfaces_results(reg, slug)
        assert res["view_services"][0]["view_service"] == "Classification Explorer"
        h = _egeria_interfaces_headline(reg, slug)
        assert "1 Egeria view service" in h["label"]

    def test_never_run_is_a_status_envelope_not_content(self, reg, slug):
        from resource_explorer.facts import _has_content
        from resource_explorer.surveyors.repo_survey_definition_adapter import _egeria_interfaces_results
        res = _egeria_interfaces_results(reg, "no_such_repo_at_all")
        assert "_status" in res and not _has_content(res)


class TestItsAnnotationsPublish:
    @pytest.fixture
    def slug(self, request):
        import re
        return "eip_" + re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:44]

    @pytest.fixture
    def reg(self, pg_registry, slug):
        from resource_explorer.registry import Project
        pg_registry.add(Project(slug=slug, display_name=slug, github_url=f"https://github.com/x/{slug}"))
        pg_registry.upsert_dependencies(slug, [
            {"dep_name": "pyegeria", "dep_version": "5.4", "dep_type": "runtime",
             "ecosystem": "python", "source_file": "pyproject.toml"},
        ])
        with pg_registry._conn() as conn:
            conn.executemany(
                "INSERT INTO project_code_symbols (project_slug, file_path, language, kind, name, "
                "qualified_name, signature, docstring, summary, start_line, end_line) "
                "VALUES (?, ?, 'python', 'function', 'f', 'f', ?, '', '', 1, 2)",
                [(slug, "a.py", "(x: ClassificationExplorer)"),
                 (slug, "b.py", "(x: GlossaryManager)"),
                 (slug, "c.py", "(x: ProjectManager)")],
            )
        return pg_registry

    def test_multiple_view_services_publish_under_distinct_qualified_names(self, reg, slug):
        from resource_explorer.surveyors.sub_surveyors.egeria_interfaces import EgeriaInterfacesSurveyor
        from resource_explorer.surveyors.survey_report import assert_unique_qualified_names
        anns = EgeriaInterfacesSurveyor(project=reg.get(slug), registry=reg).run()
        vs = [a for a in anns if a.check_name == "view_service"]
        assert len(vs) >= 2, "the fixture must produce the collision case"
        assert_unique_qualified_names(f"Annotation::{slug}::2026-09-14T00:00:00", anns)
        keys = [a.item_key for a in vs]
        assert all(keys) and len(set(keys)) == len(keys)


class TestItIsWiredEverywhere:
    def test_step_kind_and_ownership(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS, REPO_ANALYSIS_STEP_MAP, STEP_REGISTRY)
        assert "repo_egeria_interfaces" in STEP_REGISTRY
        assert REPO_ANALYSIS_STEP_MAP["egeria_interfaces"] == ["repo_egeria_interfaces"]
        from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_RESULTS_MAP
        assert "egeria_interfaces" in REPO_ANALYSIS_RESULTS_MAP

    def test_the_step_fetches_nothing_so_discovery_is_honest(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
        assert not (getattr(STEP_REGISTRY["repo_egeria_interfaces"], "requires_resources", {}) or {})

    def test_the_catalog_entry_is_discovery(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        e = {a["id"]: a for a in get_analyses("repo", include_egeria_live=False)}["egeria_interfaces"]
        assert e["intent"] == "discovery"

    def test_it_is_in_the_discovery_survey(self):
        import csv
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "repo_survey_types.csv"
        rows = [r for r in csv.DictReader(p.open()) if r["step_key"] == "repo_egeria_interfaces"]
        assert {r["survey_group"] for r in rows} == {"RepoDiscoverySurvey"}
