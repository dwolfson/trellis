"""Launching an Egeria-native survey from RE, and reading it back.

Design brief: `BRIEF-NATIVE-EGERIA-SURVEY-LAUNCH.md` (the
authoritative source for the slice and its six-point gate). Implementation
notes: `NATIVE-EGERIA-SURVEY-LAUNCH-IMPLEMENTED.md`.

What this is: a *direct* pyegeria submission of the survey Egeria's own survey
action engine already knows for a resource's technology type
(`configdata/technology_type_processes.yaml`, kind `survey_existing`), followed
by a persisted, read-only read-back of what Egeria says happened. **Prefect is
not in this path** and nothing here touches `step_runs.flow_run_id` /
`dispatch_failed` -- the whole-definition Prefect run is a different mechanism
with its own columns.

The rule the whole module is built around: **every status word on a row is
derived from persisted proof, never from which branch ran.**
`derive_native_state` is the one function that turns rows into words, and it is
pure so a table test can walk every combination:

    submitted to Egeria   the engine-action GUID is stored on the step_runs row
    running               Egeria's own status, read back, with the read time
    complete              status COMPLETED *and* a stored report GUID *and* the
                          report's annotations stored, count matching the count
                          recorded when they were read
    <Egeria's word>       Egeria's own status word and message when it failed;
                          never "complete", never blank

Two facts about Egeria found live (2026-09-30, read-only) that shape this:

* **An engine action is linked to the report it produced by a
  `ReportOriginator` relationship** (EngineAction -> SurveyReport). The earlier
  timestamp attribution in `egeria_async_survey_result.py` -- and its note that
  "no direct EngineAction-to-report relationship was found" -- predates this.
  The report is found by that relationship, never by "newest after time T", so
  two overlapping runs cannot be confused.
* **A native survey is slow** (a 157-table database took ~14 minutes), so this
  never blocks: submit returns as soon as Egeria accepts, and the read-back is a
  separate, repeatable step driven by the UI's poll and by a sweep.

Identity: nothing here reads the caller from a ContextVar. `submitted_by` is
passed in by the route, and the sweep passes none. Anything run in a thread
must pass identity explicitly (reference: ContextVar identity in threads).
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Protocol

from resource_explorer.registry import NATIVE_SURVEY_STEP_PREFIX
from resource_explorer.surveyors.technology_type_processes import (
    KIND_CATALOG_AND_SURVEY,
    KIND_DELETE,
    KIND_SURVEY_EXISTING,
    NativeProcess,
    get_native_processes,
)

log = logging.getLogger(__name__)

# Egeria's ActivityStatus symbolic names (same sets `egeria_delegated_step`
# documents from GovernanceActionStatus.java's enum table). Imported rather than
# re-declared so there is one list of "still going" words.
from resource_explorer.surveyors.egeria_delegated_step import (  # noqa: E402
    _ACTIVE_STATUSES as ACTIVE_STATUSES,
    _SUCCESS_STATUSES as SUCCESS_STATUSES,
)

#: States (see `derive_native_state`). Kept as plain strings: they travel to the
#: frontend, which maps each to a glyph in `next/glyphs.js`.
NOT_RUN = "not_run"
SUBMIT_FAILED = "submit_failed"
SUBMITTED = "submitted"
RUNNING = "running"
AWAITING_REPORT = "awaiting_report"
REPORT_INCOMPLETE = "report_incomplete"
COMPLETE = "complete"
FAILED = "failed"
UNREADABLE = "unreadable"
CANNOT_RUN = "cannot_run"


class NativeSurveyError(RuntimeError):
    """A submission that did not produce an engine action."""


class NativeSurveyCannotRun(NativeSurveyError):
    """RE knows why this survey cannot be run for this resource. The message is
    what the row shows -- it is a reason, not an error."""


class NativeSurveyBusy(NativeSurveyError):
    """The same survey is already in flight on this resource."""


# ── the port: everything that talks to Egeria ────────────────────────────────


@dataclass(frozen=True)
class ActionRead:
    status: str
    message: str


@dataclass(frozen=True)
class ReportRead:
    guid: str
    at: str
    originator_guid: str
    annotations: list[dict]


class EgeriaSurveyPort(Protocol):
    """The whole Egeria surface this feature uses. Reads are read-only; the one
    write is `initiate`. Every method raises on a transport/API failure -- a
    failure must never be returned as an empty answer (find-absence-as-answer)."""

    def asset_exists(self, guid: str) -> bool: ...
    def initiate(self, process_qualified_name: str, action_target_name: str,
                 target_guid: str) -> str: ...
    def read_action(self, engine_action_guid: str) -> ActionRead: ...
    def report_guid_for_action(self, engine_action_guid: str) -> str | None: ...
    def read_report(self, report_guid: str) -> ReportRead: ...


def _iso(value: Any) -> str:
    """Egeria's timestamp (ISO string or epoch millis) as an ISO string; '' when
    it is neither. Not guessing: an unparseable value stays absent."""
    if value in (None, "") or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return ""
    return str(value)


class PyegeriaSurveyPort:
    """The real port. Clients are built lazily, once per instance, with the same
    env-driven connection RE's other Egeria writers use.

    **One event loop per instance, not per call.** pyegeria's sync wrappers call
    `asyncio.get_event_loop()`, which a worker thread does not have, so this
    gives the thread one -- the same shape the publish routes use. But a pyegeria
    client caches an HTTP client bound to the loop it first ran on, so a loop
    created and closed around each call makes the SECOND call on the same client
    fail with "Event loop is closed" (found live, 2026-09-30, the first time a
    real port made two calls). The loop therefore lives as long as the port and
    is closed by `close()` / leaving `port_session`. A port belongs to ONE
    thread; the routes build one per request and the sweep one per pass.
    Never use a port from a thread that already runs an event loop."""

    def __init__(self) -> None:
        self._curation = None
        self._expert = None
        self._assets = None
        self._loop = None

    def _enter(self) -> None:
        import asyncio

        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

    def close(self) -> None:
        import asyncio

        if self._loop is not None:
            self._loop.close()
            self._loop = None
            asyncio.set_event_loop(None)

    def _connection(self):
        from resource_explorer.rfa_egeria_sync import _egeria_connection_kwargs

        return _egeria_connection_kwargs()

    def _client(self, cls):
        view_server, platform_url, user_id, user_password = self._connection()
        client = cls(view_server, platform_url, user_id, user_password)
        client.create_egeria_bearer_token(user_id, user_password)
        return client

    def _get_curation(self):
        if self._curation is None:
            from pyegeria import AutomatedCuration
            self._curation = self._client(AutomatedCuration)
        return self._curation

    def _get_expert(self):
        if self._expert is None:
            from pyegeria import MetadataExpert
            self._expert = self._client(MetadataExpert)
        return self._expert

    def _get_assets(self):
        if self._assets is None:
            from pyegeria import AssetMaker
            self._assets = self._client(AssetMaker)
        return self._assets

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        from pyegeria.core._exceptions import PyegeriaNotFoundException

        return isinstance(exc, PyegeriaNotFoundException)

    def asset_exists(self, guid: str) -> bool:
        self._enter()
        try:
            self._get_expert().get_metadata_element_by_guid(guid)
        except Exception as exc:  # noqa: BLE001 -- classified below
            if self._is_not_found(exc):
                return False
            raise
        return True

    def initiate(self, process_qualified_name: str, action_target_name: str,
                 target_guid: str) -> str:
        self._enter()
        guid = self._get_curation().initiate_gov_action_type(
            action_type_qualified_name=process_qualified_name,
            request_source_guids=[],
            action_targets=[{
                "class": "NewActionTarget",
                "actionTargetName": action_target_name,
                "actionTargetGUID": target_guid.strip(),
            }],
        )
        if not guid or guid == "Action not initiated":
            raise NativeSurveyError(
                f"Egeria did not initiate {process_qualified_name!r} "
                f"(it answered {guid!r})")
        return guid

    def read_action(self, engine_action_guid: str) -> ActionRead:
        self._enter()
        element = self._get_expert().get_metadata_element_by_guid(engine_action_guid)
        props = ((element or {}).get("elementProperties") or {}).get("propertyValueMap") or {}
        status = (props.get("activityStatus") or {}).get("symbolicName") or ""
        if not status:
            # Not "UNKNOWN": a response with no status is a read that did not
            # establish one, and the caller records it as such.
            raise NativeSurveyError(
                "Egeria's engine-action element carried no activityStatus")
        message = (props.get("completionMessage") or {}).get("primitiveValue") or ""
        return ActionRead(status=status, message=message)

    def report_guid_for_action(self, engine_action_guid: str) -> str | None:
        self._enter()
        result = self._get_expert().get_related_metadata_elements(
            engine_action_guid, "ReportOriginator",
            body={"class": "GetRequestBody"}, starting_at_end=0)
        if not isinstance(result, dict):
            return None  # pyegeria's "No element found" string: no report yet
        guids = [
            (entry.get("element") or {}).get("elementGUID")
            for entry in result.get("elementList") or []
        ]
        guids = [g for g in guids if g]
        if not guids:
            return None
        if len(set(guids)) > 1:
            # A survey action produces one report. More than one is something
            # to look at, not something to pick from.
            raise NativeSurveyError(
                f"Egeria links {len(set(guids))} reports to engine action "
                f"{engine_action_guid} ({sorted(set(guids))}); not choosing one")
        return guids[0]

    def read_report(self, report_guid: str) -> ReportRead:
        from resource_explorer.surveyors.egeria_survey_reader import annotations_from_report

        self._enter()
        result = self._get_assets().get_asset_by_guid(
            report_guid,
            body={"class": "GetRequestBody", "graphQueryDepth": 1},
            output_format="JSON")
        if not isinstance(result, dict):
            raise NativeSurveyError(
                f"Egeria returned no SurveyReport element for {report_guid}")
        props = result.get("properties") or {}
        header_versions = (result.get("elementHeader") or {}).get("versions") or {}
        at = (_iso(props.get("completionTime")) or _iso(props.get("createdTime"))
              or _iso(header_versions.get("createTime")))
        originator = ((result.get("reportOriginator") or {}).get("relatedElement") or {}) \
            .get("elementHeader", {}).get("guid", "")
        annotations = []
        for raw in annotations_from_report(result):
            annotations.append({
                "guid": raw.get("guid", ""),
                "annotation_type": raw.get("annotation_type", ""),
                "analysis_step": raw.get("analysis_step", ""),
                "summary": raw.get("summary", ""),
                "explanation": raw.get("explanation", ""),
                "confidence": raw.get("confidence"),
                # Everything else the wire carried, verbatim: the measurement
                # payload is not RE's to summarise away.
                "detail": {k: v for k, v in raw.items() if k not in (
                    "guid", "annotation_type", "analysis_step", "summary",
                    "explanation", "confidence")},
            })
        return ReportRead(guid=report_guid, at=at, originator_guid=originator,
                          annotations=annotations)


@contextlib.contextmanager
def port_session(port):
    """Yield `port`, closing it (its event loop) afterwards when it has a
    `close`. The one way a real port should be used."""
    try:
        yield port
    finally:
        close = getattr(port, "close", None)
        if callable(close):
            close()


# ── the one place proof rows become words ───────────────────────────────────


def _now() -> str:
    """UTC, ISO, naive -- the registry's own timestamp spelling (the frontend's
    `whenMs` reads a naive stamp as UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def derive_native_state(run: dict | None, *, stored_annotation_count: int | None = None) -> dict:
    """The row's status, computed from persisted proof and nothing else.

    `run` is the newest `step_runs` row for (resource, process), or None.
    `stored_annotation_count` is how many of that report's annotations are
    actually in `native_survey_annotations` -- passed in (not read here) so this
    stays pure, and compared to the count recorded when the report was read so a
    lost row cannot leave a row saying "complete".

    Returns {state, egeria_status, message, submitted_at, read_at, report_at,
    report_guid, engine_action_guid, annotation_count, error}. `state` is what
    the frontend keys its glyph and wording on. Every field a state does not
    have proof for is left empty, never filled with a plausible default.
    """
    out = {
        "state": NOT_RUN, "egeria_status": "", "message": "", "submitted_at": "",
        "read_at": "", "report_at": "", "report_guid": "", "engine_action_guid": "",
        "annotation_count": None, "error": "",
    }
    if not run:
        return out

    guid = run.get("engine_action_guid") or ""
    out["submitted_at"] = run.get("surveyed_at") or ""
    if not guid:
        error = run.get("submit_error") or ""
        if error:
            out.update(state=SUBMIT_FAILED, error=error)
        # else: a row with neither a GUID nor a recorded failure proves
        # nothing, and stays "not run".
        return out

    status = run.get("engine_action_status") or ""
    read_error = run.get("engine_action_read_error") or ""
    out.update(
        engine_action_guid=guid, egeria_status=status,
        message=run.get("engine_action_message") or "",
        read_at=run.get("engine_action_read_at") or "",
        error=read_error,
    )

    if not status:
        out["state"] = UNREADABLE if read_error else SUBMITTED
        return out

    if status in ACTIVE_STATUSES:
        out["state"] = RUNNING
        return out

    if status in SUCCESS_STATUSES:
        report_guid = run.get("survey_report_guid") or ""
        recorded = run.get("report_annotation_count")
        out.update(report_guid=report_guid, report_at=run.get("survey_report_at") or "",
                   annotation_count=recorded)
        if not (report_guid and run.get("report_read_at") and recorded is not None):
            out["state"] = AWAITING_REPORT
        elif stored_annotation_count != recorded:
            out["state"] = REPORT_INCOMPLETE
        else:
            out["state"] = COMPLETE
        return out

    # Any other terminal word -- FAILED, INVALID, IGNORED, CANCELLED, ... -- is
    # shown as Egeria said it. An action that failed without saying why still
    # says so, rather than rendering a blank.
    out["state"] = FAILED
    if not out["message"]:
        out["message"] = "Egeria gave no message with this status"
    return out


