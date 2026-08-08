"""
Engine-agnostic reader for live Egeria SurveyReport/Annotation data, walking
the real ReportSubject/ReportedAnnotation relationships from a resource's own
asset GUID. Works for any resource type (database, repo, filesystem) that has
an AssetMaker-capable Egeria connection, since RE's own publishers
(EgeriaDatabaseSurveyor, EgeriaPublisher, EgeriaFileSystemSurveyor) all write
SurveyReports via the identical relationship shape — this is pure AssetMaker
graph traversal with no resource-type-specific logic.

Confirmed live 2026-07-08 via AssetMaker.get_asset_by_guid(guid,
body={"graphQueryDepth": 1}): the response has a top-level "reports" key (for
a resource asset) or "reportedAnnotations" key (for a SurveyReport asset),
each listing RelatedMetadataElementSummary entries.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def get_survey_reports_by_guid(asset_maker, resource_guid: str) -> list[dict]:
    """All SurveyReports linked to a resource's asset GUID via ReportSubject,
    regardless of which engine (RE or Egeria's own native survey) created
    them. `asset_maker` is any connected pyegeria AssetMaker instance."""
    reports: list[dict] = []
    try:
        body = {"class": "GetRequestBody", "graphQueryDepth": 1}
        result = asset_maker.get_asset_by_guid(resource_guid, body=body, output_format="JSON")
        if not isinstance(result, dict):
            return []
        for entry in result.get("reports") or []:
            related = entry.get("relatedElement", {})
            header = related.get("elementHeader", {})
            props = related.get("properties", {})
            additional = props.get("additionalProperties", {})
            surveyed_at = header.get("versions", {}).get("createTime", "")
            reports.append({
                "guid": header.get("guid", ""),
                "qualified_name": props.get("qualifiedName", ""),
                "display_name": props.get("displayName", ""),
                "surveyed_at": surveyed_at,
                "annotation_count": _safe_int(additional.get("annotation_count")),
                "schema_count": _safe_int(additional.get("schema_count")),
                "table_count": _safe_int(additional.get("table_count")),
                "column_count": _safe_int(additional.get("column_count")),
                "description": props.get("description", ""),
            })
    except Exception as exc:
        log.debug(f"get_survey_reports_by_guid failed for {resource_guid}: {exc}")

    reports.sort(key=lambda r: r.get("surveyed_at", ""), reverse=True)
    return reports


def get_annotations_by_report_guid(asset_maker, report_guid: str) -> list[dict]:
    """All annotations attached to a SurveyReport via ReportedAnnotation,
    regardless of which engine produced the report."""
    annotations: list[dict] = []
    try:
        body = {"class": "GetRequestBody", "graphQueryDepth": 1}
        result = asset_maker.get_asset_by_guid(report_guid, body=body, output_format="JSON")
        if not isinstance(result, dict):
            return []
        for entry in result.get("reportedAnnotations") or []:
            related = entry.get("relatedElement", {})
            header = related.get("elementHeader", {})
            props = related.get("properties", {})
            annotation_type = props.get("annotationType", "") or header.get("type", {}).get("typeName", "")
            annotations.append({
                "guid": header.get("guid", ""),
                "annotation_type": annotation_type,
                "summary": props.get("summary", ""),
                "confidence": _safe_int(props.get("confidence", 100)),
                "analysis_step": props.get("analysisStep", ""),
                "explanation": props.get("explanation", ""),
                "expression": props.get("expression", ""),
                "json_properties": props.get("jsonProperties", {}),
            })
    except Exception as exc:
        log.debug(f"get_annotations_by_report_guid failed for {report_guid}: {exc}")

    return annotations
