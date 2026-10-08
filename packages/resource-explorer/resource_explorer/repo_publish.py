"""Egeria on a repository: publish the survey report whole, read it back, forget the cached links,
catalog selected file types (parity slice G1, PI-001..PI-006).

**Publish publishes the survey the person decided on (brief section 1, owner 2026-10-07).** The report is
the latest completed survey already in the registry (`surveyors/survey_snapshot.py`), never the result of
a survey run by the press. Re-surveying is its own act (`resurvey`), never a side effect of a publish.
`report_published` records the `surveyed_at` of the survey it published and whether the report already
existed (`reused`), in the row's own `detail`: no schema change.

Every state word derives from a PROOF ROW, never from the branch the code took (PR #514 rules).
The rows live in `catalogue_commit_proofs` (no new table): `node_kind = "repo_report"` for the
survey report and the links, `node_kind = "file_type"` for a file type's DataSet. A success row is
written ONLY by GUID and ONLY after a read of that GUID; the full sentence Egeria gave is stored in
the row's `detail`, and the screen shows its first sentence with the rest one gesture away.

* `P_REPORT` (`report_published`)       the report GUID was READ BACK from the asset's reports.
* `P_SENT` (`report_sent`)              the create returned a GUID but the read did not show it yet.
* `P_READ_FAILED` (`read_failed`)       Egeria refused, or the read failed; the sentence is stored.
* `P_FORGOTTEN` (`links_forgotten`)     RE dropped its cached GUIDs and survey history. A LOCAL act:
                                        nothing is sent to Egeria, nothing is archived or deleted there.
* `P_FILE_TYPE` (`file_type_read_back`) a file type's DataSet GUID was read back by that GUID.

The ISSUE-117 block is untouched: nothing in this module archives or deletes in Egeria.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Callable

from resource_explorer.catalogue_commit import (
    P_EGERIA_RESET, P_READ_FAILED, P_REPORT, PROJECT_UNANSWERED, PROJECT_UNBOUND, PROJECT_UNBOUND_WORDS,
    RESET_WORDS, egeria_first_sentence)
from resource_explorer.surveyors import survey_snapshot
from resource_explorer.surveyors.survey_snapshot import NO_SURVEY_SENTENCE

NODE_REPORT = "repo_report"
NODE_FILE_TYPE = "file_type"
NODE_SUB_RESOURCE = "sub_resource"
P_SENT = "report_sent"
P_FORGOTTEN = "links_forgotten"
P_FILE_TYPE = "file_type_read_back"
P_SUB_RESOURCE = "sub_resource_read_back"

#: The sentence a first press shows when nothing answers "which Egeria project?" (brief PI-006).
NO_PROJECT_SENTENCE = ("no Egeria project context · bind this investigation to a project, "
                       "or publish without one")
#: What the confirmation says survives (brief PI-005), roll-forward language, never "reset Egeria".
FORGET_SENTENCE = ("Egeria is unchanged; Resource Explorer forgets its cached GUIDs and survey history "
                   "for this resource and re-reads them on the next publish.")

_running: set[str] = set()
_running_lock = threading.Lock()


class AlreadyRunning(RuntimeError):
    """A publish for this resource is already in flight (a second press is ignored, not queued)."""


def _now() -> str:
    return datetime.utcnow().isoformat()


def _repo_proofs(registry, slug: str, node_kind: str = NODE_REPORT) -> list[dict]:
    return [p for p in registry.list_catalogue_commit_proofs(slug) if p["node_kind"] == node_kind]


# ── project context (PI-006) ─────────────────────────────────────────────────

def resolve_project_context(registry, slug: str) -> dict | None:
    """The resource's Egeria project context, or None when nothing answers.

    An `unset` row (and no row) is not an answer. When the resource is in scope of an investigation
    bound to an Egeria project, that binding IS the answer and is WRITTEN, with the investigation that
    supplied it (the same rule `POST /api/egeria/{slug}/publish` has always applied)."""
    context = registry.get_project_context("repo", slug)
    if context and context.get("status") not in PROJECT_UNANSWERED:
        return context
    inherited = registry.inherited_egeria_project_context("repo", slug)
    if not inherited:
        return None
    registry.set_project_context(
        "repo", slug, status="linked",
        egeria_project_guid=inherited["egeria_project_guid"],
        egeria_project_qualified_name=inherited["egeria_project_qualified_name"],
        free_text_name=f"inherited from investigation '{inherited['_inherited_from_name']}'")
    return registry.get_project_context("repo", slug)


def project_words(context: dict | None) -> dict:
    """What the row says about the project: a short word and the name, from the stored context."""
    if not context or context.get("status") in (None, "", "unset"):
        return {"status": "unset", "word": "no project", "name": ""}
    status = context["status"]
    qn = context.get("egeria_project_qualified_name") or ""
    free = context.get("free_text_name") or ""
    if status == "linked":
        return {"status": status, "word": "project", "name": qn.split("::")[0] or qn or "linked",
                "detail": free}
    if status == PROJECT_UNBOUND:
        # The status is the value `unbound`; the words are display text. The name it had stays visible.
        return {"status": status, "word": PROJECT_UNBOUND_WORDS, "name": qn.split("::")[0] or qn}
    if status == "deferred":
        return {"status": status, "word": "project (named, not linked)", "name": free}
    if status == "personal":
        return {"status": status, "word": "personal exploration", "name": ""}
    return {"status": status, "word": "no project (chosen)", "name": ""}


# ── the state, from proof rows only (PI-002) ─────────────────────────────────

def _report_row(last: dict | None) -> dict:
    if last is None:
        return {"word": "none", "read_at": "", "sentence": "", "first": "", "report_guid": ""}
    kind, d = last["proof"], last.get("detail") or {}
    if kind == P_REPORT:
        return {"word": "published", "read_at": last["read_at"], "report_guid": last["element_guid"],
                "reused": bool(d.get("reused")), "annotation_count": d.get("annotation_count"),
                "sentence": "", "first": "", "surveyed_at": d.get("surveyed_at", "")}
    if kind == P_SENT:
        return {"word": "sent", "read_at": last["read_at"], "report_guid": last["element_guid"],
                "sentence": d.get("note", ""), "first": d.get("note", ""), "surveyed_at": d.get("surveyed_at", "")}
    if kind == P_READ_FAILED:
        full = d.get("error", "")
        first, rest = egeria_first_sentence(full)
        return {"word": "not published", "read_at": last["read_at"], "report_guid": last["element_guid"],
                "sentence": full, "first": first, "rest": rest}
    if kind == P_EGERIA_RESET:
        return {"word": "reset", "read_at": last["read_at"], "report_guid": "", "sentence": RESET_WORDS,
                "first": RESET_WORDS, "reset": d.get("text", "")}
    if kind == P_FORGOTTEN:
        return {"word": "forgotten", "read_at": last["read_at"], "report_guid": "", "sentence": FORGET_SENTENCE,
                "first": "links forgotten", "forgot": d}
    return {"word": "none", "read_at": "", "sentence": "", "first": "", "report_guid": ""}


def stale_step_keys(registry, slug: str, snapshot=None) -> list[str]:
    """The steps of the kept survey that are older than their refresh rule (the same freshness rule
    `workflows.analysis.assess_freshness` applies everywhere, via the commit's own stale-step
    computation). Named, not auto-run: a person chooses whether to re-survey. A repository with no
    run history has nothing the rule can judge, so nothing is called stale."""
    from resource_explorer.workflows.curate_commit import _resurvey_plan

    snap = snapshot or survey_snapshot.latest(registry, slug)
    if snap is None:
        return []
    steps, _note = _resurvey_plan(registry, slug)
    return sorted(k for k in (steps or []) if k in snap.steps)


def survey_state(registry, slug: str, now=None) -> dict:
    """What a publish would send: the kept survey, its age, its size, and how much of it is stale.
    RE's own records only; nothing here contacts Egeria and nothing here surveys."""
    snap = survey_snapshot.latest(registry, slug)
    if snap is None:
        return {"exists": False, "sentence": NO_SURVEY_SENTENCE}
    stale = stale_step_keys(registry, slug, snap)
    return {"exists": True, "surveyed_at": snap.surveyed_at, "age_seconds": snap.age_seconds(now),
            "annotations": snap.annotation_count, "steps": snap.step_count,
            "stale_steps": len(stale), "stale": stale}


