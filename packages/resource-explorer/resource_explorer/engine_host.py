"""RE as an Egeria engine host: declare, discover and claim (E1, E3), run and complete (E4), restart (E5).

Design: `docs/design-notes/DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md`. RE's Python engine appears to Egeria
as a `SurveyActionEngine` named `ResourceExplorerSurvey`; each admitted RE step is one request type on it.
Egeria creates an engine action for that engine; RE discovers it, claims it, and queues it (step 1). The
queue runs it with `run_engine_action` (E4): IN_PROGRESS, the step through the synthetic-step executor, a
native-shaped SurveyReport (`ReportSubject` + `ReportOriginator`) through the database survey publisher, the
outcome stored on the run row, then `record_completion_status` with a `SurveyActionGuard` guard and a
`surveyReport` action target. The run also writes the native-survey row the Understanding pane lists
(`ResourceExplorerSurvey::re-db-derived`, read back like a PostgreSQLSurvey run). At start, and then every
`COMPLETION_RETRY_SECONDS`, `EngineHost.restart_pass` (E5) queues RE's claimed actions that have no run and
completes, from the stored outcome, those whose run ended without telling Egeria. An action not yet due
(`requestedStartTime` in the future) is left unclaimed until it is.

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
* none of its targets is a database with a private owner (`registry.private_owner_for_entity`). The engine
  host is unattended, so it is a daemon; private work never runs as the service account (owner, Q-O3). The
  owner runs such work attended from RE. Claiming and then refusing would write a FAILED action into a
  private context (§3.5).

An action with no target, or with a target that is not a database RE has registered
(`registry.database_slug_for_asset_guid`) and no private one, IS claimed, and then completed `survey-invalid`
with the reason: "not a database registered in Resource Explorer" for a target RE knows as a repo or file
system, else "not registered in Resource Explorer" (owner rulings, 2026-10-14; native claims such an action
too, NO_TARGET_ASSET). An action RE already holds whose target has since gone private is completed once,
survey-invalid, "target is now private to its owner".

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
`target` carries everything the handler needs (`_row_target`). `run_queue.HANDLERS["engine_action"]` runs it
as `Daemon(ENGINE_HOST, requested_by=...)` (`run_queue._run_as_engine_host`), not `_run_as_requester`'s
`RUN_QUEUE`. Such a row is never cancellable from RE (`run_queue.UNCANCELLABLE_KINDS`).

**Completion only from proof.** The outcome (guard, status, message, report GUID, annotation count) is
written to the row's `target.outcome` before Egeria is told; `target.completion_recorded_at` marks that
Egeria accepted it. No DDL: both ride in the existing `runs.target` JSON.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

log = logging.getLogger(__name__)

#: The engine element (C1). Native engines are named by a plain qualified name (`PostgreSQLSurvey`).
ENGINE_QUALIFIED_NAME = "ResourceExplorerSurvey"
ENGINE_DISPLAY_NAME = "Resource Explorer Survey Engine"
ENGINE_TYPE_NAME = "SurveyActionEngine"           # Q-M2: right for surveys
SERVICE_TYPE_NAME = "SurveyActionService"         # owner, 2026-10-14: a SurveyActionEngine's services

#: `SurveyActionGuard`'s standard guards (C9). Mandy (Q-M5): use the standard guards.
SURVEY_GUARDS = ("survey-completed", "survey-invalid", "survey-failed")
SURVEY_COMPLETED, SURVEY_INVALID, SURVEY_FAILED = SURVEY_GUARDS

#: Each guard's completion status, as `SurveyActionGuard` pairs them (`SurveyActionGuard.java:18-20`):
#: ACTIONED, INVALID, FAILED (Egeria's `CompletionStatus` names, as `record_completion_status` takes them).
GUARD_STATUS = {SURVEY_COMPLETED: "ACTIONED", SURVEY_INVALID: "INVALID", SURVEY_FAILED: "FAILED"}

#: The action target a survey's completion adds, carrying the report GUID (`SurveyActionTarget.SURVEY_REPORT`,
#: `SurveyActionServiceHandler.java`): native always adds it; RE adds it whenever a report exists.
SURVEY_REPORT_TARGET = "surveyReport"

#: Owner rulings, 2026-10-14: an action whose target is not a database RE has registered is claimed and
#: completed `survey-invalid` with this reason ("the supplied information (such as the asset) is invalid for
#: this type of survey", `SurveyActionGuard.SURVEY_INVALID`). A target RE knows as another kind of resource
#: says so instead.
NOT_REGISTERED_SENTENCE = "not registered in Resource Explorer"
NOT_A_DATABASE_SENTENCE = "not a database registered in Resource Explorer"

#: An action RE already claimed whose target has since joined a private investigation: completed once,
#: survey-invalid, never run as the service account (owner, Q-O3).
NOW_PRIVATE_SENTENCE = "target is now private to its owner"

#: How often the running engine host repeats the completion pass (`restart_pass`, idempotent): a completion
#: that timed out, or a run whose worker died, is told to Egeria within this long, not only at the next start.
COMPLETION_RETRY_SECONDS = 60

#: Native's words for an action with no asset target (`SurveyActionErrorCode.NO_TARGET_ASSET`,
#: OMES-SURVEY-ACTION-400-003). Native claims such an action and then only writes its audit log, leaving
#: it claimed for ever (`GovernanceEngineHandler.executeEngineAction`'s catch); RE completes it instead.
NO_TARGET_SENTENCE = ("no asset action target was supplied, so the survey was not run "
                      "(native: OMES-SURVEY-ACTION-400-003 NO_TARGET_ASSET)")

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

#: How long `EngineHostLoop.stop()` waits for an in-flight sweep.
STOP_JOIN_SECONDS = 10.0

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
    from resource_explorer.surveyors.database.survey_definition_adapter import (
        DATABASE_STEP_REGISTRY,
    )

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

def _daemon_user() -> str:
    """RE's service-account userId: the processingEngineUserId Egeria records on RE's claims."""
    from resource_explorer.egeria_clients import _daemon_credential

    return (_daemon_credential()[0] or "").strip()


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
    adopted: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    skipped: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    note: str = ""

    def skip(self, reason: str, guid: str) -> None:
        self.skipped.setdefault(reason, []).append(guid)


@dataclass
class RestartResult:
    """What one restart pass did, by engine action GUID."""

    adopted: list[str] = field(default_factory=list)
    left_running: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    #: Completed in Egeria, but the run row's marker could not be written.
    unmarked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    note: str = ""


#: Skip reasons that are not RE's business (another engine's work, not yet approved, claimed by someone
#: else, or already queued here): silent. The rest are logged once per action.
_SILENT = frozenset({"other_engine", "not_approved", "already_claimed", "already_queued", "not_due",
                     "completed_now_private"})

#: The `_screen` verdict for an action RE's own user already claimed in Egeria but RE has no runs row for:
#: queue it without claiming again.
ADOPT = "adopt"


class EngineHost:
    """One engine host: resolves RE's engine and sweeps for work to claim.

    Belongs to ONE thread. It owns an event loop for that thread, as `native_survey_run.EgeriaSurveyPort`
    does, because a pyegeria client binds its HTTP pool to the loop that first drives it (ISSUE-96); and it
    keeps one `EgeriaClients` per identity for its life so a 5-second sweep reuses the daemon token instead
    of minting one per pass."""

    def __init__(self, registry=None) -> None:
        self._registry = registry
        self._engine_guid: str | None = None
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

        if self._loop is not None:
            asyncio.set_event_loop(self._loop)
        for clients in self._clients.values():
            # pyegeria's own close (`close_session`, base server client), on this host's loop, before it closes.
            for client in list(getattr(clients, "_clients", {}).values()):
                close = getattr(client, "close_session", None)
                if callable(close):
                    try:
                        close()
                    except Exception:  # noqa: BLE001 - tidy-up, never the answer
                        pass
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

    def resolve_engine_guid(self) -> str | None:
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
        claimant = str(action.get("processingEngineUserId") or "").strip()
        adopt = False
        if claimant:
            # Ours with no row: a claim that raised after Egeria committed it, or whose row could not be
            # written. Anyone else's claim (another engine host, a person) is never ours to take.
            if claimant.casefold() != _daemon_user().casefold():
                return "already_claimed", {}
            if self.registry.engine_action_run_exists(_guid(action)):
                return "already_queued", {}
            adopt = True
        elif _status(action) != "APPROVED":
            return "not_approved", {}
        elif _not_yet_due(action):
            # Left unclaimed until its requested start time (native claims and then waits, C6; RE does not
            # hold a claimed action it cannot start yet).
            return "not_due", {}
        request_type = str(action.get("requestType") or "")
        step_key = supported.get(request_type)
        if not step_key:
            return "unknown_request_type", {"request_type": request_type}
        targets = _targets(action)
        slugs = [self.registry.database_slug_for_asset_guid(t["guid"]) for t in targets]
        # Private first: if ANY target is a resource in a private investigation the action is left unclaimed,
        # whatever else it names (owner, Q-O3; claiming and refusing would write a FAILED action into a
        # private context, §3.5).
        for slug in slugs:
            if slug and self.registry.private_owner_for_entity(ENTITY_TYPE, slug):
                # `ours`: RE already holds the claim (it was claimed before the target went private).
                return "private_target", {"slug": slug, "ours": adopt}
        facts = {"request_type": request_type, "step_key": step_key, "targets": targets, "slug": "",
                 "asset_guid": "", "refusal": "", "other_targets": []}
        if not targets:
            facts["refusal"] = NO_TARGET_SENTENCE
        elif not all(slugs):
            # Owner rulings, 2026-10-14: claimed, then completed survey-invalid with the reason (step 1 left it
            # unclaimed). An unregistered target cannot be private in RE (privacy is a registered resource's).
            words = []
            for t, slug in zip(targets, slugs):
                if not slug:
                    kind = self.registry.resource_kind_for_asset_guid(t["guid"])
                    words.append(f"{t['guid']}: " + (f"{NOT_A_DATABASE_SENTENCE} (it is registered as a {kind})"
                                                     if kind else NOT_REGISTERED_SENTENCE))
            facts["refusal"] = "; ".join(words)
        else:
            facts["slug"], facts["asset_guid"] = slugs[0], targets[0]["guid"]
            # Several database targets: the first is surveyed and the completion message names the rest.
            facts["other_targets"] = [t["guid"] for t in targets[1:]]
        return (ADOPT if adopt else ""), facts

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
            try:
                reason, facts = self._screen(action, engine_guid, supported)
            except Exception as exc:  # noqa: BLE001 -- fail closed: an unreadable check claims nothing
                reason, facts = "screen_failed", {"error": f"{type(exc).__name__}: {exc}"}
            if reason == ADOPT:
                self._enqueue(action, guid, facts, engine_guid, result, adopted=True)
                continue
            if reason == "private_target" and facts.get("ours"):
                recorded, _error = self._complete_now_private(action, guid)
                result.skip("completed_now_private" if recorded else "private_target", guid)
                continue
            if reason:
                result.skip(reason, guid)
                if reason not in _SILENT:
                    self._report_once(reason, guid, "engine host: left engine action %s unclaimed (%s: %s)",
                                      guid, reason, facts, level=logging.WARNING
                                      if reason in ("unknown_request_type", "screen_failed") else logging.INFO)
                continue
            self._claim(action, guid, facts, engine_guid, result)
        return result

    # -- E5: the restart pass (§3.4) ------------------------------------------------

    def _claimed_actions(self, engine_guid: str) -> list[dict]:
        """The actions RE's user has claimed for RE's engine that Egeria still holds active (WAITING,
        ACTIVATING, IN_PROGRESS): native's restart listing (C11), the one per-engine listing the View Server
        has."""
        from pyegeria import AutomatedCuration

        curation = self._client(AutomatedCuration)
        out: list[dict] = []
        start = 0
        while True:
            page = curation.get_active_claimed_engine_actions(engine_guid, start_from=start, page_size=PAGE_SIZE)
            if isinstance(page, str):         # pyegeria's "No elements found": the end of the list
                return out
            if not isinstance(page, list):
                raise RuntimeError("Egeria answered the claimed engine-action listing with "
                                   f"{type(page).__name__}")
            out.extend(a for a in page if isinstance(a, dict))
            if len(page) < PAGE_SIZE:
                return out
            start += PAGE_SIZE

    def _complete_now_private(self, action: dict, guid: str) -> tuple[bool, str]:
        """An action RE already claimed whose target is now in a private investigation: completed once,
        survey-invalid, as the engine host for its requester; nothing is run. Egeria then stops listing it."""
        from pyegeria import AutomatedCuration

        from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

        requester = str(action.get("requesterUserId") or "").strip()
        outcome = _outcome(SURVEY_INVALID, f"Resource Explorer did not run {action.get('requestType')}: "
                           f"{NOW_PRIVATE_SENTENCE}")
        with acting_as(Daemon(DaemonReason.ENGINE_HOST, requested_by=requester or None)):
            recorded, error = _record_completion(self._client(AutomatedCuration), guid, outcome)
        if recorded:
            log.info("engine host: completed engine action %s survey-invalid (%s)", guid, NOW_PRIVATE_SENTENCE)
        else:
            self._report_once("now_private_unrecorded", guid, "engine host: engine action %s (%s) could not be "
                              "completed yet: %s", guid, NOW_PRIVATE_SENTENCE, error, level=logging.WARNING)
        return recorded, error

    def restart_pass(self) -> RestartResult:
        """At engine-host start, before the first sweep (§3.4), and then every `COMPLETION_RETRY_SECONDS`
        while it runs (idempotent). For each action RE's user still holds:

        * no runs row: queue it once (the sweep's own adoption, `_screen` -> ADOPT -> `_enqueue`), or, when its
          target is now private, complete it once survey-invalid;
        * a row queued or claimed: leave it, the queue runs it;
        * a row running (under a live process, or awaiting the queue reconciler): leave it;
        * a row that cannot be read: leave it, and say so;
        * a terminal row whose completion was never recorded in Egeria: complete it from the row's stored
          outcome, never by running the step again. A row that stored no outcome completes survey-failed with
          the row's own words (a departure from §3.4's "re-run": see `_outcome_from_ended_row`).

        Each action is handled on its own: one that raises is counted in `errors` and the pass goes on."""
        result = RestartResult()
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
            claimed = self._claimed_actions(engine_guid)

        for action in claimed:
            guid = _guid(action)
            if not guid:
                continue
            try:
                self._restart_one(action, guid, engine_guid, supported, result)
            except Exception as exc:  # noqa: BLE001 -- one action, never the whole pass
                result.errors.append(guid)
                log.warning("engine host restart: engine action %s left as it is: %s", guid, _short(exc))
        return result

    def _restart_one(self, action: dict, guid: str, engine_guid: str, supported: dict, result: RestartResult) -> None:
        from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

        rows = self.registry.engine_action_runs(guid)
        if not rows:
            sweep = SweepResult()
            try:
                reason, facts = self._screen(action, engine_guid, supported)
            except Exception as exc:  # noqa: BLE001 -- fail closed
                reason, facts = "screen_failed", {"error": _short(exc)}
            if reason == ADOPT:
                self._enqueue(action, guid, facts, engine_guid, sweep, adopted=True)
                result.adopted.extend(sweep.adopted)
                result.errors.extend(sweep.errors)
            elif reason == "private_target" and facts.get("ours"):
                recorded, _error = self._complete_now_private(action, guid)
                (result.completed if recorded else result.errors).append(guid)
            else:
                result.errors.append(guid)
                self._report_once("restart_not_queued", guid, "engine host restart: engine action %s is claimed "
                                  "by RE in Egeria with no run, and was not queued (%s: %s)", guid, reason, facts,
                                  level=logging.WARNING)
            return
        row = rows[0]
        if row.get("target_unreadable"):
            result.errors.append(guid)
            self._report_once("unreadable_row", guid, "engine host restart: run %s of engine action %s has an "
                              "unreadable target; left alone", row["id"], guid, level=logging.WARNING)
            return
        state = row.get("state") or ""
        if state in ("queued", "claimed"):
            result.pending.append(guid)
            return
        if state == "running":
            from resource_explorer.run_reconciler import _is_alive

            try:
                runner = json.loads(row.get("runner") or "{}") or {}
            except (TypeError, ValueError):
                runner = {}
            if _is_alive(runner) is True:
                result.left_running.append(guid)
            else:
                result.pending.append(guid)
                log.info("engine host restart: run %s of engine action %s is 'running' with no live process; "
                         "left for the queue reconciler", row["id"], guid)
            return
        target = _row_target_json(row)
        if target.get("completion_recorded_at"):
            result.pending.append(guid)
            self._report_once("recorded_still_active", guid, "engine host restart: engine action %s is still "
                              "active in Egeria although run %s recorded its completion at %s; left alone", guid,
                              row["id"], target["completion_recorded_at"], level=logging.WARNING)
            return
        stored = target.get("outcome")
        if stored is not None and not (isinstance(stored, dict) and stored.get("guard") in GUARD_STATUS):
            result.errors.append(guid)
            self._report_once("bad_outcome", guid, "engine host restart: run %s of engine action %s stores an "
                              "outcome that is not one RE writes (%r); left alone", row["id"], guid,
                              str(stored)[:120], level=logging.WARNING)
            return
        outcome = stored or _outcome_from_ended_row(row)
        with acting_as(Daemon(DaemonReason.ENGINE_HOST, requested_by=(row.get("requested_by") or None))):
            from pyegeria import AutomatedCuration

            recorded, error = _record_completion(self._client(AutomatedCuration), guid, outcome)
        if not recorded:
            result.errors.append(guid)
            log.warning("engine host restart: completion of engine action %s from run %s not recorded: %s",
                        guid, row["id"], error)
            return
        try:
            self.registry.merge_run_target(row["id"], {"outcome": outcome, "completion_recorded_at": _now_iso()})
        except Exception as exc:  # noqa: BLE001 -- Egeria has it, and stops listing the action
            result.unmarked.append(guid)
            log.warning("engine host restart: completed engine action %s but could not mark run %s (%s)",
                        guid, row["id"], _short(exc))
        result.completed.append(guid)
        log.info("engine host restart: completed engine action %s from run %s (%s)", guid, row["id"],
                 outcome.get("guard"))

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
                log.warning("engine host: claim of engine action %s raised; outcome unknown (Egeria may have "
                            "recorded it: if so the next sweep adopts it, if not it claims again): %s",
                            guid, scrub_text(" ".join(str(exc).split()))[:400])
                return
        result.claimed.append(guid)
        self._enqueue(action, guid, facts, engine_guid, result, adopted=False)

    def _enqueue(self, action: dict, guid: str, facts: dict, engine_guid: str, result: SweepResult, *,
                 adopted: bool) -> None:
        requester = str(action.get("requesterUserId") or "").strip()
        try:
            run_id = self.registry.enqueue_run(RUN_KIND, _row_target(action, guid, facts, engine_guid),
                                               requested_by=requester)
        except Exception as exc:  # noqa: BLE001 -- the action is RE's in Egeria with no row; say so loudly
            log.error("engine host: engine action %s is claimed by RE in Egeria but could not be queued "
                      "(%s: %s); the next sweep adopts it", guid, type(exc).__name__, exc)
            result.errors.append(guid)
            return
        if adopted:
            result.adopted.append(guid)
        result.run_ids.append(run_id)
        log.info("engine host: %s engine action %s (%s on %s %s) for %s; queued run %s%s",
                 "adopted RE's own earlier claim of" if adopted else "claimed", guid, facts["request_type"],
                 ENTITY_TYPE, facts["slug"] or "-", requester or "nobody recorded", run_id,
                 f" (to be completed: {facts['refusal']})" if facts.get("refusal") else "")


def _not_yet_due(action: dict) -> bool:
    """The action's `requestedStartTime` (epoch ms) is still in the future. Missing or unreadable is due."""
    import time

    value = action.get("requestedStartTime")
    if isinstance(value, dict):
        value = value.get("primitiveValue")
    if isinstance(value, bool) or value in (None, ""):
        return False
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return False
    return ms > time.time() * 1000


