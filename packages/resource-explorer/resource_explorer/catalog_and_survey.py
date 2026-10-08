"""Registering a database server with Egeria, so Egeria's own surveys can run on it.

OPTIONAL BY DESIGN. RE reaches a database itself; Egeria may not be able to
(Egeria connects from its own platform). Nothing here is required for RE's own
surveys, curation or anything else, nothing nags, and a database that was never
registered shows a NEUTRAL state, not an error. The one thing here that writes
to Egeria is a person's press of "Register the server with Egeria".

What the press does (every write is followed by a read of what it wrote, and a
pointer / proof row is stored only AFTER that read):

1. **The server element.** Looked up by its exact qualifiedName
   (`PostgreSQL Server::<host:port>`, the name Egeria's template derives). If it
   exists it is ADOPTED -- never a second server for the next database on the
   same host:port. If not, it is created from Egeria's own "PostgreSQL Server"
   catalog template (`POSTGRES_SERVER_TEMPLATE`, GUID below, the template step 1
   of `PostgreSQLServer:CreateAndSurvey...` uses). Read back BY GUID, qualifiedName
   compared, then the server pointer is stored (registry `settings`, no DDL).
2. **Egeria's server survey** (`PostgreSQLSurvey::survey-postgres-server`) is
   submitted on that server through the native-survey machinery (poll, read the
   engine action, read the report). It reports the databases it found as
   annotations; it does NOT create database elements ("the databases are not
   catalogued at this time", `PostgresServerSurveyActionService`).
3. **The database element.** Looked up by qualifiedName
   (`PostgreSQL Relational Database::<host:port>::<database>`); adopted if present
   (read back by GUID, `egeria_asset_guid` stored). If absent, Egeria's own
   `PostgreSQLDatabase:CreateAndSurveyGovernanceActionProcess` is submitted with
   the template placeholders mapped from RE's stored record. The database is read
   back by qualifiedName and then by GUID before `egeria_asset_guid` is written;
   the survey engine action the process started is found from the database's own
   ActionTarget relationship and recorded under the ordinary "Survey PostgreSQL
   Database" row, so that row shows it through the existing read-back.

Credentials never travel in a request. The templates' connection names a secrets
COLLECTION and a store path; Egeria's engine host reads the user and password from
the `.omsecrets` file at survey time. RE's existing projection
(`omsecrets_reproject`, `omsecrets_store`) writes that file from the registry; this
module only checks the collection is there and asks the projection to fill it when
it is not. The server element's connection uses the same collection as the database
it was registered from (`<slug>::PostgreSQL Secret`).

Which kinds have a separate server element at all is one tested function,
`technology_type_processes.server_has_separate_element`. A kind the config does not
cover says "this kind is not wired yet".
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from resource_explorer import native_survey_run as nsr
from resource_explorer.catalogue_gateway import (
    GatewayError, PyegeriaCatalogueGateway, Relationship, database_qualified_name,
    parse_element_answer, server_name_for, server_qualified_name)
from resource_explorer.surveyors.technology_type_processes import (
    KIND_CATALOG_AND_SURVEY, KIND_SURVEY_EXISTING, NativeProcess, get_native_processes,
    get_wiring, server_has_separate_element)

log = logging.getLogger(__name__)

#: Egeria's own template for the server element (`PostgreSQLTemplateType.POSTGRES_SERVER_TEMPLATE`,
#: egeria checkout, postgres-server-connectors). A constant from the source, like the schema template's.
SERVER_TEMPLATE_GUID = "542134e6-b9ce-4dce-8aef-22e8daf34fdb"
DATABASE_SURVEY_QN = "PostgreSQLSurvey::survey-postgres-database"
#: The `requestType` of the engine action the database survey runs as.
DATABASE_SURVEY_REQUEST_TYPE = "survey-postgres-database"
VERSION_NOT_RECORDED = "not recorded"
#: A completed process whose database is still unreadable is "in flight" this long, then it is a stall.
AWAITING_REGISTRATION_WINDOW = timedelta(minutes=15)

# ── states (the catalog row's own; the survey rows keep native_survey_run's) ──
NOT_REGISTERED = "not_registered"
REGISTERED = "registered"
AWAITING_REGISTRATION = "awaiting_registration"

# ── wording ──
NOT_REGISTERED_WORDS = ("Egeria has not been given this database · register it to run Egeria's "
                        "own survey · optional")
SERVER_NOT_REGISTERED_WORDS = ("Egeria has not been given this database's server · register it "
                               "first · optional")
STALE_WORDS = "the Egeria asset RE had stored no longer exists"
REACH_NOTE = "Egeria connects from its own platform; RE can still survey this database itself"
REGISTER_LABEL = "Register the server with Egeria →"
SINGLE_STEP_NOT_BUILT = ("the server and the database are one thing for this kind, and registering them "
                         "in one step is not built yet")


def not_wired_words(technology_type: str) -> str:
    return f"this kind is not wired yet ({technology_type or 'no technology type'})"


# ── what is missing from the stored record, said exactly ───────────────────

def record_missing(entity) -> list[str]:
    """What the stored record lacks for Egeria to be given the database. Names the field."""
    missing = []
    if not (getattr(entity, "host", "") or "").strip():
        missing.append("the host")
    port = getattr(entity, "port", 0)
    if not isinstance(port, int) or isinstance(port, bool) or port <= 0:
        missing.append("the port")
    if not (getattr(entity, "database_name", "") or "").strip():
        missing.append("the database name")
    if not (getattr(entity, "db_user", "") or "").strip():
        missing.append("the database user")
    return missing


def unusable_record_reason(entity) -> str:
    missing = record_missing(entity)
    if not missing:
        return ""
    return "RE's stored record for this database has no " + ", no ".join(m.replace("the ", "") for m in missing) \
        + ", which Egeria's template needs"


def wiring_reason(entity_type: str, technology_type: str, entity) -> str:
    """Why RE cannot register this resource with Egeria, '' when it can. Registry-only: no Egeria call."""
    if entity is None:
        return "This resource is not registered."
    sep = server_has_separate_element(entity_type, technology_type)
    if sep is None:
        return not_wired_words(technology_type)
    if sep is False:
        return SINGLE_STEP_NOT_BUILT
    return unusable_record_reason(entity)


# ── names and the placeholders ──────────────────────────────────────────────

def secrets_collection_for(entity) -> str:
    from resource_explorer import omsecrets_store
    return omsecrets_store.secrets_collection_name(entity.slug)


def _store_path_name() -> str:
    from resource_explorer.config import get_config
    return get_config().egeria.secrets_store_path_name


def server_placeholders(entity) -> dict[str, str]:
    """The placeholders Egeria's server template takes (`getPostgresServerPlaceholderPropertyTypes`):
    hostIdentifier, portNumber, serverName, description, versionIdentifier, resourceName,
    secretsStorePathName, secretsCollectionName. No password: the connection reads the collection."""
    name = server_name_for(entity)
    return {
        "hostIdentifier": getattr(entity, "egeria_host", "") or entity.host,
        "portNumber": str(entity.port),
        "serverName": name,
        "description": f"PostgreSQL server at {name}",
        "versionIdentifier": VERSION_NOT_RECORDED,
        "resourceName": name,
        "secretsStorePathName": _store_path_name(),
        "secretsCollectionName": secrets_collection_for(entity),
    }


def database_placeholders(entity) -> dict[str, str]:
    """The placeholders Egeria's database template / the CreateAndSurvey process take
    (`getPostgresDatabasePlaceholderPropertyTypes`): hostIdentifier, portNumber, serverName,
    versionIdentifier, databaseName, databaseDescription, secretsStorePathName, secretsCollectionName."""
    return {
        "hostIdentifier": getattr(entity, "egeria_host", "") or entity.host,
        "portNumber": str(entity.port),
        "serverName": server_name_for(entity),
        "versionIdentifier": VERSION_NOT_RECORDED,
        "databaseName": entity.database_name,
        "databaseDescription": entity.description or f"PostgreSQL database {entity.database_name}",
        "secretsStorePathName": _store_path_name(),
        "secretsCollectionName": secrets_collection_for(entity),
    }


def server_pointer_key(server_name: str) -> str:
    return "egeria_server_guid::" + server_qualified_name(server_name)


def server_pointer(registry, entity) -> str:
    """The server element's GUID RE stored after reading it back ('' when it never has)."""
    return (registry.get_setting(server_pointer_key(server_name_for(entity)), "") or "").strip()


