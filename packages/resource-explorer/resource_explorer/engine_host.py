"""RE as an Egeria engine host, step 1: declare, discover and claim (E1's names, E3's sweep).

Design: `docs/design-notes/DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md`. RE's Python engine appears to Egeria
as a `SurveyActionEngine` named `ResourceExplorerSurvey`; each admitted RE step is one request type on it.
Egeria creates an engine action for that engine; RE discovers it, claims it, and queues it. Running it,
publishing its SurveyReport and recording completion are E4; the restart pass is E5. Neither is here.

**Discovery is option A (§3.1).** The View Server has no per-engine "approved" listing yet (Q-M1: Mandy will
add one), so the sweep reads the whole server's active list, `AutomatedCuration.get_active_engine_actions`,
and filters client-side, every `SWEEP_INTERVAL_SECONDS` (5 s, the native engine host's own sweep interval).
`find_engine_actions` was considered and not used: it is a search-string asset search (EngineAction is an
Asset in 6.2) that cannot filter on status or executor, so it would return every terminal action too.
`get_engine_actions` no longer exists (pyegeria 6.2.3, ISSUE-151).

**What is claimed.** An action is claimed only when all of these hold; anything else is left for its owner,
exactly as native leaves it:

* its `governanceEngineGUID` is RE's engine (resolved once by qualified name, `ENGINE_QUALIFIED_NAME`);
* its `actionStatus` is `APPROVED` and its `processingEngineUserId` is empty (Egeria's own claim gate, C5);
* its `requestType` is one RE declares (`supported_request_types()`, the same function the declaration
  generator uses); an unknown type is left unclaimed and logged once (§3.3; Q-M7 is still open);
* its target is a database RE has registered (`registry.database_slug_for_asset_guid`), and
* that database has no private owner (`registry.private_owner_for_entity`). The engine host is unattended,
  so it is a daemon; private work never runs as the service account (owner, Q-O3). The owner runs such work
  attended from RE. Claiming and then refusing would write a FAILED action into a private context (§3.5).

**Who RE acts as.** Owner, 2026-10-14: "when RE accepts an action or process for execution, it is acting as a
daemon - there is no relationship to logged in users." Every Egeria call here runs under RE's existing
service account: the listing and the engine lookup as `Daemon(ENGINE_HOST)`, each claim as
`Daemon(ENGINE_HOST, requested_by=requesterUserId)`. `requesterUserId` is recorded on the `runs` row and is
never used as a credential. Native does the same: the engine user claims and writes; the requester is a
stored string (design note, "Native does the same").

**A refused claim is ordinary.** Another host claiming first is `OMAG-GENERIC-HANDLERS-403-003`; it is skipped,
nothing is written and nothing is logged as an error (§3.3 step 2).

**Off means off.** With `RE_ENGINE_HOST_ENABLED` unset or false (the default), the worker starts no loop and
`EngineHost.sweep_once()` returns before any client is built.

**Where E4 hooks in.** Each claim enqueues one `runs` row of kind `engine_action` (`RUN_KIND`) whose
`target` carries everything the handler needs (`_row_target`). `run_queue.HELD_KINDS` holds such rows queued
until E4 registers `run_queue.HANDLERS["engine_action"]` and removes the kind from `HELD_KINDS`. E4 must run
the row as `Daemon(ENGINE_HOST, requested_by=...)`, not `run_queue._run_as_requester`'s `RUN_QUEUE` reason.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

#: The engine element (C1). Native engines are named by a plain qualified name (`PostgreSQLSurvey`).
ENGINE_QUALIFIED_NAME = "ResourceExplorerSurvey"
ENGINE_DISPLAY_NAME = "Resource Explorer Survey Engine"
ENGINE_TYPE_NAME = "SurveyActionEngine"           # Q-M2: right for surveys
SERVICE_TYPE_NAME = "SurveyActionService"         # owner, 2026-10-14: a SurveyActionEngine's services

#: `SurveyActionGuard`'s standard guards (C9). Mandy (Q-M5): use the standard guards.
SURVEY_GUARDS = ("survey-completed", "survey-invalid", "survey-failed")

#: The RE steps admitted to the engine host. One zero-fetch step in the first slice (§5): it never opens a
#: connection, so no credential question arises. A step is added here on purpose, never by default.
ENGINE_HOST_STEPS = ("db_derived",)

#: The resource kind every admitted step targets (all are database steps today).
ENTITY_TYPE = "database"

#: The `runs` kind a claim enqueues (registry.RUN_KINDS).
RUN_KIND = "engine_action"

ENABLE_ENV = "RE_ENGINE_HOST_ENABLED"

#: The native engine host's sweep interval (`EngineConfigurationRefreshThread.java:51`, 5000 ms).
SWEEP_INTERVAL_SECONDS = 5

#: Page size for the active-actions listing (native pages 10 at a time; a larger page is fewer round trips).
PAGE_SIZE = 100

#: Egeria's "another claimant already holds this action" (C5; live-confirmed in ISSUE-78).
CLAIM_REFUSED_MESSAGE_ID = "OMAG-GENERIC-HANDLERS-403-003"

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def engine_host_enabled() -> bool:
    """`RE_ENGINE_HOST_ENABLED` is on. Off (the default) means no loop and no Egeria call."""
    raw = os.environ.get(ENABLE_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ── the declared names: ONE source for the generator (E1) and the sweep (E3) ──

def request_type_for_step(step_key: str) -> str:
    """`db_derived` -> `re-db-derived`: the request type RE's engine advertises for a step."""
    return "re-" + step_key.replace("_", "-")