def _row_target(action: dict, guid: str, facts: dict, engine_guid: str) -> dict:
    """The `runs.target` of an `engine_action` row: what E4 needs, read once from the claimed action."""
    return {
        "engine_action_guid": guid,
        "governance_engine_guid": engine_guid,
        "request_type": facts["request_type"],
        "step_key": facts["step_key"],
        "entity_type": ENTITY_TYPE,
        "slug": facts["slug"],
        # The database asset the SurveyReport hangs off (ReportSubject), as native uses the action target.
        "asset_guid": facts.get("asset_guid", ""),
        # Set when the action is claimed only to be completed with a reason (no target, or not registered).
        "refusal": facts.get("refusal", ""),
        "action_targets": facts["targets"],
        # Database targets after the first: not surveyed, named in the completion message.
        "other_targets": facts.get("other_targets", []),
        "requester_user_id": str(action.get("requesterUserId") or ""),
        # Epoch ms as Egeria sent it. Recorded only: the sweep leaves an action unclaimed until it is due
        # (`_not_yet_due`), so a queued row never waits for its start time.
        "requested_start_time": action.get("requestedStartTime"),
        "request_parameters": action.get("requestParameters") or {},
    }


# ── E4: running a claimed engine action ─────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def _row_target_json(row: dict) -> dict:
    try:
        target = json.loads(row.get("target") or "{}")
    except (TypeError, ValueError):
        return {}
    return target if isinstance(target, dict) else {}