# ── the rows a resource shows ───────────────────────────────────────────────

_NEEDS_CATALOGUING = (
    "Not cataloged in Egeria yet -- the survey acts on the resource's Egeria "
    "asset, and this resource has none. Publish it to Egeria first.")
_NEEDS_TEMPLATE = (
    "RE cannot run this one: it creates the catalog entry from a connection "
    "template (host, port, credentials) before surveying it, and RE does not "
    "collect those template properties. Use a survey that acts on an "
    "already-cataloged resource.")


def _resource_entity(registry, entity_type: str, slug: str):
    if entity_type == "database":
        return registry.get_database(slug)
    if entity_type == "filesystem":
        return registry.get_filesystem(slug)
    return None


def cannot_run_reason(process: NativeProcess, entity) -> str:
    """Why RE cannot run this process for this resource, or '' when it can.
    Kind-based and registry-only: no Egeria call, so it is safe on a list read."""
    if process.kind == KIND_CATALOG_AND_SURVEY:
        return _NEEDS_TEMPLATE
    if process.kind != KIND_SURVEY_EXISTING:
        return f"RE does not run processes of kind {process.kind!r}."
    if entity is None:
        return "This resource is not registered."
    if not (getattr(entity, "egeria_asset_guid", "") or "").strip():
        return _NEEDS_CATALOGUING
    return _missing_credentials_reason(entity)