def _process_for(entity_type: str, technology_type: str, kind: str) -> NativeProcess | None:
    return next((p for p in get_native_processes(entity_type, technology_type) if p.kind == kind), None)


def server_survey_process(entity_type: str, technology_type: str) -> NativeProcess | None:
    st = get_wiring(entity_type, technology_type).server_technology_type
    if not st:
        return None
    return next((p for p in get_native_processes(entity_type, st)
                 if p.kind == KIND_SURVEY_EXISTING and p.target == "server"), None)


# ── the port ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ElementBack:
    guid: str
    qualified_name: str


class RegistrationPort(nsr.EgeriaSurveyPort, Protocol):
    """The Egeria surface the registration adds to the survey port. Reads raise on a
    transport failure; `None` means Egeria answered that there is no such element."""

    def find_element(self, qualified_name: str) -> ElementBack | None: ...
    def read_element(self, guid: str) -> ElementBack | None: ...
    def create_server(self, placeholders: dict[str, str]) -> str: ...
    def initiate_process(self, process_qualified_name: str, request_parameters: dict[str, str]) -> str: ...
    def read_process(self, process_instance_guid: str) -> nsr.ActionRead: ...
    def survey_actions_for(self, database_guid: str) -> list[str]: ...


class PyegeriaRegistrationPort(nsr.PyegeriaSurveyPort):
    """The real port. Reads of elements and relationships go through the catalogue
    gateway's parsers (live-verified shapes); the two writes are `create_server`
    (Egeria's template) and `initiate_process`."""

    def __init__(self) -> None:
        super().__init__()
        self._gateway = None

    def _gw(self) -> PyegeriaCatalogueGateway:
        if self._gateway is None:
            view_server, platform_url, user_id, user_password = self._connection()
            self._gateway = PyegeriaCatalogueGateway(
                view_server=view_server, platform_url=platform_url, user_id=user_id,
                user_password=user_password)
        return self._gateway

    def find_element(self, qualified_name: str) -> ElementBack | None:
        self._enter()
        el = self._gw().read_element(qualified_name)
        return ElementBack(el.guid, el.qualified_name) if el else None

    def read_element(self, guid: str) -> ElementBack | None:
        self._enter()
        try:
            res = self._get_expert().get_metadata_element_by_guid(guid)
        except Exception as exc:  # noqa: BLE001 -- classified
            if self._is_not_found(exc):
                return None
            raise
        el = parse_element_answer(res)
        return ElementBack(el.guid, el.qualified_name) if el else None

    def create_server(self, placeholders: dict[str, str]) -> str:
        self._enter()
        body = {
            "class": "TemplateRequestBody",
            "templateGUID": SERVER_TEMPLATE_GUID,
            "isOwnAnchor": True,
            "deepCopy": True,
            "placeholderPropertyValues": dict(placeholders),
        }
        guid = self._get_curation().create_elem_from_template(body)
        if not isinstance(guid, str) or not guid.strip():
            raise nsr.NativeSurveyError(f"Egeria's template create answered {guid!r}, not a GUID")
        return guid.strip()

    def initiate_process(self, process_qualified_name: str, request_parameters: dict[str, str]) -> str:
        self._enter()
        guid = self._get_curation().initiate_gov_action_process(
            action_type_qualified_name=process_qualified_name,
            request_parameters=dict(request_parameters))
        if not guid or guid == "Action not initiated":
            raise nsr.NativeSurveyError(
                f"Egeria did not initiate {process_qualified_name!r} (it answered {guid!r})")
        return guid

    def read_process(self, process_instance_guid: str) -> nsr.ActionRead:
        """The process instance's own activityStatus when it carries one; otherwise its FIRST engine
        action's (found by the ActionRequester relationship, as Egeria's own FVT finds it). UNVERIFIED
        LIVE which of the two a build populates; neither is guessed -- no status is an error."""
        self._enter()
        try:
            return self.read_action(process_instance_guid)
        except nsr.NativeSurveyError:
            pass
        result = self._get_expert().get_related_metadata_elements(
            process_instance_guid, "ActionRequester",
            body={"class": "GetRequestBody"}, starting_at_end=1)
        guids = [(e.get("element") or {}).get("elementGUID")
                 for e in (result.get("elementList") or [])] if isinstance(result, dict) else []
        guids = [g for g in guids if g]
        if not guids:
            raise nsr.NativeSurveyError(
                "Egeria's process instance has no status and no engine action is linked to it yet")
        return self.read_action(guids[0])

    def survey_actions_for(self, database_guid: str) -> list[str]:
        self._enter()
        rels = self._gw().relationships(database_guid)
        return _survey_action_guids(rels)


