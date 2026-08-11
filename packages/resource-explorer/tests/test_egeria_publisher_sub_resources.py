"""Tests for EgeriaPublisher._catalog_sub_resources() — the cataloging half
of the Assessment sub-resource cataloging plan
(docs/assessment-sub-resource-cataloging.md, D6/D8). Covers folder-before-
file ordering, correct parentGUID/parentRelationshipTypeName resolution
across all three edge shapes confirmed live in D5, and skip-if-already-found
idempotency."""
from __future__ import annotations

from unittest.mock import MagicMock

from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
from resource_explorer.surveyors.survey_report import ClassificationAnnotation, SurveyResult


def _result(with_sub_resource_step=True):
    annotations = [
        ClassificationAnnotation(
            summary="unrelated step", analysis_step="LanguageDetect",
        ),
    ]
    if with_sub_resource_step:
        annotations.append(
            ClassificationAnnotation(
                summary="sub-resource survey", analysis_step="SubResourceSurvey",
            )
        )
    return SurveyResult(
        project_slug="myproj",
        project_display_name="My Project",
        github_url="https://github.com/test/myproj",
        annotations=annotations,
    )


def _finding_row(path, kind, worthy=True, owners=None, **extra):
    import json
    detail = {"path": path, "kind": kind, "reason": "test", "owners": owners or [], **extra}
    return {
        "check_name": path or "(root)",
        "label": "worthy" if worthy else "not_worthy",
        "summary": "test",
        "confidence": 100,
        "detail_json": json.dumps(detail),
    }


def _publisher(registry):
    pub = EgeriaPublisher(platform_url="https://fake", registry=registry)
    pub._automated_curation = MagicMock()
    pub._asset_maker = MagicMock()
    # Nothing pre-exists in Egeria by default.
    pub._automated_curation.get_guid_for_name.return_value = []
    pub._automated_curation._async_get_template_guid_for_technology_type = MagicMock(
        return_value="template-guid-fake"
    )
    # _resolve_template_guid awaits this via asyncio — wrap so it returns directly.
    import asyncio

    async def _fake_async_template(type_name):
        return f"template-{type_name}"

    pub._automated_curation._async_get_template_guid_for_technology_type = _fake_async_template
    counter = {"n": 0}

    def _create(body):
        counter["n"] += 1
        return f"guid-{counter['n']}"

    pub._automated_curation.create_elem_from_template.side_effect = _create
    return pub


class TestNoOpWithoutSubResourceStep:
    def test_no_op_when_step_not_in_result(self):
        registry = MagicMock()
        pub = _publisher(registry)
        pub._catalog_sub_resources(_result(with_sub_resource_step=False), "asset-guid")
        registry.query_findings.assert_not_called()
        pub._automated_curation.create_elem_from_template.assert_not_called()

    def test_no_op_when_no_worthy_findings(self):
        registry = MagicMock()
        registry.query_findings.return_value = [_finding_row("README.md", "file", worthy=False)]
        pub = _publisher(registry)
        pub._catalog_sub_resources(_result(), "asset-guid")
        pub._automated_curation.create_elem_from_template.assert_not_called()


