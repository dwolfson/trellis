"""Egeria on a repository: publish the survey report whole, read it back, forget the cached links,
catalog selected file types (parity slice G1, PI-001..PI-006).

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

from resource_explorer.catalogue_commit import P_READ_FAILED, P_REPORT, egeria_first_sentence

NODE_REPORT = "repo_report"
NODE_FILE_TYPE = "file_type"
P_SENT = "report_sent"
P_FORGOTTEN = "links_forgotten"
P_FILE_TYPE = "file_type_read_back"

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
    if context and context.get("status") != "unset":
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
    if kind == P_FORGOTTEN:
        return {"word": "forgotten", "read_at": last["read_at"], "report_guid": "", "sentence": FORGET_SENTENCE,
                "first": "links forgotten", "forgot": d}
    return {"word": "none", "read_at": "", "sentence": "", "first": "", "report_guid": ""}


def publish_state(registry, slug: str) -> dict:
    """One read of RE's own records. Nothing here contacts Egeria."""
    asset_guid = registry.get_egeria_asset_guid(slug) or ""
    proofs = [p for p in _repo_proofs(registry, slug) if p["proof"] in (P_REPORT, P_SENT, P_READ_FAILED, P_FORGOTTEN)]
    last = proofs[-1] if proofs else None
    context = registry.get_project_context("repo", slug)
    inherited = None
    if not context or context.get("status") == "unset":
        inherited = registry.inherited_egeria_project_context("repo", slug)
    project = project_words(context) if (context and context.get("status") != "unset") else (
        {"status": "inherited", "word": "project", "name": (inherited["egeria_project_qualified_name"].split("::")[0]
                                                             or inherited["egeria_project_qualified_name"]),
         "detail": f"from investigation '{inherited['_inherited_from_name']}'"} if inherited
        else project_words(None))
    return {"slug": slug, "in_egeria": bool(asset_guid), "asset_guid": asset_guid,
            "row": _report_row(last), "project": project,
            "can_publish_again": any(p["proof"] in (P_REPORT, P_SENT) for p in proofs)}


# ── publish whole (PI-001) ───────────────────────────────────────────────────

def publish_report(registry, slug: str, author: str, *, without_project: bool = False) -> dict:
    """Survey whole, publish whole, read the report back by its GUID, then write the proof row.

    Returns `{"gate": "context_required"}` (the route maps it to 428) when no project answer exists
    and the press did not choose "without one". Zones are NEVER a per-press choice: the publisher's
    own zone rule (RE's draft zone; `EXPLORER_PUBLISH_ZONES` on promotion) applies. A 409 on the
    report's name reuses the report already in Egeria (the publisher does that), recorded as such."""
    if without_project:
        registry.set_project_context("repo", slug, status="declined")
    context = resolve_project_context(registry, slug)
    if context is None:
        return {"gate": "context_required", "sentence": NO_PROJECT_SENTENCE}

    with _running_lock:
        if slug in _running:
            raise AlreadyRunning(f"a publish for {slug} is already running")
        _running.add(slug)
    try:
        return _publish_report_locked(registry, slug, author, context)
    finally:
        with _running_lock:
            _running.discard(slug)


def _proof(registry, slug: str, proof: str, **kw) -> int:
    return registry.append_catalogue_commit_proof(slug, proof=proof, node_kind=kw.pop("node_kind", NODE_REPORT), **kw)


def _publish_report_locked(registry, slug: str, author: str, context: dict) -> dict:
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    project = project_words(context)
    try:
        result = SurveyOrchestrator(registry=registry).run(slug, steps=None)
    except Exception as exc:
        _proof(registry, slug, P_READ_FAILED, recorded_by=author,
               detail={"error": f"Survey failed: {exc}", "stage": "survey", "project": project})
        return {"ok": False, "stage": "survey", **publish_state(registry, slug)}

    surveyed_at = result.surveyed_at.isoformat()
    publisher = EgeriaPublisher(registry=registry)           # zones: the publisher's own rule only
    try:
        report_guid = publisher.publish(result)
    except Exception as exc:
        _proof(registry, slug, P_READ_FAILED, recorded_by=author,
               detail={"error": str(exc), "stage": "publish", "surveyed_at": surveyed_at, "project": project})
        return {"ok": False, "stage": "publish", **publish_state(registry, slug)}

    asset_guid = registry.get_egeria_asset_guid(slug) or ""
    reused = bool(getattr(publisher, "report_reused", False))
    common = {"surveyed_at": surveyed_at, "annotation_count": len(result.annotations),
              "reused": reused, "project": project}
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
    return {"ok": True, "report_guid": report_guid, "reused": reused, **publish_state(registry, slug)}


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


# ── catalog selected file types (PI-004) ─────────────────────────────────────

