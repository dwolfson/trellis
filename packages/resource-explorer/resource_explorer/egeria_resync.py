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
        res.findings.append(self._scan_unlinked_members(res))
        res.findings.append(self._scan_unpublished_but_expected())
        res.findings.append(self._scan_local_investigations())
        res.findings.append(self._scan_definition_drift(res))
        res.findings.append(self._scan_specification_gap())
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

    def _scan_unlinked_members(self, res: ScanResult) -> Finding:
        """In-scope resources that have an asset but are not in the Collection.

        promote() links membership once and refuses to run again, so members
        published AFTER promotion have no way in.

        Checks actual Egeria Collection membership (get_member_list), not just
        "has an asset" — the first version of this scan conflated the two, so
        it kept reporting the same members as "linkable" forever, even
        immediately after a successful relink_investigation_members repair
        actually attached them. Confirmed live 2026-08-26: repair reported
        22 members linked with zero errors, and the very next scan showed the
        identical 2 investigations again, because the scan never checked
        whether they were already there. "Has an asset" only proves a member
        is *linkable*, not that it still *needs* linking.

        A collection whose membership can't be read (unreachable, auth
        failure, method missing) goes to `undetermined`, not into `items` —
        reporting it as needing a repair we can't actually verify is done
        would be the same "guess dressed as a fact" this module's docstring
        warns against elsewhere.
        """
        cm = self._clients["collection"]
        items = []
        for inv in self._registry.list_investigations():
            if not inv.get("egeria_project_guid"):
                continue
            ws = self._registry.get_or_create_working_set(inv["slug"])
            collection_guid = (ws or {}).get("egeria_collection_guid")
            if not collection_guid:
                continue
            candidates = [
                m for m in self._registry.list_investigation_members(inv["slug"])
                if self._asset_guid(m["entity_type"], m["entity_slug"])
            ]
            if not candidates:
                continue
            try:
                members = cm.get_member_list(collection_guid=collection_guid)
                if not isinstance(members, list):
                    raise ValueError(f"get_member_list returned {members!r}, not a list")
            except Exception as exc:
                res.undetermined.append({
                    "kind": "collection membership",
                    "ref": f"investigation:{inv['slug']}",
                    "reason": f"{type(exc).__name__}: {exc}",
                })
                continue
            already_linked = {m.get("guid", "") for m in members}
            linkable = [
                m for m in candidates
                if self._asset_guid(m["entity_type"], m["entity_slug"]) not in already_linked
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
        """Repos with an Egeria Project context but no asset — two causes, kept apart.

        This reported them all as "previously catalogued that Egeria no longer
        holds", which is true of only some. Measured 2026-08-27: of seven, four
        really had been published (2026-08-24/25) and lost the asset to the
        redeploy, while three — `docs`, `enterprise_rag`, `genaicomps` — carry
        only a scout import from 2026-08-21 and were never catalogued at all.

        Telling a reader they lost something they never had sends them looking
        for a fault that does not exist, and the two need different actions:
        one is re-registering a known asset, the other is a first publish.
        """
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
                # A completed catalog/publish in the activity log is the
                # evidence that an asset once existed. Absent it, nothing was
                # lost — this repo has simply never been published.
                published_before = conn.execute(
                    "SELECT 1 FROM activity_log WHERE entity_slug = ? "
                    "AND operation = 'catalog' AND status = 'ok' LIMIT 1",
                    (r["slug"],),
                ).fetchone() is not None
                items.append({
                    "slug": r["slug"],
                    "context": r["status"],
                    "was_published": published_before,
                    "cause": ("asset lost — it was catalogued before"
                              if published_before else
                              "never catalogued — a context was set but no publish ran"),
                })
        lost = sum(1 for i in items if i["was_published"])
        return Finding(
            key="needs_republish",
            title=(f"Repos with an Egeria Project context but no asset "
                   f"({lost} lost an asset, {len(items) - lost} never had one)"),
            detail="Publishing is a write and can be slow, so it is never done for you. "
                   "Scope it to one cheap step to register the asset: "
                   "POST /api/egeria/{slug}/publish with steps ['repo_health']. "
                   "The call is the same either way, but the situations are not: "
                   "one restores something Egeria lost, the other catalogues a "
                   "repo for the first time.",
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
        """RECOVERY: Egeria no longer matches the authored documents.

        The documents are the definition — they carry guards, request
        parameters and ordering the CSV has no column for — so this is the
        comparison the repair acts on, and it tolerates nothing.

        Order is compared, not just membership. Run order is load-bearing:
        repo_foss_scorecard reads what repo_cve_scan writes, and for a while
        ran before it, scoring the previous run's advisories.

        A definition live in Egeria with no document of ours is NOT drift. It
        is somebody else's — an Egeria-native survey, or one authored directly
        — and we have nothing to restore it from. Reporting it would be
        claiming authority over a definition RE did not write.
        """
        documented = _documented_definitions()
        behind, foreign = [], []
        try:
            reader = _reader()
            for cand in reader.find_candidate_process_guids("Git Repository"):
                name = cand["qualified_name"].split("::")[-1]
                doc = documented.get(name)
                if doc is None:
                    foreign.append(name)
                    continue
                want = doc["steps"]
                try:
                    live_steps = reader.fetch(cand["guid"]).steps
                except Exception as exc:
                    res.undetermined.append({
                        "kind": "survey definition", "ref": name,
                        "reason": type(exc).__name__,
                    })
                    continue
                live = [st.re_analysis_step for st in live_steps]

                # Descriptions are part of the definition too. Comparing only
                # step keys is what let Egeria sit on a description the
                # documents had already moved past — invisible to a scan whose
                # whole job is to notice exactly that.
                stale = sorted(
                    st.re_analysis_step for st in live_steps
                    if st.re_analysis_step in doc["descriptions"]
                    and doc["descriptions"][st.re_analysis_step]
                    and (st.description or "").strip()
                    != doc["descriptions"][st.re_analysis_step].strip()
                )
                if live == want and not stale:
                    continue
                behind.append({
                    "definition": name,
                    "missing": [k for k in want if k not in live],
                    "extra": [k for k in live if k and k not in want],
                    "reordered": (live != want and set(live) == set(want)),
                    "stale_descriptions": stale,
                    "live_steps": len(live), "documented_steps": len(want),
                })
        except Exception as exc:
            res.undetermined.append({"kind": "survey definition", "ref": "(all)",
                                     "reason": f"{type(exc).__name__}: {str(exc)[:60]}"})

        if foreign:
            log.info("survey definitions live in Egeria with no document here: %s",
                     ", ".join(sorted(foreign)))
        return Finding(
            key="definition_drift",
            title="Survey Definitions in Egeria differ from their authored documents",
            detail="Steps that exist and are runnable per-card but appear in no survey, "
                   "or run in the wrong order. Repairing re-executes the Dr.Egeria "
                   "documents AND runs the step-link reconciler — never one without "
                   "the other, because Link Next Process Step is not idempotent: the "
                   "relationship carries a guard and is multi-link by design, so "
                   "re-running it adds a second edge rather than merging, and a "
                   "definition with two outgoing next-steps is refused by the reader "
                   "and renders with zero steps.",
            items=behind, repair_step="reauthor_survey_definitions",
        )

    def _scan_specification_gap(self) -> Finding:
        """COVERAGE: the CSV specifies a survey that no document defines.

        A different question from drift, and it was conflated with it until
        2026-08-26. The CSV is a specification of what surveys are NEEDED; the
        documents are the definitions. A gap here means a step will never reach
        Egeria no matter how many times the repair runs, because nothing
        authored it in the first place.

        Deliberately no repair step. Closing this means running the generator,
        which edits the source tree — and may rightly refuse, if a document has
        been hand-authored since. This panel repairs the catalog, not the
        repository, and a button here that rewrote committed files would be a
        different kind of thing wearing the same shape.

        Membership only, never order: the CSV's full-survey row is the sentinel
        "*", which has no order to compare, and its rows are not stored sorted.
        The documents are where order is authoritative.
        """
        documented = _documented_definitions()
        specified = _intended_steps_from_csv()
        gaps = []
        for name, want in sorted(specified.items()):
            entry = documented.get(name)
            have = entry["steps"] if entry else None
            if have is None:
                gaps.append({"definition": name, "reason": "no document defines it",
                             "missing": sorted(want), "specified_steps": len(want)})
                continue
            missing = [k for k in want if k not in have]
            if missing:
                gaps.append({"definition": name,
                             "reason": "the document is behind the CSV",
                             "missing": missing, "specified_steps": len(want),
                             "documented_steps": len(have)})
        # A document with no CSV row is not a gap. The CSV is not required to
        # be complete — that is the whole point of it being a specification of
        # what is needed rather than a definition of what exists.
        return Finding(
            key="specification_gap",
            title="Surveys specified in the CSV that no document defines",
            detail="repo_survey_types.csv says these surveys are needed, but no "
                   "Dr.Egeria document defines them (or the document predates the "
                   "CSV row). Until a document exists, re-authoring cannot put "
                   "these steps into Egeria. Fix by running "
                   "scripts/generate_repo_survey_definition.py — a source-tree "
                   "change, which is why there is no repair button here.",
            items=gaps, needs_decision=True,
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

        # An interlock stood here (2026-08-26): the repair refused to run while any
        # document carried a guard other than "Any", because the link reconciler
        # keyed duplicates on (previous, next) and would have deleted the branch.
        # The reconciler is keyed on (previous, next, guard) now and reconciles
        # against the authored document rather than a linear chain, so a branch
        # survives the repair and the refusal is no longer honest.
        #
        # A branching definition is still not RUNNABLE by RE: SurveyDefinitionReader
        # walks a single chain and raises UnsupportedSurveyDefinitionError. That is a
        # loud, safe failure rather than silent destruction, and coordinating a
        # branching process is Egeria's job under the engine-host model
        # (docs/survey-model-and-engine-host-design.md section 4), not RE's.
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


def _as_int(value) -> int:
    """A step_order as a number, or 0 when it cannot be read.

    Used only for sorting. An unreadable order sorts first rather than raising:
    the callers of this compare membership, not sequence, so a wrong position
    is cosmetic where an exception would lose the whole CSV.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


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
            # Sorted by the column that means order — rows are not stored in
            # it. Even so, callers compare membership rather than sequence:
            # the full-survey sentinel expands to a set with no order at all,
            # so a sorted list here is tidier, not authoritative. The documents
            # are where order is authoritative.
            rows = sorted(csv.DictReader(fh),
                          key=lambda r: _as_int(r.get("step_order")))
            for row in rows:
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


def _documented_definitions() -> dict:
    """{name: {"steps": [...], "descriptions": {...}}} for the scan's use.

    A thin projection of survey_definition_docs, which is the single parser for
    these files — the link reconciler reads the same documents to build its
    expected edge set, and two parsers of one format is how they drift apart.
    """
    from resource_explorer.surveyors.survey_definition_docs import (
        documented_definitions,
    )
    return {name: {"steps": doc.steps, "descriptions": doc.descriptions}
            for name, doc in documented_definitions().items()}


def _reader():
    from resource_explorer.surveyors.survey_definition_reader import (
        SurveyDefinitionReader,
    )
    return SurveyDefinitionReader()