def _short(exc: BaseException, limit: int = 400) -> str:
    from resource_explorer.secret_redaction import scrub_text

    return scrub_text(" ".join(f"{type(exc).__name__}: {exc}".split()))[:limit]


def _outcome(guard: str, message: str, *, report_guid: str = "", annotation_count: int | None = None,
             **extra) -> dict:
    """The outcome stored on the run row BEFORE Egeria is told, and the only thing a completion is made from."""
    if guard not in GUARD_STATUS:
        raise ValueError(f"{guard!r} is not one of the declared guards {SURVEY_GUARDS}")
    return {"guard": guard, "status": GUARD_STATUS[guard], "message": message, "report_guid": report_guid,
            "annotation_count": annotation_count, "decided_at": _now_iso(), **extra}


def _outcome_from_ended_row(row: dict) -> dict:
    """A terminal row that stored no outcome: the run ended (reconciled, or crashed) before it decided one.
    Completed survey-failed with the row's own words; never re-run (E5)."""
    why = (row.get("error") or "").strip() or f"the run ended '{row.get('state')}' without recording an outcome"
    return _outcome(SURVEY_FAILED, f"Resource Explorer's run {row.get('id')} ended before it finished: {why}")


def _record_completion(curation, guid: str, outcome: dict) -> tuple[bool, str]:
    """`record_completion_status` from a stored outcome. (recorded, error). The `surveyReport` action target
    is added only when a report exists. Egeria ignores a completion on an action that is no longer active
    (no else branch in `EngineActionHandler.recordCompletionStatus`), so a repeat is harmless."""
    report_guid = outcome.get("report_guid") or ""
    try:
        curation.record_completion_status(
            guid, outcome["status"], output_guards=[outcome["guard"]],
            new_action_targets=([{"actionTargetName": SURVEY_REPORT_TARGET, "actionTargetGUID": report_guid}]
                                if report_guid else None),
            completion_message=outcome.get("message") or "")
    except Exception as exc:  # noqa: BLE001 -- returned: the run says so and E5 sends it at the next start
        return False, _short(exc)
    return True, ""