def _survey_action_guids(rels: list[Relationship]) -> list[str]:
    return [r.other_guid for r in rels
            if r.type_name == "ActionTarget" and r.action_kind == DATABASE_SURVEY_REQUEST_TYPE and r.other_guid]


# ── the one place the catalog row's words come from ─────────────────────────

def _now() -> str:
    return nsr._now()


def derive_catalog_state(run: dict | None, *, has_pointer: bool) -> dict:
    """The "Catalog and Survey" row's state, from persisted proof only.

    The base derivation is `native_survey_run.derive_native_state` (submitted, running, Egeria's
    own failure words, ...). A process Egeria reports COMPLETED is REGISTERED only when the
    database pointer was stored (after a read of that GUID); until then it is awaiting registration.
    With no run at all, a stored pointer is `registered` and no pointer is the NEUTRAL `not_registered`."""
    base = nsr.derive_native_state(run, stored_annotation_count=None)
    st = base["state"]
    if st == nsr.NOT_RUN:
        base["state"] = REGISTERED if has_pointer else NOT_REGISTERED
    elif st in (nsr.AWAITING_REPORT, nsr.REPORT_INCOMPLETE, nsr.COMPLETE):
        base["state"] = REGISTERED if has_pointer else AWAITING_REGISTRATION
    return base


