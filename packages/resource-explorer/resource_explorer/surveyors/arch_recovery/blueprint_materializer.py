"""Turns a curator's ACCEPTED verdict on a candidate_blueprint finding into
a real Egeria `SolutionBlueprint`.

docs/blueprint-materialization-plan.md is the authoritative design for this
module; read it before changing anything here. This is Phase A of that
plan: the materializer itself, unit-testable in isolation with a fake/mocked
SolutionArchitect — no route, no outbox wiring, no frontend. Membership and
wire enqueueing (Phase B) are deliberately NOT here; see the module-level
scope note below and Decision 5 in the plan.

**Scope, deliberately narrow for this slice (mirrors materializer.py's own
"scope, deliberately narrow" framing):**

- `materialize_blueprint_element` finds-or-creates ONLY the `SolutionBlueprint`
  element itself. It does NOT attach members, does NOT attach child
  blueprints, and does NOT create any `SolutionLinkingWire`s — those are the
  route's job (Phase B), via the outbox, because a blueprint write is N+1+M
  elements and a crash mid-write must leave a resumable, visible state, not
  a half-formed live blueprint with no record of what's missing (plan
  Decision 5).
- `resolve_member_guids`/`resolve_child_blueprint_guids` are read-only
  lookups against already-materialized state. They never create anything
  and never raise for missing data — an unmaterialized member or child is
  data the caller (the route, in Phase B) acts on, not an error condition
  (plan Decisions 1 and 2: accepting a blueprint does NOT implicitly accept
  or materialize its members/children).

**Draft-status divergence from `ComponentMaterializer` — achieved, on the
second attempt (Backlog.md item 6, 2026-09-03).** `architecture-recovery.md`
§10 Phase 2 says explicitly "All at `ContentStatus = Draft`" for this
projection. First attempt: `class: "NewSolutionElementRequestBody"` with a
top-level `initialStatus: "DRAFT"`, per `SolutionArchitect.
create_solution_blueprint`'s own docstring — **failed client-side, before
any HTTP call**: `NewSolutionElementRequestBody` is documented in that
docstring in two separate pyegeria versions (5.3.4.23 here, 6.1.9 in the
canonical egeria-python checkout) but was never a real pydantic model, nor
(per egeria-python's own review, ISSUE-84) ever a real Egeria API surface —
`initialStatus` appears in no `.http` ground-truth file either. The
installed client validates every create-blueprint body against a bare
`TypeAdapter(NewElementRequestBody)`, whose `class` field is a strict
`Literal["NewElementRequestBody"]`; any other value raised a
`PyegeriaInvalidParameterException` ("Request body failed validation") that
read like an Egeria-side rejection but wasn't one. Second attempt, the real
mechanism (egeria-python-65's finding, odpi/egeria-python#337):
`contentStatus` is a plain field on `ReferenceableProperties` (base of
`SolutionBlueprintProperties`), settable inside `properties` on the
existing, real `NewElementRequestBody` — no separate request-body class
needed. Confirmed live against the real platform (post
`jdbcMaximumPoolSize` fix): `properties.contentStatus` round-trips as
`"DRAFT"` on read-back. `elementHeader.status` stays `"ACTIVE"` regardless
— that's OMRS's own instance-status axis (soft-delete/active at the
repository level), a different thing from the content-maturity axis
`contentStatus` represents; the design doc's own wording ("ContentStatus =
Draft") names the field this now sends, not the instance status.
`ComponentMaterializer` carried the identical gap (`NewElementRequestBody` with
no `contentStatus`) — fixed the same day, same fix, in that module directly
(`materializer.py`) rather than here, since it's out of scope for this module.

**Idempotency, not a create-blind path.** Same reasoning as
`ComponentMaterializer`: a repeat "accepted" call for the same
(perspective, cluster_name) — a curator re-accepting after re-running the
survey, or a retried request — must land on the SAME Egeria element, not a
duplicate. Local-cache check (`get_materialized_blueprint`) first, then a
qualifiedName search (`_find_element_guid`) before ever creating.
"""
from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)