class EngineHostPublishFailed(RuntimeError):
    """Raised by the engine host's publisher to the synthetic-step executor when the report did not land as a
    complete, linked report: the executor's run words then say "publish failed · <these words>"."""


def _decide(registry, target: dict) -> dict:
    """Run the step and publish its report; return the outcome to store. Never raises for a step or Egeria
    answer: each becomes a guard with its words. Runs as the current principal (the engine host daemon)."""
    outcome = _decide_one(registry, target)
    others = [g for g in target.get("other_targets") or [] if g]
    if others:
        outcome["message"] = (f"{outcome['message'].rstrip('.')}. Only the first database target was surveyed; "
                              f"{len(others)} other target(s) not surveyed: {', '.join(others)}.")
    return outcome


def _decide_one(registry, target: dict) -> dict:
    refusal = (target.get("refusal") or "").strip()
    if refusal:
        # Owner ruling, 2026-10-14: survey-invalid ("the supplied information (such as the asset) is invalid").
        return _outcome(SURVEY_INVALID, f"Resource Explorer did not run {target.get('request_type')}: {refusal}")
    slug, step_key = target.get("slug") or "", target.get("step_key") or ""
    request_type = target.get("request_type") or ""
    if step_key not in declared_steps():
        return _outcome(SURVEY_FAILED, f"step {step_key!r} is not one Resource Explorer's engine runs")

    from resource_explorer.surveyors import result_status
    from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutor

    published: dict = {}

    def publisher(entity, step_outputs, surveyed_at, _registry):
        """The executor's publish step for this run: ONE native-shaped report, linked to the action. The
        executor records what this returns (the report GUID) or raises as the run's publish words."""
        annotations = [a for out in step_outputs if isinstance(out, dict) for a in (out.get("annotations") or [])]
        published["outcome"] = _publish(registry, target, annotations)
        if published["outcome"]["guard"] != SURVEY_COMPLETED:
            raise EngineHostPublishFailed(published["outcome"]["message"])
        return published["outcome"]["report_guid"]

    try:
        ran = SurveyDefinitionExecutor(registry).run_synthetic_step(
            entity_type=ENTITY_TYPE, slug=slug, re_analysis_step=step_key, executes_at="resource-explorer",
            # In this process, never Prefect (Prefect-only steps are not in the slice, §5.4).
            engine_override="resource-explorer", publisher=publisher,
            display_name=f"{request_type} (engine action {target.get('engine_action_guid')})")
    except Exception as exc:  # noqa: BLE001 -- the step could not run: survey-failed with its words
        return published.get("outcome") or _outcome(SURVEY_FAILED, f"{step_key} on {slug} could not run: "
                                                    f"{_short(exc)}")
    if "outcome" in published:
        return published["outcome"]
    report = next((r for r in ran.get("steps") or [] if r.get("re_analysis_step") == step_key), {})
    status = report.get("status") or ""
    if status == result_status.SKIPPED_BY_DESIGN:
        # db_derived's precondition: no stored schema inventory. "an absence, not a finding" (survey-invalid:
        # "the supplied information (such as the asset) is invalid for this type of survey").
        return _outcome(SURVEY_INVALID, f"{step_key} did not run on {slug}: "
                        f"{report.get('detail') or 'its precondition is not met'} (no stored schema inventory "
                        "to derive from: an absence, not a finding)")
    errors = "; ".join(str(e) for e in ran.get("errors") or []) or f"step status {status or 'unknown'}"
    if status == "ok":
        errors = f"the step produced no output to publish ({errors})"
    return _outcome(SURVEY_FAILED, f"{step_key} failed on {slug}: {errors}"[:1500])


