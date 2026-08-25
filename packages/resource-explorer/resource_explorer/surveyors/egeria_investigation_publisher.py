"""Promote a local investigation into Egeria.

`docs/investigation-framing-design.md` §1 and §6. The local record was shaped
from the start so this is a **replay, not a migration**:

    investigations                -> Project (+ purposes on its charter)
    working_sets                  -> Collection
    investigation_resource_lists  -> ResourceList  (Project -> Collection)
    working_set_members           -> CollectionMembership (Collection -> asset)

Every step reports what it actually did. A partially-promoted investigation is a
real outcome — a member whose repo has never been published to Egeria has no
asset GUID to link, and inventing one would be worse than saying so.

This never edits pyegeria. Where a call fails, the failure is returned; per the
standing rule, pyegeria bugs get logged in PYEGERIA_ISSUES.md rather than worked
around here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class PromotionResult:
    """What actually happened, step by step."""
    project_guid: str = ""
    project_qualified_name: str = ""
    collection_guid: str = ""
    resource_list_linked: bool = False
    members_linked: list[str] = field(default_factory=list)
    members_unlinkable: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.project_guid) and not self.errors

    def as_dict(self) -> dict:
        return {
            "project_guid": self.project_guid,
            "project_qualified_name": self.project_qualified_name,
            "collection_guid": self.collection_guid,
            "resource_list_linked": self.resource_list_linked,
            "members_linked": self.members_linked,
            "members_unlinkable": self.members_unlinkable,
            "errors": self.errors,
            "ok": self.ok,
        }


class EgeriaInvestigationPublisher:
    """Creates the Egeria side of an investigation. Read-only on the local row —
    the caller decides whether to record the returned GUIDs."""

    def __init__(self, registry, *, project_manager=None, collection_manager=None):
        self._registry = registry
        self._pm = project_manager
        self._cm = collection_manager

    def _managers(self):
        if self._pm is not None and self._cm is not None:
            return self._pm, self._cm
        from resource_explorer.config import get_config
        from pyegeria import CollectionManager, ProjectManager

        cfg = get_config().egeria
        pm = ProjectManager(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
        cm = CollectionManager(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
        for mgr in (pm, cm):
            mgr.create_egeria_bearer_token()
        self._pm, self._cm = pm, cm
        return pm, cm

    def promote(self, investigation_slug: str) -> PromotionResult:
        res = PromotionResult()
        inv = self._registry.get_investigation(investigation_slug)
        if not inv:
            res.errors.append(f"investigation '{investigation_slug}' not found")
            return res
        if inv.get("egeria_project_guid"):
            res.errors.append(
                "already bound to an Egeria Project — unbind first rather than "
                "creating a second one for the same body of work"
            )
            return res

        try:
            pm, cm = self._managers()
        except Exception as exc:
            res.errors.append(f"could not reach Egeria: {type(exc).__name__}: {exc}")
            return res

        # 1. the Project itself.
        #
        # Purposes go in `additionalProperties`, NOT appended to the description.
        # `mission` and `purposes` are both `ProjectCharter` (0442) properties,
        # and a charter is a separate element `create_project` cannot make — so
        # neither is reachable here. `Project` (0130) is a `Referenceable`
        # though, and `additionalProperties` is the sanctioned carrier for
        # exactly this: structured data the type has no dedicated slot for.
        # Stuffing them into free-text description would make them unreadable
        # by anything but a human, and would have to be parsed back out when the
        # charter is eventually written.
        #
        # (Corrected after review: the first version did use the description.
        # Same error the SolutionPort work hit earlier — reading a type's own
        # attribute list, finding no home, and settling, when the answer was one
        # inheritance edge away.)
        purposes = inv.get("purposes") or []
        qualified_name = f"Project::Investigation::{investigation_slug}"
        properties: dict = {
            "class": "ProjectProperties",
            "typeName": "Project",
            "qualifiedName": qualified_name,
            "displayName": inv["display_name"],
            "description": inv.get("description") or "",
            "identifier": investigation_slug,
        }
        if purposes:
            properties["additionalProperties"] = {
                "purposes": ", ".join(purposes),
                "purposeSource": "ProjectCharter.purposes (pending a real charter)",
                "createdBy": "resource-explorer",
            }
        try:
            res.project_guid = pm.create_project(
                body={"class": "NewElementRequestBody", "properties": properties},
            ) or ""
            res.project_qualified_name = qualified_name
        except Exception as exc:
            # A qualifiedName collision is a specific, actionable situation, not
            # a generic failure: a Project for this investigation already exists
            # in Egeria — typically because a previous promotion succeeded and
            # the local binding was cleared, orphaning it. Egeria signals this as
            # a 409 wrapped in a large Java error payload; surfacing that raw to
            # a user is useless, so it is translated once here.
            detail = str(exc)
            if "OMAG-COMMON-409-001" in detail or "is not available for use" in detail:
                res.errors.append(
                    f"An Egeria Project with qualifiedName '{qualified_name}' already "
                    "exists. This investigation was promoted before and the local "
                    "binding was cleared, leaving it orphaned. Bind to the existing "
                    "Project instead of creating a second one, or delete it in Egeria "
                    "first."
                )
            else:
                res.errors.append(f"create_project failed: {type(exc).__name__}: {detail}")
            return res
        if not res.project_guid:
            res.errors.append("create_project returned no GUID")
            return res

        # 2. the working set, as a Collection
        members = self._registry.list_investigation_members(investigation_slug)
        try:
            res.collection_guid = cm.create_collection(
                display_name=f"{inv['display_name']} working set",
                description="Resources in scope for this investigation.",
            ) or ""
        except Exception as exc:
            res.errors.append(f"create_collection failed: {type(exc).__name__}: {exc}")
            return res

        # Record it: a Collection created and then forgotten is an orphan the
        # next promotion cannot see.
        ws_slug = self._registry.investigation_working_set_slug(investigation_slug)
        if not ws_slug:
            ws_slug = (self._registry.get_or_create_working_set(investigation_slug) or {}).get("slug", "")
        if ws_slug and res.collection_guid:
            self._registry.set_working_set_egeria_collection(ws_slug, res.collection_guid)

        # 3. ResourceList: Project -> Collection
        try:
            cm.attach_collection(res.project_guid, res.collection_guid)
            res.resource_list_linked = True
        except Exception as exc:
            res.errors.append(f"attach_collection failed: {type(exc).__name__}: {exc}")

        # 4. CollectionMembership per member, where the resource actually exists
        #    in Egeria. A member whose repo was never published has no asset to
        #    link — reported, never invented.
        for m in members:
            asset_guid = self._asset_guid(m["entity_type"], m["entity_slug"])
            if not asset_guid:
                res.members_unlinkable.append({
                    **m, "reason": "not published to Egeria yet — no asset GUID",
                })
                continue
            try:
                cm.add_to_collection(res.collection_guid, asset_guid)
                res.members_linked.append(m["entity_slug"])
            except Exception as exc:
                res.members_unlinkable.append({
                    **m, "reason": f"add_to_collection failed: {type(exc).__name__}: {exc}",
                })
        return res

    def ensure_working_set(self, investigation_slug: str) -> PromotionResult:
        """Give an already-bound investigation its Egeria working set.

        Binding to an EXISTING Project (§1's second starting mode) previously
        recorded the GUID and stopped there — leaving the investigation with a
        Project but no Collection, so its membership had nowhere to go in
        Egeria. Creating the Project and creating the working set are the same
        need arriving by two different routes, so both routes now run this.

        Idempotent by the recorded collection GUID: called twice it does
        nothing the second time, rather than creating a second Collection and
        orphaning the first.
        """
        res = PromotionResult()
        inv = self._registry.get_investigation(investigation_slug)
        if not inv:
            res.errors.append(f"investigation '{investigation_slug}' not found")
            return res
        project_guid = inv.get("egeria_project_guid") or ""
        if not project_guid:
            res.errors.append("not bound to an Egeria Project — nothing to attach a working set to")
            return res
        res.project_guid = project_guid

        ws = self._registry.get_or_create_working_set(investigation_slug)
        if ws and ws.get("egeria_collection_guid"):
            res.collection_guid = ws["egeria_collection_guid"]
            res.resource_list_linked = True
            return res

        try:
            _, cm = self._managers()
        except Exception as exc:
            res.errors.append(f"could not reach Egeria: {type(exc).__name__}: {exc}")
            return res

        # Idempotent against EGERIA, not just against our own record. An
        # investigation promoted before the GUID was persisted has a real
        # Collection in Egeria and a blank column here; creating another would
        # orphan the first and silently split its membership across two. Ask
        # Egeria what is already attached before making anything.
        try:
            attached = cm.get_attached_collections(project_guid) or []
            for entry in attached if isinstance(attached, list) else []:
                guid = ((entry or {}).get("elementHeader") or {}).get("guid", "")
                if guid:
                    res.collection_guid = guid
                    res.resource_list_linked = True
                    self._registry.set_working_set_egeria_collection(ws["slug"], guid)
                    return res
        except Exception as exc:
            # Not fatal: an unreadable attachment list means we cannot ADOPT,
            # but it must not stop a genuinely missing working set being made.
            log.debug("could not list attached collections: %s", exc)

        try:
            res.collection_guid = cm.create_collection(
                display_name=f"{inv['display_name']} working set",
                description="Resources in scope for this investigation.",
            ) or ""
        except Exception as exc:
            res.errors.append(f"create_collection failed: {type(exc).__name__}: {exc}")
            return res
        try:
            cm.attach_collection(project_guid, res.collection_guid)
            res.resource_list_linked = True
        except Exception as exc:
            res.errors.append(f"attach_collection failed: {type(exc).__name__}: {exc}")
        self._registry.set_working_set_egeria_collection(ws["slug"], res.collection_guid)
        return res

    def _asset_guid(self, entity_type: str, entity_slug: str) -> str:
        if entity_type == "repo":
            return self._registry.get_egeria_asset_guid(entity_slug) or ""
        return ""