def project_state(registry, slug: str) -> dict:
    """What the Egeria project answer is right now, WITHOUT writing it (a publish writes an inherited
    answer; a read must not). `status` "unset" means nothing answers and a press would be refused."""
    context = registry.get_project_context("repo", slug)
    inherited = None
    if not context or context.get("status") in PROJECT_UNANSWERED:
        inherited = registry.inherited_egeria_project_context("repo", slug)
    # An unbound context with nothing inheriting is shown as itself (its words), not as "no project".
    answered = context and (context.get("status") not in PROJECT_UNANSWERED or
                            (context.get("status") == PROJECT_UNBOUND and not inherited))
    return project_words(context) if answered else (
        {"status": "inherited", "word": "project", "name": (inherited["egeria_project_qualified_name"].split("::")[0]
                                                             or inherited["egeria_project_qualified_name"]),
         "detail": f"from investigation '{inherited['_inherited_from_name']}'"} if inherited
        else project_words(None))


def publish_state(registry, slug: str) -> dict:
    """One read of RE's own records. Nothing here contacts Egeria."""
    asset_guid = registry.get_egeria_asset_guid(slug) or ""
    proofs = [p for p in _repo_proofs(registry, slug)
              if p["proof"] in (P_REPORT, P_SENT, P_READ_FAILED, P_FORGOTTEN, P_EGERIA_RESET)]
    # The newest fact by time (read_at), not by row id: the reset marker is written after the fact, but it
    # carries the reset time, so a publish made after the reset still wins over it.
    proofs.sort(key=lambda p: (p["read_at"] or "", p["id"]))
    last = proofs[-1] if proofs else None
    proofs = [p for p in proofs if p["proof"] != P_EGERIA_RESET]
    project = project_state(registry, slug)
    return {"slug": slug, "in_egeria": bool(asset_guid), "asset_guid": asset_guid,
            "row": _report_row(last), "project": project,
            "survey": survey_state(registry, slug),
            "can_publish_again": any(p["proof"] in (P_REPORT, P_SENT) for p in proofs)}


