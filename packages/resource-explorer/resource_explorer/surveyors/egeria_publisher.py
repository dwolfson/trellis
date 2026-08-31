"""
Publishes a SurveyResult to Egeria via pyegeria.

Element type: SourceControlLibrary — a SoftwareCapability, NOT an Asset.
Supertypes, confirmed from the server 2026-08-21: ResourceManager,
SoftwareCapability, Referenceable, OpenMetadataRoot. It therefore does not
appear in Egeria's Asset Catalog views, and `AssetMaker.get_asset_by_guid`
correctly cannot retrieve it — a fact that has already produced one bug (see
resource_explorer/egeria_linkage.py). The method below is still called
_find_or_create_asset and the registry column is still egeria_asset_guid;
both names are inherited and both are misleading.
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


def _analyses_for_steps(step_keys) -> set:
    """The analyses whose steps these are.

    An analysis counts as published when ANY of its steps ran: a partial run
    still published real findings under its name, and reporting nothing would
    lose them. Imported lazily — the adapter imports this module.
    """
    if not step_keys:
        return set()
    try:
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_STEP_MAP,
        )
    except ImportError:  # pragma: no cover - defensive
        return set()
    wanted = set(step_keys)
    return {aid for aid, keys in REPO_ANALYSIS_STEP_MAP.items()
            if wanted & set(keys)}


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
        self._automated_curation = None
        self._external_references = None
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

        # Everything below depends on the asset GUID RE cached for this project,
        # directly or through the report created against it. If Egeria no longer
        # knows that GUID, this raises a named error and records the divergence
        # instead of surfacing a 500-word server stack — see egeria_linkage.py.
        from resource_explorer.egeria_linkage import guard_linkage

        cached_guid = ""
        if self._registry:
            try:
                cached_guid = self._registry.get_egeria_asset_guid(result.resource_slug) or ""
            except Exception:
                cached_guid = ""

        with guard_linkage(self._registry, "repo", result.resource_slug,
                           result.project_display_name, cached_guid):
            asset_guid = self._find_or_create_asset(result)
            # Best-effort and deliberately not fatal — see the method's docstring.
            self._publish_homepage_reference(result, asset_guid)
            report_guid = self._create_survey_report(result, asset_guid)
            self._create_annotations(result, report_guid)
        # Best-effort, deliberately outside the guard_linkage block above —
        # this is local bookkeeping for the Survey Results dashboards'
        # per-card "last published" badge (get_last_published_annotation_
        # types), not part of the real Egeria write; a failure here must
        # never raise and make an already-successful publish look failed.
        # Not silently log-only, though (tests/test_no_silent_success.py's
        # ratchet caught the first version of this doing exactly that): the
        # outcome is folded into the log_catalog activity_log entry below —
        # a real, greppable, user-visible signal (Activity tab), not a debug
        # line nobody reads. Recoverable either way: a card just shows "Not
        # published" until the next successful publish, or via
        # scripts/backfill_published_annotation_types.py.
        annotation_types_warning = ""
        if self._registry:
            try:
                self._registry.record_published_annotation_types(
                    result.resource_slug,
                    {a.annotation_type.value for a in result.annotations},
                    report_guid,
                )
                # Which ANALYSES this publish covered, recorded directly rather
                # than inferred later from shared annotation types. The
                # orchestrator put the step keys on the result; mapping them is
                # a lookup, not a guess.
                self._registry.record_published_analyses(
                    result.resource_slug,
                    _analyses_for_steps(result.steps_run),
                    report_guid,
                )
            except Exception as exc:
                annotation_types_warning = f" (⚠ last-published tracking not recorded: {exc})"
                log.warning("record_published_annotation_types failed (non-fatal): %s", exc)
        log.info(
            "Published survey for %s → SurveyReport GUID %s (%d annotations)",
            result.resource_slug,
            report_guid,
            len(result.annotations),
        )

        if self._registry:
            try:
                from resource_explorer.activity_logger import log_catalog
                log_catalog(
                    self._registry,
                    entity_type="repo",
                    entity_slug=result.resource_slug,
                    entity_name=result.project_display_name,
                    entity_location=result.github_url,
                    status="ok",
                    summary=(
                        f"Published to Egeria: {len(result.annotations)} annotations"
                        f" → {(report_guid or 'no-guid')[:12]}…{annotation_types_warning}"
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
                                f"SurveyReport::GitHubRepo::{result.resource_slug}"
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
            from pyegeria import AssetMaker, AutomatedCuration, ExternalReferences
            from pyegeria.omvs.data_discovery import DataDiscovery

            self._asset_maker = AssetMaker(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._asset_maker.create_egeria_bearer_token(self.user_id, self.user_password)

            self._discovery = DataDiscovery(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._discovery.create_egeria_bearer_token(self.user_id, self.user_password)

            # Used only by _catalog_sub_resources() (D6) — template-based
            # FileFolder/DataFile creation for worthy sub-resources.
            self._automated_curation = AutomatedCuration(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._automated_curation.create_egeria_bearer_token(self.user_id, self.user_password)

            # Used only by _publish_homepage_reference() — catalogs the
            # project's external website and links it to the library element.
            self._external_references = ExternalReferences(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._external_references.create_egeria_bearer_token(self.user_id, self.user_password)
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
            cached = self._registry.get_egeria_asset_guid(result.resource_slug)
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
                        log.info("Using cached Egeria asset GUID %s for %s", cached, result.resource_slug)
                        return cached
                    # GUID not found — Egeria DB may have been reset; clear the stale cache
                    log.warning(
                        "Cached GUID %s no longer in Egeria for %s — will re-register",
                        cached, result.resource_slug,
                    )
                    self._registry.clear_egeria_registration(result.resource_slug)
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
                # EXACT qualifiedName only. The search is starts_with=True, so
                # a repo whose URL is a PREFIX of another's matches both — and
                # taking existing[0] adopted the wrong asset. Measured live
                # 2026-08-25: docling (.../docling) matched docling-eval and
                # docling-core, and docling + docling_eval ended up sharing one
                # asset GUID, so one repo's survey reports were attaching to the
                # other's catalog entry. Nothing errored; the catalog was just
                # wrong.
                #
                # starts_with is kept rather than narrowed, because the search
                # is also how a legitimately-renamed asset is still found; the
                # filtering belongs here, on the result.
                match = next(
                    (e for e in existing
                     if (e.get("properties") or {}).get("qualifiedName") == qualified_name),
                    None,
                )
                guid = (match or {}).get("elementHeader", {}).get("guid") if match else None
                if guid:
                    log.info("Found existing Egeria asset GUID %s for %s", guid, result.resource_slug)
                    self._cache_asset_guid(result.resource_slug, guid)
                    return guid
                if existing:
                    # Prefix matches that are not this asset are the normal case
                    # for sibling repos; say so rather than silently creating.
                    log.info(
                        "%d prefix match(es) for %s but none with an exact qualifiedName — creating",
                        len(existing), result.resource_slug,
                    )
        except Exception as exc:
            log.debug("Asset search failed (will create): %s", exc)

        # Gather project stats for additional metadata
        primary_language = ""
        license_name = ""
        topics_csv = ""
        if self._registry:
            stats = self._registry.get_latest_project_stats(result.resource_slug)
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
            # The repo's own location, in the attribute Egeria defines for it.
            # `url` is inherited from Referenceable (confirmed against the live
            # type system, not assumed — SourceControlLibrary -> ResourceManager
            # -> SoftwareCapability -> Referenceable, which declares it).
            # Previously the git URL existed only inside additionalProperties and
            # interpolated into the description text, so nothing generic could
            # find it: anything walking the catalog for "where does this live"
            # looks at `url`, not at a private extension key.
            #
            # additionalProperties["github_url"] is kept rather than moved —
            # existing consumers read it, and the duplication is cheap.
            "url": result.github_url,
            "additionalProperties": {
                "github_url": result.github_url,
                "project_slug": result.resource_slug,
                "primary_language": primary_language,
                "license": license_name,
                "topics": topics_csv,
            },
        }
        if self.zone_names:
            props["zoneMembership"] = self.zone_names
        body = {"class": "NewElementRequestBody", "properties": props}
        guid = self._asset_maker.create_software_capability(body=body)
        log.info("Created SourceControlLibrary GUID %s for %s", guid, result.resource_slug)
        self._cache_asset_guid(result.resource_slug, guid)
        return guid

    def _cache_asset_guid(self, slug: str, guid: str) -> None:
        if self._registry:
            try:
                self._registry.set_egeria_asset_guid(slug, guid)
            except Exception as exc:
                log.warning("Could not persist Egeria asset GUID to registry: %s", exc)

    def _publish_homepage_reference(self, result: SurveyResult, asset_guid: str) -> str:
        """Catalog the project's external website as an ExternalReference linked
        to its SourceControlLibrary.

        The URL comes from HomepageSurveyor (projects.homepage_url), which tries
        GitHub's declared homepage, then the packaging manifests, then the README,
        then the repo URL itself. The repo-URL fallback is deliberately NOT
        published here: an ExternalReference pointing back at the same repo the
        library element already describes adds a catalog entry and no
        information. Scouting still shows it as a link; only Egeria skips it.

        Best-effort throughout. A failure here must not fail the publish — the
        survey and its annotations are the point, this is an extra.

        Returns the ExternalReference GUID, or "" if nothing was published.
        """
        if not self._registry:
            return ""
        try:
            project = self._registry.get(result.resource_slug)
        except Exception:
            return ""
        homepage = (getattr(project, "homepage_url", "") or "").strip()
        if not homepage:
            return ""

        # Skip the repo-URL fallback (see docstring). Compared host-wise rather
        # than by string equality so ".git"/trailing-slash variants still match.
        from urllib.parse import urlparse

        def _same(a: str, b: str) -> bool:
            pa, pb = urlparse(a), urlparse(b)
            return (pa.hostname or "").lower() == (pb.hostname or "").lower() and \
                   pa.path.rstrip("/").removesuffix(".git") == pb.path.rstrip("/").removesuffix(".git")

        if _same(homepage, result.github_url):
            log.debug("Homepage for %s is the repo itself — not cataloged separately",
                      result.resource_slug)
            return ""

        qualified_name = f"ExternalReference::{homepage}"
        try:
            existing = self._find_element_guid(qualified_name)
            if existing:
                ref_guid = existing
            else:
                body = {
                    "class": "NewElementRequestBody",
                    "properties": {
                        "class": "ExternalReferenceProperties",
                        "typeName": "ExternalReference",
                        "qualifiedName": qualified_name,
                        "displayName": f"{result.project_display_name} — project website",
                        "description": (
                            f"External website for {result.project_display_name}, derived by "
                            f"Resource Explorer's Homepage survey step."
                        ),
                        # `url` is inherited from Referenceable, same as on the
                        # library element above.
                        "url": homepage,
                        "referenceTitle": f"{result.project_display_name} website",
                    },
                }
                ref_guid = self._external_references.create_external_reference(body=body)
                log.info("Created ExternalReference %s for %s (%s)",
                         ref_guid, result.resource_slug, homepage)

            # Linking is separately guarded: a duplicate link attempt on a
            # re-publish is harmless to report but must not lose the reference.
            try:
                self._external_references.link_external_reference(asset_guid, ref_guid)
            except Exception as exc:
                log.debug("Could not link ExternalReference %s to %s: %s",
                          ref_guid, asset_guid, exc)
            return ref_guid
        except Exception as exc:
            log.warning("Could not publish homepage ExternalReference for %s: %s",
                        result.resource_slug, exc)
            return ""

    # ── survey report ─────────────────────────────────────────────────────────

    def _create_survey_report(self, result: SurveyResult, asset_guid: str) -> str:
        surveyed_at_iso = result.surveyed_at.isoformat()
        qualified_name = (
            f"SurveyReport::GitHubRepo::{result.resource_slug}::{surveyed_at_iso}"
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
                    result.resource_slug,
                    surveyed_at_iso,
                    report_guid,
                    annotation_count=len(result.annotations),
                )
            except Exception as exc:
                log.warning("Could not persist Egeria survey record to registry: %s", exc)

        return report_guid

    # ── annotations ───────────────────────────────────────────────────────────

    def _create_annotations(self, result: SurveyResult, report_guid: str) -> None:
        """Delegates to the shared implementation — see annotation_props.py.

        Kept as a method (rather than inlining the call at the one call site)
        because tests reach for it by name. The qualifiedName prefix built
        here — and specifically `result.surveyed_at.isoformat()`, this run's
        own timestamp, NOT recomputed at publish time — is this run's
        identity; do not remove it as a "fix"."""
        from resource_explorer.surveyors.annotation_props import publish_annotations

        qualified_name_prefix = f"Annotation::{result.resource_slug}::{result.surveyed_at.isoformat()}"
        publish_annotations(
            self._discovery, self._find_element_guid,
            result.annotations, report_guid, qualified_name_prefix,
        )

    # ── sub-resource cataloging (repo scope-narrowing funnel doc, D2/D3) ────

    _FOLDER_TECH_TYPE = "File System Directory"

    def publish_sub_resources(
        self, resource_slug: str, github_url: str, asset_guid: str, locators: list[str],
    ) -> dict[str, str]:
        """Publish specific, already-locally-catalogued sub-resources (repo
        only today — resource_type='repo') to Egeria as FileFolder/DataFile
        assets, parented under the repo's SourceControlLibrary asset (or an
        already-catalogued ancestor folder).

        This replaces the old auto-publish behavior (finding "worthy" ->
        immediately create in Egeria, with every publish() call). Egeria
        publish is now always an explicit, separate action from local
        cataloging (registry.catalog_sub_resource) — see
        docs/repo-scope-narrowing-funnel.md D2/D3. Only locators that are
        already rows in the local `sub_resources` table are published;
        the caller (the catalog route) is responsible for ensuring every
        selected file's ancestor folders are locally catalogued too, since
        NestedFile strictly requires a FileFolder parent.

        Returns {locator: guid} for everything successfully created or
        already found. Idempotent — re-publishing an already-published
        locator finds it by qualifiedName rather than duplicating it.
        """
        if not self._registry:
            return {}
        self._connect()

        rows = {
            r["locator"]: r
            for r in self._registry.list_sub_resources("repo", resource_slug)
            if r["locator"] in locators
        }
        entries = []
        for locator, row in rows.items():
            detail = {}
            if row.get("detail_json"):
                try:
                    detail = json.loads(row["detail_json"])
                except (TypeError, ValueError):
                    detail = {}
            entries.append({
                "path": locator,
                "kind": row["kind"],
                "owners": detail.get("owners", []),
                "last_updated_at": detail.get("last_updated_at", ""),
                "first_added_at": detail.get("first_added_at", ""),
            })
        if not entries:
            return {}

        # Folders before files — a file's parentGUID must already exist.
        entries.sort(key=lambda e: 0 if e["kind"] == "folder" else 1)

        guids_by_path: dict[str, str] = {}
        template_guid_cache: dict[str, str] = {}
        results: dict[str, str] = {}

        for entry in entries:
            path = entry["path"]
            qualified_name = f"SourceControlLibrary::{github_url}::{path}"
            try:
                existing_guid = self._find_element_guid(qualified_name)
            except Exception as exc:
                log.debug("Sub-resource lookup failed for %s (will attempt create): %s", path, exc)
                existing_guid = ""
            if existing_guid:
                guids_by_path[path] = existing_guid
                results[path] = existing_guid
                self._registry.set_sub_resource_egeria_guid("repo", resource_slug, path, existing_guid)
                continue

            parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
            if entry["kind"] == "file":
                # NestedFile strictly requires a FileFolder parent — the
                # caller (catalog route) guarantees an ancestor chain exists
                # in the local table for every selected file.
                parent_guid = guids_by_path.get(parent_path)
                relationship_type = "NestedFile"
            elif path == "" or parent_path == "":
                # A root-level (or the synthetic root itself) folder attaches
                # directly to the repo's SourceControlLibrary asset.
                parent_guid = asset_guid
                relationship_type = "CapabilityAssetUse"
            else:
                parent_guid = guids_by_path.get(parent_path)
                relationship_type = "FolderHierarchy"

            if not parent_guid:
                log.warning(
                    "Skipping sub-resource %s — no parent GUID resolved for %r",
                    path or "(root)", parent_path,
                )
                continue

            try:
                guid = self._create_sub_resource(
                    entry, qualified_name, parent_guid, relationship_type, template_guid_cache
                )
            except Exception as exc:
                log.warning("Could not catalog sub-resource %s: %s", path or "(root)", exc)
                continue
            if guid:
                guids_by_path[path] = guid
                results[path] = guid
                self._registry.set_sub_resource_egeria_guid("repo", resource_slug, path, guid)

        return results

    def _create_sub_resource(
        self,
        entry: dict,
        qualified_name: str,
        parent_guid: str,
        relationship_type: str,
        template_guid_cache: dict[str, str],
    ) -> str:
        path = entry["path"]
        name = path.rsplit("/", 1)[-1] if path else qualified_name.split("::")[1].rstrip("/")

        if entry["kind"] == "folder":
            tech_type = self._FOLDER_TECH_TYPE
            placeholder_values = {
                "directoryPathName": qualified_name,
                "directoryName": name or "/",
                "description": f"Sub-resource folder cataloged from survey: {path or '(root)'}",
            }
        else:
            from resource_explorer.surveyors.sub_resource_templates import resolve_technology_type

            tech_type = resolve_technology_type(path)
            ext = path.rsplit(".", 1)[-1].lower() if "." in name else ""
            placeholder_values = {
                "fileName": name,
                "fileType": tech_type,
                "filePathName": qualified_name,
                "fileExtension": ext,
                "description": f"Sub-resource file cataloged from survey: {path}",
                "versionIdentifier": "1.0",
            }

        template_guid = template_guid_cache.get(tech_type)
        if not template_guid:
            template_guid = self._resolve_template_guid(tech_type)
            template_guid_cache[tech_type] = template_guid

        additional_props = {"path": path or "(root)", "kind": entry["kind"]}
        if entry.get("owners"):
            additional_props["owners"] = ",".join(entry["owners"])
        if entry.get("last_updated_at"):
            additional_props["last_updated_at"] = entry["last_updated_at"]
        if entry.get("first_added_at"):
            additional_props["first_added_at"] = entry["first_added_at"]

        body = {
            "class": "TemplateRequestBody",
            "templateGUID": template_guid,
            "isOwnAnchor": False,
            "parentGUID": parent_guid,
            "parentRelationshipTypeName": relationship_type,
            "placeholderPropertyValues": placeholder_values,
            # Without this, the template derives its own qualifiedName from
            # its placeholder values using Egeria's own convention
            # ("FileFolder::~{fileSystemName}~:<directoryPathName>", not our
            # qualified_name string byte-for-byte) — confirmed live,
            # 2026-08-11: that mismatch silently breaks D8's find-by-
            # qualifiedName idempotency guard (every publish re-creates a
            # duplicate). "class": "AssetProperties" is required here or
            # Egeria 400s (InvalidTypeIdException: missing "class" on
            # EntityProperties), also confirmed live.
            "replacementProperties": {"class": "AssetProperties", "qualifiedName": qualified_name},
        }
        guid = self._automated_curation.create_elem_from_template(body)
        if guid and additional_props:
            # Best-effort: template creation doesn't accept additionalProperties
            # directly, so attach D9 metadata via a follow-up update if the
            # client supports it; skip quietly on older pyegeria versions.
            try:
                self._asset_maker.update_asset(
                    guid, body={"class": "UpdateElementRequestBody",
                                 "mergeUpdate": True,
                                 "properties": {"class": "AssetProperties",
                                                 "additionalProperties": additional_props}},
                )
            except Exception as exc:
                log.debug("Could not attach additionalProperties to %s: %s", guid, exc)
        return guid

    def _resolve_template_guid(self, technology_type: str) -> str:
        import asyncio

        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self._automated_curation._async_get_template_guid_for_technology_type(technology_type)
        )

    def _find_element_guid(self, qualified_name: str) -> str:
        """Return the GUID of an existing Egeria element by qualified name,
        or '' if not found — the D8 idempotency guard for sub-resources."""
        import re as _re

        uuid_re = _re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.IGNORECASE
        )
        result = self._automated_curation.get_guid_for_name(qualified_name)
        if isinstance(result, list) and result:
            candidate = result[0] if isinstance(result[0], str) else result[0].get("guid", "")
            return candidate if uuid_re.match(candidate or "") else ""
        if isinstance(result, str) and uuid_re.match(result):
            return result
        return ""

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