class FileTypeGateway:
    """What the file-type commit needs from Egeria. The real one drives pyegeria's AssetMaker; tests
    substitute a fake with the same four methods."""

    def __init__(self, registry=None):
        import os
        self._registry = registry
        self._env = (os.getenv("EGERIA_VIEW_SERVER", "qs-view-server"),
                     os.getenv("EGERIA_PLATFORM_URL", "https://localhost:9443"),
                     os.getenv("EGERIA_USER", "erinoverview"),
                     os.getenv("EGERIA_USER_PASSWORD", "secret"))
        self._am = None

    def _maker(self):
        if self._am is None:
            from pyegeria import AssetMaker
            view_server, url, user, pwd = self._env
            self._am = AssetMaker(view_server, url, user, pwd)
            self._am.create_egeria_bearer_token(user, pwd)
        return self._am

    def find(self, qualified_name: str) -> str:
        from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
        pub = EgeriaPublisher(registry=self._registry)
        pub._connect()
        return pub._find_element_guid(qualified_name)

    def create(self, body: dict) -> str:
        return self._maker().create_asset(body=body)

    def read(self, guid: str) -> dict | None:
        out = self._maker().get_asset_by_guid(guid, output_format="JSON")
        return out if isinstance(out, dict) else None

    def link(self, asset_guid: str, dataset_guid: str, label: str) -> None:
        self._maker().add_capability_asset_use(
            software_capability_guid=asset_guid, asset_guid=dataset_guid,
            body={"class": "NewRelationshipRequestBody",
                  "properties": {"class": "CapabilityAssetUseProperties", "useType": "GOVERNS",
                                 "description": f"{label} files managed by this repository"}})


def file_type_qualified_name(slug: str, label: str) -> str:
    return f"DataSet::{slug}::{label}"


def _file_type_body(project, slug: str, label: str, count: int, extensions: list[str]) -> dict:
    return {"class": "NewElementRequestBody",
            "properties": {
                "class": "DataSetProperties", "typeName": "DataSet",
                "qualifiedName": file_type_qualified_name(slug, label),
                "displayName": f"{label} — {project.display_name}",
                "description": (f"{count} {label} file(s) in {project.github_url}. "
                                + (f"Extensions: {', '.join(extensions)}." if extensions else "")),
                "additionalProperties": {"project_slug": slug, "file_type_label": label,
                                         "file_count": str(count), "extensions": ", ".join(extensions),
                                         "github_url": project.github_url}}}


def file_types_preview(registry, project, slug: str) -> dict:
    """What a commit WOULD create, from RE's own survey rows. Nothing is sent. A type already
    cataloged by an earlier commit (a proof row) is marked, so the press never adds a second one."""
    import json as _json
    done = {}
    for p in _repo_proofs(registry, slug, NODE_FILE_TYPE):
        if p["proof"] == P_FILE_TYPE:
            done[p["table_name"]] = p
    rows = []
    for r in registry.query_file_type_counts(slug):
        label = r["type_label"]
        exts: list[str] = []
        if r.get("details_json"):
            try:
                d = _json.loads(r["details_json"])
                exts = sorted(d) if isinstance(d, dict) else list(d)
            except Exception:
                exts = []
        rows.append({"label": label, "file_count": r["file_count"], "extensions": exts,
                     "qualified_name": file_type_qualified_name(slug, label),
                     "cataloged": label in done, "dataset_guid": done[label]["element_guid"] if label in done else "",
                     "linked": bool(done[label]["detail"].get("linked")) if label in done else False})
    asset = registry.get_egeria_asset_guid(slug) or ""
    return {"slug": slug, "asset_guid": asset, "in_egeria": bool(asset), "types": rows,
            "blocker": "" if asset else "publish the report first: the repository is not in Egeria yet"}


def file_types_commit(registry, project, slug: str, elements: list[dict], author: str,
                      gateway: FileTypeGateway | Any) -> dict:
    """Catalog the chosen file types as DataSets. Each one: look the name up (adopt, never a second
    element), create when missing, READ the GUID back, and only then write the success row. The link
    to the repository asset is a separate step with its own row: a link that fails leaves the DataSet
    created and says so, with Egeria's full sentence stored."""
    asset = registry.get_egeria_asset_guid(slug) or ""
    if not asset:
        raise ValueError("the repository is not in Egeria yet: publish the report first")
    out = []
    for e in elements:
        label = e["label"]
        qn = file_type_qualified_name(slug, label)
        item = {"label": label, "qualified_name": qn, "guid": "", "state": "failed", "words": ""}
        try:
            guid = gateway.find(qn)
            adopted = bool(guid)
            if not guid:
                guid = gateway.create(_file_type_body(project, slug, label, int(e.get("file_count") or 0),
                                                      list(e.get("extensions") or [])))
            seen = gateway.read(guid)
            if not seen:
                raise RuntimeError(f"Egeria did not return the element {guid} when it was read back")
        except Exception as exc:
            full = str(exc)
            _proof(registry, slug, P_READ_FAILED, node_kind=NODE_FILE_TYPE, table_name=label, qualified_name=qn,
                   recorded_by=author, detail={"error": full, "what": f"file type {label}"})
            first, rest = egeria_first_sentence(full)
            item.update(words=f"not cataloged · {first}", details=rest)
            out.append(item)
            continue
        linked, link_error = True, ""
        try:
            gateway.link(asset, guid, label)
        except Exception as exc:
            linked, link_error = False, str(exc)
        _proof(registry, slug, P_FILE_TYPE, node_kind=NODE_FILE_TYPE, table_name=label, element_guid=guid,
               target_guid=asset, qualified_name=qn, recorded_by=author,
               detail={"adopted": adopted, "linked": linked, "link_error": link_error,
                       "file_count": e.get("file_count")})
        if linked:
            item.update(state="cataloged", guid=guid, words="cataloged · read back")
        else:
            first, rest = egeria_first_sentence(link_error)
            item.update(state="cataloged_unlinked", guid=guid,
                        words=f"cataloged, not linked to the repository · {first}", details=rest)
        out.append(item)
    return {"ok": all(i["state"] != "failed" for i in out), "items": out}