# ── publish whole (PI-001) ───────────────────────────────────────────────────

def publish_report(registry, slug: str, author: str, *, without_project: bool = False) -> dict:
    """Publish the kept survey whole, read the report back by its GUID, then write the proof row.

    **Never runs a survey** (brief section 1). With no kept survey it returns `{"gate": "no_survey"}`
    (the route maps it to 409) and nothing is sent; the first survey is never run implicitly.

    Returns `{"gate": "context_required"}` (the route maps it to 428) when no project answer exists
    and the press did not choose "without one". Zones are NEVER a per-press choice: the publisher's
    own zone rule (RE's draft zone; the CONFIGURED publish zones only, on promotion) applies. A 409
    on the report's name reuses the report already in Egeria (the publisher does that), recorded as
    such."""
    if without_project:
        registry.set_project_context("repo", slug, status="declined")
    context = resolve_project_context(registry, slug)
    if context is None:
        return {"gate": "context_required", "sentence": NO_PROJECT_SENTENCE}
    snapshot = survey_snapshot.latest(registry, slug)
    if snapshot is None:
        return {"gate": "no_survey", "sentence": NO_SURVEY_SENTENCE}

    with _running_lock:
        if slug in _running:
            raise AlreadyRunning(f"a publish for {slug} is already running")
        _running.add(slug)
    try:
        out = publish_snapshot(registry, slug, author, context, snapshot)
        return {"ok": out["ok"], "stage": out.get("stage", ""), "report_guid": out.get("report_guid", ""),
                "reused": out.get("reused", False), **publish_state(registry, slug)}
    finally:
        with _running_lock:
            _running.discard(slug)


def _proof(registry, slug: str, proof: str, **kw) -> int:
    return registry.append_catalogue_commit_proof(slug, proof=proof, node_kind=kw.pop("node_kind", NODE_REPORT), **kw)