NO_CREDENTIALS = "Egeria has no credentials for this database · re-project secrets"
UNCONFIRMED_CREDENTIALS = "can't confirm Egeria has credentials · secrets path not configured"

#: The three credential states -- exactly these, one word each.
PRESENT = "present"
ABSENT = "absent"
NOT_CONFIGURED = "not-configured"


def credentials_state(entity) -> str:
    """Whether the projected `.omsecrets` file holds this database's credentials.

    The survey engine reads them from that file by collection name. When it is
    gone (a redeploy reset the secrets directory on 2026-09-29) the JDBC
    connector has no user, falls back to the container's OS user, and every
    survey fails minutes later with `role "default" does not exist`.

    * `present` -- path configured and the collection is in the file.
    * `absent` -- path configured, but the file or the collection is missing:
      Run is refused with `NO_CREDENTIALS`.
    * `not-configured` -- `EGERIA_SECRETS_STORE_LOCAL_PATH` unset. RE has no
      host-visible path and has established nothing either way (CI, a remote
      engine host, secrets managed elsewhere), so Run stays available and the
      row says it cannot confirm (`UNCONFIRMED_CREDENTIALS`).

    Only a database has a PostgreSQL credential collection; anything else is
    reported `present` (nothing to check)."""
    if not hasattr(entity, "db_type"):
        return PRESENT
    from resource_explorer import omsecrets_store

    path = omsecrets_store.local_path()
    if not path:
        return NOT_CONFIGURED
    if omsecrets_store.has_collection(
            omsecrets_store.secrets_collection_name(entity.slug), path=path):
        return PRESENT
    return ABSENT