def _publish(registry, target: dict, annotations: list) -> dict:
    """Publish the report through the database survey publisher; the outcome follows the proof."""
    from resource_explorer.egeria_clients import current_principal
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    slug, request_type = target.get("slug") or "", target.get("request_type") or ""
    guid = target.get("engine_action_guid") or ""
    identity = current_principal()
    try:
        entity = registry.get_database(slug, allow_unreadable=True)     # never connects: no credential needed
        if entity is None:
            return _outcome(SURVEY_FAILED, f"database {slug!r} is no longer registered in Resource Explorer")
        pub = EgeriaDatabaseSurveyor(identity=identity).publish_engine_action_report(
            entity, annotations, asset_guid=target.get("asset_guid") or entity.egeria_asset_guid,
            request_type=request_type, engine_action_guid=guid, engine_user=identity.client_user or "",
            requester=(identity.requested_by or "").strip(), registry=registry)
    except Exception as exc:  # noqa: BLE001 -- a publish that raised is a failed survey, said in its words
        return _outcome(SURVEY_FAILED, f"the survey report for {slug} was not published: {_short(exc)}",
                        annotation_count=len(annotations))
    report_guid = pub.get("report_guid") or ""
    sent, landed = len(annotations), pub.get("annotations_in_egeria")
    extra = {"annotations_in_egeria": landed, "qualified_name": pub.get("qualified_name", ""),
             "ownership": (pub.get("governance") or {}).get("ownership")}
    if not report_guid:
        return _outcome(SURVEY_FAILED, "the survey report for "
                        f"{slug} was not published: {pub.get('report_error') or 'Egeria gave no report GUID'}",
                        annotation_count=sent, **extra)
    if pub.get("originator_error"):
        return _outcome(SURVEY_FAILED, f"survey report {report_guid} was published but not linked to this "
                        f"engine action (ReportOriginator): {pub['originator_error']}",
                        report_guid=report_guid, annotation_count=sent, **extra)
    problem = pub.get("annotation_error") or pub.get("report_error") or ""
    if landed is None or landed < sent or problem:
        told = "could not be counted" if landed is None else f"{landed} of {sent} reached Egeria"
        return _outcome(SURVEY_FAILED, f"survey report {report_guid} is incomplete: its annotations {told}"
                        + (f" ({problem})" if problem else ""),
                        report_guid=report_guid, annotation_count=sent, **extra)
    governance = "" if extra["ownership"] else " (Ownership was not recorded on the report)"
    return _outcome(SURVEY_COMPLETED, f"Resource Explorer ran {request_type} on {slug}: survey report "
                    f"{report_guid} with {sent} annotation(s){governance}.",
                    report_guid=report_guid, annotation_count=sent, **extra)