def resurvey(registry, slug: str, author: str, steps: list[str] | None = None) -> dict:
    """Run the survey and NOTHING else (brief section 1): no publish, no Egeria write. `steps` names
    the steps to run (the stale ones); `None` runs them all. The orchestrator keeps what completed as
    the repository's latest survey, and the returned state shows the new age."""
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    key = f"survey:{slug}"
    with _running_lock:
        if key in _running:
            raise AlreadyRunning(f"a survey for {slug} is already running")
        _running.add(key)
    try:
        result = SurveyOrchestrator(registry=registry).run(slug, steps=steps)
    finally:
        with _running_lock:
            _running.discard(key)
    errors = list(result.errors) + ([result.snapshot_error] if result.snapshot_error else [])
    return {"ok": not errors, "errors": errors, "survey": survey_state(registry, slug), "by": author}


def publish_snapshot(registry, slug: str, author: str, context: dict, snapshot) -> dict:
    """Send one kept survey to Egeria and record what happened. The one publish both the band's
    "Publish to Egeria" and the Curate commit use, so the two cannot disagree about the proof row.

    Returns `{ok, stage, report_guid, reused, surveyed_at, annotation_count, asset_guid}`."""
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher

    project = project_words(context)
    registered = registry.get(slug)
    result = survey_snapshot.to_result(registered, snapshot)
    # Runtime dependencies a person CONFIRMED travel as annotations only (brief section 3): Egeria's
    # planned "deployed by" relationship types are not available, and nothing here writes a relationship.
    from resource_explorer import dependency_table
    for annotation in dependency_table.runtime_annotations(registry, slug):
        result.add(annotation)
    surveyed_at = snapshot.surveyed_at
    publisher = EgeriaPublisher(registry=registry)           # zones: the publisher's own rule only
    try:
        report_guid = publisher.publish(result)
    except Exception as exc:
        _proof(registry, slug, P_READ_FAILED, recorded_by=author,
               detail={"error": str(exc), "stage": "publish", "surveyed_at": surveyed_at, "project": project})
        return {"ok": False, "stage": "publish", "error": str(exc), "surveyed_at": surveyed_at}

    asset_guid = registry.get_egeria_asset_guid(slug) or ""
    reused = bool(getattr(publisher, "report_reused", False))
    common = {"surveyed_at": surveyed_at, "annotation_count": len(result.annotations),
              "steps": snapshot.step_count, "reused": reused, "project": project}
    # The proof is written AFTER a read of the report's own GUID: the asset's reports as Egeria answers them.
    read: list[dict] | None
    try:
        read = publisher.get_survey_reports_by_guid(asset_guid) if asset_guid else []
    except Exception as exc:
        read = None
        read_error = str(exc)
    if read is None:
        _proof(registry, slug, P_SENT, element_guid=report_guid or "", target_guid=asset_guid, recorded_by=author,
               detail={**common, "note": f"waiting for Egeria · the report could not be read back: {read_error}"[:400]})
    else:
        match = next((r for r in read if r.get("guid") == report_guid), None) if report_guid else None
        if match is not None:
            _proof(registry, slug, P_REPORT, element_guid=report_guid, target_guid=asset_guid,
                   qualified_name=match.get("qualified_name", ""), recorded_by=author,
                   detail={**common, "annotations_in_egeria": match.get("annotation_count")})
        else:
            _proof(registry, slug, P_SENT, element_guid=report_guid or "", target_guid=asset_guid, recorded_by=author,
                   detail={**common, "note": "sent · waiting for Egeria: the report is not in the asset's reports yet"})
    return {"ok": True, "stage": "", "report_guid": report_guid, "reused": reused, "surveyed_at": surveyed_at,
            "annotation_count": len(result.annotations), "asset_guid": asset_guid,
            "read_back": read is not None and match_found(read, report_guid)}


def match_found(read: list[dict], report_guid: str) -> bool:
    """Whether the report's own GUID is among the asset's reports as Egeria answered them."""
    return bool(report_guid) and any(r.get("guid") == report_guid for r in read)


# ── the commit's sub-resources: a proof row per element, by GUID, after a read (brief section 2) ──

