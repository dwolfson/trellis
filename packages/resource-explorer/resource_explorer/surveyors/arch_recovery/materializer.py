"""Turns a curator's ACCEPTED verdict into a real Egeria `SolutionComponent`.

docs/architecture-recovery-report-then-curate.md's whole premise: RE reports
what the analysis believes; a curator decides whether it becomes real.
Everything up to here — findings, the review surface, the accept/reject/
retype verdict (this session's earlier work) — is RE reporting and a human
deciding. This module is the one remaining step: acting on that decision.

**Scope, deliberately narrow for this first slice:**

- Triggers on `verdict == "accepted"` ONLY. `rejected` writes nothing to
  Egeria — declining a proposal is not an Egeria event. `retyped` also
  writes nothing here; retyping is a correction to the PROPOSAL, and #10's
  design has no fixed vocabulary a retype could validate against (a repo's
  detected `type` values are free text), so this module trusts whatever the
  curator entered as-is if it later gets accepted under that new type — the
  same free-text field, not a second validated path.
- Creates a `SolutionComponent`, alone. Does NOT create or attach a
  `SolutionBlueprint` — candidate-cluster proposal (architecture-recovery-
  clustering.md, §10 of the report-then-curate note) is unbuilt, so there is
  no candidate blueprint to attach to yet. Wiring a materialized component
  into a blueprint is future work once that exists, not faked here.
- Does NOT touch an already-materialized component when a LATER verdict on
  the same scope changes (e.g. accept, then later reject). §9 of the
  report-then-curate note is explicit that reconciling a changed decision
  against an existing Egeria element "is not a reconciliation rule RE gets
  to apply" — that is a human choosing to update or retire the element
  directly in Egeria, not something this module does automatically.

**Idempotency, not a create-blind path.** Two things can each independently
cause a second "accepted" call for the same scope: a curator re-accepting
after re-running the survey, and this route being retried after a timeout
whose actual write succeeded. Both must land on the SAME Egeria element, not
a duplicate — the same qualifiedName-search-before-create discipline
`EgeriaPublisher._find_element_guid` already uses, backed by a local table
(`architecture_materialized_components`) that also skips the search call on
a warm read, mirroring `_find_or_create_asset`'s own caching shape.
"""
from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)

# Same defaults EgeriaPublisher uses (standard pyegeria env vars) — one
# Egeria connection convention for the whole codebase, not a second one
# invented here.
_DEFAULT_PLATFORM_URL = "https://localhost:9443"
_DEFAULT_VIEW_SERVER = "qs-view-server"
_DEFAULT_USER = "erinoverview"
_DEFAULT_PASSWORD = "secret"
_DEFAULT_TIMEOUT = 30

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class MaterializationError(RuntimeError):
    """Raised when Egeria credentials are absent, the platform is
    unreachable, or the create call itself fails. Caught at the route
    boundary (curate.py) and reported alongside the verdict — the verdict
    save is not rolled back for this, since the curator's decision is real
    and locally durable independent of whether Egeria is reachable right
    now (same non-fatal-but-visible shape as EgeriaPublisher.publish()'s
    own annotation_types_warning)."""


