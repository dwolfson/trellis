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


def _create_typed_collection(cm, type_name: str, display_name: str,
                             description: str, qualified_name: str = "") -> str:
    """Create a Collection SUBTYPE (Folio, WorkingSet, ...).

    `create_collection`'s convenience parameters build a plain Collection, so the
    subtype goes through `body` as `typeName` — the same route the publisher
    already uses for asset properties. Folio and WorkingSet are subtypes of
    Collection, not classifications, so this is a typeName rather than an
    initial_classification.
    """
    # qualifiedName is REQUIRED and is not generated for you once you pass an
    # explicit body — the convenience path supplies one, the body path does not.
    # Egeria rejects the create with OPEN-METADATA-400-004 otherwise.
    body = {
        "class": "NewElementRequestBody",
        "properties": {
            "class": "CollectionProperties",
            "typeName": type_name,
            "qualifiedName": qualified_name or f"{type_name}::{display_name}",
            "displayName": display_name,
            "description": description,
        },
    }
    return cm.create_collection(body=body) or ""


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
            res.collection_guid = _create_typed_collection(
                cm, "Folio", inv["display_name"],
                "Everything in scope for this investigation.",
                qualified_name=f"Folio::Investigation::{investigation_slug}",
            )
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
        self._link_members(cm, res, members, investigation_slug)
        return res

    def _link_members(self, cm, res: "PromotionResult", members: list,
                      investigation_slug: str) -> None:
        """Attach every member that HAS an asset to the working set, via the outbox.

        CollectionMembership is uni-link, so add_to_collection is an upsert:
        calling it for an already-attached member is safe and does not
        duplicate. That is what lets this be re-run — and, now, what makes a
        queued retry safe by the relationship's own semantics rather than by a
        qualifiedName lookup, since a membership has no qualifiedName to search
        for. Measured live 2026-08-25; the return value is the test.

        **Why this is the part that goes through the outbox** (design §6 step 5).
        The Project and the Collection are created synchronously above: their
        GUIDs are needed by the steps that follow and are returned in the
        PromotionResult, so they cannot become deferred work. Members are the
        plural part, and — exactly as with the repo publisher's annotations —
        the part that swallowed failures one at a time. A member whose
        add_to_collection failed was reported as unlinkable and then forgotten;
        nothing ever tried again.

        Two outcomes stay firmly distinct, because conflating them is how a
        real gap in an investigation reads as a transient glitch:

        - **No asset GUID** is not a failed write. The member's repo was never
          published, so there is nothing to attach. It is reported as
          unlinkable and NOT queued — retrying it forever would be retrying a
          fact about the catalog, not an error.
        - **A failed attach** is a failed write, and is now a durable row the
          scheduler retries with backoff.

        The happy path is unchanged: rows are enqueued and drained inline, so a
        successful promotion still links everything before returning.
        """
        from resource_explorer.egeria_outbox import (
            OutboxClients, drain_outbox, enqueue_collection_members,
        )

        linkable: list[dict] = []
        for m in members:
            asset_guid = self._asset_guid(m["entity_type"], m["entity_slug"])
            if not asset_guid:
                res.members_unlinkable.append({
                    **m, "reason": "not published to Egeria yet — no asset GUID",
                })
                continue
            linkable.append({**m, "member_guid": asset_guid})

        if not linkable:
            return

        run_id = f"Investigation::{investigation_slug}::{res.collection_guid}"
        enqueue_collection_members(
            self._registry, investigation_slug, res.collection_guid, linkable,
            run_id=run_id,
        )
        summary = drain_outbox(
            self._registry, OutboxClients(collection_manager=cm), lambda qn: "",
            limit=max(len(linkable), 1), run_id=run_id,
        )

        # Report per member from what the drain actually did, not from what was
        # enqueued — an enqueued row is a promise, not a result.
        by_qn = {
            f"CollectionMembership::{res.collection_guid}::{m['member_guid']}": m
            for m in linkable
        }
        outstanding = {
            r["qualified_name"]: r
            for r in self._registry.list_outbox_elements(run_id=run_id, limit=len(linkable) * 2)
            if r["status"] != "done"
        }
        for qn, m in by_qn.items():
            row = outstanding.get(qn)
            if row is None:
                res.members_linked.append(m["entity_slug"])
            else:
                res.members_unlinkable.append({
                    **{k: v for k, v in m.items() if k != "member_guid"},
                    "reason": (
                        f"attach failed ({row['last_error'] or 'unknown error'}) — "
                        f"queued for retry, see Admin → Publish Queue"
                    ),
                })
        if summary.get("failed") or summary.get("dead"):
            log.warning("Investigation %s: %d membership(s) queued for retry",
                        investigation_slug, summary.get("failed", 0) + summary.get("dead", 0))

    def relink_members(self, investigation_slug: str) -> "PromotionResult":
        """Re-attach an already-promoted investigation's members.

        promote() links members once, at promotion time, and refuses to run
        again on a bound investigation. So a member that had no asset GUID THEN
        — every one of them, if the investigation was promoted before its repos
        were published — has no way to be linked later, and the Egeria
        Collection stays permanently empty while RE shows the resources in
        scope.

        Hit for real after the 2026-08-26 redeploy: both investigations
        promoted with `members_linked: []` because no repo had been
        republished yet, and nothing existed to run afterwards.

        Idempotent: add_to_collection upserts on a uni-link relationship.
        """
        res = PromotionResult()
        inv = self._registry.get_investigation(investigation_slug)
        if not inv:
            res.errors.append(f"investigation '{investigation_slug}' not found")
            return res
        res.project_guid = inv.get("egeria_project_guid") or ""
        if not res.project_guid:
            res.errors.append("not bound to an Egeria Project — promote or bind it first")
            return res

        ws = self._registry.get_or_create_working_set(investigation_slug)
        res.collection_guid = (ws or {}).get("egeria_collection_guid") or ""
        if not res.collection_guid:
            res.errors.append(
                "no working set Collection — run ensure_working_set first"
            )
            return res
        res.resource_list_linked = True

        try:
            _, cm = self._managers()
        except Exception as exc:
            res.errors.append(f"could not reach Egeria: {type(exc).__name__}: {exc}")
            return res

        self._link_members(cm, res,
                           self._registry.list_investigation_members(investigation_slug),
                           investigation_slug)
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
            # Not fatal — an unreadable attachment list must not stop a
            # genuinely missing working set being made — but NOT silent either.
            # Failing to look is exactly when a duplicate Collection gets
            # created, so the caller has to be able to see that the check did
            # not happen. Recorded on the result, not just logged.
            res.errors.append(
                f"could not check for an existing working set "
                f"({type(exc).__name__}: {exc}) — if one already exists in Egeria "
                "this may have created a second"
            )
            log.warning("could not list attached collections for %s: %s", project_guid, exc)

        try:
            res.collection_guid = _create_typed_collection(
                cm, "Folio", inv["display_name"],
                "Everything in scope for this investigation.",
                qualified_name=f"Folio::Investigation::{investigation_slug}",
            )
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

    def sync_project_properties(self, investigation_slug: str) -> PromotionResult:
        """Push a renamed/re-described investigation to its Egeria Project.

        Without this a rename silently drifts: the local record says one thing
        and the catalog another, about the same body of work. That is the
        two-sources-disagree failure this codebase keeps finding, and a rename
        is exactly when it starts.

        Not called automatically from the PATCH route — that route is a local
        edit and must not depend on Egeria being reachable to succeed. This is
        the deliberate follow-up.
        """
        res = PromotionResult()
        inv = self._registry.get_investigation(investigation_slug)
        if not inv:
            res.errors.append(f"investigation '{investigation_slug}' not found")
            return res
        guid = inv.get("egeria_project_guid") or ""
        if not guid:
            res.errors.append("not bound to an Egeria Project — nothing to sync")
            return res
        res.project_guid = guid
        try:
            pm, _ = self._managers()
        except Exception as exc:
            res.errors.append(f"could not reach Egeria: {type(exc).__name__}: {exc}")
            return res
        # Explicit body, NOT the display_name convenience parameter.
        # pyegeria's _async_update_project sends `name` where ProjectProperties
        # expects `displayName`, so the convenience path returns cleanly, logs
        # success, and changes nothing (PYEGERIA_ISSUES.md ISSUE-73, reproduced
        # live 2026-08-25). Its own create path uses displayName correctly, so
        # this is a spelling mismatch between the two, not a server behaviour.
        # pyegeria is not patched here — the body parameter is a supported API.
        body = {
            "class": "UpdateElementRequestBody",
            "properties": {
                "class": "ProjectProperties",
                "displayName": inv["display_name"],
                "description": inv.get("description") or "",
            },
        }
        try:
            pm.update_project(guid, body=body)
        except Exception as exc:
            res.errors.append(f"update_project failed: {type(exc).__name__}: {exc}")
            return res

        # Read back. A rename that reports success and changes nothing is the
        # exact failure above, so "no exception" is not evidence here.
        try:
            after = pm.get_project_by_guid(guid)
            props = (after or {}).get("properties", {}) if isinstance(after, dict) else {}
            if props.get("displayName") != inv["display_name"]:
                res.errors.append(
                    "update reported success but Egeria still shows "
                    f"{props.get('displayName')!r} — the rename did not apply"
                )
        except Exception as exc:
            res.errors.append(f"could not verify the rename applied: {type(exc).__name__}: {exc}")
        return res

    def sync_disposition_sets(self, investigation_slug: str) -> dict:
        """Create an Egeria WorkingSet per disposition IN USE, and link it.

        Only dispositions that actually have members: a WorkingSet carries a
        single Disposition, so pre-creating all six per investigation would fill
        the catalog with empty Collections that cannot be told apart from ones
        nobody has used.

        Each is a Collection subtype linked to the Project by its own
        ResourceList, with `resourceUse` naming the disposition — so the catalog
        answers "what is being tracked here" without reading membership.
        """
        out: dict = {"created": [], "skipped": [], "errors": []}
        inv = self._registry.get_investigation(investigation_slug)
        if not inv or not inv.get("egeria_project_guid"):
            out["errors"].append("not bound to an Egeria Project")
            return out
        project_guid = inv["egeria_project_guid"]
        try:
            _, cm = self._managers()
        except Exception as exc:
            out["errors"].append(f"could not reach Egeria: {type(exc).__name__}: {exc}")
            return out

        for disposition in self._registry.investigation_dispositions(investigation_slug):
            ws = self._registry.get_or_create_disposition_set(investigation_slug, disposition)
            if not ws:
                continue
            if ws.get("egeria_collection_guid"):
                out["skipped"].append(disposition)
                continue
            try:
                guid = _create_typed_collection(
                    cm, "WorkingSet", ws["display_name"],
                    f"Resources in this investigation with disposition '{disposition}'.",
                    # Slug-based, NOT derived from display_name. A qualifiedName
                    # built from a mutable label breaks the moment someone
                    # renames the investigation — which happened today — leaving
                    # an orphan whose name no longer matches anything, or a
                    # collision with the new one.
                    qualified_name=f"WorkingSet::Investigation::{investigation_slug}::{disposition}",
                )
                cm.attach_collection(project_guid, guid)
                self._registry.set_working_set_egeria_collection(ws["slug"], guid)
                out["created"].append({"disposition": disposition, "guid": guid})
            except Exception as exc:
                out["errors"].append(f"{disposition}: {type(exc).__name__}: {exc}")
        return out

    def _asset_guid(self, entity_type: str, entity_slug: str) -> str:
        if entity_type == "repo":
            return self._registry.get_egeria_asset_guid(entity_slug) or ""
        return ""