def _within_window(run: dict | None) -> bool:
    raw = (run or {}).get("surveyed_at") or ""
    try:
        started = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started < AWAITING_REGISTRATION_WINDOW


def catalog_in_flight(state: dict, run: dict | None) -> bool:
    if state["state"] in (nsr.SUBMITTED, nsr.RUNNING, nsr.UNREADABLE):
        return True
    return state["state"] == AWAITING_REGISTRATION and _within_window(run)


# ── connection-ish failures get the one extra line ──────────────────────────

_CONNECTION_WORDS = re.compile(
    r"connect|refused|timed? ?out|unknown ?host|unreachable|hikari|jdbc|authenticat|password|"
    r"\brole\b|fatal|no route|network", re.IGNORECASE)


def reach_note_for(run_state: dict) -> str:
    """Egeria's own sentence is always shown verbatim. When a failed or refused run reads as a
    connection problem, one line says Egeria connects from ITS platform and RE can still survey it.
    A heuristic on Egeria's words, deliberately generous: the line is true whatever the cause."""
    if run_state.get("state") not in (nsr.FAILED, nsr.SUBMIT_FAILED):
        return ""
    text = " ".join(str(run_state.get(k) or "") for k in ("message", "error"))
    return REACH_NOTE if _CONNECTION_WORDS.search(text) else ""


# ── pointer checks (the only read that decides "stale") ─────────────────────

def check_pointers(registry, port, entity_type: str, slug: str) -> dict:
    """Read the stored pointers back from Egeria. 'resolves' | 'gone' | 'none' (never stored) |
    'unreadable' (the read failed -- NOT the same as gone). A pointer is called gone only when
    Egeria answered that no such element exists."""
    entity = nsr._resource_entity(registry, entity_type, slug)
    out = {"database": "none", "server": "none", "error": ""}
    if entity is None:
        return out
    ptr = (getattr(entity, "egeria_asset_guid", "") or "").strip()
    if ptr:
        out["database"] = _classify(port, ptr, out)
    sptr = server_pointer(registry, entity)
    if sptr:
        out["server"] = _classify(port, sptr, out)
    return out


def _classify(port, guid: str, out: dict) -> str:
    try:
        return "resolves" if port.asset_exists(guid) else "gone"
    except Exception as exc:  # noqa: BLE001
        out["error"] = nsr._short_error(exc)
        return "unreadable"


# ── registering ─────────────────────────────────────────────────────────────

class RegistrationRefused(nsr.NativeSurveyCannotRun):
    """RE knows why it cannot register this resource. The message is what the row shows."""


