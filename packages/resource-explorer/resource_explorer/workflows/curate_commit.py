"""Catalogue →: the commit behind the Curate screen, run asynchronously.

The design's three consequences of Curate being a handoff rather than a
state change inside RE: the commit is asynchronous and can fail elsewhere;
"running · N targets" is read, not known; after Curate RE is not the
source of truth. So the commit is a queued run, each step writes its
outcome to the curation record as it lands, and the screen shows the
record. Nothing here raises past a step: a step that fails is a failed
step on the record, and the next step runs unless it depends on it.

Steps, in order:
  publish_asset     survey + publish, the existing publish path -- creates
                    or finds the SourceControlLibrary asset and links a
                    SurveyReport (measurements LINKED, not copied)
  classifications   enrichment judgements COPIED onto the asset as
                    Confidentiality / Criticality / Retention, with the
                    author as steward and the date in the notes -- they
                    exist nowhere else
  sub_resources     the worthy sub-resources the person confirmed, as
                    FileFolder/DataFile assets under the repo's
  components        skipped here: accepted components materialize when
                    they are accepted (workflows/curate.py); the record
                    says so rather than pretending to have done it
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from resource_explorer.curate_plan import CONFIDENTIALITY_LEVELS, CRITICALITY_LEVELS, Curations
from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)

STEPS = ("publish_asset", "classifications", "sub_resources", "components")


def _classification_bodies(enrichment: dict) -> list[tuple[str, str, dict]]:
    """(step-method name, human name, body) for each judgement that maps to a
    governance classification. A value outside the level map is not
    dropped -- it goes into `notes` with level 0, because testimony is
    copied, not normalised away."""
    out = []
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def common(f):
        return {"steward": f.get("author", "") or "", "stewardTypeName": "UserIdentity",
                "stewardPropertyName": "userId", "source": "resource-explorer enrichment",
                "confidence": 100,
                "notes": f"{f.get('value','')} — set by {f.get('author','?')} on {(f.get('set_at') or '')[:10]}"
                         f"{' · interim' if f.get('interim') else ''}; copied to the catalogue {stamp}"}

    f = enrichment.get("sensitivity") or {}
    if f.get("value"):
        out.append(("set_confidentiality_classification", f"Confidentiality · {f['value']}", {
            "class": "NewClassificationRequestBody",
            "properties": {"class": "ConfidentialityProperties",
                           "confidentialityLevel": CONFIDENTIALITY_LEVELS.get(str(f["value"]).lower(), 0),
                           "statusIdentifier": 0, **common(f)}}))
    f = enrichment.get("criticality") or {}
    if f.get("value"):
        out.append(("set_criticality_classification", f"Criticality · {f['value']}", {
            "class": "NewClassificationRequestBody",
            "properties": {"class": "CriticalityProperties",
                           "criticalityLevel": CRITICALITY_LEVELS.get(str(f["value"]).lower(), 0),
                           "statusIdentifier": 0, **common(f)}}))
    f = enrichment.get("retention") or {}
    if f.get("value"):
        out.append(("set_retention_classification", f"Retention · {f['value']}", {
            "class": "NewClassificationRequestBody",
            "properties": {"class": "RetentionClassificationProperties",
                           "retentionBasis": str(f["value"]), "status": "ACTIVE", **common(f)}}))
    return out


def execute_curation(registry: ProjectRegistry, curation_id: str) -> dict:
    cur = Curations(registry)
    rec = cur.get(curation_id)
    if not rec:
        raise KeyError(curation_id)
    slug = rec["entity_slug"]
    sel = rec.get("selection") or {}
    project = registry.get(slug)
    if not project:
        cur.set_step(curation_id, "publish_asset", "failed", "resource no longer registered")
        return cur.finish(curation_id)

    # ── 1. the asset and its survey report ─────────────────────────────
    asset_guid = ""
    cur.set_step(curation_id, "publish_asset", "running",
                 "surveying first, then publishing — minutes on a large repository; the existing publish path")
    try:
        context = registry.get_project_context("repo", slug)
        if not context or context.get("status") == "unset":
            inherited = registry.inherited_egeria_project_context("repo", slug)
            if not inherited:
                raise RuntimeError("no Egeria Project context — decide it on the Scouting pane (or bind the investigation) and press Catalogue again")
            registry.set_project_context(
                "repo", slug, status="linked",
                egeria_project_guid=inherited["egeria_project_guid"],
                egeria_project_qualified_name=inherited["egeria_project_qualified_name"],
                free_text_name=f"inherited from investigation '{inherited['_inherited_from_name']}'")
        from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator
        survey = SurveyOrchestrator(registry=registry).run(slug, steps=None)
        import asyncio
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        try:
            report_guid = EgeriaPublisher(registry=registry).publish(survey)
        finally:
            loop.close(); asyncio.set_event_loop(None)
        asset_guid = registry.get_egeria_asset_guid(slug) or ""
        cur.set_step(curation_id, "publish_asset", "done",
                     f"asset {asset_guid or '?'} · survey report {report_guid} · {len(survey.annotations)} annotations linked")
    except Exception as exc:
        log.warning("curation %s: publish failed for %s: %s", curation_id, slug, exc)
        cur.set_step(curation_id, "publish_asset", "failed", f"{type(exc).__name__}: {exc}")
        asset_guid = registry.get_egeria_asset_guid(slug) or ""

    # ── 2. testimony, copied ───────────────────────────────────────────
    ctx = registry.get_context("repo", slug) or {}
    bodies = _classification_bodies(ctx.get("enrichment") or {})
    if not bodies:
        cur.set_step(curation_id, "classifications", "skipped", "no sensitivity, criticality or retention set on the Enrichment pane")
    elif not asset_guid:
        cur.set_step(curation_id, "classifications", "failed", "no asset to classify — the publish step did not produce one")
    else:
        cur.set_step(curation_id, "classifications", "running")
        from resource_explorer.egeria_identity import classification_client
        done, failed = [], []
        try:
            client = classification_client()
            for method, name, body in bodies:
                try:
                    getattr(client, method)(asset_guid, body)
                    done.append(name)
                except Exception as exc:
                    failed.append(f"{name}: {type(exc).__name__}: {exc}"[:200])
        except Exception as exc:
            failed.append(f"no classification client: {exc}"[:200])
        cur.set_step(curation_id, "classifications", "failed" if failed else "done",
                     " · ".join(done + failed))

    # ── 3. what it holds ───────────────────────────────────────────────
    locators = list(sel.get("sub_resources") or [])
    if not locators:
        cur.set_step(curation_id, "sub_resources", "skipped", "none selected")
    elif not asset_guid:
        cur.set_step(curation_id, "sub_resources", "failed", "no parent asset — the publish step did not produce one")
    else:
        cur.set_step(curation_id, "sub_resources", "running")
        try:
            from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
            # Local cataloguing first: publish_sub_resources publishes only
            # rows already in the local sub_resources table, and NestedFile
            # needs every ancestor folder catalogued too -- the same two
            # rules the catalog route (routes/projects.py) enforces.
            from resource_explorer.surveyors.sub_surveyors import ancestor_folder_paths
            import json as _json
            kinds: dict[str, str] = {}
            for f in registry.query_findings(slug, "repo_sub_resource_survey"):
                try:
                    kinds[f["check_name"]] = (_json.loads(f.get("detail_json") or "{}").get("kind") or "folder")
                except ValueError:
                    kinds[f["check_name"]] = "folder"
            want: dict[str, str] = {loc: kinds.get(loc, "folder") for loc in locators}
            for loc, kind in list(want.items()):
                if kind == "file":
                    for anc in ancestor_folder_paths(loc):
                        want.setdefault(anc, "folder")
            for loc in sorted(want):
                registry.catalog_sub_resource("repo", slug, loc, want[loc], source_finding="repo_sub_resource_survey")
            guids = EgeriaPublisher(registry=registry).publish_sub_resources(slug, project.github_url, asset_guid, sorted(want))
            missing = [l for l in locators if l not in guids]
            ancestors = len(want) - len(locators)
            # Count against what was SELECTED; the ancestor folders NestedFile
            # needs are named separately ("32 of 31" on the first live press).
            cur.set_step(curation_id, "sub_resources", "failed" if missing else "done",
                         f"{len(locators) - len(missing)} of {len(locators)} published"
                         + (f" · plus {ancestors} ancestor folder{'s' if ancestors != 1 else ''}" if ancestors else "")
                         + (f" · not published: {', '.join(missing[:8])}" if missing else ""))
        except Exception as exc:
            cur.set_step(curation_id, "sub_resources", "failed", f"{type(exc).__name__}: {exc}")

    # ── 4. what it is made of ──────────────────────────────────────────
    cur.set_step(curation_id, "components", "skipped",
                 "accepted components materialize at the moment they are accepted (Architecture verdicts); nothing to do at commit")
    return cur.finish(curation_id)