def governance_action_type_qn(step_key: str) -> str:
    """`ResourceExplorerSurvey::re-db-derived`, the shape of native `PostgreSQLSurvey::survey-postgres-database`."""
    return f"{ENGINE_QUALIFIED_NAME}::{request_type_for_step(step_key)}"


def service_qualified_name(step_key: str) -> str:
    return f"{SERVICE_TYPE_NAME}::{ENGINE_QUALIFIED_NAME}::{step_key}"


def declared_steps() -> dict:
    """{step_key: StepInfo} for every admitted step, read from DATABASE_STEP_REGISTRY. A step named in
    ENGINE_HOST_STEPS but missing from the registry is a KeyError, not a silent omission."""
    from resource_explorer.surveyors.database.survey_definition_adapter import DATABASE_STEP_REGISTRY

    return {key: DATABASE_STEP_REGISTRY[key] for key in ENGINE_HOST_STEPS}


def supported_request_types() -> dict[str, str]:
    """{request type: step key} RE's engine can run."""
    return {request_type_for_step(key): key for key in declared_steps()}


def is_claim_refused(exc: BaseException) -> bool:
    """Egeria refused a claim because another claimant holds the action (403-003): an ordinary outcome."""
    for e in (exc, getattr(exc, "__cause__", None)):
        if e is None:
            continue
        info = getattr(e, "additional_info", None) or {}
        ids = (str(info.get("exceptionErrorMessageId") or ""), str(getattr(e, "response_egeria_msg_id", "") or ""))
        if CLAIM_REFUSED_MESSAGE_ID in ids or CLAIM_REFUSED_MESSAGE_ID in str(e):
            return True
    return False


# ── reading one EngineActionElement ────────────────────────────────────────────

def _guid(action: dict) -> str:
    return str(((action or {}).get("elementHeader") or {}).get("guid") or "")


def _status(action: dict) -> str:
    status = action.get("actionStatus")
    if isinstance(status, dict):          # tolerate an enum serialised as an object
        status = status.get("name") or status.get("symbolicName") or ""
    return str(status or "").upper()


def _targets(action: dict) -> list[dict]:
    out = []
    for t in action.get("actionTargetElements") or []:
        if isinstance(t, dict) and t.get("actionTargetGUID"):
            out.append({"name": str(t.get("actionTargetName") or ""), "guid": str(t["actionTargetGUID"])})
    return out


@dataclass
class SweepResult:
    """What one sweep did. `skipped` maps a reason to the action GUIDs left unclaimed for it."""

    claimed: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    skipped: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    note: str = ""

    def skip(self, reason: str, guid: str) -> None:
        self.skipped.setdefault(reason, []).append(guid)


#: Skip reasons that are not RE's business (another engine's work, not yet approved, already claimed):
#: silent. The rest are logged once per action.
_SILENT = frozenset({"other_engine", "not_approved", "already_claimed"})