def _ensure_credentials(registry, entity) -> None:
    """The collection the connection names must exist in the secrets file Egeria's engine host
    reads. Present: nothing to do. Absent with a path RE can write: the existing projection fills
    it (from the registry; no credential is read into a message here). Absent and unfillable:
    refuse, naming it. Path not configured: RE cannot see the file and proceeds, as Run does."""
    state = nsr.credentials_state(entity)
    if state != nsr.ABSENT:
        return
    from resource_explorer import omsecrets_reproject
    try:
        omsecrets_reproject.reproject(registry, [entity.slug], only_missing=True)
    except Exception as exc:  # noqa: BLE001 -- the projection never puts a credential in a message
        raise RegistrationRefused(f"{nsr.NO_CREDENTIALS} ({type(exc).__name__})") from exc
    if nsr.credentials_state(entity) == nsr.ABSENT:
        raise RegistrationRefused(nsr.NO_CREDENTIALS)


def _in_flight(registry, entity_type: str, slug: str, process_qn: str, *, catalog: bool) -> dict | None:
    runs = registry.list_native_survey_runs(entity_type, slug, process_qn)
    if not runs:
        return None
    latest = runs[0]
    if catalog:
        has_ptr = bool((getattr(nsr._resource_entity(registry, entity_type, slug), "egeria_asset_guid", "") or "").strip())
        st = derive_catalog_state(latest, has_pointer=has_ptr)
        return latest if catalog_in_flight(st, latest) else None
    stored = (registry.count_native_survey_annotations(latest["survey_report_guid"])
              if latest.get("survey_report_guid") else None)
    st = nsr.derive_native_state(latest, stored_annotation_count=stored)
    return latest if st["state"] in (nsr.SUBMITTED, nsr.RUNNING, nsr.AWAITING_REPORT, nsr.UNREADABLE) else None


def _read_back(port, qualified_name: str, what: str) -> ElementBack:
    """Find by exact qualifiedName and read that element back BY GUID. Returns it, or raises
    NativeSurveyError saying exactly what Egeria did not show. Never returns a guess."""
    found = port.find_element(qualified_name)
    if found is None:
        raise nsr.NativeSurveyError(f"Egeria has no {what} with the qualifiedName {qualified_name}")
    return _verify(port, found.guid, qualified_name, what)


def _verify(port, guid: str, qualified_name: str, what: str) -> ElementBack:
    back = port.read_element(guid)
    if back is None:
        raise nsr.NativeSurveyError(f"Egeria has no {what} with the GUID {guid} (read back after finding it)")
    if back.qualified_name != qualified_name:
        raise nsr.NativeSurveyError(
            f"the {what} Egeria holds under {guid} is named {back.qualified_name!r}, not {qualified_name!r}; "
            "nothing was stored")
    return back


