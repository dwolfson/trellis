"""
Publishes a SurveyResult to Egeria via pyegeria.

Asset type: SourceControlLibrary (subtype of SoftwareCapability / ResourceManager).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING

from resource_explorer.surveyors.survey_report import AnnotationType, SurveyResult

if TYPE_CHECKING:
    from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)

# ── Egeria connection defaults (standard pyegeria env vars) ──────────────────
_DEFAULT_PLATFORM_URL = "https://localhost:9443"
_DEFAULT_VIEW_SERVER = "qs-view-server"
_DEFAULT_USER = "erinoverview"
_DEFAULT_PASSWORD = "secret"
_DEFAULT_TIMEOUT = 30


class EgeriaConnectionError(RuntimeError):
    """Raised when Egeria credentials are absent or the platform is unreachable."""


class EgeriaPublisher:
    """
    Converts a SurveyResult into Egeria API calls:
      1. Find or create the SourceControlLibrary asset
      2. Create a SurveyReport linked via ReportSubject
      3. Create one Annotation per SurveyResult.annotation

    All Egeria coupling is contained here — sub-surveyors and SurveyResult
    have no pyegeria dependency.
    """

    def __init__(
        self,
        platform_url: str | None = None,
        view_server: str | None = None,
        user_id: str | None = None,
        user_password: str | None = None,
        timeout: int | None = None,
        registry: "ProjectRegistry | None" = None,
        zone_names: list[str] | None = None,
    ) -> None:
        self.platform_url = platform_url or os.getenv("EGERIA_PLATFORM_URL", _DEFAULT_PLATFORM_URL)
        self.view_server = view_server or os.getenv("EGERIA_VIEW_SERVER", _DEFAULT_VIEW_SERVER)
        self.user_id = user_id or os.getenv("EGERIA_USER", _DEFAULT_USER)
        self.user_password = user_password or os.getenv("EGERIA_USER_PASSWORD", _DEFAULT_PASSWORD)
        self.timeout = timeout or int(os.getenv("PYEGERIA_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT)))
        self._registry = registry
        self._asset_maker = None
        self._discovery = None
        # Zone names: caller-supplied > config default > []
        if zone_names is not None:
            self.zone_names = zone_names
        else:
            try:
                from resource_explorer.config import get_config
                self.zone_names = get_config().egeria.default_catalog_zones
            except Exception:
                self.zone_names = []

    # ── public entry point ────────────────────────────────────────────────────

    def publish(self, result: SurveyResult, zone_names: list[str] | None = None) -> str:
        """
        Push the full SurveyResult to Egeria.
        Returns the GUID of the created SurveyReport.
        Raises EgeriaConnectionError if credentials are missing or platform unreachable.
        zone_names overrides the instance-level zone_names for this call only.
        """
        if zone_names is not None:
            self.zone_names = zone_names
        self._connect()
        asset_guid = self._find_or_create_asset(result)
        report_guid = self._create_survey_report(result, asset_guid)
        self._create_annotations(result, report_guid)
        log.info(
            "Published survey for %s → SurveyReport GUID %s (%d annotations)",
            result.project_slug,
            report_guid,
            len(result.annotations),
        )

        if self._registry:
            try:
                from resource_explorer.activity_logger import log_catalog
                log_catalog(
                    self._registry,
                    entity_type="repo",
                    entity_slug=result.project_slug,
                    entity_name=result.project_display_name,
                    entity_location=result.github_url,
                    status="ok",
                    summary=(
                        f"Published to Egeria: {len(result.annotations)} annotations"
                        f" → {(report_guid or 'no-guid')[:12]}…"
                    ),
                    items=[
                        {
                            "kind": "SourceControlLibrary",
                            "display_name": result.project_display_name,
                            "qualified_name": f"SourceControlLibrary::{result.github_url}",
                            "guid": asset_guid,
                            "location": result.github_url,
                        },
                        {
                            "kind": "SurveyReport",
                            "display_name": f"Survey: {result.project_display_name}",
                            "qualified_name": (
                                f"SurveyReport::GitHubRepo::{result.project_slug}"
                                f"::{result.surveyed_at.isoformat()}"
                            ),
                            "guid": report_guid,
                            "location": "",
                        },
                    ],
                )
            except Exception as exc:
                log.warning("Could not write activity log entry: %s", exc)

        return report_guid

    def get_survey_reports_by_guid(self, project_guid: str) -> list[dict]:
        """All SurveyReports linked to this repo's asset GUID via the real
        ReportSubject relationship — regardless of which engine created them.
        Thin wrapper over the engine-agnostic reader shared with
        EgeriaDatabaseSurveyor/EgeriaFileSystemSurveyor (egeria_survey_reader.py)."""
        from resource_explorer.surveyors.egeria_survey_reader import get_survey_reports_by_guid

        self._connect()
        return get_survey_reports_by_guid(self._asset_maker, project_guid)

    def get_annotations_by_report_guid(self, report_guid: str) -> list[dict]:
        """All annotations attached to a specific SurveyReport via the real
        ReportedAnnotation relationship. Thin wrapper over the engine-agnostic
        reader in egeria_survey_reader.py."""
        from resource_explorer.surveyors.egeria_survey_reader import get_annotations_by_report_guid

        self._connect()
        return get_annotations_by_report_guid(self._asset_maker, report_guid)

    # ── connection ────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        if not self.platform_url:
            raise EgeriaConnectionError(
                "EGERIA_PLATFORM_URL is not set. "
                "Add it to your .env file or pass platform_url= to EgeriaPublisher."
            )
        try:
            from pyegeria import AssetMaker
            from pyegeria.omvs.data_discovery import DataDiscovery

            self._asset_maker = AssetMaker(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._asset_maker.create_egeria_bearer_token(self.user_id, self.user_password)

            self._discovery = DataDiscovery(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._discovery.create_egeria_bearer_token(self.user_id, self.user_password)
        except ImportError as exc:
            raise EgeriaConnectionError(
                "pyegeria is not installed. Add it to your dependencies."
            ) from exc
        except Exception as exc:
            raise EgeriaConnectionError(
                f"Could not connect to Egeria at {self.platform_url}: {exc}"
            ) from exc

    # ── asset registration ────────────────────────────────────────────────────

    def _find_or_create_asset(self, result: SurveyResult) -> str:
        """Return the GUID of a SourceControlLibrary asset for the GitHub repo.

        Checks the registry cache first to avoid an unnecessary search call on
        repeated --publish runs. Creates the asset when not already registered.
        """
        qualified_name = f"SourceControlLibrary::{result.github_url}"

        # Check local cache first, but verify the GUID still exists in Egeria.
        # If the Egeria database was reset, the cached GUID is stale — clear it
        # and fall through to the search/create path rather than failing later.
        if self._registry:
            cached = self._registry.get_egeria_asset_guid(result.project_slug)
            if cached:
                try:
                    check = self._asset_maker.find_software_capabilities(
                        search_string=qualified_name,
                        starts_with=True,
                        ignore_case=False,
                        output_format="JSON",
                    )
                    if isinstance(check, list) and any(
                        e.get("elementHeader", {}).get("guid") == cached for e in check
                    ):
                        log.info("Using cached Egeria asset GUID %s for %s", cached, result.project_slug)
                        return cached
                    # GUID not found — Egeria DB may have been reset; clear the stale cache
                    log.warning(
                        "Cached GUID %s no longer in Egeria for %s — will re-register",
                        cached, result.project_slug,
                    )
                    self._registry.clear_egeria_registration(result.project_slug)
                except Exception as exc:
                    log.debug("Cache verification failed (will proceed): %s", exc)
                    return cached  # network error — trust the cache rather than re-create

        # Search Egeria for an existing asset with this qualifiedName
        try:
            existing = self._asset_maker.find_software_capabilities(
                search_string=qualified_name,
                starts_with=True,
                ignore_case=False,
                output_format="JSON",
            )
            if isinstance(existing, list) and existing:
                guid = existing[0].get("elementHeader", {}).get("guid")
                if guid:
                    log.info("Found existing Egeria asset GUID %s for %s", guid, result.project_slug)
                    self._cache_asset_guid(result.project_slug, guid)
                    return guid
        except Exception as exc:
            log.debug("Asset search failed (will create): %s", exc)

        # Gather project stats for additional metadata
        primary_language = ""
        license_name = ""
        topics_csv = ""
        if self._registry:
            stats = self._registry.get_latest_project_stats(result.project_slug)
            if stats:
                primary_language = stats.get("primary_language") or ""
                license_name = stats.get("license") or ""
                topics_csv = stats.get("topics") or ""

        props: dict = {
            "class": "SoftwareCapabilityProperties",
            "typeName": "SourceControlLibrary",
            "qualifiedName": qualified_name,
            "displayName": result.project_display_name,
            "description": f"GitHub repository: {result.github_url}",
            "deployedImplementationType": "GitHub Repository",
            "libraryType": "GitHub Repository",
            "additionalProperties": {
                "github_url": result.github_url,
                "project_slug": result.project_slug,
                "primary_language": primary_language,
                "license": license_name,
                "topics": topics_csv,
            },
        }
        if self.zone_names:
            props["zoneMembership"] = self.zone_names
        body = {"class": "NewElementRequestBody", "properties": props}
        guid = self._asset_maker.create_software_capability(body=body)
        log.info("Created SourceControlLibrary GUID %s for %s", guid, result.project_slug)
        self._cache_asset_guid(result.project_slug, guid)
        return guid

    def _cache_asset_guid(self, slug: str, guid: str) -> None:
        if self._registry:
            try:
                self._registry.set_egeria_asset_guid(slug, guid)
            except Exception as exc:
                log.warning("Could not persist Egeria asset GUID to registry: %s", exc)

    # ── survey report ─────────────────────────────────────────────────────────

    def _create_survey_report(self, result: SurveyResult, asset_guid: str) -> str:
        surveyed_at_iso = result.surveyed_at.isoformat()
        qualified_name = (
            f"SurveyReport::GitHubRepo::{result.project_slug}::{surveyed_at_iso}"
        )
        body = {
            "class": "NewElementRequestBody",
            "parentGUID": asset_guid,
            "parentRelationshipTypeName": "ReportSubject",
            "properties": {
                "class": "AssetProperties",
                "typeName": "SurveyReport",
                "qualifiedName": qualified_name,
                "displayName": f"Survey: {result.project_display_name}",
                "description": (
                    f"Automated survey of {result.github_url} "
                    f"run at {surveyed_at_iso} by resource-explorer."
                ),
                "additionalProperties": {
                    "annotation_count": str(len(result.annotations)),
                    "error_count": str(len(result.errors)),
                },
            },
        }
        report_guid = self._asset_maker.create_asset(body=body)

        # Persist so the pull path (EgeriaReader) and CLI can reference it
        if self._registry:
            try:
                self._registry.record_egeria_survey(
                    result.project_slug,
                    surveyed_at_iso,
                    report_guid,
                    annotation_count=len(result.annotations),
                )
            except Exception as exc:
                log.warning("Could not persist Egeria survey record to registry: %s", exc)

        return report_guid

    # ── annotations ───────────────────────────────────────────────────────────

    def _create_annotations(self, result: SurveyResult, report_guid: str) -> None:
        for i, ann in enumerate(result.annotations):
            qualified_name = (
                f"Annotation::{result.project_slug}::{result.surveyed_at.isoformat()}::{i}"
            )
            props = self._build_annotation_props(ann, qualified_name)
            body = {
                "class": "NewElementRequestBody",
                "parentGUID": report_guid,
                "parentRelationshipTypeName": "ReportedAnnotation",
                "properties": props,
            }
            try:
                self._discovery.create_annotation(body=body)
            except Exception as exc:
                log.warning(
                    "Failed to create annotation %d (%s): %s",
                    i, ann.annotation_type.value, exc,
                )

    @staticmethod
    def _to_string_map(d: dict) -> dict[str, str]:
        """Convert a dict to map<string, string> as required by Egeria typed map fields.

        Nested dicts/lists are JSON-serialised to a string value so no nested
        structures escape into the wire format.  All scalar values are str()-coerced.
        """
        result: dict[str, str] = {}
        for k, v in d.items():
            result[str(k)] = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        return result

    def _build_annotation_props(self, ann, qualified_name: str) -> dict:
        """Map an Annotation dataclass to the correct Egeria subtype properties body."""
        atype = ann.annotation_type

        # Map our AnnotationType enum to the Egeria Jackson subtype class name.
        # Note: RequestForActionAnnotationProperties is NOT valid — use RequestForActionProperties.
        _class_map = {
            AnnotationType.RESOURCE_MEASURE:   "ResourceMeasureAnnotationProperties",
            AnnotationType.CLASSIFICATION:     "ClassificationAnnotationProperties",
            AnnotationType.QUALITY_SCORE:      "QualityAnnotationProperties",
            AnnotationType.DATA_CLASS:         "DataClassAnnotationProperties",
            AnnotationType.REQUEST_FOR_ACTION: "RequestForActionProperties",
            AnnotationType.SCHEMA_ANALYSIS:    "SchemaAnalysisAnnotationProperties",
            AnnotationType.RELATIONSHIP:       "RelationshipAdviceAnnotationProperties",
        }
        egeria_class = _class_map.get(atype, "AnnotationProperties")

        props: dict = {
            "class": egeria_class,
            "qualifiedName": qualified_name,
            "annotationType": atype.value,
            "summary": ann.summary,
            "analysisStep": ann.analysis_step,
            "confidence": ann.confidence,
        }
        if ann.explanation:
            props["explanation"] = ann.explanation
        if ann.expression:
            props["expression"] = ann.expression
        if ann.json_properties:
            props["jsonProperties"] = json.dumps(ann.json_properties)

        # Subtype-specific fields — native typed fields for registered subtypes;
        # additionalProperties (map<string,string>) for unregistered types.
        if atype == AnnotationType.RESOURCE_MEASURE:
            rp = getattr(ann, "resource_properties", {})
            if rp:
                props["resourceProperties"] = self._to_string_map(rp)

        elif atype == AnnotationType.CLASSIFICATION:
            cc = getattr(ann, "candidate_classifications", [])
            if cc:
                props["candidateClassifications"] = cc

        elif atype == AnnotationType.QUALITY_SCORE:
            qs = getattr(ann, "quality_scores", {})
            if qs:
                props["qualityScores"] = self._to_string_map(qs)

        elif atype == AnnotationType.DATA_CLASS:
            dc = getattr(ann, "candidate_data_class_names", [])
            if dc:
                props["candidateDataClassGUIDs"] = dc  # field name per Egeria type

        elif atype == AnnotationType.REQUEST_FOR_ACTION:
            action_req = getattr(ann, "action_requested", "")
            if action_req:
                props["actionRequested"] = action_req
            action_target = getattr(ann, "action_target_name", "")
            if action_target:
                props["actionProperties"] = {"actionTargetName": action_target}

        elif atype == AnnotationType.SCHEMA_ANALYSIS:
            sn = getattr(ann, "schema_name", "")
            st = getattr(ann, "schema_type", "")
            if sn:
                props["schemaName"] = sn
            if st:
                props["schemaType"] = st

        elif atype == AnnotationType.RELATIONSHIP:
            ren = getattr(ann, "related_entity_name", "")
            rtn = getattr(ann, "relationship_type_name", "")
            if ren:
                props["relatedEntityName"] = ren
            if rtn:
                props["relationshipTypeName"] = rtn

        return props