def _missing_credentials_reason(entity) -> str:
    return NO_CREDENTIALS if credentials_state(entity) == ABSENT else ""


def native_survey_rows(registry, entity_type: str, slug: str, technology_type: str) -> list[dict]:
    """One row per native survey process known for this resource's technology
    type: what it is, whether RE can run it (and if not, why), and the state
    derived from the newest persisted run. Registry-only -- no Egeria call --
    so it is cheap enough to ride on the survey pane's candidates read."""
    entity = _resource_entity(registry, entity_type, slug)
    rows = []
    for process in get_native_processes(entity_type, technology_type):
        if process.kind == KIND_DELETE:
            continue  # never offered, in any form
        reason = cannot_run_reason(process, entity)
        creds = credentials_state(entity) if process.kind == KIND_SURVEY_EXISTING else PRESENT
        runs = registry.list_native_survey_runs(entity_type, slug, process.qualified_name)
        latest = runs[0] if runs else None
        stored = None
        if latest and latest.get("survey_report_guid"):
            stored = registry.count_native_survey_annotations(latest["survey_report_guid"])
        derived = derive_native_state(latest, stored_annotation_count=stored)
        rows.append({
            "qualified_name": process.qualified_name,
            "display_name": process.display_name,
            "kind": process.kind,
            "description": process.description,
            "runnable": not reason,
            "cannot_run_reason": reason,
            "credentials": creds,
            "credentials_note": UNCONFIRMED_CREDENTIALS if creds == NOT_CONFIGURED else "",
            "in_flight": derived["state"] in (SUBMITTED, RUNNING, AWAITING_REPORT, UNREADABLE),
            "run": derived,
        })
    return rows