class EngineHost:
    """One engine host: resolves RE's engine and sweeps for work to claim.

    Belongs to ONE thread. It owns an event loop for that thread, as `native_survey_run.EgeriaSurveyPort`
    does, because a pyegeria client binds its HTTP pool to the loop that first drives it (ISSUE-96); and it
    keeps one `EgeriaClients` per identity for its life so a 5-second sweep reuses the daemon token instead
    of minting one per pass."""

    def __init__(self, registry=None) -> None:
        self._registry = registry
        self._engine_guid: Optional[str] = None
        self._clients: dict[tuple, Any] = {}
        self._reported: set[tuple[str, str]] = set()
        self._loop = None

    # -- plumbing --------------------------------------------------------------

    @property
    def registry(self):
        if self._registry is None:
            from resource_explorer.registry import ProjectRegistry

            self._registry = ProjectRegistry()
        return self._registry

    def _enter(self) -> None:
        import asyncio

        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

    def close(self) -> None:
        import asyncio

        self._clients.clear()
        if self._loop is not None:
            self._loop.close()
            self._loop = None
            asyncio.set_event_loop(None)

    def _client(self, cls):
        """The pyegeria client of class `cls` for the identity this code is acting as."""
        from resource_explorer.egeria_clients import current_principal, egeria_client, identity_key

        identity = current_principal()
        key = identity_key(identity)
        clients = self._clients.get(key)
        if clients is None:
            # Not scope-shared: these clients are bound to this host's own event loop.
            clients = egeria_client(identity, purpose="engine host", shared=False)
            self._clients[key] = clients
        return clients.of(cls)

    def _report_once(self, reason: str, guid: str, message: str, *args, level: int = logging.INFO) -> None:
        if (reason, guid) in self._reported:
            return
        self._reported.add((reason, guid))
        log.log(level, message, *args)

    # -- the engine ------------------------------------------------------------

    def resolve_engine_guid(self) -> Optional[str]:
        """RE's engine GUID, by its qualified name. None when Egeria has no such element (the owner has not
        run the declaration yet) or the answer was not a GUID. Cached once found (config refresh, C12, is not
        in this slice)."""
        if self._engine_guid:
            return self._engine_guid
        from pyegeria import MetadataExpert

        answer = self._client(MetadataExpert).get_metadata_guid_by_unique_name(ENGINE_QUALIFIED_NAME)
        if isinstance(answer, str) and _GUID_RE.match(answer.strip()):
            self._engine_guid = answer.strip()
            log.info("engine host: engine %s is %s", ENGINE_QUALIFIED_NAME, self._engine_guid)
            return self._engine_guid
        self._report_once("no_engine", ENGINE_QUALIFIED_NAME,
                          "engine host: no engine %r in Egeria (answer %r); nothing is claimed until the "
                          "owner runs docs/dr-egeria/engine-host/", ENGINE_QUALIFIED_NAME,
                          " ".join(str(answer).split())[:120], level=logging.WARNING)
        return None

    # -- the sweep -------------------------------------------------------------

    def _active_actions(self) -> list[dict]:
        from pyegeria import AutomatedCuration

        curation = self._client(AutomatedCuration)
        out: list[dict] = []
        start = 0
        while True:
            page = curation.get_active_engine_actions(start_from=start, page_size=PAGE_SIZE)
            if isinstance(page, str):         # pyegeria's "No elements found": the end of the list
                return out
            if not isinstance(page, list):
                raise RuntimeError(f"Egeria answered the active engine-action listing with {type(page).__name__}")
            out.extend(a for a in page if isinstance(a, dict))
            if len(page) < PAGE_SIZE:
                return out
            start += PAGE_SIZE

    def _screen(self, action: dict, engine_guid: str, supported: dict[str, str]) -> tuple[str, dict]:
        """(reason, facts): reason "" means claim it. Facts carry what the runs row needs."""
        if str(action.get("governanceEngineGUID") or "") != engine_guid:
            return "other_engine", {}
        if _status(action) != "APPROVED":
            return "not_approved", {}
        if (action.get("processingEngineUserId") or "").strip():
            return "already_claimed", {}
        request_type = str(action.get("requestType") or "")
        step_key = supported.get(request_type)
        if not step_key:
            return "unknown_request_type", {"request_type": request_type}
        targets = _targets(action)
        slugs = [s for s in (self.registry.database_slug_for_asset_guid(t["guid"]) for t in targets) if s]
        if not slugs:
            return "unknown_target", {"targets": targets}
        for slug in slugs:
            if self.registry.private_owner_for_entity(ENTITY_TYPE, slug):
                return "private_target", {"slug": slug}
        return "", {"request_type": request_type, "step_key": step_key, "slug": slugs[0], "targets": targets}

    def sweep_once(self) -> SweepResult:
        """One pass: list, filter, claim, enqueue. Never raises for an Egeria answer; returns what it did."""
        result = SweepResult()
        if not engine_host_enabled():
            result.note = f"{ENABLE_ENV} is off"
            return result
        from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

        self._enter()
        supported = supported_request_types()
        with acting_as(Daemon(DaemonReason.ENGINE_HOST)):
            engine_guid = self.resolve_engine_guid()
            if not engine_guid:
                result.note = "engine not declared in Egeria"
                return result
            actions = self._active_actions()

        for action in actions:
            guid = _guid(action)
            if not guid:
                continue
            reason, facts = self._screen(action, engine_guid, supported)
            if reason:
                result.skip(reason, guid)
                if reason not in _SILENT:
                    self._report_once(reason, guid, "engine host: left engine action %s unclaimed (%s: %s)",
                                      guid, reason, facts, level=logging.WARNING
                                      if reason == "unknown_request_type" else logging.INFO)
                continue
            self._claim(action, guid, facts, engine_guid, result)
        return result

    def _claim(self, action: dict, guid: str, facts: dict, engine_guid: str, result: SweepResult) -> None:
        from pyegeria import AutomatedCuration

        from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

        requester = str(action.get("requesterUserId") or "").strip()
        with acting_as(Daemon(DaemonReason.ENGINE_HOST, requested_by=requester or None)):
            try:
                self._client(AutomatedCuration).claim_engine_action(guid)
            except Exception as exc:  # noqa: BLE001 -- classified: a lost race is ordinary, the rest is logged
                if is_claim_refused(exc):
                    result.refused.append(guid)
                    log.info("engine host: engine action %s was claimed by another host first", guid)
                    return
                from resource_explorer.secret_redaction import scrub_text

                result.errors.append(guid)
                log.warning("engine host: claiming engine action %s failed; left for the next sweep: %s",
                            guid, scrub_text(" ".join(str(exc).split()))[:400])
                return
        result.claimed.append(guid)
        try:
            run_id = self.registry.enqueue_run(RUN_KIND, _row_target(action, guid, facts, engine_guid),
                                               requested_by=requester)
        except Exception as exc:  # noqa: BLE001 -- the action is RE's in Egeria with no row; say so loudly
            log.error("engine host: claimed engine action %s in Egeria but could not queue it (%s: %s); the "
                      "restart pass must find it (claimed, no runs row)", guid, type(exc).__name__, exc)
            result.errors.append(guid)
            return
        result.run_ids.append(run_id)
        log.info("engine host: claimed engine action %s (%s on %s %s) for %s; queued run %s", guid,
                 facts["request_type"], ENTITY_TYPE, facts["slug"], requester or "nobody recorded", run_id)


