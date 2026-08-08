"""
Survey Definition adapter for filesystems.

Registers a ResourceTypeAdapter (entity_type="filesystem") with
resource_explorer.surveyors.survey_definition_executor, wiring the
"filesystem_inventory" re_analysis_step to the existing LocalFileSystemSurveyor,
and publishing results via EgeriaFileSystemSurveyor.publish_step_annotations (the
narrow publish path — does not auto-catalog the filesystem root or its files).
"""
from __future__ import annotations

from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    register_adapter,
)


def _run_filesystem_inventory(fs_entity, registry, **_) -> dict:
    from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import LocalFileSystemSurveyor

    surveyor = LocalFileSystemSurveyor(fs_entity, registry)
    return {"survey_data": surveyor.run()}


def _get_filesystem_entity(registry, slug: str):
    return registry.get_filesystem(slug)


def _publish(entity, step_outputs: list, surveyed_at: str, registry) -> str:
    from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyor

    survey_data: dict = {}
    for output in step_outputs:
        survey_data = output.get("survey_data") or survey_data

    surveyor = EgeriaFileSystemSurveyor()
    result = surveyor.publish_step_annotations(entity, survey_data, registry)
    return result.get("report_guid", "")


_ADAPTER = ResourceTypeAdapter(
    entity_type="filesystem",
    # Confirmed live against Egeria's real Technology Type catalog (2026-07-13,
    # EgeriaTechTypeCatalog.get_tech_type_detail): the correct display name is
    # "File System Directory" (deployedImplementationType-(File System
    # Directory)); "File Folder" is only the underlying open-metadata type name
    # (FileFolder), not a Technology Type. The previous "File Folder" guess
    # meant a Survey Definition authored with the real name would never match
    # RE's candidate lookup.
    technology_type="File System Directory",
    re_analysis_steps={"filesystem_inventory": _run_filesystem_inventory},
    get_entity=_get_filesystem_entity,
    publish=_publish,
    re_analysis_step_info={
        "filesystem_inventory": {
            "description": (
                "Walks the filesystem (counts, sizes, hidden/symlink/executable/writable "
                "flags, timestamps, Egeria-reference-data classification), flags "
                "inaccessible/unclassified files, and profiles data file schemas."
            ),
            "annotation_types": [
                "ResourceMeasureAnnotation",
                "ClassificationAnnotation",
                "RequestForActionAnnotation",
                "SchemaAnalysisAnnotation",
            ],
        },
    },
    egeria_technology_type_name="File System Directory",
)

register_adapter(_ADAPTER)