# ── submit and read back ────────────────────────────────────────────────────


def refresh_run(registry, port: EgeriaSurveyPort, run: dict, *, entity_type: str,
                slug: str) -> dict:
    """Read one engine action back from Egeria (read-only) and, once Egeria says
    it completed, read its report into RE. Persists exactly what it read, and
    the time it read it. Never raises: a failed read is recorded on the row as
    a failed read -- it does not become a status.

    Idempotent. Reading a completed action's report twice writes the report's
    annotations once (keyed on report + annotation GUID), so a second browser
    polling the same row cannot duplicate findings.
    """
    guid = run["engine_action_guid"]
    process_qn = (run.get("executor_ref")
                  or (run.get("step_key") or "")[len(NATIVE_SURVEY_STEP_PREFIX):])

    try:
        action = port.read_action(guid)
    except Exception as exc:  # noqa: BLE001 -- recorded, not raised
        registry.record_native_survey_readback(
            guid, read_at=_now(), error=_short_error(exc))
        return _refetch(registry, entity_type, slug, process_qn)
    registry.record_native_survey_readback(
        guid, read_at=_now(), status=action.status, message=action.message)

    if action.status in SUCCESS_STATUSES:
        _read_report_in(registry, port, run, action, entity_type=entity_type,
                        slug=slug, process_qn=process_qn)
    return _refetch(registry, entity_type, slug, process_qn)