def _row_target(action: dict, guid: str, facts: dict, engine_guid: str) -> dict:
    """The `runs.target` of an `engine_action` row: what E4 needs, read once from the claimed action."""
    return {
        "engine_action_guid": guid,
        "governance_engine_guid": engine_guid,
        "request_type": facts["request_type"],
        "step_key": facts["step_key"],
        "entity_type": ENTITY_TYPE,
        "slug": facts["slug"],
        "action_targets": facts["targets"],
        "requester_user_id": str(action.get("requesterUserId") or ""),
        # Epoch ms as Egeria sent it; a future start is honoured by E4 (claim first, then wait: C6, Q-O4).
        "requested_start_time": action.get("requestedStartTime"),
        "request_parameters": action.get("requestParameters") or {},
    }


# ── the worker loop ────────────────────────────────────────────────────────────

class EngineHostLoop:
    """The worker's engine-host thread: one `EngineHost`, swept every SWEEP_INTERVAL_SECONDS. Started by the
    worker's leader-elected supervisor only when RE_ENGINE_HOST_ENABLED is on (worker.loop_specs)."""

    def __init__(self, interval: float = SWEEP_INTERVAL_SECONDS) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _run(self) -> None:
        host = EngineHost()
        try:
            while not self._stop.is_set():
                try:
                    host.sweep_once()
                except Exception:  # noqa: BLE001 -- one bad pass must not end the loop
                    import traceback

                    from resource_explorer.secret_redaction import scrub_text

                    log.error("engine host: sweep failed; continuing\n%s", scrub_text(traceback.format_exc()))
                if self._stop.wait(self.interval):
                    return
        finally:
            host.close()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="re-engine-host", daemon=True)
        self._thread.start()
        log.info("engine host: sweep started every %ss for engine %s (request types %s)", self.interval,
                 ENGINE_QUALIFIED_NAME, sorted(supported_request_types()))

    def stop(self) -> None:
        self._stop.set()
        self._thread = None


_loop = EngineHostLoop()


def start_engine_host() -> None:
    if not engine_host_enabled():
        log.info("engine host: not started (%s is off)", ENABLE_ENV)
        return
    _loop.start()


def stop_engine_host() -> None:
    _loop.stop()
