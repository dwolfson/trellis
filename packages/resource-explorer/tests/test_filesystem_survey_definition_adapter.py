"""Tests for the filesystem Survey Definition adapter (survey_definition_adapter.py)
and the richer annotation set publish_step_annotations now builds from an
enriched survey_data dict — see docs/filesystem-survey-analytics-plan.md.
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

from resource_explorer.registry import FileSystemEntity
from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyor
from resource_explorer.surveyors.survey_definition_executor import get_adapter


def test_filesystem_adapter_registration():
    adapter = get_adapter("filesystem")
    assert adapter.entity_type == "filesystem"
    assert adapter.technology_type == "File System Directory"
    assert adapter.egeria_technology_type_name == "File System Directory"
    assert "filesystem_inventory" in adapter.re_analysis_steps
    info = adapter.re_analysis_step_info["filesystem_inventory"]
    assert "ClassificationAnnotation" in info["annotation_types"]
    assert "RequestForActionAnnotation" in info["annotation_types"]


def test_run_filesystem_inventory_and_publish_roundtrip():
    """The adapter's runner + publish functions, wired together the same way
    the executor calls them, against a real temp directory with a malformed
    CSV — exercises the full path from walk -> annotations -> publish call."""
    import resource_explorer.surveyors.filesystem.survey_definition_adapter as fs_adapter

    with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmpdir:
        with open(os.path.join(tmpdir, "good.csv"), "w") as f:
            f.write("a,b\n1,2\n3,4\n")
        with open(os.path.join(tmpdir, "bad.csv"), "w") as f:
            f.write("header\nx\nx\nx\nx\na,b,c,d\n")  # triggers a tokenizing error
        with open(os.path.join(tmpdir, "mystery.xyz123"), "w") as f:
            f.write("unclassifiable")

        fs_entity = FileSystemEntity(
            slug="test-fs",
            display_name="Test FS",
            local_mount_point=tmpdir,
            canonical_mount_point="file://shared-nfs/test-fs",
            egeria_asset_guid="fs-guid-1",
        )
        registry = MagicMock()

        step_output = fs_adapter._run_filesystem_inventory(fs_entity, registry)
        survey_data = step_output["survey_data"]
        assert survey_data["total_files"] == 3
        assert survey_data["profiling_errors"], "malformed CSV should be recorded, not silently dropped"
        assert survey_data["classification"]["unclassified_count"] >= 1

        captured_annotations = []
        with patch.object(EgeriaFileSystemSurveyor, "connect", lambda self: None), \
             patch.object(EgeriaFileSystemSurveyor, "_create_annotations",
                           lambda self, annotations, guid, slug, ts: captured_annotations.extend(annotations)):
            e = EgeriaFileSystemSurveyor()
            e._asset_maker = MagicMock()
            e._asset_maker.create_asset.return_value = "report-guid-1"

            with patch(
                "resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor.EgeriaFileSystemSurveyor",
                return_value=e,
            ):
                report_guid = fs_adapter._publish(fs_entity, [step_output], survey_data["surveyed_at"], registry)

        assert report_guid == "report-guid-1"

        summaries = [a.summary for a in captured_annotations]
        assert any("could not be schema-profiled" in s for s in summaries)
        assert any("could not be classified" in s for s in summaries)
        assert any("classified as" in s for s in summaries)


def test_publish_step_annotations_requires_cataloged_filesystem():
    """publish_step_annotations must not silently no-op or auto-catalog — a
    filesystem with no known Egeria GUID and nothing findable by canonical
    mount point should raise, not create a new asset as a side effect."""
    fs_entity = FileSystemEntity(
        slug="uncataloged-fs",
        display_name="Uncataloged FS",
        local_mount_point="/tmp/nowhere",
        canonical_mount_point="file://nowhere",
    )
    minimal_survey_data = {
        "total_files": 0, "total_data_files": 0, "total_size_bytes": 0, "total_size": "0 B",
        "formats": {}, "inventory": [], "classification": {}, "inaccessible_files": [], "profiling_errors": [],
    }

    with patch.object(EgeriaFileSystemSurveyor, "connect", lambda self: None), \
         patch.object(EgeriaFileSystemSurveyor, "_find_element_guid", lambda self, mount: None):
        e = EgeriaFileSystemSurveyor()
        try:
            e.publish_step_annotations(fs_entity, minimal_survey_data, MagicMock())
            assert False, "expected EgeriaFileSystemSurveyorError"
        except Exception as exc:
            assert "not yet cataloged" in str(exc)