class TestOrderingAndParentResolution:
    def test_root_level_file_parents_to_synthetic_root_folder_via_nested_file(self):
        registry = MagicMock()
        registry.query_findings.return_value = [
            _finding_row("", "folder"),
            _finding_row("README.md", "file"),
        ]
        pub = _publisher(registry)
        pub._catalog_sub_resources(_result(), "asset-guid")

        calls = pub._automated_curation.create_elem_from_template.call_args_list
        assert len(calls) == 2
        folder_body = calls[0].args[0]
        file_body = calls[1].args[0]
        assert folder_body["parentGUID"] == "asset-guid"
        assert folder_body["parentRelationshipTypeName"] == "CapabilityAssetUse"
        assert file_body["parentGUID"] == "guid-1"  # the folder created first
        assert file_body["parentRelationshipTypeName"] == "NestedFile"

    def test_replacement_properties_pin_the_real_qualified_name(self):
        """Regression guard, confirmed live 2026-08-11: without an explicit
        replacementProperties override, Egeria's template mechanism derives
        its own qualifiedName from the placeholder values using its own
        convention (e.g. "FileFolder::~{fileSystemName}~:<path>"), NOT our
        qualified_name string byte-for-byte — silently breaking D8's
        find-by-qualifiedName idempotency guard. Every create call must pin
        qualifiedName explicitly, with the required "class" discriminator
        (a bare {"qualifiedName": ...} dict 400s: Egeria expects a typed
        EntityProperties subtype)."""
        registry = MagicMock()
        registry.query_findings.return_value = [_finding_row("docs", "folder")]
        pub = _publisher(registry)
        pub._catalog_sub_resources(_result(), "asset-guid")

        body = pub._automated_curation.create_elem_from_template.call_args_list[0].args[0]
        expected_qn = "SourceControlLibrary::https://github.com/test/myproj::docs"
        assert body["replacementProperties"] == {
            "class": "AssetProperties", "qualifiedName": expected_qn,
        }

    def test_depth_1_folder_parents_directly_to_repo_asset(self):
        registry = MagicMock()
        registry.query_findings.return_value = [_finding_row("docs", "folder")]
        pub = _publisher(registry)
        pub._catalog_sub_resources(_result(), "asset-guid")

        body = pub._automated_curation.create_elem_from_template.call_args_list[0].args[0]
        assert body["parentGUID"] == "asset-guid"
        assert body["parentRelationshipTypeName"] == "CapabilityAssetUse"

    def test_subfolder_parents_to_ancestor_folder_via_folder_hierarchy(self):
        registry = MagicMock()
        registry.query_findings.return_value = [
            _finding_row("docs", "folder"),
            _finding_row("docs/guides", "folder"),
        ]
        pub = _publisher(registry)
        pub._catalog_sub_resources(_result(), "asset-guid")

        calls = pub._automated_curation.create_elem_from_template.call_args_list
        sub_body = calls[1].args[0]
        assert sub_body["parentGUID"] == "guid-1"
        assert sub_body["parentRelationshipTypeName"] == "FolderHierarchy"

    def test_nested_file_parents_to_its_containing_folder_via_nested_file(self):
        registry = MagicMock()
        registry.query_findings.return_value = [
            _finding_row("docs", "folder"),
            _finding_row("docs/SECURITY.md", "file"),
        ]
        pub = _publisher(registry)
        pub._catalog_sub_resources(_result(), "asset-guid")

        calls = pub._automated_curation.create_elem_from_template.call_args_list
        file_body = calls[1].args[0]
        assert file_body["parentGUID"] == "guid-1"
        assert file_body["parentRelationshipTypeName"] == "NestedFile"

    def test_folders_are_all_created_before_any_file(self):
        registry = MagicMock()
        # File listed before its folder in the findings list — ordering must
        # still guarantee folder-before-file regardless of input order.
        registry.query_findings.return_value = [
            _finding_row("docs/SECURITY.md", "file"),
            _finding_row("docs", "folder"),
        ]
        pub = _publisher(registry)
        pub._catalog_sub_resources(_result(), "asset-guid")

        calls = pub._automated_curation.create_elem_from_template.call_args_list
        assert calls[0].args[0]["placeholderPropertyValues"]["directoryName"] == "docs"
        assert calls[1].args[0]["placeholderPropertyValues"]["fileName"] == "SECURITY.md"


class TestIdempotency:
    def test_skips_creation_when_qualified_name_already_found(self):
        registry = MagicMock()
        registry.query_findings.return_value = [_finding_row("docs", "folder")]
        pub = _publisher(registry)
        pub._automated_curation.get_guid_for_name.return_value = [
            "11111111-1111-1111-1111-111111111111"
        ]
        pub._catalog_sub_resources(_result(), "asset-guid")
        pub._automated_curation.create_elem_from_template.assert_not_called()

    def test_a_later_entry_can_still_use_the_found_guid_as_its_parent(self):
        registry = MagicMock()
        registry.query_findings.return_value = [
            _finding_row("docs", "folder"),
            _finding_row("docs/SECURITY.md", "file"),
        ]
        pub = _publisher(registry)

        def _lookup(qn):
            if qn.endswith("::docs"):
                return ["22222222-2222-2222-2222-222222222222"]
            return []

        pub._automated_curation.get_guid_for_name.side_effect = _lookup
        pub._catalog_sub_resources(_result(), "asset-guid")

        # Only the file should have been created via template — the folder
        # was already found.
        calls = pub._automated_curation.create_elem_from_template.call_args_list
        assert len(calls) == 1
        assert calls[0].args[0]["parentGUID"] == "22222222-2222-2222-2222-222222222222"
        assert calls[0].args[0]["parentRelationshipTypeName"] == "NestedFile"