def run_engine_action(registry, run_id: str, target: dict) -> tuple[str, str]:
    """E4: run one claimed engine action to a completion recorded in Egeria. (run state, error).

    Runs as the current principal, which `run_queue` sets to `Daemon(ENGINE_HOST, requested_by=<requester>)`
    (`run_queue._run_as_engine_host`), never the requester and never `RUN_QUEUE`. In order:

    1. IN_PROGRESS on the action (C7). A failed status update is logged and the run goes on.
    2. The outcome: the step through the synthetic-step executor, then the SurveyReport (`_decide`).
    3. The outcome stored on the run row (`target.outcome`: guard, status, message, report GUID, annotation
       count). If it cannot be stored, nothing is sent to Egeria and the run fails: E5 completes it later.
    4. `record_completion_status` from that stored outcome, then `target.completion_recorded_at`.

    No R21 OpenLineage event is emitted for this work: Egeria reports its lineage from the action's status
    changes (Q-M6)."""
    from resource_explorer.observability import openlineage

    guid = (target or {}).get("engine_action_guid") or ""
    if registry is None or not run_id or not guid:
        return "failed", "engine_action run with no registry, run id or engine action GUID; nothing was sent"
    with openlineage.suppressed():
        from resource_explorer.catalogue_commit import run_with_loop

        return run_with_loop(_run_engine_action, registry, run_id, target)