def _read_report_in(registry, port, run, action, *, entity_type, slug, process_qn) -> None:
    guid = run["engine_action_guid"]
    recorded = run.get("report_annotation_count")
    have = run.get("survey_report_guid") or ""
    if have and run.get("report_read_at") and recorded is not None \
            and registry.count_native_survey_annotations(have) == recorded:
        return  # already read in and intact; nothing to do
    try:
        report_guid = have or port.report_guid_for_action(guid)
        if not report_guid:
            return  # Egeria has not linked a report yet -- stays "awaiting"
        report = port.read_report(report_guid)
        if report.originator_guid and report.originator_guid != guid:
            raise NativeSurveyError(
                f"report {report_guid} says it originated from "
                f"{report.originator_guid}, not from engine action {guid}")
        registry.record_native_survey_report(
            guid, entity_type=entity_type, slug=slug, process_qualified_name=process_qn,
            report_guid=report_guid, report_at=report.at, read_at=_now(),
            annotations=report.annotations)
    except Exception as exc:  # noqa: BLE001 -- recorded, not raised
        # Error-only: the action's own status/message, written a moment ago,
        # stay on the row beside the fact that the report could not be read.
        registry.record_native_survey_readback(
            guid, read_at=_now(), error="report read failed: " + _short_error(exc))


def _short_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return (text[:300] or type(exc).__name__)


def _refetch(registry, entity_type: str, slug: str, process_qn: str) -> dict:
    runs = registry.list_native_survey_runs(entity_type, slug, process_qn)
    latest = runs[0] if runs else None
    stored = None
    if latest and latest.get("survey_report_guid"):
        stored = registry.count_native_survey_annotations(latest["survey_report_guid"])
    return derive_native_state(latest, stored_annotation_count=stored)


