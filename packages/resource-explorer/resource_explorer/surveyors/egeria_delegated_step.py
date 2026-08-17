"""
Case 4 of docs/re-as-engine-host-plan.md: delegate a single survey step to
a real Egeria governance/survey action service instead of running it
locally. RE stays the orchestrator (SurveyOrchestrator.run(steps=[...]))
but one step's actual work happens on a real Egeria engine — the mirror
image of case 2 (RE claiming steps *from* an Egeria-orchestrated process).

Deliberately uses only the requester-side pyegeria surface that already
exists — AutomatedCuration.initiate_engine_action() to trigger,
MetadataExpert.get_metadata_element_by_guid() to poll (the same
generic-element-read pattern already live-verified in rfa_egeria_sync.py
for ToDo status) — no new pyegeria client work needed for this case,
confirmed in the plan doc's gap analysis (that's case 2's problem, not
case 4's).

**Live verification found a real, blocking pyegeria bug (2026-08-17),
logged as PYEGERIA_ISSUES.md ISSUE-50, not fixed here per standing
policy**: `AutomatedCuration.initiate_engine_action()` always 404s — it
posts to a URL missing the governance engine's name as a required path
segment (confirmed against the real Java route,
`OpenGovernanceResource.java`'s `/governance-engines/{governanceEngineName}
/engine-actions/initiate`), and the method has no parameter to supply one.
This module is fully built and unit-tested (mocked pyegeria clients) and
is structurally ready to work once that's fixed — `initiate_and_wait()`'s
trigger call is the only piece that cannot be live-verified today.

Two layers:
  initiate_and_wait()          — the generic trigger-and-block primitive.
  EgeriaDelegatedStepSurveyor  — a BaseSurveyor-shaped wrapper around it,
                                  so a specific SurveyOrchestrator step can
                                  delegate its work by construction kwargs
                                  alone (StepInfo.static_kwargs' existing
                                  convention) — no new surveyor subclass
                                  needed per delegated request_type.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from resource_explorer.rfa_egeria_sync import _egeria_connection_kwargs
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import (
    Annotation,
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
)

log = logging.getLogger(__name__)

# ActivityStatus symbolic names (Egeria's EngineActionElement.actionStatus)
# that mean "still running" — anything else is terminal. Confirmed against
# GovernanceActionStatus.java's enum table (docs/re-as-engine-host-plan.md's
# research): REQUESTED/APPROVED/WAITING/ACTIVATING/IN_PROGRESS precede a
# terminal ACTIONED(->COMPLETED)/INVALID/IGNORED outcome.
_ACTIVE_STATUSES = {"REQUESTED", "APPROVED", "WAITING", "ACTIVATING", "IN_PROGRESS"}
# Terminal statuses that count as success for annotation purposes. Egeria's
# own "ACTIONED" maps to ActivityStatus.COMPLETED per the enum table, but
# both symbolic names are accepted defensively since which one actually
# appears on the wire wasn't live-verified as part of this build.
_SUCCESS_STATUSES = {"COMPLETED", "ACTIONED"}

DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_TIMEOUT_SECONDS = 300.0


class EgeriaEngineActionTimeoutError(RuntimeError):
    """Raised when a delegated engine action does not reach a terminal
    status within the configured timeout. The action itself is left
    running in Egeria — this only means RE gave up waiting for it; the
    action is not cancelled."""


def _get_clients():
    """Construct (AutomatedCuration, MetadataExpert) clients, bearer-tokened
    — mirrors rfa_egeria_sync._get_clients()'s construction pattern exactly
    (same env-var-driven connection helper, same create_egeria_bearer_token
    dance), kept as its own local helper rather than shared since these two
    modules otherwise have no coupling."""
    from pyegeria import AutomatedCuration, MetadataExpert

    view_server, platform_url, user_id, user_password = _egeria_connection_kwargs()
    automated_curation = AutomatedCuration(view_server, platform_url, user_id, user_password)
    automated_curation.create_egeria_bearer_token(user_id, user_password)
    metadata_expert = MetadataExpert(view_server, platform_url, user_id, user_password)
    metadata_expert.create_egeria_bearer_token(user_id, user_password)
    return automated_curation, metadata_expert


def _poll_action_status(
    metadata_expert, engine_action_guid: str, poll_interval: float, timeout: float
) -> tuple[str, str]:
    """Poll get_metadata_element_by_guid() until the engine action reaches
    a terminal ActivityStatus, or raise EgeriaEngineActionTimeoutError.
    Returns (final_status, completion_message).

    Uses the raw typed elementProperties.propertyValueMap shape (same as
    rfa_egeria_sync's pre-update_asset ToDo verification) rather than a
    flattened report-spec read — get_metadata_element_by_guid is a single-
    element point lookup with no pagination concerns, the simplest correct
    tool for polling one known GUID.
    """
    deadline = time.monotonic() + timeout
    status = "UNKNOWN"
    while True:
        element = metadata_expert.get_metadata_element_by_guid(engine_action_guid)
        prop_map: dict[str, Any] = {}
        if isinstance(element, dict):
            prop_map = (element.get("elementProperties") or {}).get("propertyValueMap") or {}
        status = (prop_map.get("actionStatus") or {}).get("symbolicName", "UNKNOWN")

        if status not in _ACTIVE_STATUSES:
            completion_message = (prop_map.get("completionMessage") or {}).get("primitiveValue", "")
            return status, completion_message

        if time.monotonic() >= deadline:
            raise EgeriaEngineActionTimeoutError(
                f"Engine action {engine_action_guid} still {status} after {timeout}s"
            )
        time.sleep(poll_interval)


def initiate_and_wait(
    *,
    qualified_name: str,
    display_name: str,
    description: str,
    request_type: str,
    domain_identifier: int = 0,
    request_parameters: dict[str, str] | None = None,
    action_targets: list[dict] | None = None,
    request_source_guids: list[str] | None = None,
    received_guards: list[str] | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, str, str]:
    """Trigger a single Egeria governance/survey action service via
    AutomatedCuration.initiate_engine_action() and block until it reaches
    a terminal status, or the timeout elapses.

    Returns (engine_action_guid, final_status, completion_message).
    Raises EgeriaEngineActionTimeoutError on timeout, or a plain exception
    if initiation itself fails (bad request_type, connection failure, …) —
    callers that want "never raise" semantics (e.g. a BaseSurveyor) must
    catch both explicitly; this primitive itself stays honest about
    failure rather than swallowing it.
    """
    automated_curation, metadata_expert = _get_clients()
    guid = automated_curation.initiate_engine_action(
        qualified_name=qualified_name,
        domain_identifier=domain_identifier,
        display_name=display_name,
        description=description,
        request_source_guids=request_source_guids or [],
        action_targets=action_targets or [],
        received_guards=received_guards or [],
        request_type=request_type,
        request_parameters=request_parameters or {},
    )
    if not guid or guid == "Action not initiated":
        raise RuntimeError(
            f"Egeria did not initiate an engine action for request_type={request_type!r} "
            f"(qualified_name={qualified_name!r})"
        )
    status, completion_message = _poll_action_status(metadata_expert, guid, poll_interval, timeout)
    return guid, status, completion_message


class EgeriaDelegatedStepSurveyor(BaseSurveyor):
    """A SurveyOrchestrator step whose actual work happens on a real Egeria
    governance/survey engine instead of locally in RE. Parameterized
    entirely via constructor kwargs, matching StepInfo.static_kwargs'
    existing convention — registering a real delegated step in
    STEP_REGISTRY is just naming the target request_type, no new surveyor
    subclass needed per delegated step. Never raises; failures (including
    a timeout) become a RequestForActionAnnotation via BaseSurveyor._warn,
    matching every other surveyor's contract.
    """

    def __init__(
        self,
        project,
        registry,
        *,
        request_type: str,
        display_name: str = "",
        description: str = "",
        request_parameters: dict[str, str] | None = None,
        action_targets: list[dict] | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(project, registry)
        self._request_type = request_type
        self._display_name = display_name or f"RE-delegated: {request_type}"
        self._description = description
        self._request_parameters = request_parameters or {}
        self._action_targets = action_targets or []
        self._poll_interval = poll_interval
        self._timeout = timeout

    @property
    def step_name(self) -> str:
        return f"EgeriaDelegatedStep[{self._request_type}]"

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        qualified_name = (
            f"EngineAction::{self.project.slug}::{self._request_type}::{int(time.time())}"
        )
        try:
            guid, status, completion_message = initiate_and_wait(
                qualified_name=qualified_name,
                display_name=self._display_name,
                description=self._description
                or f"Delegated from Resource Explorer for {self.project.slug}",
                request_type=self._request_type,
                request_parameters=self._request_parameters,
                action_targets=self._action_targets,
                poll_interval=self._poll_interval,
                timeout=self._timeout,
            )
        except EgeriaEngineActionTimeoutError as exc:
            self._warn(results, str(exc))
            return results
        except Exception as exc:
            self._warn(
                results, f"Could not delegate {self._request_type} to Egeria: {exc}"
            )
            return results

        if status in _SUCCESS_STATUSES:
            results.append(
                ResourceMeasureAnnotation(
                    summary=f"Delegated Egeria action ({self._request_type}) completed: {status}",
                    analysis_step=self.step_name,
                    source="egeria",
                    resource_properties={
                        "engine_action_guid": guid,
                        "final_status": status,
                        "request_type": self._request_type,
                    },
                )
            )
        else:
            results.append(
                RequestForActionAnnotation(
                    summary=(
                        f"Delegated Egeria action ({self._request_type}) did not "
                        f"complete successfully: {status}"
                    ),
                    analysis_step=self.step_name,
                    action_requested="Review the engine action in Egeria",
                    action_target_name=guid,
                    explanation=completion_message or f"Final status: {status}",
                    confidence=50,
                    source="egeria",
                )
            )
        return results
