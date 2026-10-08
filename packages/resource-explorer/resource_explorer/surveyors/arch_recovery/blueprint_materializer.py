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

#: qualifiedName prefix of the SolutionComponents Egeria's content packs already define.
CONTENT_PACK_QN_PREFIX = "Egeria:ValidMetadataValue:"

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class BlueprintMaterializationError(RuntimeError):
    """Raised when Egeria credentials are absent, the platform is
    unreachable, or the create call itself fails. Caught at the route
    boundary (curate.py, Phase B) and reported alongside the verdict — the
    verdict save is not rolled back for this, same non-fatal-but-visible
    shape as materializer.py's MaterializationError."""


class BlueprintIdentifierNeeded(BlueprintMaterializationError):
    """A second blueprint of a kind was accepted for a repository with no identifier. Raised BEFORE any
    search or create: nothing was written. The message is the sentence the pane shows."""


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
        """The PRE-#556 form `SolutionBlueprint::{entity_type}::{entity_slug}::{perspective}::{cluster_name}`.
        LEGACY: it carries the root cluster's name, which the architect's ruling (2026-10-08) took out of a
        blueprint's identity. Kept only so a blueprint written under it is recognised and adopted; nothing is
        created under it. The identity RE writes is `blueprint_kinds.identity_qualified_name` (kind + repository)."""
        return f"SolutionBlueprint::{entity_type}::{entity_slug}::{perspective}::{cluster_name}"

    def _log_legacy_adoption(self, entity_type: str, entity_slug: str, guid: str) -> None:
        """Say, in the activity log, why a blueprint still carries a root name. Never raises: it is the
        visibility mechanism, not the work."""
        if not self._registry:
            return
        try:
            from resource_explorer.activity_logger import log_catalog
            log_catalog(
                self._registry, entity_type, entity_slug, "", "", status="ok",
                summary=f"adopted legacy-named blueprint {guid} \u00b7 delete it in Egeria to recreate under the new name",
            )
        except Exception:
            log.warning("could not write the legacy-adoption activity row for %s", guid, exc_info=True)

    def materialize_blueprint_element(
        self,
        entity_type: str,
        entity_slug: str,
        perspective: str,
        cluster_name: str,
        *,
        display_name: str,
        oversized: bool = False,
        verify_cached: bool = False,
        identifier: str = "",
        live_clusters: set[str] | None = None,
    ) -> dict:
        """Find-or-create ONLY the SolutionBlueprint element itself (Draft,
        via NewSolutionElementRequestBody — see the module docstring's
        divergence note). Synchronous, same shape as
        ComponentMaterializer.materialize().

        **Identity: kind + repository** (architect's ruling, 2026-10-08):
        `SolutionBlueprint::<type>::<slug>::<kind>[::<identifier>]` (`blueprint_kinds.identity_qualified_name`).
        The root cluster's name is NOT in it and not in the cache key: the cluster name is RE's internal key,
        kept on the registry row. A second blueprint of a kind needs a PERSON's `identifier` (never derived
        from a cluster name); without one it is refused before anything is created.

        Blueprints written before that carry the cluster's name (two older forms,
        `blueprint_kinds.legacy_qualified_names`): they are ADOPTED, never duplicated and never created
        again, and the adoption is written to the activity log.

        `live_clusters` (optional): the names of the clusters that exist now; a registry row under the same
        identity for a cluster not among them is stale (re-clustered) and is taken over.

        Returns {"status": "already_materialized" | "materialized",
        "guid": ..., "qualified_name": ...}. Raises
        BlueprintMaterializationError on any failure to reach or write to
        Egeria — the caller (curate.py, Phase B) catches this and reports it
        alongside the verdict, which is already saved and does not get
        rolled back.
        """
        from resource_explorer.blueprint_kinds import (
            identifier_needed_sentence,
            identity_property,
            identity_qualified_name,
            kind_word,
            legacy_qualified_names,
            validate_identifier,
        )
        try:
            identifier = validate_identifier(identifier)
        except ValueError as exc:
            raise BlueprintMaterializationError(f"{exc}: nothing was created") from exc
        qualified_name = identity_qualified_name(entity_type, entity_slug, perspective, identifier)
        legacy_names = legacy_qualified_names(entity_type, entity_slug, perspective, cluster_name)

        # Local cache first — same shape as ComponentMaterializer.materialize's
        # cached-GUID check, and for the same reason: a repeat accept
        # (re-running the survey, or a retried request) should not cost a
        # search call, let alone a create. The cluster's own row is read whatever name it was written
        # under (the registry's (..., perspective, cluster_name) key is the legacy key, read through the
        # mapping: a row whose qualifiedName is one of the old forms is an ADOPTED legacy blueprint).
        if self._registry:
            cached = self._registry.get_materialized_blueprint(
                entity_type, entity_slug, perspective, cluster_name
            )
            if cached and cached.get("guid"):
                # `verify_cached` (the shape workflow): the cache names a GUID, and a blueprint a person has
                # since deleted in Egeria must not be re-attached to. Read it by GUID; gone means create
                # afresh. An UNREADABLE answer is not "gone" and raises, so the cache is never wiped on a
                # connection problem.
                hit = {"status": "already_materialized", "guid": cached["guid"],
                       "qualified_name": cached["qualified_name"]}
                if not verify_cached:
                    if cached["qualified_name"] in legacy_names:
                        self._log_legacy_adoption(entity_type, entity_slug, cached["guid"])
                    return hit
                self._ensure_connected()
                if self.blueprint_exists(cached["guid"]):
                    if cached["qualified_name"] in legacy_names:
                        self._log_legacy_adoption(entity_type, entity_slug, cached["guid"])
                    return hit

            # A second blueprint of the kind: another LIVE cluster already holds this identity.
            other = self._registry.get_materialized_blueprint_by_identity(
                entity_type, entity_slug, qualified_name)
            if (isinstance(other, dict) and other.get("cluster_name") != cluster_name
                    and (live_clusters is None or other.get("cluster_name") in live_clusters)):
                if not identifier:
                    raise BlueprintIdentifierNeeded(identifier_needed_sentence(perspective, entity_slug))
                raise BlueprintMaterializationError(
                    f"the identifier {identifier!r} is already used by another {kind_word(perspective)} "
                    f"Blueprint for {entity_slug} \u00b7 give this one a different identifier: nothing was created")

        if not verify_cached:
            self._connect()
        else:
            self._ensure_connected()      # connected already by the cache check above, when it ran

        # A search that cannot be read is not a search that found nothing: creating on it could duplicate a
        # blueprint that is there (an outage, an index lag). Refuse instead.
        adopted_legacy = False
        try:
            existing_guid = self._find_element_guid(qualified_name)
            if not existing_guid:
                for legacy in legacy_names:
                    existing_guid = self._find_element_guid(legacy)
                    if existing_guid:
                        qualified_name, adopted_legacy = legacy, True
                        break
        except Exception as exc:
            raise BlueprintMaterializationError(
                f"could not search Egeria for the blueprint by qualifiedName ({type(exc).__name__}): "
                f"nothing was created") from exc
        if existing_guid:
            if self._registry:
                self._registry.record_materialized_blueprint(
                    entity_type, entity_slug, perspective, cluster_name, qualified_name, existing_guid,
                )
            if adopted_legacy:
                self._log_legacy_adoption(entity_type, entity_slug, existing_guid)
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
            # `<SLUG>-<KIND>` as the owner's own blueprints carry it. UNVERIFIED LIVE: pyegeria's
            # SolutionBlueprintProperties declares no `identifier` (only `version_identifier`; the Java
            # type may), so the wire name is the one the owner's blueprints show, sent as given.
            "identifier": identity_property(entity_slug, perspective, identifier),
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

    # ── the shape writes (DESIGN-BLUEPRINT-BENCHMARK-EGERIA-WORKSPACES.md 6a) ─────────────────────────────

    def _ensure_connected(self) -> None:
        """Connect once. A cached-GUID path returns before `_connect`, so a method that needs the clients
        afterwards cannot assume them."""
        if self._solution_architect is None or self._automated_curation is None:
            self._connect()

    def blueprint_exists(self, guid: str) -> bool:
        """Whether a SolutionBlueprint is still in Egeria, read by GUID. Gone only on Egeria's own
        no-elements answer, a not-found exception or an API exception carrying a 404 (`egeria_absence`).
        Anything else (unauthorised, transport, 5xx, text we do not recognise) is UNREADABLE and raises:
        the caller must never create a second blueprint on a guess."""
        from resource_explorer.egeria_absence import ABSENT, PRESENT, is_absent

        try:
            result = self._solution_architect.get_solution_blueprint_by_guid(guid)
        except Exception as exc:
            if is_absent(exc) == ABSENT:
                return False
            raise BlueprintMaterializationError(
                f"could not tell whether the blueprint {guid} still exists: {type(exc).__name__}") from exc
        verdict = is_absent(result)
        if verdict == PRESENT:
            return True
        if verdict == ABSENT:
            return False
        raise BlueprintMaterializationError(
            f"could not tell whether the blueprint {guid} still exists: Egeria's answer was not readable")

    @staticmethod
    def _element_type_and_qn(element) -> tuple[str, str]:
        """(typeName, qualifiedName) of an element read by GUID, in either the raw or the formatted shape;
        "" for what the answer does not carry."""
        if not isinstance(element, dict):
            return "", ""
        header = element.get("elementHeader") or {}
        type_name = ((header.get("type") or {}).get("typeName") or element.get("typeName")
                     or element.get("type_name") or "")
        props = element.get("properties") or {}
        qn = props.get("qualifiedName") or element.get("qualifiedName") or element.get("qualified_name") or ""
        return type_name, qn

    def adopt_unmaterialized_members(
        self, registry, entity_type: str, entity_slug: str, member_slugs: list[str],
        slug_to_scope: dict[str, str],
    ) -> dict[str, str]:
        """slug -> GUID for members whose SolutionComponent already EXISTS in Egeria under RE's own
        qualifiedName though this registry never recorded it. They are ADOPTED (recorded, never created
        again): the owner's old blueprint left its components behind, and the new blueprint must meet them,
        not duplicate them. Creating a component stays the component verdict's job (privacy, zones), so a
        member Egeria does not hold is simply left out.

        `get_guid_for_name` searches several properties with no type restriction, so a hit is VERIFIED by
        reading it by GUID: it must be a SolutionComponent carrying exactly that qualifiedName. A hit that
        fails (or cannot be verified) is skipped and reported in `self.adoption_skipped` {slug: why}. Never
        raises."""
        from resource_explorer.surveyors.arch_recovery.materializer import ComponentMaterializer

        adopted: dict[str, str] = {}
        self.adoption_skipped: dict[str, str] = {}
        try:
            self._ensure_connected()
        except BlueprintMaterializationError as exc:
            log.warning("cannot adopt components, Egeria unreachable: %s", exc)
            for slug in member_slugs:
                self.adoption_skipped[slug] = "Egeria unreachable"
            return adopted
        for slug in member_slugs:
            scope = slug_to_scope.get(slug)
            if not scope:
                continue
            qn = ComponentMaterializer.qualified_name_for(entity_type, entity_slug, scope)
            try:
                guid = self._find_element_guid(qn)
            except Exception as exc:                       # several hits, or a search failure
                self.adoption_skipped[slug] = f"search failed: {type(exc).__name__}"
                continue
            if not guid:
                continue
            try:
                type_name, found_qn = self._element_type_and_qn(
                    self._solution_architect.get_solution_component_by_guid(guid))
            except Exception as exc:
                self.adoption_skipped[slug] = f"could not verify {guid}: {type(exc).__name__}"
                continue
            if type_name != "SolutionComponent" or found_qn != qn:
                self.adoption_skipped[slug] = (
                    f"{guid} is not a SolutionComponent named {qn} (read back as {type_name or 'unknown type'})")
                continue
            registry.record_materialized_component(entity_type, entity_slug, scope, qn, guid)
            adopted[slug] = guid
        return adopted

    def find_content_pack_component(self, display_name: str) -> dict | None:
        """The content-pack SolutionComponent Egeria already defines under EXACTLY this name, or None.
        Content-pack elements carry a qualifiedName of the form `Egeria:ValidMetadataValue:...`. The by-name
        search may match loosely, so a hit counts only when its displayName equals the name (case and
        punctuation aside). More than one such element is ambiguous: nothing is adopted and the answer is
        {"refused": "<sentence>"}. Never raises: no answer is no content-pack element."""
        import re as _re

        def norm(t: str) -> str:
            return _re.sub(r"[^a-z0-9]", "", (t or "").lower())

        try:
            self._ensure_connected()
            found = self._solution_architect.get_solution_components_by_name(display_name)
        except Exception as exc:
            log.warning("content-pack lookup for %r failed: %s", display_name, type(exc).__name__)
            return None
        if not isinstance(found, list):
            return None
        hits = []
        for el in found:
            if not isinstance(el, dict):
                continue
            props = el.get("properties") or {}
            qn = props.get("qualifiedName") or el.get("qualifiedName") or ""
            name = props.get("displayName") or el.get("displayName") or ""
            guid = (el.get("elementHeader") or {}).get("guid") or el.get("guid") or ""
            if (qn.startswith(CONTENT_PACK_QN_PREFIX) and norm(name) == norm(display_name)
                    and _UUID_RE.match(guid or "")):
                hits.append({"guid": guid, "qualified_name": qn, "name": name})
        if len(hits) > 1:
            return {"refused": f"{len(hits)} content-pack elements are named {display_name!r}: "
                               f"none adopted"}
        return hits[0] if hits else None

    @staticmethod
    def _child_guids(element) -> tuple[set[str], bool]:
        """(child GUIDs, known) from a container read by GUID. `nestedSolutionComponents` is the container's
        children side of SolutionComposition (Egeria's own end definition: the other end,
        `usedInSolutionComponents`, is "the components that embed this component"); `subComponents` is the
        report-spec form pyegeria also reads. `known` is True only when at least one of the keys is
        PRESENT: an answer with neither says nothing about children, so an empty set is not "none"."""
        if not isinstance(element, dict):
            return set(), False
        keys = [k for k in ("nestedSolutionComponents", "subComponents") if k in element]
        out: set[str] = set()
        for k in keys:
            for entry in element.get(k) or []:
                if not isinstance(entry, dict):
                    continue
                header = (entry.get("relatedElement") or entry).get("elementHeader") or {}
                if header.get("guid"):
                    out.add(header["guid"])
        return out, bool(keys)

    def sub_component_guids(self, container_guid: str) -> tuple[set[str], bool]:
        """(the container's sub-component GUIDs, whether the read said anything about them). Raises when
        Egeria gives no usable element at all: "could not read" must not look like "has none"."""
        element = self._solution_architect.get_solution_component_by_guid(container_guid)
        if not isinstance(element, dict) or not element:
            raise BlueprintMaterializationError(
                f"could not read the container {container_guid}: Egeria's answer was not an element")
        return self._child_guids(element)

    def blueprint_member_guids(self, blueprint_guid: str) -> set[str] | None:
        """The GUIDs that are direct members of the blueprint, or None when the read does not carry its
        members (then nothing is claimed about them). Read only; never removes anything."""
        try:
            element = self._solution_architect.get_solution_blueprint_by_guid(blueprint_guid)
        except Exception as exc:
            log.warning("could not read the blueprint's members: %s", type(exc).__name__)
            return None
        if not isinstance(element, dict) or "collectionMembers" not in element:
            return None
        out = set()
        for entry in element.get("collectionMembers") or []:
            if isinstance(entry, dict):
                header = (entry.get("relatedElement") or entry).get("elementHeader") or {}
                if header.get("guid"):
                    out.add(header["guid"])
        return out

    def link_sub_components(self, container_guid: str, container_qn: str,
                            children: list[tuple[str, str]]) -> list[dict]:
        """`SolutionComposition` container -> each child, idempotent by the PAIR. `children` is
        [(child_guid, child_qn)]. Reads the container's sub-components BEFORE (a pair already held, by the
        content pack or an earlier run, is not rewritten: the relationship is multi-link and would
        duplicate), writes only the missing pairs, then reads AFTER. Each row is {key, container_guid,
        child_guid, status, read_back, note?, error?}:

          already_present  the before-read showed the pair (read_back True)
          linked           written, and the after-read shows it (read_back True)
          unconfirmed      written but not shown after, OR the read did not say whether children exist so
                           nothing was written (read_back False in the second case)
          unread           the before-read failed: nothing written (read_back False)
          error            the write raised (read_back False)
        """
        self._ensure_connected()
        rows = [{"key": f"SolutionComposition::{container_qn}::{child_qn}", "container_guid": container_guid,
                 "child_guid": child_guid, "status": "", "read_back": False}
                for child_guid, child_qn in children]
        try:
            before, known = self.sub_component_guids(container_guid)
        except Exception as exc:
            for r in rows:
                r.update(status="unread", error=f"{type(exc).__name__}: {exc}"[:300],
                         note="the read before the write failed: nothing was written")
            return rows
        if not known:
            for r in rows:
                r.update(status="unconfirmed", note="the read did not say whether children exist: "
                                                    "nothing was written")
            return rows
        wrote = False
        for r in rows:
            if r["child_guid"] in before:
                r.update(status="already_present", read_back=True)
                continue
            try:
                self._solution_architect.link_subcomponent(
                    container_guid, r["child_guid"], {"class": "NewRelationshipRequestBody"})
                wrote = True
                r["status"] = "pending"
            except Exception as exc:
                r.update(status="error", error=f"{type(exc).__name__}: {exc}"[:300])
        if wrote:
            try:
                after, after_known = self.sub_component_guids(container_guid)
            except Exception as exc:
                after, after_known = set(), False
                for r in rows:
                    if r["status"] == "pending":
                        r["error"] = f"read after the write failed: {type(exc).__name__}"
        else:
            after, after_known = before, True
        for r in rows:
            if r["status"] == "pending":
                if after_known and r["child_guid"] in after:
                    r.update(status="linked", read_back=True)
                else:
                    r.update(status="unconfirmed", read_back=after_known)
        return rows

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
