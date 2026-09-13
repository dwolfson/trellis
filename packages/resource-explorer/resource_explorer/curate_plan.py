"""Curate: what the catalogue should know about this resource, assembled
for review before the one near-irreversible act in the product.

The design (Enrichment and Curate Wireframes, Repo Handoff item 6): one
screen, three columns answering one question -- what it IS (library,
capability, endpoints), what it HOLDS (data files, sub-resources), what it
is MADE OF (components, ports, wires) -- plus how it relates, and a
manifest of what the commit writes. A database answers the first two; a
repository answers all three. The screen is a review-and-commit, not a
form: almost everything on it was decided earlier, and this is where it is
seen assembled.

Three rules from the design, held here:
- Candidates with evidence, never auto-applied. Every row names the
  analysis it came from and its state; a candidate is `□` until a person
  confirms it, and "3 Dockerfiles" carries a question mark, not
  "Infrastructure Asset (suggested)".
- Testimony is COPIED (enrichment -> classifications on the asset, with
  author and date, because it exists nowhere else); measurements are
  LINKED (survey reports are already Egeria objects; copying them makes a
  second truth). Unresolved things travel.
- Only worthy things get curated: the population is resources dispositioned
  `tracking` or `using`. The pane says so rather than hiding the resource.

Everything here is a local read: facts, findings, enrichment, verdicts, the
disposition. Nothing calls Egeria, so the plan renders when Egeria is down
and says which parts it could not know.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from resource_explorer.registry import ProjectRegistry

#: Curate's population, by disposition (Repo Handoff, model statement 5).
CURATE_POPULATION = ("tracking", "using")

#: Enrichment judgements that become governance classifications on the asset,
#: and the Egeria level each value maps to. The levels are Egeria's default
#: GovernanceClassificationLevel sets; a value not in the map is copied as
#: notes on the classification rather than dropped.
CONFIDENTIALITY_LEVELS = {"public": 0, "internal": 1, "confidential": 2, "restricted": 4}
CRITICALITY_LEVELS = {"low": 1, "important": 2, "critical": 3}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fact(layer, slug: str, analysis_id: str) -> dict:
    try:
        facts = layer.facts(slug, [analysis_id])
    except Exception as exc:                        # a reader that raises is a state, not a crash
        return {"analysis_id": analysis_id, "state": "unreadable", "headline": str(exc), "value": {}}
    return facts[0].as_dict() if facts else {"analysis_id": analysis_id, "state": "never_run", "value": {}}


def _findings(fact: dict) -> list[dict]:
    return list(((fact.get("value") or {}).get("findings")) or [])


def _detail(finding: dict) -> dict:
    """A finding row carries its detail as `detail_json`; a fact's finding
    carries `detail`. Read either."""
    if isinstance(finding.get("detail"), dict):
        return finding["detail"]
    try:
        return json.loads(finding.get("detail_json") or "{}") or {}
    except ValueError:
        return {}


def _row(kind: str, label: str, *, evidence: str, source: str, state: str, count: int | None = None,
         members: dict | None = None, candidate: bool = True, detail: dict | None = None) -> dict:
    """One line on the screen. `state` is the analysis's own state; `candidate`
    False means the row is a count, not a thing to confirm."""
    return {"kind": kind, "label": label, "evidence": evidence, "source": source,
            "state": state, "count": count, "members": members, "candidate": candidate,
            "detail": detail or {}}


def build_plan(registry: ProjectRegistry, slug: str) -> dict:
    from resource_explorer.facts import FactLayer

    project = registry.get(slug)
    if not project:
        raise KeyError(slug)
    layer = FactLayer(registry)
    disp = registry.get_disposition(project.github_url) if project.github_url else None
    disposition = (disp or {}).get("disposition") or "undecided"

    # ── what it is ─────────────────────────────────────────────────────
    what_it_is: list[dict] = []
    dist = registry.query_findings(slug, "distribution")
    if dist:
        for d in dist:
            det = _detail(d)
            lab = det.get("name") or d["check_name"]
            where = {"python": "PyPI", "javascript": "npm", "java": "Maven"}.get(det.get("ecosystem", ""), det.get("ecosystem", ""))
            what_it_is.append(_row(
                "SoftwareLibrary", f"Software Library · {lab}" + (f", on {where}" if d.get("label") == "published" else f" ({det.get('ecosystem','')}, not published)"),
                evidence=d.get("summary", ""), source="manifest_parse", state="measured",
                members={"analysis_id": "dependency_analysis"}, detail=det))
    else:
        mp = _fact(layer, slug, "manifest_parse")
        manifests = ((mp.get("value") or {}).get("dependencies") or {}).get("manifests") or []
        if manifests:
            what_it_is.append(_row(
                "SoftwareLibrary", "Software Library · name not read",
                evidence=f"manifests present ({', '.join(manifests)}); the distribution name is read by the "
                         "manifest_parse step from 2026-09-12 — re-survey to have it",
                source="manifest_parse", state=mp.get("state", ""), detail={"manifests": manifests}))
        else:
            what_it_is.append(_row("SoftwareLibrary", "Software Library?",
                                   evidence="no dependency manifest found", source="manifest_parse",
                                   state=mp.get("state", "")))

    ctx = registry.get_context("repo", slug) or {}
    enrichment = ctx.get("enrichment") or {}
    use = (enrichment.get("intended_use") or {}).get("value") or ctx.get("purpose") or ""
    if use:
        who = (enrichment.get("intended_use") or {}).get("author", "")
        what_it_is.append(_row("SoftwareCapability", f"Software Capability · {use}",
                               evidence=f"your note{' · ' + who if who else ''}", source="enrichment",
                               state="measured"))
    else:
        what_it_is.append(_row("SoftwareCapability", "Software Capability · no intended use recorded",
                               evidence="set Intended use on the Enrichment pane", source="enrichment",
                               state="needs_human"))

    iface = _fact(layer, slug, "interface_surface")
    # interface_surface's vocabulary is `specified` / `implied` / `no`
    kinds = [f for f in _findings(iface) if f.get("check_name") != "published_spec" and f.get("label") in ("specified", "implied")]
    spec = next((f for f in _findings(iface) if f.get("check_name") == "published_spec"), None)
    if kinds:
        names = ", ".join(f["check_name"] for f in kinds)
        contract = "no contract" if (spec and spec.get("label") == "no") else "contract published"
        implied = all(f.get("label") == "implied" for f in kinds)
        what_it_is.append(_row(
            "Endpoint", f"Endpoint × {len(kinds)} · {names} · {'implied' if implied else 'specified'}, {contract}",
            evidence="; ".join(f.get("summary", "") for f in kinds)[:400], source="interface_surface",
            state=iface.get("state", ""), count=len(kinds), members={"analysis_id": "interface_surface"},
            detail={"interfaces": [f["check_name"] for f in kinds], "implied": implied}))
    conv = _fact(layer, slug, "repo_conventions")
    docker = next((f for f in _findings(conv) if f.get("check_name") == "deployment_docker"), None)
    if docker and docker.get("label") == "pass":
        files = (_detail(docker).get("files") or [])
        what_it_is.append(_row(
            "InfrastructureAsset", f"Infrastructure Asset? {len(files) or ''} Dockerfile{'s' if len(files) != 1 else ''}".replace("?  ", "? "),
            evidence=docker.get("summary", ""), source="repo_conventions", state=conv.get("state", ""),
            detail={"files": files}))

    # ── what it holds ──────────────────────────────────────────────────
    holds: list[dict] = []
    dfp = _fact(layer, slug, "data_file_profiling")
    profiles = (dfp.get("value") or {}).get("profiles") or []
    with_schema = sum(1 for p in profiles if p.get("schema_json"))
    holds.append(_row("DataFile", f"{len(profiles):,} data files · {with_schema:,} with a profiled schema",
                      evidence="datasets with schemas — the same objects a database would give you",
                      source="data_file_profiling", state=dfp.get("state", ""), count=len(profiles),
                      members={"analysis_id": "data_file_profiling"}, candidate=len(profiles) > 0))
    srs = _fact(layer, slug, "sub_resource_survey")
    subs = _findings(srs)
    worthy = [f for f in subs if f.get("label") == "worthy"]
    rejected = [f for f in subs if f.get("label") == "not_worthy"]
    holds.append(_row("SubResource", f"{len(worthy)} of {len(subs)} sub-resources worth cataloguing · {len(rejected)} not",
                      evidence="each becomes its own asset, related to this one",
                      source="sub_resource_survey", state=srs.get("state", ""), count=len(worthy),
                      members={"analysis_id": "sub_resource_survey"}, candidate=len(worthy) > 0,
                      detail={"worthy": [f["check_name"] for f in worthy]}))

    # ── what it is made of ─────────────────────────────────────────────
    verdicts = registry.get_component_verdicts("repo", slug)
    comp_v = {k: v for k, v in verdicts.items() if v.get("verdict_target", "component") == "component"}
    bp_v = {k: v for k, v in verdicts.items() if v.get("verdict_target") == "blueprint"}
    arch = _fact(layer, slug, "architecture_recovery")
    comps = (arch.get("value") or {}).get("components") or []
    accepted = sum(1 for v in comp_v.values() if v.get("verdict") == "accepted")
    made_of = [
        _row("Component", f"{accepted} of {len(comps):,} components accepted · {len(comp_v)} reviewed",
             evidence="ports and wires are derived from the accepted components' interfaces and relationships; "
                      "review is per component and lives on Architecture verdicts (current UI) until it moves here",
             source="architecture_recovery", state=arch.get("state", ""), count=accepted,
             members={"analysis_id": "architecture_recovery"}, candidate=accepted > 0,
             detail={"reviewed": len(comp_v), "blueprints_reviewed": len(bp_v),
                     "blueprints_accepted": sum(1 for v in bp_v.values() if v.get("verdict") == "accepted")}),
    ]

    # ── how it relates ─────────────────────────────────────────────────
    deps = _fact(layer, slug, "dependency_analysis")
    n_deps = sum(len(v) for v in ((deps.get("value") or {}).get("by_ecosystem") or {}).values())
    relates = [
        _row("Dependency", f"{n_deps} dependencies · already-catalogued ones not looked up",
             evidence="which of these are already assets in the catalogue is an Egeria search, not a local fact; not built yet",
             source="dependency_analysis", state=deps.get("state", ""), count=n_deps,
             members={"analysis_id": "dependency_analysis"}, candidate=False),
    ]

    # ── what gets written ──────────────────────────────────────────────
    classifications = []
    for key, name in (("sensitivity", "Confidentiality"), ("criticality", "Criticality"), ("retention", "Retention")):
        f = enrichment.get(key) or {}
        if f.get("value"):
            classifications.append({"key": key, "classification": name, "value": f["value"],
                                    "author": f.get("author", ""), "set_at": f.get("set_at", ""),
                                    "interim": bool(f.get("interim")), "review": bool(f.get("review"))})
    owner = enrichment.get("owner") or {}
    licence = enrichment.get("licence") or {}
    published = registry.get_last_published_annotation_types(slug) or {}
    writes = {
        "entities": [r["kind"] for r in what_it_is if r["candidate"]],
        "contained": {"data_files": len(profiles), "sub_resources": len(worthy)},
        "classifications": classifications,
        "owner": {"value": owner.get("value", ""), "interim": bool(owner.get("interim")), "author": owner.get("author", "")},
        "licence": licence.get("value", ""),
        "survey_reports_linked": len(published),
        "last_published_at": max(published.values(), default=""),
        "catalogued": bool(getattr(project, "egeria_asset_guid", "")),
        "asset_guid": getattr(project, "egeria_asset_guid", "") or "",
    }

    return {
        "slug": slug,
        "display_name": project.display_name,
        "technology_type": "Git Repository",
        "disposition": disposition,
        "in_population": disposition in CURATE_POPULATION,
        "population": list(CURATE_POPULATION),
        "last_surveyed_at": getattr(project, "last_surveyed_at", "") or "",
        "what_it_is": what_it_is,
        "what_it_holds": holds,
        "made_of": made_of,
        "relates": relates,
        "writes": writes,
        "keeps_current": "Resource Explorer surveys, on the Automate schedule. No integration connector exists for this type.",
        "commits": Curations(registry).for_resource("repo", slug),
    }


# ── the record of the act ──────────────────────────────────────────────

def _ensure_schema(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resource_curation (
            id            TEXT PRIMARY KEY,
            entity_type   TEXT NOT NULL,
            entity_slug   TEXT NOT NULL,
            author        TEXT NOT NULL,
            requested_at  TEXT NOT NULL,
            selection     TEXT NOT NULL DEFAULT '{}',
            manifest      TEXT NOT NULL DEFAULT '{}',
            state         TEXT NOT NULL DEFAULT 'queued',
            steps         TEXT NOT NULL DEFAULT '[]',
            finished_at   TEXT NOT NULL DEFAULT '',
            activity_id   TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resource_curation_entity "
                 "ON resource_curation(entity_type, entity_slug, requested_at)")


@dataclass
class CurationStep:
    name: str
    state: str = "pending"        # pending | running | done | failed | skipped
    detail: str = ""
    at: str = ""


class Curations:
    """Append-only record of each Catalogue → press: who, when, what was
    selected, what the manifest said it would write, and how each step went.
    The commit is asynchronous and can fail elsewhere (the design's point),
    so the record is what the screen shows while it runs and after."""

    def __init__(self, registry: ProjectRegistry):
        self.registry = registry

    def _conn(self):
        return self.registry._conn()

    def create(self, entity_type: str, slug: str, *, author: str, selection: dict, manifest: dict,
               steps: list[str], activity_id: str = "") -> dict:
        if not author:
            raise ValueError("a curation needs an author")
        cid = uuid.uuid4().hex
        now = _now()
        rows = [CurationStep(s).__dict__ for s in steps]
        with self._conn() as conn:
            _ensure_schema(conn)
            conn.execute(
                "INSERT INTO resource_curation (id, entity_type, entity_slug, author, requested_at, selection, manifest, state, steps, activity_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
                (cid, entity_type, slug, author, now, json.dumps(selection), json.dumps(manifest), json.dumps(rows), activity_id))
        return self.get(cid)

    def get(self, cid: str) -> dict | None:
        with self._conn() as conn:
            _ensure_schema(conn)
            row = conn.execute("SELECT * FROM resource_curation WHERE id = ?", (cid,)).fetchone()
        return self._decode(row) if row else None

    def for_resource(self, entity_type: str, slug: str) -> list[dict]:
        with self._conn() as conn:
            _ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM resource_curation WHERE entity_type = ? AND entity_slug = ? ORDER BY requested_at DESC",
                (entity_type, slug)).fetchall()
        return [self._decode(r) for r in rows]

    def set_step(self, cid: str, name: str, state: str, detail: str = "") -> None:
        cur = self.get(cid)
        if not cur:
            return
        steps = cur["steps"]
        for s in steps:
            if s["name"] == name:
                s.update({"state": state, "detail": detail[:2000], "at": _now()})
        with self._conn() as conn:
            conn.execute("UPDATE resource_curation SET steps = ?, state = 'running' WHERE id = ?",
                         (json.dumps(steps), cid))

    def finish(self, cid: str) -> dict:
        cur = self.get(cid)
        states = {s["state"] for s in cur["steps"]}
        final = "failed" if "failed" in states else "done"
        with self._conn() as conn:
            conn.execute("UPDATE resource_curation SET state = ?, finished_at = ? WHERE id = ?",
                         (final, _now(), cid))
        return self.get(cid)

    @staticmethod
    def _decode(row) -> dict:
        d = dict(row) if not isinstance(row, dict) else dict(row)
        for k in ("selection", "manifest", "steps"):
            try:
                d[k] = json.loads(d.get(k) or ("[]" if k == "steps" else "{}"))
            except ValueError:
                d[k] = [] if k == "steps" else {}
        return d
