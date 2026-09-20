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
                    or finds the repository's own Asset and links a
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

**Decision (project owner, 2026-09-20):** pressing Catalogue used to run
`SurveyOrchestrator(...).run(slug, steps=None)` unconditionally -- every
sub-surveyor, every time, regardless of whether fresh data already sat in
Egeria. The project owner's framing: "it shouldn't have to execute all of
the surveys anyway -- it's likely that the surveys that the user is
interested in have already been published to Egeria? And why would we
execute and run surveys that the user isn't interested in?"

`publish_asset` now reuses the freshness gate `assess_freshness()`
(`workflows/analysis.py`) already applies elsewhere (Assessment/Analysis
cards, the scheduler) instead of introducing a second one: it reads
`registry.get_analysis_last_run("repo", slug)` for this repo's run
history and re-surveys only the analyses that are BOTH (a) something
someone has actually run before and (b) currently stale by
`RunsConfig.freshness_seconds`.

Two things follow from "someone has actually run before":

* An analysis with NO run history at all is excluded from the re-survey
  list even though it would trivially count as "stale" (there is no
  last-run timestamp for it to be fresh against). Catalogue must not be
  the thing that runs an analysis for the very first time -- that is
  running a survey nobody asked for, exactly the complaint above. A
  first-ever press of Catalogue, with no history for anything at all, is
  different (see below): there is nothing yet to be selective ABOUT, so
  that one case still runs a full survey once.
* A step whose last run was recorded as `error` still counts as "having
  run history" (it is a key in `get_analysis_last_run`'s result), so it
  stays eligible for re-running -- `assess_freshness` already treats an
  error run as not-fresh, so it gets re-run. Refusing to retry a step
  that failed last time is not a behaviour anyone wants.

Most of the time the re-survey list comes back short or empty:
`workflows/analysis.py`'s auto-publish already pushes an individual
analysis's results to Egeria the moment it runs, for any repo with
`has_assigned_egeria_project("repo", slug)` -- which is Catalogue's own
precondition a few lines below. So by the time a curator reaches
Catalogue, most analyses that ever ran have typically already been
published; freshness is what's left to decide. The one edge case that
assumption doesn't cover -- an analysis ran before the Egeria project was
ever assigned to this repo, so its data is fresh but was never actually
published -- is handled explicitly: if nothing is stale but this repo has
no cached Egeria asset guid yet, the survey still runs (with an empty
`steps=[]`, since nothing needs re-computing) purely so
`EgeriaPublisher.publish()` can find-or-create the asset; that call is
idempotent (`_find_or_create_asset`), so making it defensively is cheaper
than trying to prove up front that it is unnecessary.
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


def _resurvey_plan(registry: ProjectRegistry, slug: str) -> tuple[list[str] | None, str]:
    """What `publish_asset` should re-survey for `slug`, and why.

    Returns (steps, note):

    steps
      * ``None``       — no run history at all for this repo; run a full
        survey (``steps=None``), same as this call always did before this
        freshness gate existed. There is nothing to be selective about on
        a genuinely first catalogue.
      * ``[]``         — every previously-run analysis is still fresh.
        Nothing needs re-computing; the caller decides separately whether
        the asset itself still needs to be created (see
        ``execute_curation`` below).
      * ``[key, ...]`` — the ``re_analysis_step`` keys (translated from
        stale ``analysis_id``s via ``REPO_ANALYSIS_SOURCE_STEPS``, the same
        vocabulary ``SurveyOrchestrator.run(steps=...)`` expects) to re-run.
        Deliberately ``REPO_ANALYSIS_SOURCE_STEPS`` and not
        ``REPO_ANALYSIS_STEP_MAP`` -- the latter is the ownership
        *partition* (used for run attribution) and resolves a
        derives-from analysis that owns no steps of its own, such as
        ``architecture_diagram``, to an empty list; that would silently
        never re-run the steps that actually refresh it. See
        ``test_run_publish_honesty.py``'s
        ``TestOwnershipMapIsOnlyUsedForAttribution``, which pins this
        distinction and would fail if this module read the ownership map
        directly.

    Only analyses with run history are ever candidates — an analysis
    nobody has ever run is excluded outright, never treated as "stale",
    so Catalogue can't be the thing that runs it for the first time. An
    analysis whose last run errored still has run history (it is a key
    in ``get_analysis_last_run``'s result) and is therefore still a
    candidate; ``assess_freshness`` itself already treats an error run as
    not-fresh, so it comes back stale and is re-run.
    """
    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_SOURCE_STEPS
    from resource_explorer.workflows.analysis import assess_freshness

    history = registry.get_analysis_last_run("repo", slug)
    if not history:
        return None, "no run history for this repo yet — running a full survey for the first catalogue"

    stale_ids, fresh_ids = [], []
    for analysis_id in sorted(history):
        # A reserved bookkeeping key, not a real analysis_id -- see
        # get_analysis_last_run()'s own comment on "__unattributed_surveys__".
        if analysis_id.startswith("__") and analysis_id.endswith("__"):
            continue
        freshness = assess_freshness(registry, "repo", slug, analysis_id)
        (fresh_ids if freshness.fresh else stale_ids).append(analysis_id)

    step_keys = sorted({key for aid in stale_ids for key in REPO_ANALYSIS_SOURCE_STEPS.get(aid, [])})

    plural = "is" if len(history) == 1 else "es"
    if stale_ids:
        note = (f"{len(fresh_ids)} of {len(history)} previously-run analys{plural} already fresh "
                f"and skipped; re-surveying {len(stale_ids)} stale one(s)")
    else:
        note = f"all {len(history)} previously-run analys{plural} already fresh — nothing to re-survey"
    return step_keys, note


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
                 "checking which analyses are already fresh before publishing — see module docstring")
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

        steps, note = _resurvey_plan(registry, slug)
        existing_guid = registry.get_egeria_asset_guid(slug) or ""

        if steps is not None and not steps and existing_guid:
            # Nothing stale to re-survey, and the asset already exists in
            # Egeria — no reason to touch Egeria at all this time.
            asset_guid = existing_guid
            cur.set_step(curation_id, "publish_asset", "done",
                         f"{note}; asset {asset_guid} already published — nothing re-published")
        else:
            # Either something is stale (steps is a non-empty list),
            # nothing has ever run for this repo (steps is None — full
            # survey), or everything is fresh but this repo has no cached
            # asset yet (steps == [] with no existing_guid — an empty
            # survey purely so publish() can find-or-create the asset).
            survey = SurveyOrchestrator(registry=registry).run(slug, steps=steps)
            import asyncio
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            try:
                report_guid = EgeriaPublisher(registry=registry).publish(survey)
            finally:
                loop.close(); asyncio.set_event_loop(None)
            asset_guid = registry.get_egeria_asset_guid(slug) or ""
            cur.set_step(curation_id, "publish_asset", "done",
                         f"{note} · asset {asset_guid or '?'} · survey report {report_guid} · "
                         f"{len(survey.annotations)} annotations linked")
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
