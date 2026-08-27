"""Find and repair drift between Resource Explorer and Egeria.

RE keeps its own registry, so an Egeria reset loses nothing of yours — but it
leaves RE holding pointers into a catalog that no longer contains what they
point at. Rebuilding after the 2026-08-26 redeploy took four operations run by
hand in a specific order, and one of them did not exist. This is that sequence,
made a first-class thing.

Two rules the whole module is built around:

**Unreachable is never stale.** A failed lookup means we could not tell, and is
reported as such — never cleared. Reading a network error as "gone" would clear
a live catalog, which is exactly what an earlier version of the sweep script
did: it declared all 23 valid GUIDs stale on a healthy Egeria.

**Ambiguity is reported, never guessed.** Some drift has one correct repair and
some needs a person. A resource whose Egeria Project was deleted cannot be
re-bound automatically — RE does not know which Project it should join now, and
picking one would recreate the class of wrong-but-plausible answer this codebase
keeps removing. Those land in `decisions`, not `repairs`.

Scanning never writes. Repairs run only for the step names a caller asks for.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)

#: Repairs, in dependency order. Order is load-bearing: clearing stale pointers
#: must happen before republishing (or a publish reuses a dead GUID), and
#: republishing before relinking (or a member still has no asset to link to).
REPAIR_STEPS = (
    "reauthor_survey_definitions",
    "clear_stale_assets",
    "clear_orphan_publish_claims",
    "clear_stale_investigations",
    "clear_stale_contexts",
    "relink_investigation_members",
)


@dataclass
class Finding:
    """One kind of drift: what it is, what it affects, and what to do."""
    key: str
    title: str
    detail: str
    items: list = field(default_factory=list)
    repair_step: str = ""       # "" when no automatic repair is correct
    needs_decision: bool = False

    @property
    def count(self) -> int:
        return len(self.items)

    def as_dict(self) -> dict:
        return {
            "key": self.key, "title": self.title, "detail": self.detail,
            "count": self.count, "items": self.items[:50],
            "truncated": max(0, self.count - 50),
            "repair_step": self.repair_step, "needs_decision": self.needs_decision,
        }


@dataclass
class ScanResult:
    reachable: bool = True
    unreachable_reason: str = ""
    findings: list = field(default_factory=list)
    undetermined: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "reachable": self.reachable,
            "unreachable_reason": self.unreachable_reason,
            "findings": [f.as_dict() for f in self.findings],
            # Surfaced separately from findings so a lookup that FAILED is never
            # read as a lookup that found nothing.
            "undetermined": self.undetermined[:50],
            "undetermined_count": len(self.undetermined),
            "total": sum(f.count for f in self.findings),
            "repairable": sum(f.count for f in self.findings if f.repair_step),
            "needs_decision": sum(f.count for f in self.findings if f.needs_decision),
        }


class EgeriaResync:
    """Scan for drift, and repair the parts that have one correct repair."""

    def __init__(self, registry: "ProjectRegistry | None" = None) -> None:
        from resource_explorer.registry import ProjectRegistry

        self._registry = registry or ProjectRegistry()
        self._clients: dict = {}

    # ── connections ─────────────────────────────────────────────────────────
    def _connect(self) -> tuple[bool, str]:
        if self._clients:
            return True, ""
        try:
            from pyegeria import AssetMaker, CollectionManager, ProjectManager

            from resource_explorer.config import get_config

            cfg = get_config().egeria
            am = AssetMaker(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
            pm = ProjectManager(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
            cm = CollectionManager(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
            for c in (am, pm, cm):
                c.create_egeria_bearer_token()
            self._clients = {"asset": am, "project": pm, "collection": cm}
            return True, ""
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _resolves(lookup: Callable, guid: str) -> bool | None:
        """True / False / None — the third is "could not determine".

        Never collapse None into False. An unreachable Egeria, an auth failure,
        or a method that does not exist on the client are all reasons we cannot
        tell, and treating any of them as "gone" clears live data.
        """
        try:
            found = lookup(guid)
        except Exception as exc:
            name = type(exc).__name__
            if "NotFound" in name or "404" in str(exc):
                return False
            return None
        if isinstance(found, str):
            return "No elements" not in found and bool(found.strip())
        return bool(found)

    # ── scan ────────────────────────────────────────────────────────────────
    def scan(self) -> ScanResult:
        res = ScanResult()
        ok, why = self._connect()
        if not ok:
            res.reachable = False
            res.unreachable_reason = why
            return res

        res.findings.append(self._scan_assets(res))
        res.findings.append(self._scan_orphan_publish_claims())
        res.findings.append(self._scan_investigation_guids(res))
        res.findings.append(self._scan_contexts(res))
        res.findings.append(self._scan_unlinked_members())
        res.findings.append(self._scan_unpublished_but_expected())
        res.findings.append(self._scan_local_investigations())
        res.findings.append(self._scan_definition_drift(res))
        res.findings = [f for f in res.findings if f.count]
        return res

    def _scan_assets(self, res: ScanResult) -> Finding:
        """Cached asset GUIDs that no longer resolve.

        Verified the way EgeriaPublisher._find_or_create_asset verifies before
        reusing one — search by qualifiedName and check the GUID is among the
        results. NOT get_asset_by_guid, which raises NotFound for GUIDs that
        plainly exist.
        """
        am = self._clients["asset"]
        with self._registry._conn() as conn:
            rows = conn.execute(
                "SELECT slug, github_url, egeria_asset_guid FROM projects "
                "WHERE coalesce(egeria_asset_guid, '') <> '' ORDER BY slug"
            ).fetchall()
        stale = []
        for r in rows:
            try:
                check = am.find_software_capabilities(
                    search_string=f"SourceControlLibrary::{r['github_url']}",
                    starts_with=True, ignore_case=False, output_format="JSON",
                )
            except Exception as exc:
                res.undetermined.append({
                    "kind": "asset", "ref": r["slug"],
                    "reason": f"{type(exc).__name__}: {str(exc)[:80]}",
                })
                continue
            live = isinstance(check, list) and any(
                (e.get("elementHeader") or {}).get("guid") == r["egeria_asset_guid"]
                for e in check
            )
            if not live:
                stale.append({"slug": r["slug"], "guid": r["egeria_asset_guid"]})
        return Finding(
            key="stale_assets",
            title="Cached asset GUIDs pointing at nothing",
            detail="These repos render as Published while their catalog entry is gone. "
                   "Clearing also drops their survey records and publish claims, which "
                   "are local claims about what Egeria holds.",
            items=stale, repair_step="clear_stale_assets",
        )

    def _scan_orphan_publish_claims(self) -> Finding:
        """Publish claims for repos with no asset GUID behind them.

        These outlive the GUID the clearing keys on, so anything an earlier pass
        missed becomes unreachable the moment that GUID is cleared.
        """
        with self._registry._conn() as conn:
            rows = conn.execute(
                "SELECT p.slug AS slug, count(*) AS n "
                "FROM project_published_annotation_types t "
                "JOIN projects p ON p.slug = t.project_slug "
                "WHERE coalesce(p.egeria_asset_guid, '') = '' "
                "GROUP BY p.slug ORDER BY n DESC"
            ).fetchall()
        return Finding(
            key="orphan_publish_claims",
            title="Publish claims with no asset behind them",
            detail="The Analyses cards' Published badge is derived from these. "
                   "Nothing points at a catalog entry, so the badge is false.",
            items=[{"slug": r["slug"], "claims": r["n"]} for r in rows],
            repair_step="clear_orphan_publish_claims",
        )

    def _scan_investigation_guids(self, res: ScanResult) -> Finding:
        pm, cm = self._clients["project"], self._clients["collection"]
        stale = []
        with self._registry._conn() as conn:
            invs = conn.execute(
                "SELECT slug, egeria_project_guid FROM investigations "
                "WHERE coalesce(egeria_project_guid, '') <> ''"
            ).fetchall()
            sets = conn.execute(
                "SELECT slug, egeria_collection_guid FROM working_sets "
                "WHERE coalesce(egeria_collection_guid, '') <> ''"
            ).fetchall()
        for r in invs:
            v = self._resolves(pm.get_project_by_guid, r["egeria_project_guid"])
            if v is False:
                stale.append({"kind": "investigation", "ref": r["slug"],
                              "guid": r["egeria_project_guid"]})
            elif v is None:
                res.undetermined.append({"kind": "investigation", "ref": r["slug"],
                                         "reason": "lookup failed"})
        for r in sets:
            v = self._resolves(cm.get_collection_by_guid, r["egeria_collection_guid"])
            if v is False:
                stale.append({"kind": "working set", "ref": r["slug"],
                              "guid": r["egeria_collection_guid"]})
            elif v is None:
                res.undetermined.append({"kind": "working set", "ref": r["slug"],
                                         "reason": "lookup failed"})
        return Finding(
            key="stale_investigation_guids",
            title="Investigation Projects and working sets that are gone",
            detail="A dangling asset GUID makes a badge lie; a dangling Project GUID "
                   "makes promote fail outright against a Project nothing resolves.",
            items=stale, repair_step="clear_stale_investigations",
        )

    def _scan_contexts(self, res: ScanResult) -> Finding:
        """entity_egeria_project_context — the row that decides whether a
        resource may publish and what it attaches to."""
        pm = self._clients["project"]
        with self._registry._conn() as conn:
            rows = conn.execute(
                "SELECT entity_type, entity_slug, egeria_project_guid "
                "FROM entity_egeria_project_context "
                "WHERE coalesce(egeria_project_guid, '') <> ''"
            ).fetchall()
        seen: dict = {}
        stale = []
        for r in rows:
            guid = r["egeria_project_guid"]
            if guid not in seen:
                seen[guid] = self._resolves(pm.get_project_by_guid, guid)
            if seen[guid] is False:
                stale.append({"ref": f"{r['entity_type']}:{r['entity_slug']}", "guid": guid})
            elif seen[guid] is None:
                res.undetermined.append({
                    "kind": "project context",
                    "ref": f"{r['entity_type']}:{r['entity_slug']}", "reason": "lookup failed",
                })
        return Finding(
            key="stale_contexts",
            title="Resources bound to an Egeria Project that no longer exists",
            detail="Publishing these would attach them to a Project that is gone. "
                   "Clearing returns them to 'unset' so the question is asked again.",
            items=stale, repair_step="clear_stale_contexts",
        )

    def _scan_unlinked_members(self) -> Finding:
        """In-scope resources that have an asset but are not in the Collection.

        promote() links membership once and refuses to run again, so members
        published AFTER promotion have no way in.
        """
        items = []
        for inv in self._registry.list_investigations():
            if not inv.get("egeria_project_guid"):
                continue
            ws = self._registry.get_or_create_working_set(inv["slug"])
            if not (ws or {}).get("egeria_collection_guid"):
                continue
            linkable = [
                m for m in self._registry.list_investigation_members(inv["slug"])
                if self._asset_guid(m["entity_type"], m["entity_slug"])
            ]
            if linkable:
                items.append({"investigation": inv["slug"], "linkable": len(linkable)})
        return Finding(
            key="unlinked_members",
            title="Investigation members that can be attached",
            detail="Safe to re-run: CollectionMembership is uni-link, so attaching an "
                   "already-attached member upserts rather than duplicating.",
            items=items, repair_step="relink_investigation_members",
        )

    def _scan_unpublished_but_expected(self) -> Finding:
        """Repos that decided a context once but now hold no asset."""
        items = []
        with self._registry._conn() as conn:
            rows = conn.execute(
                "SELECT c.entity_slug AS slug, c.status AS status "
                "FROM entity_egeria_project_context c "
                "JOIN projects p ON p.slug = c.entity_slug "
                "WHERE c.entity_type = 'repo' AND coalesce(p.egeria_asset_guid, '') = '' "
                "ORDER BY c.entity_slug"
            ).fetchall()
        for r in rows:
            items.append({"slug": r["slug"], "context": r["status"]})
        return Finding(
            key="needs_republish",
            title="Repos previously catalogued that Egeria no longer holds",
            detail="Publishing is a write and can be slow, so it is never done for you. "
                   "Scope it to one cheap step to re-register the asset: "
                   "POST /api/egeria/{slug}/publish with steps ['repo_health'].",
            items=items, repair_step="", needs_decision=True,
        )

    def _scan_local_investigations(self) -> Finding:
        items = [
            {"slug": i["slug"], "members": len(self._registry.list_investigation_members(i["slug"]))}
            for i in self._registry.list_investigations()
            if not i.get("egeria_project_guid")
        ]
        return Finding(
            key="local_investigations",
            title="Investigations with no Egeria Project",
            detail="Creating a Project is a write into a shared system and names a real "
                   "catalog object, so it stays your decision — bind an existing Project "
                   "or create one from the investigation's own card.",
            items=items, repair_step="", needs_decision=True,
        )

    def _scan_definition_drift(self, res: ScanResult) -> Finding:
        """Survey Definitions in Egeria that no longer match their source.

        The CSV and the generated Dr.Egeria documents are the source of truth;
        Egeria holds whatever was last authored into it. Adding a step to an
        analysis moves the first and not the second, so a definition can be
        silently short — the step exists, is runnable per-card, and simply
        never appears in any survey.
        """
        from resource_explorer.surveyors.survey_definition_reader import (
            SurveyDefinitionReader,
        )

        try:
            from resource_explorer.surveyors.survey_definition_reconciler import (
                intended_steps_by_definition,
            )
            intended = intended_steps_by_definition()
        except Exception:
            intended = _intended_steps_from_csv()

        behind = []
        try:
            reader = SurveyDefinitionReader()
            for cand in reader.find_candidate_process_guids("Git Repository"):
                name = cand["qualified_name"].split("::")[-1]
                want = intended.get(name)
                if not want:
                    continue
                try:
                    live = [s.re_analysis_step for s in reader.fetch(cand["guid"]).steps]
                except Exception as exc:
                    res.undetermined.append({
                        "kind": "survey definition", "ref": name,
                        "reason": f"{type(exc).__name__}",
                    })
                    continue
                missing = [k for k in want if k not in live]
                extra = [k for k in live if k and k not in want]
                if missing or extra:
                    behind.append({"definition": name, "missing": missing,
                                   "extra": extra, "live_steps": len(live),
                                   "intended_steps": len(want)})
        except Exception as exc:
            res.undetermined.append({"kind": "survey definition", "ref": "(all)",
                                     "reason": f"{type(exc).__name__}: {str(exc)[:60]}"})

        return Finding(
            key="definition_drift",
            title="Survey Definitions behind their source",
            detail="Steps exist and are runnable per-card but appear in no survey. "
                   "Repairing re-executes the Dr.Egeria documents AND runs the "
                   "step-link reconciler — never one without the other, because "
                   "Link Next Process Step is not idempotent: the relationship "
                   "carries a guard and is multi-link by design, so re-running it "
                   "adds a second edge rather than merging, and a definition with "
                   "two outgoing next-steps is refused by the reader and renders "
                   "with zero steps.",
            items=behind, repair_step="reauthor_survey_definitions",
        )

    def _asset_guid(self, entity_type: str, entity_slug: str) -> str:
        if entity_type != "repo":
            return ""
        p = self._registry.get(entity_slug)
        return (getattr(p, "egeria_asset_guid", "") or "") if p else ""

    # ── repair ──────────────────────────────────────────────────────────────
    def apply(self, steps: list) -> dict:
        """Run the named repairs, in REPAIR_STEPS order regardless of input order.

        Order is load-bearing — clearing must precede relinking — so a caller
        cannot get it wrong by listing them in a different order.
        """
        unknown = [s for s in steps if s not in REPAIR_STEPS]
        if unknown:
            raise ValueError(f"unknown repair step(s): {unknown}")
        ok, why = self._connect()
        if not ok:
            return {"reachable": False, "unreachable_reason": why, "applied": {}}

        applied: dict = {}
        for step in REPAIR_STEPS:
            if step in steps:
                applied[step] = getattr(self, f"_do_{step}")()
        return {"reachable": True, "unreachable_reason": "", "applied": applied}

    def _do_reauthor_survey_definitions(self) -> dict:
        """Re-execute the survey-definitions batch, then reconcile its links.

        Delegates to bootstrap.heal_batch, which already runs a batch's
        documents in dependency order and its declared post_heal script — for
        this batch, the link reconciler. Reusing it means the reconciler cannot
        be forgotten, which is the failure mode that takes a definition out of
        service: forgetting it is far easier than noticing the duplicate edges
        it prevents.
        """
        from resource_explorer.bootstrap import discover_batches, heal_batch

        batch = next((b for b in discover_batches()
                      if b.batch_id == "survey-definitions"), None)
        if batch is None:
            return {"reauthored": False,
                    "error": "the survey-definitions batch was not found"}
        ok, detail = heal_batch(batch)
        return {"reauthored": bool(ok), "detail": detail,
                "documents": len(batch.files),
                "post_heal": (batch.post_heal or {}).get("script", "")}

    def _do_clear_stale_assets(self) -> dict:
        res = ScanResult()
        finding = self._scan_assets(res)
        cleared, surveys, claims = 0, 0, 0
        for item in finding.items:
            r = self._registry.clear_egeria_registration(item["slug"])
            cleared += 1
            surveys += r.get("surveys_deleted", 0)
            claims += r.get("published_types_deleted", 0)
        return {"cleared": cleared, "survey_records_deleted": surveys,
                "publish_claims_deleted": claims,
                "undetermined": len(res.undetermined)}

    def _do_clear_orphan_publish_claims(self) -> dict:
        with self._registry._conn() as conn:
            deleted = conn.execute(
                "DELETE FROM project_published_annotation_types WHERE project_slug IN ("
                "SELECT slug FROM projects WHERE coalesce(egeria_asset_guid, '') = '')"
            ).rowcount
        return {"claims_deleted": deleted}

    def _do_clear_stale_investigations(self) -> dict:
        res = ScanResult()
        finding = self._scan_investigation_guids(res)
        invs = [i for i in finding.items if i["kind"] == "investigation"]
        sets = [i for i in finding.items if i["kind"] == "working set"]
        with self._registry._conn() as conn:
            for i in invs:
                conn.execute(
                    "UPDATE investigations SET egeria_project_guid = '', "
                    "egeria_project_status = 'local' WHERE slug = ?", (i["ref"],))
            for i in sets:
                conn.execute(
                    "UPDATE working_sets SET egeria_collection_guid = '' WHERE slug = ?",
                    (i["ref"],))
        return {"investigations_cleared": len(invs), "working_sets_cleared": len(sets),
                "undetermined": len(res.undetermined)}

    def _do_clear_stale_contexts(self) -> dict:
        res = ScanResult()
        finding = self._scan_contexts(res)
        with self._registry._conn() as conn:
            for item in finding.items:
                etype, _, eslug = item["ref"].partition(":")
                # Back to 'unset', not 'personal' or 'declined': the decision
                # that was made pointed at something gone, so it must be asked
                # again rather than reinterpreted as an answer never given.
                conn.execute(
                    "UPDATE entity_egeria_project_context SET egeria_project_guid = '', "
                    "egeria_project_qualified_name = '', status = 'unset' "
                    "WHERE entity_type = ? AND entity_slug = ?", (etype, eslug))
        return {"contexts_cleared": len(finding.items),
                "undetermined": len(res.undetermined)}

    def _do_relink_investigation_members(self) -> dict:
        from resource_explorer.surveyors.egeria_investigation_publisher import (
            EgeriaInvestigationPublisher,
        )

        pub = EgeriaInvestigationPublisher(self._registry)
        linked, unlinkable, per_inv = 0, 0, {}
        for inv in self._registry.list_investigations():
            if not inv.get("egeria_project_guid"):
                continue
            r = pub.relink_members(inv["slug"])
            linked += len(r.members_linked)
            unlinkable += len(r.members_unlinkable)
            per_inv[inv["slug"]] = {
                "linked": len(r.members_linked),
                "unlinkable": len(r.members_unlinkable),
                "errors": r.errors,
            }
        return {"members_linked": linked, "members_unlinkable": unlinkable,
                "per_investigation": per_inv}


def _intended_steps_from_csv() -> dict:
    """{definition name: [step_key, ...]} from repo_survey_types.csv.

    A fallback for when the reconciler module cannot be imported. The CSV is
    the source of truth either way — the generated documents are derived from
    it, so comparing Egeria against it is comparing against what SHOULD have
    been authored.
    """
    import csv
    from pathlib import Path

    path = (Path(__file__).resolve().parent.parent / "docs" / "dr-egeria"
            / "repo_survey_types.csv")
    out: dict = {}
    try:
        with path.open() as fh:
            for row in csv.DictReader(fh):
                group = (row.get("survey_group") or "").strip()
                step = (row.get("step_key") or "").strip()
                if not group or not step:
                    continue
                if step == _FULL_SURVEY_SENTINEL:
                    # The full bundle is generated FROM STEP_REGISTRY rather
                    # than enumerated here, so the CSV carries a sentinel. A
                    # literal read would make it look like a one-step survey
                    # and report every other step as missing.
                    out[group] = _all_step_keys()
                    continue
                out.setdefault(group, []).append(step)
    except OSError:
        return {}
    return out


#: The CSV's stand-in for "every registered step", used by the full-survey row.
_FULL_SURVEY_SENTINEL = "*"


def _all_step_keys() -> list:
    try:
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            STEP_REGISTRY,
        )
    except ImportError:  # pragma: no cover - defensive
        return []
    return sorted(STEP_REGISTRY.keys())
