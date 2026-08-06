"""
Read-only access to Egeria's real Technology Type catalog (AutomatedCuration's
find_technology_types/get_tech_type_detail) — distinct from the RE-specific
additionalProperties.supported_technology_type convention used to tag Survey
Definitions (see survey_definition_reader.py).

This is the source of ground-truth technology names (e.g. "PostgreSQL
Relational Database", not "PostgreSQL Database") and of what a native Egeria
survey action service actually produces (get_tech_type_detail's
resourceList/governanceActionProcesses[].specification.producedAnnotationType),
confirmed live 2026-07-08. Process results in-memory per platform+server —
these calls are workspace-wide catalog metadata that doesn't change often
within a session, so callers should share one instance rather than refetch
per request.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


class EgeriaTechTypeCatalogError(RuntimeError):
    """Raised when Egeria Technology Type catalog operations fail."""


class EgeriaTechTypeCatalog:
    def __init__(
        self,
        platform_url: str | None = None,
        view_server: str | None = None,
        user_id: str | None = None,
        user_password: str | None = None,
    ) -> None:
        self.platform_url = platform_url or os.getenv("EGERIA_PLATFORM_URL", "")
        self.view_server = view_server or os.getenv("EGERIA_VIEW_SERVER", "qs-view-server")
        self.user_id = user_id or os.getenv("EGERIA_USER_ID", "erinoverview")
        self.user_password = user_password or os.getenv("EGERIA_USER_PASSWORD", "secret")
        self._automated_curation = None
        self._all_types_cache: list[dict] | None = None
        self._detail_cache: dict[str, dict] = {}

    def connect(self) -> None:
        if self._automated_curation is not None:
            return
        if not self.platform_url:
            raise EgeriaTechTypeCatalogError(
                "EGERIA_PLATFORM_URL is not set. Set it in .env or pass platform_url=."
            )
        try:
            from pyegeria import AutomatedCuration

            self._automated_curation = AutomatedCuration(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._automated_curation.create_egeria_bearer_token(self.user_id, self.user_password)
        except ImportError as exc:
            raise EgeriaTechTypeCatalogError("pyegeria is not installed.") from exc
        except Exception as exc:
            raise EgeriaTechTypeCatalogError(
                f"Could not connect to Egeria at {self.platform_url}: {exc}"
            ) from exc

    def list_technology_types(self, search: str = "*", refresh: bool = False) -> list[dict]:
        """All registered Technology Types (or a filtered subset if search is
        narrower than "*"), each a dict with technologyTypeGUID/qualifiedName/
        displayName/description/category. Cached per (search) after first call."""
        self.connect()
        if search == "*" and self._all_types_cache is not None and not refresh:
            return self._all_types_cache

        try:
            result = self._automated_curation.find_technology_types(
                search_string=search, output_format="JSON"
            )
        except Exception as exc:
            raise EgeriaTechTypeCatalogError(f"find_technology_types({search!r}) failed: {exc}") from exc

        types = result if isinstance(result, list) else []
        if search == "*":
            self._all_types_cache = types
        return types

    def get_tech_type_detail(self, display_name: str, refresh: bool = False) -> dict | None:
        """Full detail for one Technology Type by its exact real display name
        (e.g. "PostgreSQL Relational Database") — includes catalogTemplates,
        governanceActionProcesses, and resourceList. Returns None if Egeria has
        no Technology Type registered under that exact name. Cached per name."""
        self.connect()
        if display_name in self._detail_cache and not refresh:
            return self._detail_cache[display_name]

        try:
            result = self._automated_curation.get_tech_type_detail(display_name, output_format="JSON")
        except Exception as exc:
            raise EgeriaTechTypeCatalogError(
                f"get_tech_type_detail({display_name!r}) failed: {exc}"
            ) from exc

        detail = result if isinstance(result, dict) else None
        self._detail_cache[display_name] = detail
        return detail

    def get_produced_annotation_types(self, display_name: str) -> list[dict]:
        """What a native Egeria survey/catalog process for this Technology Type
        actually produces, deduplicated by name — pulled from the real
        specification.producedAnnotationType lists in resourceList and
        governanceActionProcesses. Each entry: name, description, explanation,
        annotation_type (the real openMetadataTypeName, e.g.
        "ResourceMeasureAnnotation"), analysis_step_name. Empty list if the
        Technology Type isn't found or documents nothing."""
        detail = self.get_tech_type_detail(display_name)
        if not detail:
            return []

        seen: dict[str, dict] = {}
        for source_key in ("resourceList", "governanceActionProcesses"):
            for entry in detail.get(source_key) or []:
                spec = entry.get("specification") or {}
                for pat in spec.get("producedAnnotationType") or []:
                    name = pat.get("name", "")
                    if not name or name in seen:
                        continue
                    seen[name] = {
                        "name": name,
                        "description": pat.get("description", ""),
                        "explanation": pat.get("explanation", ""),
                        "annotation_type": pat.get("openMetadataTypeName", ""),
                        "analysis_step_name": pat.get("analysisStepName", ""),
                    }
        return list(seen.values())
