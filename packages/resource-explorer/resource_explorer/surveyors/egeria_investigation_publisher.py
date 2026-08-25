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

        # 1. the Project itself
        try:
            purposes = inv.get("purposes") or []
            description = inv.get("description") or ""
            if purposes:
                # Purpose is ProjectCharter.purposes (§2). Until the charter is
                # written separately, carry them in the description rather than
                # dropping them — losing WHY the work exists is the one thing
                # this whole frame exists to prevent.
                description = (description + "\n\n" if description else "") + \
                    "Purposes: " + ", ".join(purposes)
            res.project_guid = pm.create_project(
                display_name=inv["display_name"], description=description,
            ) or ""
        except Exception as exc:
            res.errors.append(f"create_project failed: {type(exc).__name__}: {exc}")
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

    def _asset_guid(self, entity_type: str, entity_slug: str) -> str:
        if entity_type == "repo":
            return self._registry.get_egeria_asset_guid(entity_slug) or ""
        return ""