def submit_native_survey(registry, port: EgeriaSurveyPort, entity_type: str, slug: str,
                         process_qualified_name: str, *, technology_type: str,
                         submitted_by: str = "") -> dict:
    """Submit one native survey and prove the dispatch by reading it back.

    Returns the derived row state. Raises `NativeSurveyCannotRun` (a reason RE
    knew before asking Egeria), `NativeSurveyBusy` (the same survey is already
    in flight -- a launch is not idempotent at Egeria, so a second click would
    make a second engine action), or `NativeSurveyError` (Egeria refused; the
    refusal is also persisted, so the row can say so).
    """
    entity = _resource_entity(registry, entity_type, slug)
    if entity is None:
        raise NativeSurveyCannotRun(f"{entity_type} {slug!r} is not registered")
    process = next((p for p in get_native_processes(entity_type, technology_type)
                    if p.qualified_name == process_qualified_name), None)
    if process is None or process.kind == KIND_DELETE:
        raise NativeSurveyCannotRun(
            f"{process_qualified_name!r} is not a survey RE offers for this resource")
    reason = cannot_run_reason(process, entity)
    if reason:
        raise NativeSurveyCannotRun(reason)

    runs = registry.list_native_survey_runs(entity_type, slug, process_qualified_name)
    if runs:
        latest = runs[0]
        stored = (registry.count_native_survey_annotations(latest["survey_report_guid"])
                  if latest.get("survey_report_guid") else None)
        if derive_native_state(latest, stored_annotation_count=stored)["state"] in (
                SUBMITTED, RUNNING, AWAITING_REPORT, UNREADABLE):
            raise NativeSurveyBusy(
                "This survey is already in flight on this resource "
                f"(engine action {latest['engine_action_guid']}).")

    asset_guid = entity.egeria_asset_guid.strip()
    try:
        exists = port.asset_exists(asset_guid)
    except Exception as exc:  # noqa: BLE001
        raise NativeSurveyError(
            f"Could not check the resource's Egeria asset first: {_short_error(exc)}") from exc
    if not exists:
        raise NativeSurveyCannotRun(
            f"Egeria has no asset with the GUID RE has stored for this resource "
            f"({asset_guid}); the catalog entry was removed or replaced. "
            "Publish the resource to Egeria again.")

    submitted_at = _now()
    try:
        engine_action_guid = port.initiate(
            process_qualified_name, process.action_target_name, asset_guid)
    except Exception as exc:  # noqa: BLE001
        error = _short_error(exc)
        registry.record_native_survey_submission(
            entity_type, slug, process_qualified_name, submitted_at,
            submit_error=error, submitted_by=submitted_by)
        raise NativeSurveyError(error) from exc

    registry.record_native_survey_submission(
        entity_type, slug, process_qualified_name, submitted_at,
        engine_action_guid=engine_action_guid, submitted_by=submitted_by)
    log.info("submitted native survey %s for %s/%s: engine action %s",
             process_qualified_name, entity_type, slug, engine_action_guid)

    # The dispatch is proven by reading the action back, read-only. If that one
    # read fails, the row says exactly that (submitted, last read failed) rather
    # than pretending the read happened.
    run = registry.list_native_survey_runs(entity_type, slug, process_qualified_name)[0]
    return refresh_run(registry, port, run, entity_type=entity_type, slug=slug)


_IN_FLIGHT = (SUBMITTED, RUNNING, AWAITING_REPORT, UNREADABLE, REPORT_INCOMPLETE)


def refresh_resource(registry, port: EgeriaSurveyPort, entity_type: str, slug: str) -> int:
    """Read back every in-flight native survey on one resource -- the polling
    target. A registry read only when nothing is in flight. Returns how many
    runs it read back."""
    n = 0
    for run in registry.list_native_survey_runs(entity_type, slug):
        if not run.get("engine_action_guid"):
            continue
        stored = (registry.count_native_survey_annotations(run["survey_report_guid"])
                  if run.get("survey_report_guid") else None)
        if derive_native_state(run, stored_annotation_count=stored)["state"] in _IN_FLIGHT:
            refresh_run(registry, port, run, entity_type=entity_type, slug=slug)
            n += 1
    return n


def sweep_in_flight(registry, port: EgeriaSurveyPort) -> int:
    """Read back every in-flight native survey on every resource, so a survey
    still completes -- and its report still lands in RE -- when nobody has the
    page open. Identity-free by construction: it reads Egeria and writes the
    proof rows of runs somebody else submitted, on nobody's behalf. Returns how
    many runs it read back."""
    n = 0
    for run in registry.list_in_flight_native_survey_runs():
        stored = (registry.count_native_survey_annotations(run["survey_report_guid"])
                  if run.get("survey_report_guid") else None)
        if derive_native_state(run, stored_annotation_count=stored)["state"] not in _IN_FLIGHT:
            continue
        refresh_run(registry, port, run, entity_type=run.get("entity_type") or "database",
                    slug=run["slug"])
        n += 1
    return n