def register_with_egeria(registry, port: RegistrationPort, entity_type: str, slug: str, *,
                         technology_type: str, submitted_by: str = "") -> dict:
    """The press. Returns {"server": {...}, "database": {...}, "server_survey_error": str}.

    Raises `RegistrationRefused` (a reason RE knew before asking Egeria), `NativeSurveyBusy`, or
    `NativeSurveyError` (Egeria's own sentence). Whatever was proven before a failure stays proven:
    a server read back and pointed at is not undone by a later step failing."""
    from resource_explorer import secret_redaction

    entity = nsr._resource_entity(registry, entity_type, slug)
    reason = wiring_reason(entity_type, technology_type, entity)
    if reason:
        raise RegistrationRefused(reason)
    process = _process_for(entity_type, technology_type, KIND_CATALOG_AND_SURVEY)
    if process is None:
        raise RegistrationRefused(not_wired_words(technology_type))
    if _in_flight(registry, entity_type, slug, process.qualified_name, catalog=True):
        raise nsr.NativeSurveyBusy("Registering this database with Egeria is already in flight.")

    with secret_redaction.redacting_logs(getattr(entity, "db_password", "") or ""):
        _ensure_credentials(registry, entity)
        out: dict[str, Any] = {"server": {}, "database": {}, "server_survey_error": ""}

        # 1. the server: adopt by qualifiedName, else create from Egeria's template; read back by GUID
        server_name = server_name_for(entity)
        sqn = server_qualified_name(server_name)
        try:
            existing = port.find_element(sqn)
            if existing is not None:
                server_guid, how = existing.guid, "adopted"
            else:
                server_guid, how = port.create_server(server_placeholders(entity)), "created"
            back = _verify(port, server_guid, sqn, "server")
        except nsr.NativeSurveyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise nsr.NativeSurveyError(_egeria_sentence(exc, entity)) from exc
        registry.set_setting(server_pointer_key(server_name), back.guid)   # AFTER the read
        out["server"] = {"guid": back.guid, "qualified_name": back.qualified_name, "how": how}
        _log_write(f"registered server {sqn}: {how}, GUID {back.guid} (read back)")

        # 2. Egeria's own server survey, through the same machinery as every native survey
        sproc = server_survey_process(entity_type, technology_type)
        if sproc is not None and not _in_flight(registry, entity_type, slug, sproc.qualified_name, catalog=False):
            try:
                nsr.submit_native_survey(registry, port, entity_type, slug, sproc.qualified_name,
                                         technology_type=technology_type, submitted_by=submitted_by)
            except nsr.NativeSurveyError as exc:
                # The failure is on the row (submit_error) when Egeria refused; the registration stands.
                out["server_survey_error"] = nsr.scrub_secret(str(exc), entity)

        # 3. the database: adopt by qualifiedName, else Egeria's own process creates it
        dqn = database_qualified_name(server_name, entity.database_name)
        try:
            found = port.find_element(dqn)
        except Exception as exc:  # noqa: BLE001
            raise nsr.NativeSurveyError(_egeria_sentence(exc, entity)) from exc
        if found is not None:
            try:
                dback = _verify(port, found.guid, dqn, "database")
            except nsr.NativeSurveyError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise nsr.NativeSurveyError(_egeria_sentence(exc, entity)) from exc
            registry.set_database_egeria_guid(slug, dback.guid)           # AFTER the read
            out["database"] = {"guid": dback.guid, "how": "adopted"}
            _record_survey_action(registry, port, entity_type, slug, dback.guid, submitted_by)
            return out

        submitted_at = _now()
        try:
            process_guid = port.initiate_process(process.qualified_name, database_placeholders(entity))
        except Exception as exc:  # noqa: BLE001
            error = _egeria_sentence(exc, entity)
            registry.record_native_survey_submission(
                entity_type, slug, process.qualified_name, submitted_at,
                submit_error=error, submitted_by=submitted_by)
            raise nsr.NativeSurveyError(error) from exc
        registry.record_native_survey_submission(
            entity_type, slug, process.qualified_name, submitted_at,
            engine_action_guid=process_guid, submitted_by=submitted_by)
        _log_write(f"submitted {process.qualified_name} for {slug}: process instance {process_guid}")
        out["database"] = {"how": "submitted", "process_instance_guid": process_guid}
        run = registry.list_native_survey_runs(entity_type, slug, process.qualified_name)[0]
        refresh_registration_run(registry, port, run, entity_type=entity_type, slug=slug)
        return out


def _egeria_sentence(exc: Exception, entity=None) -> str:
    """Egeria's own sentence, whole (not cut at 300 characters), with the resource's password masked
    should a driver error have echoed it."""
    from resource_explorer.catalogue_gateway import _short
    return nsr.scrub_secret(_short(exc), entity)


def _log_write(message: str) -> None:
    log.info("egeria write: %s", message)


def _record_survey_action(registry, port, entity_type: str, slug: str, database_guid: str,
                          submitted_by: str) -> None:
    """The survey the process started on the database, recorded under the ordinary database-survey
    row so it shows through the existing read-back. Exactly one candidate or nothing is recorded:
    choosing among several would be a guess."""
    try:
        guids = port.survey_actions_for(database_guid)
    except Exception as exc:  # noqa: BLE001 -- the registration stands; the survey row says not run
        log.warning("could not find the survey action on %s: %s", database_guid, exc)
        return
    if len(set(guids)) != 1:
        return
    guid = guids[0]
    known = {r.get("engine_action_guid") for r in registry.list_native_survey_runs(
        entity_type, slug, DATABASE_SURVEY_QN)}
    if guid in known:
        return
    registry.record_native_survey_submission(
        entity_type, slug, DATABASE_SURVEY_QN, _now(), engine_action_guid=guid,
        submitted_by=submitted_by)


