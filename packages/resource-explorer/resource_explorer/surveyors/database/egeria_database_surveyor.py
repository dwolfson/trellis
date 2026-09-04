"""Egeria-based database surveyor for triggering native PostgreSQL surveys."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resource_explorer.registry import DatabaseEntity

log = logging.getLogger(__name__)

# The real registered qualifiedName for each native survey (e.g.
# "PostgreSQLSurvey::survey-postgres-database") now comes from
# config/technology_type_processes.yaml (resource_explorer.surveyors.
# technology_type_processes) instead of being hardcoded here — adding a new
# Technology Type's native survey is a config change, not a code change.
#
# Note: pyegeria's AutomatedCuration.initiate_postgres_server_survey/
# initiate_postgres_database_survey hardcode a single-colon separator
# ("PostgreSQLSurvey:survey-postgres-database") — a pyegeria bug that makes
# those two SDK methods fail with OMAG-GENERIC-HANDLERS-400-013 ("name is not
# recognized") against any correctly-registered server (real qualifiedNames
# use "::"). That's why _initiate_native_survey below calls the private
# _async_initiate_survey directly instead of those two SDK methods.


class EgeriaDatabaseSurveyorError(RuntimeError):
    """Raised when Egeria survey operations fail."""


class EgeriaDatabaseSurveyor:
    """Trigger and retrieve PostgreSQL surveys using Egeria's native capabilities.
    
    This surveyor uses Egeria's pre-built governance processes to survey databases,
    leveraging Egeria's expertise and standardized metadata.
    
    Parameters
    ----------
    platform_url : Egeria platform URL (falls back to EGERIA_PLATFORM_URL env var)
    view_server : Egeria view server name
    user_id : Egeria user id
    user_password : Egeria user password
    """

    def __init__(
        self,
        platform_url: str | None = None,
        view_server: str | None = None,
        user_id: str | None = None,
        user_password: str | None = None,
    ) -> None:
        self.platform_url = platform_url or os.getenv("EGERIA_PLATFORM_URL", "")
        self.view_server = view_server or os.getenv("EGERIA_VIEW_SERVER", "qs-view-server")
        self.user_id = user_id or os.getenv("EGERIA_USER", "erinoverview")
        self.user_password = user_password or os.getenv("EGERIA_USER_PASSWORD", "secret")
        self._automated_curation = None
        self._asset_maker = None
        self._discovery = None

    def connect(self) -> None:
        """Establish pyegeria client connections."""
        if self._automated_curation is not None:
            return
        
        if not self.platform_url:
            raise EgeriaDatabaseSurveyorError(
                "EGERIA_PLATFORM_URL is not set. "
                "Set it in .env or pass platform_url= to EgeriaDatabaseSurveyor."
            )
        
        try:
            from pyegeria import AutomatedCuration, AssetMaker
            from pyegeria.omvs.data_discovery import DataDiscovery

            # AutomatedCuration for triggering surveys
            self._automated_curation = AutomatedCuration(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._automated_curation.create_egeria_bearer_token(self.user_id, self.user_password)

            # AssetMaker for finding survey reports
            self._asset_maker = AssetMaker(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._asset_maker.create_egeria_bearer_token(self.user_id, self.user_password)

            # DataDiscovery for retrieving annotations
            self._discovery = DataDiscovery(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._discovery.create_egeria_bearer_token(self.user_id, self.user_password)

        except ImportError as exc:
            raise EgeriaDatabaseSurveyorError("pyegeria is not installed.") from exc
        except Exception as exc:
            raise EgeriaDatabaseSurveyorError(
                f"Could not connect to Egeria at {self.platform_url}: {exc}"
            ) from exc

    def catalog_and_survey(
        self,
        db_entity: "DatabaseEntity",
        db_user: str,
        db_pwd: str,
        registry=None,
        survey_after_catalog: bool = True,
    ) -> dict:
        """Guarded front door — see _catalog_and_survey."""
        from resource_explorer.egeria_linkage import guard_linkage

        with guard_linkage(registry, "database", db_entity.slug,
                           db_entity.display_name or db_entity.slug,
                           db_entity.egeria_asset_guid or ""):
            return self._catalog_and_survey(
                db_entity, db_user, db_pwd, registry, survey_after_catalog)

    @staticmethod
    def _note_stale_guid_if_any(exc, db_entity, guid: str, registry) -> None:
        """Record a divergence found inside a deliberately non-fatal handler.

        Separate from guard_linkage because the two answer different questions.
        The guard converts a *fatal* failure into a named one; this reports a
        failure the caller has decided to continue past. Both must record it —
        the whole defect being fixed is that an unusable GUID produced no visible
        signal anywhere.
        """
        if registry is None or not guid:
            return
        from resource_explorer.egeria_linkage import is_unknown_guid_error, note_divergence

        if not is_unknown_guid_error(exc):
            return
        note_divergence(registry, "database", db_entity.slug,
                        db_entity.display_name or db_entity.slug, guid, exc)

    def _catalog_and_survey(
        self,
        db_entity: "DatabaseEntity",
        db_user: str,
        db_pwd: str,
        registry=None,
        survey_after_catalog: bool = True,
    ) -> dict:
        """Catalog the PostgreSQL server + database in Egeria, then optionally initiate a native survey.

        Egeria's template-based creation stores the connection details (including
        credentials) so that subsequent surveys can be initiated without supplying
        credentials again.

        Returns dict with keys: server_guid, database_guid, survey_action_guid.
        """
        self.connect()

        # Use egeria_host if set (e.g. host.docker.internal when Egeria runs in Docker);
        # fall back to the locally-visible host.
        egeria_host = getattr(db_entity, "egeria_host", "") or db_entity.host
        server_name = f"{egeria_host}:{db_entity.port}"

        # ── 1. Create / find PostgreSQL Server element ─────────────────────────
        server_guid = db_entity.egeria_asset_guid  # reuse if already stored as server
        if not server_guid:
            server_guid = self._find_element_guid(server_name)

        if not server_guid:
            try:
                server_guid = self._automated_curation.create_postgres_server_element_from_template(
                    postgres_server=server_name,
                    host_name=egeria_host,
                    port=str(db_entity.port),
                    db_user=db_user,
                    db_pwd=db_pwd,
                    description=db_entity.description or f"PostgreSQL server at {egeria_host}:{db_entity.port}",
                )
                log.info(f"Created PostgreSQL server element: {server_guid}")
            except Exception as exc:
                raise EgeriaDatabaseSurveyorError(
                    f"Could not create PostgreSQL server element for {server_name}: {exc}"
                ) from exc

        # ── 2. Create / find PostgreSQL Database element ───────────────────────
        db_guid = self._find_element_guid(db_entity.database_name)

        if not db_guid:
            try:
                db_guid = self._automated_curation.create_postgres_database_element_from_template(
                    postgres_database=db_entity.database_name,
                    server_name=server_name,
                    host_identifier=egeria_host,
                    port=str(db_entity.port),
                    db_user=db_user,
                    db_pwd=db_pwd,
                    description=db_entity.description or f"PostgreSQL database {db_entity.database_name}",
                )
                log.info(f"Created PostgreSQL database element: {db_guid}")
            except Exception as exc:
                raise EgeriaDatabaseSurveyorError(
                    f"Could not create PostgreSQL database element for {db_entity.database_name}: {exc}"
                ) from exc

        # Persist database GUID to registry
        if registry and db_guid:
            registry.set_database_egeria_guid(db_entity.slug, db_guid)

        # ── 3. Optionally initiate Egeria's native surveys ────────────────────
        server_survey_guid = ""
        survey_action_guid = ""
        if survey_after_catalog:
            # Survey the server first (captures connection info, database list, server config)
            if server_guid:
                try:
                    server_survey_guid = self._initiate_survey("PostgreSQL Server", server_guid)
                    log.info(f"Egeria server survey initiated: {server_survey_guid}")
                except Exception as exc:
                    log.warning(f"Server survey initiation failed (non-fatal): {exc}")
                    # This is where a stale cached GUID actually surfaces, and it
                    # was being thrown away at WARNING level. Confirmed live
                    # 2026-08-20: pointing this at a GUID Egeria cannot have
                    # returns OMAG-REPOSITORY-HANDLER-404-007 here, and the
                    # method still returned success with server_survey_guid=''.
                    # The catalog work above genuinely did succeed, so this stays
                    # non-fatal — but "non-fatal" must not mean "invisible", or
                    # every subsequent run silently skips the server survey too.
                    self._note_stale_guid_if_any(exc, db_entity, server_guid, registry)

            # Survey the database (captures schemas, tables, columns, relationships)
            if db_guid:
                try:
                    survey_action_guid = self._initiate_survey("PostgreSQL Relational Database", db_guid)
                    log.info(f"Egeria database survey initiated: {survey_action_guid}")
                except Exception as exc:
                    log.warning(f"Cataloged OK but Egeria database survey initiation failed: {exc}")
                    self._note_stale_guid_if_any(exc, db_entity, db_guid, registry)

        return {
            "server_guid": server_guid,
            "server_survey_guid": server_survey_guid,
            "database_guid": db_guid,
            "survey_action_guid": survey_action_guid,
        }

    def trigger_survey_by_guid(self, db_guid: str, start_time: datetime | None = None) -> str:
        """Initiate Egeria's native PostgreSQL database survey using a stored GUID.

        Use this when the database is already cataloged in Egeria (db_guid known).
        Egeria uses its stored connection details — no credentials required here.

        start_time: when set, Egeria's own engine host defers execution to that
        moment (pyegeria converts it to epoch-millis on the wire) instead of
        firing immediately — this is what lets scheduler.py hand off precise
        timing to Egeria instead of relying purely on RE's own poll loop. Only
        honored on the dynamically-discovered-process branch of
        _initiate_survey; the native-survey fallback (_initiate_native_survey,
        already a workaround for a separate pyegeria bug — see its own
        docstring) calls a private pyegeria method with no start_time
        parameter at all, so start_time is silently not applied if that
        fallback is the one that ends up running.
        """
        self.connect()
        try:
            action_guid = self._initiate_survey("PostgreSQL Relational Database", db_guid, start_time=start_time)
            log.info(f"Egeria database survey initiated: {action_guid}")
            return action_guid
        except Exception as exc:
            raise EgeriaDatabaseSurveyorError(
                f"Failed to initiate Egeria survey for db_guid={db_guid}: {exc}"
            ) from exc

    def _find_survey_process_name(self, tech_type: str) -> str | None:
        """Query get_tech_type_detail for a survey process and return its qualifiedName.

        Delegates to SurveyDefinitionReader.find_candidate_process_guids, which
        generalizes this same lookup to return *all* matching candidates (used by
        the Survey Definition executor to detect ambiguity) — this method keeps its
        original single-result contract for backward compatibility with
        catalog_and_survey/_initiate_survey.
        """
        from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

        self.connect()
        reader = SurveyDefinitionReader(
            self.platform_url, self.view_server, self.user_id, self.user_password
        )
        reader._automated_curation = self._automated_curation
        candidates = reader.find_candidate_process_guids(tech_type)
        if candidates:
            qn = candidates[0]["qualified_name"]
            log.info(f"Dynamically discovered Egeria survey process for {tech_type}: {qn}")
            return qn
        return None

    def publish_step_annotations(
        self,
        db_entity: "DatabaseEntity",
        schema_info: dict,
        statistics: dict | None,
        surveyed_at: str,
        registry=None,
        views: list | None = None,
    ) -> dict:
        """Publish RE-computed annotations to Egeria WITHOUT cataloging the database
        or triggering Egeria's own native survey as a side effect.

        Narrower counterpart to publish_local_survey: that method also calls
        catalog_and_survey(survey_after_catalog=True), which re-catalogs the
        database and fires Egeria's native async PostgreSQL survey every time —
        not appropriate when a Survey Definition has already explicitly declared
        this step runs in RE. The database must already be cataloged in Egeria;
        this method does not auto-catalog it.
        """
        self.connect()
        db_guid = self._find_element_guid(db_entity.database_name)
        if not db_guid:
            raise EgeriaDatabaseSurveyorError(
                f"Database '{db_entity.database_name}' is not yet cataloged in Egeria — "
                "cannot publish a Survey Definition step's results without an existing "
                "asset to attach the SurveyReport to."
            )

        from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor

        annotations = []
        local_surveyor = DatabaseSurveyor(db_entity, {}, registry)
        if schema_info:
            annotations.extend(local_surveyor._create_schema_annotations(schema_info))
        if statistics:
            annotations.extend(local_surveyor._create_statistics_annotations(statistics))
        if views:
            annotations.extend(local_surveyor._create_views_annotations(views))

        qualified_name = f"SurveyReport::PostgreSQL::{db_entity.slug}::{surveyed_at}"
        body = {
            "class": "NewElementRequestBody",
            "parentGUID": db_guid,
            "parentRelationshipTypeName": "ReportSubject",
            "properties": {
                "class": "AssetProperties",
                "typeName": "SurveyReport",
                "qualifiedName": qualified_name,
                "displayName": f"Survey: {db_entity.display_name}",
                "description": (
                    f"Survey Definition step results for "
                    f"{db_entity.host}:{db_entity.port}/{db_entity.database_name} "
                    f"run at {surveyed_at}."
                ),
                "additionalProperties": {
                    "annotation_count": str(len(annotations)),
                },
            },
        }
        report_guid = self._asset_maker.create_asset(body=body)
        log.info(f"Published SurveyReport in Egeria: {report_guid}")
        self._create_annotations(annotations, report_guid, db_entity.slug, surveyed_at)

        # Publish column-level lineage mapping relationships to Egeria
        if db_guid and views:
            try:
                self._publish_column_lineage(db_entity, views)
            except Exception as lin_err:
                log.warning(f"Could not publish column lineage: {lin_err}")

        if registry:
            registry.record_database_survey(
                slug=db_entity.slug,
                schema_count=len(schema_info.get("schemas", [])) if schema_info else 0,
                table_count=schema_info.get("total_tables", 0) if schema_info else 0,
                column_count=schema_info.get("total_columns", 0) if schema_info else 0,
                survey_data={
                    "schema_info": schema_info,
                    "statistics": statistics or {},
                    "views": views or [],
                },
                egeria_report_guid=report_guid,
                source="egeria-published",
            )

        return {"asset_guid": db_guid, "report_guid": report_guid, "annotation_count": len(annotations)}

    def _initiate_survey(self, tech_type: str, target_guid: str, start_time: datetime | None = None) -> str:
        """Dynamically find a user-authored Survey Definition process for tech_type
        and initiate it as a GovernanceActionProcess; if none is found (or it fails
        to initiate), fall back to the native survey GovernanceActionType
        configured for this tech_type in config/technology_type_processes.yaml.

        start_time: passed straight through to initiate_gov_action_process on
        the dynamically-discovered-process branch only — see
        trigger_survey_by_guid's docstring for why the fallback branch can't
        honor it.
        """
        process_name = self._find_survey_process_name(tech_type)
        if process_name:
            try:
                targets = [
                    {
                        "class": "NewActionTarget",
                        "actionTargetName": "serverToSurvey",
                        "actionTargetGUID": target_guid,
                    }
                ]
                guid = self._automated_curation.initiate_gov_action_process(
                    action_type_qualified_name=process_name,
                    action_targets=targets,
                    start_time=start_time,
                )
                log.info(f"Initiated dynamically discovered survey process {process_name} on {target_guid}: {guid}"
                         + (f" (start_time={start_time.isoformat()})" if start_time else ""))
                return guid
            except Exception as exc:
                log.warning(f"Failed to initiate dynamically discovered survey process {process_name}: {exc}. Trying fallback...")

        from resource_explorer.surveyors.technology_type_processes import (
            KIND_SURVEY_EXISTING,
            get_process_by_kind,
        )

        native = get_process_by_kind("database", tech_type, KIND_SURVEY_EXISTING)
        if not native:
            raise RuntimeError(
                f"No native survey process configured for technology_type={tech_type!r} — "
                "add an entry to config/technology_type_processes.yaml."
            )
        if start_time:
            log.info(
                f"start_time={start_time.isoformat()} requested but the native-survey fallback path "
                f"(pyegeria's private _async_initiate_survey) has no start_time parameter — firing immediately."
            )
        return self._initiate_native_survey(native.qualified_name, target_guid)

    def _initiate_native_survey(self, survey_qualified_name: str, target_guid: str) -> str:
        """Call pyegeria's private _async_initiate_survey directly with a correct
        qualifiedName, bypassing AutomatedCuration.initiate_postgres_server_survey/
        initiate_postgres_database_survey — both hardcode a single-colon separator
        ("PostgreSQLSurvey:survey-postgres-database") that does not match the real
        double-colon qualifiedName Egeria actually registers
        ("PostgreSQLSurvey::survey-postgres-database"), causing
        OMAG-GENERIC-HANDLERS-400-013 "name is not recognized". This is a pyegeria
        bug — remove this workaround once it's fixed upstream.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self._automated_curation._async_initiate_survey(survey_qualified_name, target_guid)
        )

    _UUID_RE = __import__('re').compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        __import__('re').IGNORECASE,
    )

    def _find_element_guid(self, name: str) -> str:
        """Return the GUID of an existing Egeria element by display/qualified name, or '' if not found.

        '' is the callers' cue to *create* the element, so anything that is not a
        clean "no such element" must at least be visible. pyegeria raises for an
        ambiguous name ("Multiple elements found for supplied name!") exactly as
        it does for a transport failure; swallowing both silently meant a name
        that already had two elements got a third on the next catalog run, and a
        dead view server looked like an empty catalog. Verified live 2026-09-04
        against qs-view-server while diagnosing a stale linkage: the by-name
        search itself was fine, the element had simply been deleted.
        """
        try:
            result = self._automated_curation.get_guid_for_name(name)
            if isinstance(result, list) and result:
                candidate = result[0] if isinstance(result[0], str) else result[0].get("guid", "")
                return candidate if self._UUID_RE.match(candidate or "") else ""
            if isinstance(result, str) and self._UUID_RE.match(result):
                return result
        except Exception as exc:
            log.warning(
                f"Egeria by-name lookup for {name!r} failed rather than returning "
                f"'not found' — treating as absent, which may create a duplicate: "
                f"{' '.join(str(exc).split())[:300] or type(exc).__name__}"
            )
        return ""

    def check_survey_exists(self, db_slug: str) -> bool:
        """Check if any survey reports exist for this database in Egeria.
        
        Args:
            db_slug: Database slug to check
            
        Returns:
            True if survey reports exist, False otherwise
        """
        self.connect()
        
        search_prefix = f"SurveyReport::PostgreSQL::{db_slug}::"
        
        try:
            results = self._asset_maker.find_assets(
                search_string=search_prefix,
                starts_with=True,
                ignore_case=False,
                output_format="JSON",
            )
            return isinstance(results, list) and len(results) > 0
        except Exception as exc:
            log.debug(f"check_survey_exists failed for {db_slug}: {exc}")
            return False

    def get_survey_reports(self, db_slug: str) -> list[dict]:
        """Retrieve all survey reports for a database from Egeria.
        
        Args:
            db_slug: Database slug
            
        Returns:
            List of survey report dicts with keys:
            - guid: Survey report GUID
            - qualified_name: Full qualified name
            - display_name: Display name
            - surveyed_at: Timestamp from qualified name
            - annotation_count: Number of annotations
            - description: Report description
        """
        self.connect()
        
        search_prefix = f"SurveyReport::PostgreSQL::{db_slug}::"
        reports = []
        
        try:
            results = self._asset_maker.find_assets(
                search_string=search_prefix,
                starts_with=True,
                ignore_case=False,
                output_format="JSON",
            )
            
            if not isinstance(results, list):
                return []
            
            for el in results:
                header = el.get("elementHeader", {})
                props = el.get("properties", {})
                additional = props.get("additionalProperties", {})
                qn = props.get("qualifiedName", "")
                
                # Extract timestamp from qualifiedName: SurveyReport::PostgreSQL::{slug}::{ts}
                ts = qn.split("::")[-1] if "::" in qn else ""
                
                reports.append({
                    "guid": header.get("guid", ""),
                    "qualified_name": qn,
                    "display_name": props.get("displayName", ""),
                    "surveyed_at": ts,
                    "annotation_count": self._safe_int(additional.get("annotation_count")),
                    "schema_count": self._safe_int(additional.get("schema_count")),
                    "table_count": self._safe_int(additional.get("table_count")),
                    "column_count": self._safe_int(additional.get("column_count")),
                    "description": props.get("description", ""),
                })
        except Exception as exc:
            log.debug(f"get_survey_reports failed for {db_slug}: {exc}")
        
        # Sort newest first
        reports.sort(key=lambda r: r.get("surveyed_at", ""), reverse=True)
        return reports

    def get_annotations(self, db_slug: str, surveyed_at: str) -> list[dict]:
        """Retrieve all annotations for a specific survey from Egeria.
        
        Args:
            db_slug: Database slug
            surveyed_at: Survey timestamp
            
        Returns:
            List of annotation dicts with keys:
            - guid: Annotation GUID
            - annotation_type: Type of annotation
            - summary: Summary text
            - confidence: Confidence level (0-100)
            - analysis_step: Analysis step name
            - explanation: Detailed explanation
            - json_properties: Additional properties as JSON
        """
        self.connect()
        
        search_prefix = f"Annotation::PostgreSQL::{db_slug}::{surveyed_at}::"
        annotations = []
        
        try:
            results = self._discovery.find_annotations(
                search_string=search_prefix,
                starts_with=True,
                ignore_case=False,
                output_format="JSON",
                page_size=500,
            )
            
            if not isinstance(results, list):
                return []
            
            for el in results:
                header = el.get("elementHeader", {})
                props = el.get("properties", {})
                
                annotations.append({
                    "guid": header.get("guid", ""),
                    "annotation_type": props.get("annotationType", ""),
                    "summary": props.get("summary", ""),
                    "confidence": self._safe_int(props.get("confidence", 100)),
                    "analysis_step": props.get("analysisStep", ""),
                    "explanation": props.get("explanation", ""),
                    "expression": props.get("expression", ""),
                    "json_properties": props.get("jsonProperties", {}),
                })
        except Exception as exc:
            log.debug(f"get_annotations failed for {db_slug}/{surveyed_at}: {exc}")
        
        return annotations

    def get_survey_reports_by_guid(self, db_guid: str) -> list[dict]:
        """Retrieve all survey reports actually linked to this database asset in
        Egeria, via the real ReportSubject relationship — not a qualifiedName
        prefix guess like get_survey_reports(). This is the only way to see
        reports Egeria's own native survey engine created (triggered via
        trigger_survey_by_guid/Survey Definitions), since those use Egeria's own
        naming convention, not the "SurveyReport::PostgreSQL::{slug}::..." prefix
        RE's own publish methods use.

        Thin wrapper over the engine-agnostic reader in egeria_survey_reader.py
        (shared with EgeriaPublisher/EgeriaFileSystemSurveyor) — kept as a method
        here for backward compatibility with existing callers/tests.
        """
        from resource_explorer.surveyors.egeria_survey_reader import get_survey_reports_by_guid

        self.connect()
        return get_survey_reports_by_guid(self._asset_maker, db_guid)

    def get_annotations_by_report_guid(self, report_guid: str) -> list[dict]:
        """Retrieve all annotations attached to a specific SurveyReport via the
        real ReportedAnnotation relationship — not a qualifiedName prefix guess
        like get_annotations(). Works for reports created by any engine, since
        it walks the actual relationship rather than assuming RE's own naming
        convention.

        Thin wrapper over the engine-agnostic reader in egeria_survey_reader.py.
        """
        from resource_explorer.surveyors.egeria_survey_reader import get_annotations_by_report_guid

        self.connect()
        return get_annotations_by_report_guid(self._asset_maker, report_guid)

    def get_latest_survey(self, db_slug: str) -> dict | None:
        """Get the most recent survey report for a database.

        Args:
            db_slug: Database slug
            
        Returns:
            Survey report dict or None if no surveys exist
        """
        reports = self.get_survey_reports(db_slug)
        return reports[0] if reports else None

    def publish_local_survey(
        self,
        db_entity: "DatabaseEntity",
        schema_info: dict,
        schema_count: int,
        table_count: int,
        column_count: int,
        surveyed_at: str,
        registry=None,
        db_user: str = "",
        db_pwd: str = "",
        statistics: dict | None = None,
        views: list | None = None,
    ) -> dict:
        """Catalog the database in Egeria, trigger a native PostgreSQL survey,
        and publish the local survey report and annotations directly to Egeria.
        """
        result = self.catalog_and_survey(
            db_entity=db_entity,
            db_user=db_user,
            db_pwd=db_pwd,
            registry=registry,
            survey_after_catalog=True,
        )

        server_guid        = result.get("server_guid", "")
        db_guid            = result.get("database_guid", "")
        survey_action_guid = result.get("survey_action_guid", "")
        server_survey_guid = result.get("server_survey_guid", "")

        # ── Publish local survey report & annotations to Egeria ──────────────────
        report_guid = ""
        annotations = []
        if db_guid:
            # Recreate annotations from local scan data using DatabaseSurveyor helpers
            try:
                from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor
                local_surveyor = DatabaseSurveyor(db_entity, {}, registry)
                if schema_info:
                    annotations.extend(local_surveyor._create_schema_annotations(schema_info))
                if statistics:
                    annotations.extend(local_surveyor._create_statistics_annotations(statistics))
                if views:
                    annotations.extend(local_surveyor._create_views_annotations(views))
            except Exception as exc:
                log.warning(f"Could not reconstruct local annotations: {exc}")

            qualified_name = f"SurveyReport::PostgreSQL::{db_entity.slug}::{surveyed_at}"
            body = {
                "class": "NewElementRequestBody",
                "parentGUID": db_guid,
                "parentRelationshipTypeName": "ReportSubject",
                "properties": {
                    "class": "AssetProperties",
                    "typeName": "SurveyReport",
                    "qualifiedName": qualified_name,
                    "displayName": f"Survey: {db_entity.display_name}",
                    "description": (
                        f"Automated survey of {db_entity.host}:{db_entity.port}/{db_entity.database_name} "
                        f"run at {surveyed_at}."
                    ),
                    "additionalProperties": {
                        "annotation_count": str(len(annotations)),
                        "schema_count": str(schema_count),
                        "table_count": str(table_count),
                        "column_count": str(column_count),
                    },
                },
            }
            try:
                report_guid = self._asset_maker.create_asset(body=body)
                log.info(f"Published SurveyReport in Egeria: {report_guid}")
                
                # Push annotations under the SurveyReport in Egeria
                self._create_annotations(annotations, report_guid, db_entity.slug, surveyed_at)
            except Exception as exc:
                log.warning(f"Failed to publish SurveyReport to Egeria: {exc}")

        # Use the created report GUID if available, otherwise fall back to Egeria's native action GUID
        effective_report_guid = report_guid or survey_action_guid

        # Publish column-level lineage mapping relationships to Egeria
        if db_guid and views:
            try:
                self._publish_column_lineage(db_entity, views)
            except Exception as lin_err:
                log.warning(f"Could not publish column lineage: {lin_err}")

        if registry and db_guid:
            registry.record_database_survey(
                slug=db_entity.slug,
                schema_count=schema_count,
                table_count=table_count,
                column_count=column_count,
                survey_data={
                    "schema_info": schema_info,
                    "statistics": statistics or {},
                    "views": views or [],
                },
                egeria_report_guid=effective_report_guid,
                source="egeria-published",
            )

        return {
            "server_guid":        server_guid,
            "asset_guid":         db_guid,
            "report_guid":        effective_report_guid,
            "server_survey_guid": server_survey_guid,
            "annotation_count":   len(annotations),
        }

    def _publish_column_lineage(self, db_entity: "DatabaseEntity", views: list[dict]) -> None:
        """Publish column-level lineage to Egeria using LineageLinker."""
        if not views:
            return

        from pyegeria.omvs.lineage_linker import LineageLinker
        linker = LineageLinker(self.view_server, self.platform_url, self.user_id, self.user_password)
        linker.create_egeria_bearer_token(self.user_id, self.user_password)

        db_name = db_entity.database_name

        for view in views:
            schema_name = view["schema"]
            view_name = view["name"]
            
            # Walk column lineages
            for target_col, lineage_tree in view.get("lineage", {}).items():
                sources = self._extract_leaf_sources(lineage_tree)
                if not sources:
                    continue

                target_qn = f"{db_name}.{schema_name}.{view_name}.{target_col}"
                target_guid = self._find_element_guid(target_qn)
                if not target_guid:
                    target_guid = self._find_element_guid(f"{view_name}.{target_col}")

                if not target_guid:
                    log.debug(f"Could not find Egeria GUID for derived column '{target_qn}'")
                    continue

                for src_table, src_col in sources:
                    if "." in src_table:
                        s_name, t_name = src_table.split(".", 1)
                    else:
                        s_name, t_name = schema_name, src_table

                    src_qn = f"{db_name}.{s_name}.{t_name}.{src_col}"
                    src_guid = self._find_element_guid(src_qn)
                    if not src_guid:
                        src_guid = self._find_element_guid(f"{t_name}.{src_col}")

                    if not src_guid:
                        log.debug(f"Could not find Egeria GUID for source column '{src_qn}'")
                        continue

                    try:
                        body = {
                            "class": "NewRelationshipRequestBody",
                            "properties": {
                                "class": "LineageMappingProperties",
                                "iscQualifiedName": f"SQLGlot::LineageMapping::{target_qn}",
                                "label": "Column Derivation Link",
                                "description": f"Statically analyzed lineage map of view {view_name} via SQLGlot."
                            }
                        }
                        rel_guid = linker.link_lineage(
                            element_one_guid=src_guid,
                            relationship_type_name="LineageMapping",
                            element_two_guid=target_guid,
                            body=body
                        )
                        log.info(f"Published column lineage mapping: {src_qn} -> {target_qn} (guid: {rel_guid})")
                    except Exception as link_err:
                        log.warning(f"Failed to create LineageMapping link between {src_qn} and {target_qn}: {link_err}")

    def _extract_leaf_sources(self, node: dict) -> list[tuple[str, str]]:
        """Traverse a serialized SQLGlot lineage node tree and return leaf sources as list of (table, column)."""
        res = []
        downstream = node.get("downstream", [])
        if not downstream:
            source = node.get("source", "")
            name = node.get("name", "")
            if name and source:
                res.append((source, name))
        else:
            for child in downstream:
                res.extend(self._extract_leaf_sources(child))
        return list(set(res))

    def _create_annotations(
        self,
        annotations: list,
        report_guid: str,
        db_slug: str,
        surveyed_at: str,
    ) -> None:
        """Push a list of Annotation objects to Egeria.

        Delegates to the shared implementation — see annotation_props.py.
        Kept as a method because tests reach for it by name. `surveyed_at` is
        this run's own timestamp (this run's identity, part of the
        qualifiedName) — do not recompute it here."""
        from resource_explorer.surveyors.annotation_props import publish_annotations

        qualified_name_prefix = f"Annotation::PostgreSQL::{db_slug}::{surveyed_at}"
        publish_annotations(
            self._discovery, self._find_element_guid,
            annotations, report_guid, qualified_name_prefix,
        )

    @staticmethod
    def _to_string_map(d: dict) -> dict[str, str]:
        """Delegates to the shared implementation — see annotation_props.py."""
        from resource_explorer.surveyors.annotation_props import to_string_map

        return to_string_map(d)
    def _build_annotation_props(self, ann, qualified_name: str) -> dict:
        """Delegates to the shared implementation — see annotation_props.py.

        Kept as a method because tests and call sites reach for it by name."""
        from resource_explorer.surveyors.annotation_props import build_annotation_props

        return build_annotation_props(ann, qualified_name)
    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        """Safely convert value to int."""
        try:
            return int(value) if value is not None else default
        except (ValueError, TypeError):
            return default


def can_use_egeria() -> bool:
    """Check if Egeria is available and configured.
    
    Returns:
        True if EGERIA_PLATFORM_URL is set and pyegeria is installed
    """
    if not os.getenv("EGERIA_PLATFORM_URL"):
        return False
    
    try:
        import pyegeria  # noqa: F401
        return True
    except ImportError:
        return False

# Made with Bob