def record_sub_resource_proofs(registry, slug: str, curation_id: str, author: str, wanted: dict,
                               selected: list[str], guids: dict, reader) -> dict:
    """One proof row for every sub-resource the commit sent (the chosen ones AND the ancestor folders a
    NestedFile needs), written ONLY by GUID and ONLY after a read of that GUID.

    `wanted` is `{locator: kind}`; `selected` the locators the person chose (the rest are containers
    added so a file has its folder); `guids` what the publisher returned; `reader(guid)` reads one
    element back (a dict) or returns None when Egeria did not show it yet.

    * P_SUB_RESOURCE  the GUID was read back.
    * P_SENT          Egeria returned a GUID but the read did not show the element yet.
    * P_READ_FAILED   no GUID came back, or the read failed; the full sentence is stored.

    Returns the counts the table shows (`read_back`, `sent`, `failed`), which are these rows' counts,
    never the request's."""
    counts = {"read_back": 0, "sent": 0, "failed": 0}
    for locator in sorted(wanted):
        kind = wanted[locator]
        role = "chosen" if locator in selected else "container"
        base = {"kind": kind, "role": role, "curation_id": curation_id}
        guid = guids.get(locator, "")
        if not guid:
            _proof(registry, slug, P_READ_FAILED, node_kind=NODE_SUB_RESOURCE, table_name=locator,
                   curation_id=curation_id, recorded_by=author,
                   detail={**base, "error": "Egeria returned no GUID for this element: it was not created"})
            counts["failed"] += 1
            continue
        try:
            seen = reader(guid)
        except Exception as exc:
            _proof(registry, slug, P_READ_FAILED, node_kind=NODE_SUB_RESOURCE, table_name=locator,
                   element_guid=guid, curation_id=curation_id, recorded_by=author,
                   detail={**base, "error": str(exc)})
            counts["failed"] += 1
            continue
        if seen:
            _proof(registry, slug, P_SUB_RESOURCE, node_kind=NODE_SUB_RESOURCE, table_name=locator,
                   element_guid=guid, curation_id=curation_id, recorded_by=author, detail=base)
            counts["read_back"] += 1
        else:
            _proof(registry, slug, P_SENT, node_kind=NODE_SUB_RESOURCE, table_name=locator,
                   element_guid=guid, curation_id=curation_id, recorded_by=author,
                   detail={**base, "note": "sent · waiting for Egeria: the element was not shown yet"})
            counts["sent"] += 1
    return counts


def commit_proof_summary(registry, slug: str, curation: dict) -> dict:
    """The state column of the commit table, from PROOF ROWS only (brief section 2): what Egeria was
    shown to hold after the press, with the counts the rows have (never the request's counts).

    `report`        the newest report proof at or after the press: published / sent / not published;
    `sub_resources` counts by proof for this curation: read back / sent / failed, split chosen vs
                    container, with the first failure's first sentence;
    `file_types`    the file types cataloged so far (read back), from their own proof rows."""
    requested = curation.get("requested_at") or ""
    proofs = registry.list_catalogue_commit_proofs(slug)
    out: dict = {"report": {"state": "none"}, "sub_resources": {"read_back": 0, "sent": 0, "failed": 0,
                 "chosen_read_back": 0, "container_read_back": 0, "first_failure": "",
                 # the same counts per row of the table: the files you chose, the folders you chose, the containers
                 "by_row": {k: {"read_back": 0, "sent": 0, "failed": 0, "first_failure": ""}
                            for k in ("files", "folders", "containers")}},
                 "file_types": {"read_back": 0}}
    reports = [p for p in proofs if p["node_kind"] == NODE_REPORT and p["proof"] in (P_REPORT, P_SENT, P_READ_FAILED)
               and (p["read_at"] or "") >= requested[:19]]
    if reports:
        last, d = reports[-1], reports[-1].get("detail") or {}
        if last["proof"] == P_REPORT:
            out["report"] = {"state": "published", "read_at": last["read_at"], "surveyed_at": d.get("surveyed_at", ""),
                             "annotation_count": d.get("annotation_count"), "reused": bool(d.get("reused")),
                             "guid": last["element_guid"]}
        elif last["proof"] == P_SENT:
            out["report"] = {"state": "sent", "read_at": last["read_at"], "surveyed_at": d.get("surveyed_at", ""),
                             "guid": last["element_guid"]}
        else:
            first, rest = egeria_first_sentence(d.get("error", ""))
            out["report"] = {"state": "not published", "read_at": last["read_at"], "first": first, "rest": rest}
    for p in proofs:
        if p["node_kind"] == NODE_SUB_RESOURCE and p.get("curation_id") == curation.get("id"):
            d = p.get("detail") or {}
            row = out["sub_resources"]["by_row"]["containers" if d.get("role") == "container"
                                                  else "files" if d.get("kind") == "file" else "folders"]
            row[{P_SUB_RESOURCE: "read_back", P_SENT: "sent", P_READ_FAILED: "failed"}.get(p["proof"], "sent")] += 1
            if p["proof"] == P_READ_FAILED and not row["first_failure"]:
                row["first_failure"] = egeria_first_sentence(d.get("error", ""))[0]
            if p["proof"] == P_SUB_RESOURCE:
                out["sub_resources"]["read_back"] += 1
                out["sub_resources"]["chosen_read_back" if d.get("role") == "chosen" else "container_read_back"] += 1
            elif p["proof"] == P_SENT:
                out["sub_resources"]["sent"] += 1
            elif p["proof"] == P_READ_FAILED:
                out["sub_resources"]["failed"] += 1
                if not out["sub_resources"]["first_failure"]:
                    out["sub_resources"]["first_failure"] = egeria_first_sentence(d.get("error", ""))[0]
        elif p["node_kind"] == NODE_FILE_TYPE and p["proof"] == P_FILE_TYPE:
            out["file_types"]["read_back"] += 1
    return out