# Same defaults ComponentMaterializer/EgeriaPublisher use (standard pyegeria
# env vars) — one Egeria connection convention for the whole codebase, not a
# second one invented here.
_DEFAULT_PLATFORM_URL = "https://localhost:9443"
_DEFAULT_VIEW_SERVER = "qs-view-server"
_DEFAULT_USER = "erinoverview"
_DEFAULT_PASSWORD = "secret"
_DEFAULT_TIMEOUT = 30

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class BlueprintMaterializationError(RuntimeError):
    """Raised when Egeria credentials are absent, the platform is
    unreachable, or the create call itself fails. Caught at the route
    boundary (curate.py, Phase B) and reported alongside the verdict — the
    verdict save is not rolled back for this, same non-fatal-but-visible
    shape as materializer.py's MaterializationError."""


class BlueprintMaterializer:
    """Owns its own lightweight Egeria connection rather than reusing
    EgeriaPublisher or ComponentMaterializer — mirrors ComponentMaterializer's
    own reasoning for why (a genuinely different call path, not
    EgeriaPublisher's asset/report/annotation-lifecycle surface). Kept
    outbox-agnostic on purpose: it returns GUIDs, it doesn't enqueue
    membership or wires, which keeps it unit-testable with a fake registry
    and no outbox machinery, matching how ComponentMaterializer is tested
    today."""

    def __init__(
        self,
        platform_url: str | None = None,
        view_server: str | None = None,
        user_id: str | None = None,
        user_password: str | None = None,
        timeout: int | None = None,
        registry: "ProjectRegistry | None" = None,
        identity=None,
    ) -> None:
        # Whose materialization this is. Resolved at `_connect` rather than
        # here (see `resolve_identity`) — a materializer is built in one place
        # and used in another, and the identity that matters is the one in
        # force when Egeria is actually written to.
        self._identity = identity
        self.platform_url = platform_url or os.getenv("EGERIA_PLATFORM_URL", _DEFAULT_PLATFORM_URL)
        self.view_server = view_server or os.getenv("EGERIA_VIEW_SERVER", _DEFAULT_VIEW_SERVER)
        self.user_id = user_id or os.getenv("EGERIA_USER", _DEFAULT_USER)
        self.user_password = user_password or os.getenv("EGERIA_USER_PASSWORD", _DEFAULT_PASSWORD)
        self.timeout = timeout or int(os.getenv("PYEGERIA_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT)))
        self._registry = registry
        self._solution_architect = None
        self._automated_curation = None

    def resolve_identity(self):
        """The `EgeriaIdentity` this materialization runs as.

        Constructor-supplied first (the worker knows whose run it executes),
        then the signed-in caller, then the service account. Curate is gated
        on a signed-in owner or curator before it reaches here, so the
        fallback is for background re-materialization only.
        """
        if self._identity is not None:
            return self._identity
        from resource_explorer.egeria_identity import caller_credentials

        self._identity = caller_credentials()
        return self._identity

    def _connect(self) -> None:
        if not self.platform_url:
            raise BlueprintMaterializationError(
                "EGERIA_PLATFORM_URL is not set. "
                "Add it to your .env file or pass platform_url= to BlueprintMaterializer."
            )
        identity = self.resolve_identity()
        if identity.is_person:
            self.user_id = identity.user_id
        try:
            from pyegeria import AutomatedCuration
            from pyegeria.omvs.solution_architect import SolutionArchitect

            from resource_explorer.egeria_identity import apply_identity

            self._solution_architect = SolutionArchitect(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            apply_identity(self._solution_architect, identity)

            # Used only for the qualifiedName idempotency check
            # (get_guid_for_name) — same helper ComponentMaterializer uses,
            # same reason: search before create, never create blind.
            self._automated_curation = AutomatedCuration(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            apply_identity(self._automated_curation, identity)
        except ImportError as exc:
            raise BlueprintMaterializationError(
                "pyegeria is not installed. Add it to your dependencies."
            ) from exc
        except Exception as exc:
            raise BlueprintMaterializationError(
                f"Could not connect to Egeria at {self.platform_url}: {exc}"
            ) from exc

    def _find_element_guid(self, qualified_name: str) -> str:
        """Byte-identical copy of ComponentMaterializer._find_element_guid —
        kept as its own copy rather than a shared import for the same reason
        that class gives for not sharing one with EgeriaPublisher: the two
        classes deliberately don't share a connection or a base class."""
        result = self._automated_curation.get_guid_for_name(qualified_name)
        if isinstance(result, list) and result:
            candidate = result[0] if isinstance(result[0], str) else result[0].get("guid", "")
            return candidate if _UUID_RE.match(candidate or "") else ""
        if isinstance(result, str) and _UUID_RE.match(result):
            return result
        return ""

    @staticmethod
    def qualified_name_for(entity_type: str, entity_slug: str, perspective: str, cluster_name: str) -> str:
        """`SolutionBlueprint::{entity_type}::{entity_slug}::{perspective}::{cluster_name}`
        — same naming shape as ComponentMaterializer.qualified_name_for and
        every other qualifiedName in this codebase: kind, then the path that
        makes it unique. A blueprint has no scope_locator (clustering.py's
        candidate_blueprint findings all share scope_locator=""), so its
        identity is (perspective, cluster_name) instead — the two are
        confirmed unique together (no two clusters share a name within one
        perspective, per clustering.propose's own grouping key)."""
        return f"SolutionBlueprint::{entity_type}::{entity_slug}::{perspective}::{cluster_name}"

    def materialize_blueprint_element(
        self,
        entity_type: str,
        entity_slug: str,
        perspective: str,
        cluster_name: str,
        *,
        display_name: str,
        oversized: bool = False,
    ) -> dict:
        """Find-or-create ONLY the SolutionBlueprint element itself (Draft,
        via NewSolutionElementRequestBody — see the module docstring's
        divergence note). Synchronous, same shape as
        ComponentMaterializer.materialize().

        Returns {"status": "already_materialized" | "materialized",
        "guid": ..., "qualified_name": ...}. Raises
        BlueprintMaterializationError on any failure to reach or write to
        Egeria — the caller (curate.py, Phase B) catches this and reports it
        alongside the verdict, which is already saved and does not get
        rolled back.
        """
        qualified_name = self.qualified_name_for(entity_type, entity_slug, perspective, cluster_name)

        # Local cache first — same shape as ComponentMaterializer.materialize's
        # cached-GUID check, and for the same reason: a repeat accept
        # (re-running the survey, or a retried request) should not cost a
        # search call, let alone a create.
        if self._registry:
            cached = self._registry.get_materialized_blueprint(
                entity_type, entity_slug, perspective, cluster_name
            )
            if cached and cached.get("guid"):
                return {"status": "already_materialized", "guid": cached["guid"],
                        "qualified_name": cached["qualified_name"]}

        self._connect()

        existing_guid = self._find_element_guid(qualified_name)
        if existing_guid:
            if self._registry:
                self._registry.record_materialized_blueprint(
                    entity_type, entity_slug, perspective, cluster_name, qualified_name, existing_guid,
                )
            return {"status": "already_materialized", "guid": existing_guid,
                    "qualified_name": qualified_name}

        properties: dict = {
            "class": "SolutionBlueprintProperties",
            "qualifiedName": qualified_name,
            "displayName": display_name,
            # architecture-recovery.md §10 Phase 2's "All at ContentStatus =
            # Draft" — achieved 2026-09-03, second attempt. The first
            # (class: "NewSolutionElementRequestBody" + top-level
            # initialStatus) never validated at all (Backlog.md item 6,
            # egeria-python PYEGERIA_ISSUES.md ISSUE-84). egeria-python-65's
            # review found the real mechanism: `contentStatus` is a plain
            # field on ReferenceableProperties (base of
            # SolutionBlueprintProperties), settable at creation like any
            # other property. Confirmed live against the real platform
            # (qs-view-server, post jdbcMaximumPoolSize fix): a blueprint
            # created with contentStatus: "DRAFT" round-trips it correctly
            # on read-back (properties.contentStatus == "DRAFT"). Separately
            # confirmed: elementHeader.status stays "ACTIVE" regardless —
            # that's OMRS's own instance-status axis (soft-delete/active at
            # the repository level), a different thing from the content-
            # maturity axis contentStatus represents; the design doc's own
            # wording ("ContentStatus = Draft") names exactly the field this
            # sends, not the instance status.
            "contentStatus": "DRAFT",
        }
        # Same provenance reasoning as ComponentMaterializer.materialize:
        # this is evidence ABOUT the proposal, not a typed property of the
        # real element a curator just decided is real, so it rides in
        # additionalProperties rather than inventing a typed field.
        additional = {"recoveredBy": "architecture_recovery"}
        if oversized:
            additional["oversized"] = "true"
        properties["additionalProperties"] = additional

        # `class: "NewSolutionElementRequestBody"` + `initialStatus` (this
        # method's original body, matching SolutionArchitect.
        # create_solution_blueprint's own docstring) fails BEFORE any Egeria
        # call — confirmed live 2026-09-03 accepting a real candidate
        # blueprint (Backlog.md item 6) and by direct inspection: pyegeria
        # 5.3.4.23 (this checkout) and 6.1.9 (the canonical egeria-python
        # checkout) both document `NewSolutionElementRequestBody` in that
        # docstring but never define it as a pydantic model — the installed
        # `ServerClient._new_element_request_adapter` is a bare
        # `TypeAdapter(NewElementRequestBody)`, whose `class_` field is
        # `Literal["NewElementRequestBody"]`. Any other `class` value is a
        # client-side `PyegeriaInvalidParameterException`
        # ("Request body failed validation") raised locally by pydantic —
        # it never reaches the network, so this was never an Egeria-side
        # rejection despite how the caught exception reads. Logged as a
        # pyegeria gap (egeria-python's PYEGERIA_ISSUES.md) rather than
        # patched there directly, per this repo's own policy of routing
        # egeria-python fixes through that tracker.
        #
        # The fix here is the same one ComponentMaterializer already lives
        # with: `class: "NewElementRequestBody"`, no `initialStatus` (it
        # isn't a real field on that model either — `extra="ignore"` would
        # have silently dropped it even if the class name had validated).
        # This means materialized blueprints are created ACTIVE, not DRAFT,
        # same as materialized components — the module docstring's
        # "Divergence from ComponentMaterializer #1" no longer holds; both
        # materializers now share the identical gap, tracked as its own
        # follow-up (Backlog.md, "Confidence classification"/Draft-status
        # note) rather than fixed by inventing a body shape pyegeria can't
        # validate.
        body = {
            "class": "NewElementRequestBody",
            "isOwnAnchor": True,
            "properties": properties,
        }
        try:
            guid = self._solution_architect.create_solution_blueprint(body)
        except Exception as exc:
            raise BlueprintMaterializationError(
                f"Egeria rejected the new SolutionBlueprint: {exc}"
            ) from exc
        if not guid or not _UUID_RE.match(guid):
            raise BlueprintMaterializationError(
                f"Egeria returned no usable GUID for the new SolutionBlueprint (got {guid!r})"
            )

        if self._registry:
            self._registry.record_materialized_blueprint(
                entity_type, entity_slug, perspective, cluster_name, qualified_name, guid,
            )
        return {"status": "materialized", "guid": guid, "qualified_name": qualified_name}

    def resolve_member_guids(
        self,
        registry,
        entity_type: str,
        entity_slug: str,
        member_slugs: list[str],
        slug_to_scope: dict[str, str],
    ) -> tuple[dict[str, str], list[str]]:
        """slug -> materialized SolutionComponent GUID, for members that ARE
        materialized; the second list is member slugs that are NOT (missing
        from slug_to_scope, no verdict, or no materialization) — Decision
        2's enforcement point: accepting a blueprint does not implicitly
        accept or materialize its members.

        `slug_to_scope` MUST be built the same way
        `_architecture_recovery_results` builds it (component finding's
        `detail["slug"]` -> its scope_locator) — see the plan's identity-
        mismatch warning: clustering keys members by component slug, but
        verdicts/materialization are keyed by scope_locator. Looking a slug
        up directly in `get_materialized_components()` without going
        through this map first silently finds nothing for every member.

        Never raises; an unmaterialized member is data, not an error.
        """
        resolved: dict[str, str] = {}
        unmet: list[str] = []
        for slug in member_slugs:
            scope = slug_to_scope.get(slug)
            if not scope:
                unmet.append(slug)
                continue
            row = registry.get_materialized_component(entity_type, entity_slug, scope)
            guid = row.get("guid") if row else ""
            if guid:
                resolved[slug] = guid
            else:
                unmet.append(slug)
        return resolved, unmet

    def resolve_child_blueprint_guids(
        self,
        registry,
        entity_type: str,
        entity_slug: str,
        perspective: str,
        child_names: list[str],
    ) -> tuple[dict[str, str], list[str]]:
        """Same shape as resolve_member_guids, for Decision 1's per-level
        acceptance: a parent blueprint's write attaches only children that
        already have their own materialized SolutionBlueprint — an
        unaccepted/unmaterialized child is reported back, not silently
        skipped or auto-materialized. Never raises."""
        resolved: dict[str, str] = {}
        unmet: list[str] = []
        for child_name in child_names:
            row = registry.get_materialized_blueprint(entity_type, entity_slug, perspective, child_name)
            guid = row.get("guid") if row else ""
            if guid:
                resolved[child_name] = guid
            else:
                unmet.append(child_name)
        return resolved, unmet