class ComponentMaterializer:
    """Owns its own lightweight Egeria connection rather than reusing
    EgeriaPublisher — this is triggered from a curator's verdict on ONE
    component (curate.py), a genuinely different call path from publishing
    a whole SurveyResult, and EgeriaPublisher's surface (asset/report/
    annotation lifecycle) is not what this needs."""

    def __init__(
        self,
        platform_url: str | None = None,
        view_server: str | None = None,
        user_id: str | None = None,
        user_password: str | None = None,
        timeout: int | None = None,
        registry: "ProjectRegistry | None" = None,
    ) -> None:
        self.platform_url = platform_url or os.getenv("EGERIA_PLATFORM_URL", _DEFAULT_PLATFORM_URL)
        self.view_server = view_server or os.getenv("EGERIA_VIEW_SERVER", _DEFAULT_VIEW_SERVER)
        self.user_id = user_id or os.getenv("EGERIA_USER", _DEFAULT_USER)
        self.user_password = user_password or os.getenv("EGERIA_USER_PASSWORD", _DEFAULT_PASSWORD)
        self.timeout = timeout or int(os.getenv("PYEGERIA_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT)))
        self._registry = registry
        self._solution_architect = None
        self._automated_curation = None

    def _connect(self) -> None:
        if not self.platform_url:
            raise MaterializationError(
                "EGERIA_PLATFORM_URL is not set. "
                "Add it to your .env file or pass platform_url= to ComponentMaterializer."
            )
        try:
            from pyegeria import AutomatedCuration
            from pyegeria.omvs.solution_architect import SolutionArchitect

            self._solution_architect = SolutionArchitect(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._solution_architect.create_egeria_bearer_token(self.user_id, self.user_password)

            # Used only for the qualifiedName idempotency check
            # (get_guid_for_name) — same helper EgeriaPublisher uses, same
            # reason: search before create, never create blind.
            self._automated_curation = AutomatedCuration(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._automated_curation.create_egeria_bearer_token(self.user_id, self.user_password)
        except ImportError as exc:
            raise MaterializationError(
                "pyegeria is not installed. Add it to your dependencies."
            ) from exc
        except Exception as exc:
            raise MaterializationError(
                f"Could not connect to Egeria at {self.platform_url}: {exc}"
            ) from exc

    def _find_element_guid(self, qualified_name: str) -> str:
        """Same implementation as EgeriaPublisher._find_element_guid — kept
        as its own copy rather than a shared import because the two classes
        deliberately don't share a connection or a base class (see the
        module docstring); this is the one piece of logic worth keeping
        byte-identical between them regardless."""
        result = self._automated_curation.get_guid_for_name(qualified_name)
        if isinstance(result, list) and result:
            candidate = result[0] if isinstance(result[0], str) else result[0].get("guid", "")
            return candidate if _UUID_RE.match(candidate or "") else ""
        if isinstance(result, str) and _UUID_RE.match(result):
            return result
        return ""

    @staticmethod
    def qualified_name_for(entity_type: str, entity_slug: str, scope_locator: str) -> str:
        """`SolutionComponent::{entity_type}::{entity_slug}::{scope_locator}` —
        same naming shape as every other qualifiedName in this codebase
        (`SourceControlLibrary::{url}`, `SurveyReport::GitHubRepo::{slug}
        ::{ts}`): kind, then the path that makes it unique. scope_locator is
        the join key architecture_recovery findings already use (a
        component's path prefix), so this needs no separate identity."""
        return f"SolutionComponent::{entity_type}::{entity_slug}::{scope_locator}"

    def materialize(
        self,
        entity_type: str,
        entity_slug: str,
        scope_locator: str,
        *,
        name: str,
        component_type: str = "",
        perspective: str = "",
        confidence: int = 0,
    ) -> dict:
        """Find-or-create the SolutionComponent for one accepted proposal.

        Returns {"status": "already_materialized" | "materialized",
        "guid": ..., "qualified_name": ...}. Raises MaterializationError on
        any failure to reach or write to Egeria — the caller (curate.py)
        catches this and reports it alongside the verdict, which is already
        saved and does not get rolled back.
        """
        qualified_name = self.qualified_name_for(entity_type, entity_slug, scope_locator)

        # Local cache first — same shape as _find_or_create_asset's cached-
        # GUID check, and for the same reason: a repeat accept (re-running
        # the survey, or a retried request) should not cost a search call,
        # let alone a create.
        if self._registry:
            cached = self._registry.get_materialized_component(entity_type, entity_slug, scope_locator)
            if cached and cached.get("guid"):
                return {"status": "already_materialized", "guid": cached["guid"],
                        "qualified_name": cached["qualified_name"]}

        self._connect()

        existing_guid = self._find_element_guid(qualified_name)
        if existing_guid:
            if self._registry:
                self._registry.record_materialized_component(
                    entity_type, entity_slug, scope_locator, qualified_name, existing_guid,
                )
            return {"status": "already_materialized", "guid": existing_guid,
                    "qualified_name": qualified_name}

        properties: dict = {
            "class": "SolutionComponentProperties",
            "qualifiedName": qualified_name,
            "displayName": name,
            # Backlog.md item 6 / blueprint_materializer.py's own docstring
            # (2026-09-03): the same Draft-status gap BlueprintMaterializer
            # had, fixed the same way — contentStatus is a plain field on
            # ReferenceableProperties, settable inside properties on the
            # existing NewElementRequestBody. architecture-recovery.md §10
            # Phase 2's "All at ContentStatus = Draft" now holds for
            # components too, not just blueprints.
            "contentStatus": "DRAFT",
        }
        # Confidence and perspective are evidence ABOUT the proposal, not
        # properties of the real element a curator just decided is real —
        # accepting is the point at which that evidence stops mattering to
        # what gets written, so neither rides on the created element.
        # additionalProperties still carries them for now, since there is no
        # typed home for "recovered from architecture_recovery, originally
        # proposed at N% confidence" on a SolutionComponent today, and
        # dropping that provenance entirely would be a worse default than an
        # untyped string.
        additional = {"recoveredBy": "architecture_recovery"}
        if perspective:
            additional["perspective"] = perspective
        if confidence:
            additional["originalConfidence"] = str(confidence)
        properties["additionalProperties"] = additional
        if component_type:
            properties["solutionComponentType"] = component_type

        body = {
            "class": "NewElementRequestBody",
            "isOwnAnchor": True,
            "properties": properties,
        }
        try:
            guid = self._solution_architect.create_solution_component(body)
        except Exception as exc:
            raise MaterializationError(f"Egeria rejected the new SolutionComponent: {exc}") from exc
        if not guid or not _UUID_RE.match(guid):
            raise MaterializationError(f"Egeria returned no usable GUID for the new SolutionComponent (got {guid!r})")

        if self._registry:
            self._registry.record_materialized_component(
                entity_type, entity_slug, scope_locator, qualified_name, guid,
            )
        return {"status": "materialized", "guid": guid, "qualified_name": qualified_name}