def _run_engine_action(registry, run_id: str, target: dict) -> tuple[str, str]:
    from pyegeria import AutomatedCuration

    from resource_explorer.egeria_clients import current_principal, egeria_client

    principal = current_principal()
    # Not scope-shared: this client is closed when the run ends (it is bound to this run's event loop).
    curation = egeria_client(principal, purpose="engine host", shared=False).of(AutomatedCuration)
    try:
        return _run_with(curation, registry, run_id, target, principal)
    finally:
        _close_quietly(curation)


def _close_quietly(client) -> None:
    """pyegeria's own close (`close_session`) of a client this run built. Tidy-up, never the answer."""
    close = getattr(client, "close_session", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001 - tidy-up, never the answer
            pass


def _record_submission(registry, target: dict, principal) -> str:
    """The native-survey row the Understanding pane lists (`native_survey_run.native_survey_rows`), written
    once per engine action: the existing read-back then fills Egeria's status and the report through
    `report_guid_for_action`, as for a PostgreSQLSurvey run. "" when written or already there, else why not."""
    slug, guid = target.get("slug") or "", target["engine_action_guid"]
    if not slug:
        return ""
    process_qn = governance_action_type_qn(target.get("step_key") or "")
    try:
        if any(r.get("engine_action_guid") == guid
               for r in registry.list_native_survey_runs(ENTITY_TYPE, slug, process_qn)):
            return ""
        registry.record_native_survey_submission(ENTITY_TYPE, slug, process_qn, _now_iso(),
                                                 engine_action_guid=guid,
                                                 submitted_by=(principal.requested_by or "").strip(),
                                                 started_as="engine-host")
    except Exception as exc:  # noqa: BLE001 -- the listing row, not the work: recorded on the outcome
        why = _short(exc)
        log.warning("engine host: no native-survey row for engine action %s (%s)", guid, why)
        return why
    return ""


def _run_with(curation, registry, run_id: str, target: dict, principal) -> tuple[str, str]:
    guid = target["engine_action_guid"]
    status_error = ""
    try:
        curation.update_engine_action_status(guid, "IN_PROGRESS")
    except Exception as exc:  # noqa: BLE001 -- a status line, not the work: recorded on the outcome, run goes on
        status_error = _short(exc)
        log.warning("engine host: could not set engine action %s IN_PROGRESS (%s); running it anyway",
                    guid, status_error)
    listing_error = _record_submission(registry, target, principal)
    outcome = _decide(registry, target)
    if status_error:
        outcome["in_progress_error"] = status_error
    if listing_error:
        outcome["listing_error"] = listing_error
    registry.merge_run_target(run_id, {"outcome": outcome})      # raises: nothing is sent unstored
    recorded, error = _record_completion(curation, guid, outcome)
    log.info("engine host: engine action %s ran: %s (%s)%s", guid, outcome["guard"], outcome["message"],
             "" if recorded else f"; completion NOT recorded in Egeria: {error}")
    if not recorded:
        return "failed", (f"{outcome['guard']}: {outcome['message']} · completion not recorded in Egeria "
                          f"({error}); the engine host sends it within {COMPLETION_RETRY_SECONDS}s")[:1500]
    marker_note = ""
    try:
        registry.merge_run_target(run_id, {"completion_recorded_at": _now_iso()})
    except Exception as exc:  # noqa: BLE001 -- Egeria has the completion: the run says so, never "failed" for it
        marker_note = (f"completion recorded in Egeria; RE's completion marker on this run was not written "
                       f"({_short(exc, 200)})")
        log.warning("engine host: engine action %s completed in Egeria, but run %s's marker was not written: %s",
                    guid, run_id, marker_note)
    if outcome["guard"] == SURVEY_COMPLETED:
        return "succeeded", marker_note
    return "failed", " · ".join(x for x in (f"{outcome['guard']}: {outcome['message']}", marker_note) if x)[:1500]


# ── the worker loop ────────────────────────────────────────────────────────────

class EngineHostLoop:
    """The worker's engine-host thread: one `EngineHost`, swept every SWEEP_INTERVAL_SECONDS. Started by the
    worker's leader-elected supervisor only when RE_ENGINE_HOST_ENABLED is on (worker.loop_specs)."""

    def __init__(self, interval: float = SWEEP_INTERVAL_SECONDS,
                 completion_retry_interval: float = COMPLETION_RETRY_SECONDS) -> None:
        self.interval = interval
        self.completion_retry_interval = completion_retry_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        import time

        host = EngineHost()
        try:
            last_pass = None
            while not self._stop.is_set():
                if last_pass is None or time.monotonic() - last_pass >= self.completion_retry_interval:
                    # E5: before the first sweep (§3.4), then every completion_retry_interval: a completion that
                    # timed out, or a run whose worker died, reaches Egeria without waiting for a restart.
                    last_pass = time.monotonic()
                    self._guarded(lambda: host.restart_pass(), "completion pass")
                self._guarded(lambda: host.sweep_once(), "sweep")
                if self._stop.wait(self.interval):
                    return
        finally:
            host.close()

    @staticmethod
    def _guarded(fn, what: str) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 -- one bad pass must not end the loop
            import traceback

            from resource_explorer.secret_redaction import scrub_text

            log.error("engine host: %s failed; continuing\n%s", what, scrub_text(traceback.format_exc()))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="re-engine-host", daemon=True)
        self._thread.start()
        log.info("engine host: sweep started every %ss for engine %s (request types %s)", self.interval,
                 ENGINE_QUALIFIED_NAME, sorted(supported_request_types()))

    def stop(self, timeout: float = STOP_JOIN_SECONDS) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            # Bounded: a sweep blocked in an Egeria call must not hold shutdown open. It is a daemon thread.
            thread.join(timeout=timeout)
            if thread.is_alive():
                log.warning("engine host: sweep thread still running after %ss; it goes with the process", timeout)


_loop = EngineHostLoop()


def start_engine_host() -> None:
    if not engine_host_enabled():
        log.info("engine host: not started (%s is off)", ENABLE_ENV)
        return
    _loop.start()


def stop_engine_host() -> None:
    _loop.stop()