def refresh_registration_run(registry, port: RegistrationPort, run: dict, *, entity_type: str,
                             slug: str) -> dict:
    """Read the registration process back (read-only) and, once Egeria shows the database element,
    read it back by GUID and store the pointer. Never raises: a failed read is recorded as one."""
    guid = run["engine_action_guid"]
    entity = nsr._resource_entity(registry, entity_type, slug)
    try:
        action = port.read_process(guid)
    except Exception as exc:  # noqa: BLE001
        registry.record_native_survey_readback(
            guid, read_at=_now(), error=nsr.scrub_secret(nsr._short_error(exc), entity))
        return _refetch_catalog(registry, entity_type, slug, run)
    registry.record_native_survey_readback(guid, read_at=_now(), status=action.status,
                                           message=nsr.scrub_secret(action.message, entity))
    if entity is not None and action.status in nsr.SUCCESS_STATUSES | nsr.ACTIVE_STATUSES:
        dqn = database_qualified_name(server_name_for(entity), entity.database_name)
        try:
            found = port.find_element(dqn)
            if found is not None:
                back = _verify(port, found.guid, dqn, "database")
                registry.set_database_egeria_guid(slug, back.guid)         # AFTER the read
                _record_survey_action(registry, port, entity_type, slug, back.guid,
                                      run.get("submitted_by") or "")
        except Exception as exc:  # noqa: BLE001
            registry.record_native_survey_readback(
                guid, read_at=_now(), error="database read failed: " + nsr.scrub_secret(nsr._short_error(exc), entity))
    return _refetch_catalog(registry, entity_type, slug, run)


def _refetch_catalog(registry, entity_type: str, slug: str, run: dict) -> dict:
    process_qn = run.get("executor_ref") or ""
    runs = registry.list_native_survey_runs(entity_type, slug, process_qn)
    latest = runs[0] if runs else None
    entity = nsr._resource_entity(registry, entity_type, slug)
    return derive_catalog_state(latest, has_pointer=bool(
        (getattr(entity, "egeria_asset_guid", "") or "").strip()))


# ── the databases a server survey found ─────────────────────────────────────

DATABASE_ANNOTATION_TYPE = "Capture Database Measurements"
_QN_NAME = re.compile(r"^Annotation::[^:]*::(?P<name>.+)::[0-9a-fA-F-]{36}$")


def discovered_database_names(annotations: list[dict]) -> list[str]:
    """The database names a server survey's report holds, exactly as Egeria reported them: the
    `Database Name` resource property of each database-measurements annotation, else the name inside
    its qualifiedName. Nothing is inferred from other annotation types."""
    names: list[str] = []
    for a in annotations:
        if a.get("annotation_type") != DATABASE_ANNOTATION_TYPE:
            continue
        detail = a.get("detail") or {}
        props = detail.get("resource_properties") or {}
        name = props.get("Database Name") or props.get("databaseName") or ""
        if not name:
            m = _QN_NAME.match(str(detail.get("qualified_name") or ""))
            name = m.group("name") if m else ""
        if name and name not in names:
            names.append(name)
    return names


def discovered_databases(registry, entity, server_run: dict | None) -> list[dict]:
    """For the newest complete server survey of this database's server: each database Egeria
    reported, whether RE has it registered under that server, and whether Egeria has an asset for
    it. `state`: `cataloged` (RE's pointer is stored), `found` (Egeria reported it; no asset yet --
    "found, not yet cataloged"), and `re_slug` empty when RE has no such registered database."""
    report = (server_run or {}).get("survey_report_guid") or ""
    if not report:
        return []
    names = discovered_database_names(registry.query_native_survey_annotations(report))
    host = (getattr(entity, "egeria_host", "") or entity.host)
    by_name = {}
    for d in registry.list_databases():
        if (d.egeria_host or d.host) == host and d.port == entity.port:
            by_name[d.database_name] = d
    out = []
    for name in names:
        d = by_name.get(name)
        pointer = (getattr(d, "egeria_asset_guid", "") or "").strip() if d else ""
        out.append({
            "name": name,
            "re_slug": d.slug if d else "",
            "state": "cataloged" if pointer else "found",
            "control": REGISTER_LABEL if (d and not pointer) else "",
        })
    return out