# ── forget the cached links (PI-005) ─────────────────────────────────────────

def forget_links(registry, slug: str, author: str) -> dict:
    """Clear RE's cached asset GUID and survey history for ONE resource, in RE's registry only.

    Never sends anything to Egeria, never archives or deletes there. The act is recorded as a row so
    the screen can say it happened and who did it; the next publish re-reads the GUID from Egeria."""
    before = registry.get_egeria_asset_guid(slug) or ""
    cleared = registry.clear_egeria_registration(slug)
    _proof(registry, slug, P_FORGOTTEN, element_guid=before, recorded_by=author,
           detail={"asset_guid_cleared": cleared["asset_guid_cleared"],
                   "surveys_deleted": cleared["surveys_deleted"],
                   "published_types_deleted": cleared.get("published_types_deleted", 0),
                   "egeria_unchanged": True})
    return {"ok": True, "sentence": FORGET_SENTENCE, "forgot_asset_guid": before, **cleared,
            **publish_state(registry, slug)}


# ── file types: a measurement, not a press (ruling 2026-10-07) ───────────────

#: The one sentence the retired routes answer (HTTP 410). From DESIGN-FILE-TYPES-AS-ANNOTATIONS.md.
FILE_TYPES_RETIRED_SENTENCE = ("file types are published as profile annotations in the survey report; "
                               "files are cataloged by selection on Curate")

#: What an earlier DataSet reads as. They stay in Egeria; nothing here deletes or archives one.
RETIRED_DATASET_WORD = "retired mechanism · kept in Egeria"


def file_type_measurements(registry, project, slug: str) -> dict:
    """READ ONLY. What the survey report carries for file types, and the DataSets earlier presses made.

    `profiles`  the annotations a publish sends (Egeria's names verbatim), counted from the stored
                inventory: the same function the survey step uses, so screen and report agree.
    `retired`   one row per DataSet an earlier press created and read back, each marked
                "retired mechanism · kept in Egeria". Nothing here calls Egeria."""
    from resource_explorer.surveyors.file_type_profile import build_file_type_annotations

    summary = registry.file_inventory_summary(slug)
    anns = build_file_type_annotations(registry, slug, surveyed_at=summary.get("indexed_at") or "")
    profiles = [{"name": a.annotation_type_name, "type": a.annotation_type.value, "summary": a.summary,
                 "counts": dict(getattr(a, "value_count", None) or getattr(a, "resource_properties", {}))}
                for a in anns]
    retired = []
    for p in _repo_proofs(registry, slug, NODE_FILE_TYPE):
        if p["proof"] == P_FILE_TYPE:
            retired.append({"label": p["table_name"], "dataset_guid": p["element_guid"],
                            "qualified_name": p["qualified_name"], "word": RETIRED_DATASET_WORD,
                            "read_at": p["read_at"]})
    return {"slug": slug, "in_egeria": bool(registry.get_egeria_asset_guid(slug)),
            "inventoried": bool(summary.get("total")), "profiles": profiles, "retired": retired,
            "retired_word": RETIRED_DATASET_WORD}
