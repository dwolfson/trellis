"""
Reads "Survey Definitions" from Egeria — GovernanceActionProcess elements chained
to GovernanceActionType/GovernanceActionProcessStep steps via first/next-step
relationships — and parses them into a simple, ordered structure RE can execute
against.

Survey Definitions are authored *outside* RE entirely (as Dr.Egeria plans, see
docs/egeria-collaboration-and-survey-model.md section 6). This module only reads
what's already in Egeria's catalog; it never creates or modifies these elements.

Fully generic across resource types — this module has no knowledge of database,
repo, or filesystem specifics. Each step's Additional Properties convention keys
(executes_at, supported_technology_type, re_analysis_step) are parsed but not
interpreted here; interpretation is the executor's job.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_DEFAULT_PLATFORM_URL = "https://localhost:9443"
_DEFAULT_VIEW_SERVER = "qs-view-server"
_DEFAULT_USER = "erinoverview"
_DEFAULT_PASSWORD = "secret"

# Real response shape from GovernanceOfficer.get_governance_process_graph, confirmed
# against a live qs-view-server for both a single-step and a two-step chained
# Survey Definition (2026-07-07/08). This is a genuine graph representation —
# a flat node list plus a separate flat edge list — not a nested tree:
#
#   {
#     "governanceActionProcess": {"elementHeader": {...}, "properties": {...}},
#     "firstProcessStep": {
#       "element": {"elementHeader": {...}, "processStepProperties": {...}},
#       "linkGUID": "..."
#     },
#     "nextProcessSteps": [
#       {"elementHeader": {...}, "processStepProperties": {...}},   # flat, no "element" wrapper
#       ...
#     ],
#     "processStepLinks": [
#       {
#         "previousProcessStep": {"guid": "...", "uniqueName": "...", ...},  # ElementStub
#         "nextProcessStep": {"guid": "...", "uniqueName": "...", ...},      # ElementStub
#         "nextProcessStepLinkGUID": "...",
#         "mandatoryGuard": false,
#         "guard": "..."   # present only when a guard value was actually set
#       },
#       ...
#     ],
#     "governanceActionProcessMermaidGraph": "..."
#   }
#
# Notes this corrects vs. earlier, unconfirmed guesses: there is no
# "relationshipHeader"/"type"/"typeName" wrapper anywhere in this response; a
# step's own properties live under "processStepProperties", not "properties"
# (only the process element itself uses "properties"); "nextProcessSteps" is a
# flat list of every non-first step in the whole process (not nested per
# predecessor, and not wrapped in "element" the way firstProcessStep is); and
# the actual step-to-step topology (including branching) is only in
# "processStepLinks", keyed by GUID via "previousProcessStep"/"nextProcessStep".
_PROCESS_KEY = "governanceActionProcess"
_FIRST_STEP_KEY = "firstProcessStep"
_NEXT_STEPS_KEY = "nextProcessSteps"
_LINKS_KEY = "processStepLinks"


class SurveyDefinitionReaderError(RuntimeError):
    """Raised when a Survey Definition can't be read, or is missing required data."""


class UnsupportedSurveyDefinitionError(SurveyDefinitionReaderError):
    """Raised when a fetched Survey Definition has a shape RE's executor can't run yet
    (e.g. guard-based branching — v1 only supports linear step sequences)."""


@dataclass
class SurveyStep:
    guid: str
    display_name: str
    qualified_name: str
    additional_properties: dict = field(default_factory=dict)
    executes_at: str = ""
    re_analysis_step: str | None = None
    supported_technology_type: str | None = None
    description: str = ""  # author-provided, from Egeria's own Description attribute


@dataclass
class SurveyDefinition:
    process_guid: str
    display_name: str
    qualified_name: str
    supported_technology_type: str | None
    steps: list = field(default_factory=list)  # list[SurveyStep], in execution order
    description: str = ""  # author-provided, from Egeria's own Description attribute


class SurveyDefinitionReader:
    """Fetches Survey Definitions from Egeria via pyegeria's GovernanceOfficer/AutomatedCuration clients."""

    def __init__(
        self,
        platform_url: str | None = None,
        view_server: str | None = None,
        user_id: str | None = None,
        user_password: str | None = None,
    ) -> None:
        self.platform_url = platform_url or os.getenv("EGERIA_PLATFORM_URL", _DEFAULT_PLATFORM_URL)
        self.view_server = view_server or os.getenv("EGERIA_VIEW_SERVER", _DEFAULT_VIEW_SERVER)
        self.user_id = user_id or os.getenv("EGERIA_USER", _DEFAULT_USER)
        self.user_password = user_password or os.getenv("EGERIA_USER_PASSWORD", _DEFAULT_PASSWORD)
        self._governance_officer = None
        self._automated_curation = None

    # ── connection ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Establish pyegeria client connections (lazy)."""
        if self._governance_officer is not None:
            return
        if not self.platform_url:
            raise SurveyDefinitionReaderError(
                "EGERIA_PLATFORM_URL is not set. "
                "Set it in .env or pass platform_url= to SurveyDefinitionReader."
            )
        try:
            from pyegeria import AutomatedCuration
            from pyegeria.omvs.governance_officer import GovernanceOfficer

            self._governance_officer = GovernanceOfficer(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._governance_officer.create_egeria_bearer_token(self.user_id, self.user_password)

            self._automated_curation = AutomatedCuration(
                self.view_server, self.platform_url, self.user_id, self.user_password
            )
            self._automated_curation.create_egeria_bearer_token(self.user_id, self.user_password)
        except ImportError as exc:
            raise SurveyDefinitionReaderError("pyegeria is not installed.") from exc
        except Exception as exc:
            raise SurveyDefinitionReaderError(
                f"Could not connect to Egeria at {self.platform_url}: {exc}"
            ) from exc

    # ── discovery: find candidate Survey Definitions by Technology Type ────────

    def find_candidate_process_guids(self, technology_type: str) -> list:
        """Return every GovernanceActionProcess whose additionalProperties declare
        supported_technology_type == technology_type.

        Confirmed live (2026-07-08) that `AutomatedCuration.get_tech_type_detail`
        — the mechanism this originally used, copied from `EgeriaDatabaseSurveyor.
        _find_survey_process_name` — queries Egeria's real Technology Type /
        Deployed Implementation Type catalog. That catalog has no entry for
        user-authored Survey Definitions at all (Dr.Egeria's `Create Governance
        Action Process` only sets a plain `additionalProperties` string; it never
        links the process into that catalog), so `get_tech_type_detail` returned
        "No elements found" for a Survey Definition that demonstrably exists.
        `_find_survey_process_name` may still be the right tool for finding
        Egeria's own *native* survey processes (which genuinely are catalogued
        there) — this method is specifically for RE's own additionalProperties
        convention, which is a different, simpler mechanism: list every
        GovernanceActionProcess (via `GovernanceOfficer.find_governance_definitions`,
        `metadata_element_type="GovernanceActionProcess"`) and filter client-side
        by the additionalProperties value.

        Each item: {qualified_name, display_name, guid}. Does NOT assume there is
        exactly one — the caller decides what to do with zero/one/many.
        """
        self.connect()
        candidates = []
        try:
            # page_size is generous but not exhaustive — a server with more than
            # this many GovernanceActionProcess elements (most are unrelated
            # system processes, e.g. "Create Subscription" jobs) would need real
            # pagination here; not yet implemented.
            results = self._governance_officer.find_governance_definitions(
                search_string="*",
                metadata_element_type="GovernanceActionProcess",
                output_format="JSON",
                page_size=1000,
            )
            if isinstance(results, str):
                import json as _json
                results = _json.loads(results)
            if not isinstance(results, list):
                return []

            for el in results:
                props = el.get("properties", {}) or {}
                additional = props.get("additionalProperties", {}) or {}
                if additional.get("supported_technology_type") != technology_type:
                    continue
                qn = props.get("qualifiedName")
                if not qn:
                    continue
                header = el.get("elementHeader", {}) or {}
                candidates.append(
                    {
                        "qualified_name": qn,
                        "display_name": props.get("displayName", qn),
                        "guid": header.get("guid", ""),
                    }
                )
        except Exception as exc:
            log.debug("find_candidate_process_guids failed for %s: %s", technology_type, exc)
        return candidates

    def find_process_guid_by_name(self, name_or_qualified_name: str) -> str | None:
        """Resolve an explicit Survey Definition reference (name or qualifiedName) to a GUID."""
        self.connect()
        try:
            results = self._governance_officer.get_governance_definitions_by_name(
                name=name_or_qualified_name, output_format="JSON"
            )
            if isinstance(results, str):
                import json as _json
                results = _json.loads(results)
            if isinstance(results, list):
                for el in results:
                    header = el.get("elementHeader", {})
                    if header.get("type", {}).get("typeName") == "GovernanceActionProcess":
                        return header.get("guid")
        except Exception as exc:
            log.debug("get_governance_definitions_by_name failed: %s", exc)

        try:
            results = self._governance_officer.find_governance_definitions(
                search_string=name_or_qualified_name,
                starts_with=True,
                output_format="JSON",
            )
            if isinstance(results, str):
                import json as _json
                results = _json.loads(results)
            if isinstance(results, list) and results:
                header = results[0].get("elementHeader", {})
                return header.get("guid")
        except Exception as exc:
            log.debug("find_governance_definitions failed: %s", exc)
        return None

    # ── fetch + parse the step graph ────────────────────────────────────────────

    def fetch(self, process_guid: str) -> SurveyDefinition:
        """Fetch a Survey Definition's full step graph from Egeria and parse it.

        Raises UnsupportedSurveyDefinitionError if the graph branches (v1 only
        supports linear step sequences), or SurveyDefinitionReaderError if any
        step is missing executes_at in its Additional Properties.
        """
        self.connect()
        raw = self._governance_officer.get_governance_process_graph(
            guid=process_guid, output_format="JSON"
        )
        if isinstance(raw, str):
            import json as _json
            raw = _json.loads(raw)
        graph = raw.get("elementGraph") if isinstance(raw, dict) and "elementGraph" in raw else raw
        if not isinstance(graph, dict):
            raise SurveyDefinitionReaderError(
                f"Unexpected response fetching Survey Definition graph for {process_guid}"
            )
        return self._parse_graph(graph)

    def _parse_graph(self, graph: dict) -> SurveyDefinition:
        """Side-effect-free: turns a raw graph JSON dict into a SurveyDefinition.

        This is the unit-testable seam — exercise it directly with canned JSON,
        no live server needed.
        """
        process_element = graph.get(_PROCESS_KEY, {}) or {}
        process_header = process_element.get("elementHeader", {})
        process_props = process_element.get("properties", {})
        process_guid = process_header.get("guid", "")
        process_qn = process_props.get("qualifiedName", "")
        process_additional = process_props.get("additionalProperties", {}) or {}

        # Build a node index (guid -> raw step element) from firstProcessStep +
        # nextProcessSteps, and an edge index (guid -> [next guids]) from
        # processStepLinks — see the module-level shape comment above.
        nodes: dict = {}
        first_wrapper = graph.get(_FIRST_STEP_KEY)
        first_guid = None
        if first_wrapper is not None:
            first_element = first_wrapper.get("element") or {}
            first_guid = first_element.get("elementHeader", {}).get("guid") or None
            if first_guid:
                nodes[first_guid] = first_element

        for step_element in graph.get(_NEXT_STEPS_KEY) or []:
            guid = step_element.get("elementHeader", {}).get("guid")
            if guid:
                nodes[guid] = step_element

        edges: dict = {}
        for link in graph.get(_LINKS_KEY) or []:
            prev_guid = (link.get("previousProcessStep") or {}).get("guid")
            next_guid = (link.get("nextProcessStep") or {}).get("guid")
            if prev_guid and next_guid:
                edges.setdefault(prev_guid, []).append(next_guid)

        steps: list = []
        seen_guids: set = set()
        current_guid = first_guid
        while current_guid is not None:
            if current_guid in seen_guids:
                raise UnsupportedSurveyDefinitionError(
                    f"Survey Definition {process_qn} contains a cycle at step guid "
                    f"{current_guid} — not supported"
                )
            node = nodes.get(current_guid)
            if node is None:
                raise SurveyDefinitionReaderError(
                    f"Survey Definition {process_qn} references step guid {current_guid} "
                    "with no corresponding node in the graph"
                )
            step = self._parse_step(node)
            seen_guids.add(current_guid)
            steps.append(step)

            next_guids = edges.get(current_guid, [])
            if len(next_guids) > 1:
                raise UnsupportedSurveyDefinitionError(
                    f"Step {step.qualified_name} has {len(next_guids)} outgoing next-steps "
                    "— branching Survey Definitions are not supported yet "
                    "(v1 supports linear sequences only)"
                )
            current_guid = next_guids[0] if next_guids else None

        return SurveyDefinition(
            process_guid=process_guid,
            display_name=process_props.get("displayName", process_qn),
            qualified_name=process_qn,
            supported_technology_type=process_additional.get("supported_technology_type"),
            steps=steps,
            description=process_props.get("description", ""),
        )

    def _parse_step(self, element: dict) -> SurveyStep:
        header = element.get("elementHeader", {})
        # The process element uses "properties"; a process step's own properties
        # live under "processStepProperties" instead — confirmed live, see the
        # module-level shape comment above.
        props = element.get("processStepProperties") or element.get("properties") or {}
        qn = props.get("qualifiedName", "")
        additional = props.get("additionalProperties", {}) or {}

        executes_at = additional.get("executes_at")
        if not executes_at:
            raise SurveyDefinitionReaderError(
                f"Step {qn or header.get('guid', '<unknown>')} has no executes_at "
                "in its Additional Properties — ambiguous, refusing to guess"
            )

        return SurveyStep(
            guid=header.get("guid", ""),
            display_name=props.get("displayName", qn),
            qualified_name=qn,
            additional_properties=additional,
            executes_at=executes_at,
            re_analysis_step=additional.get("re_analysis_step"),
            supported_technology_type=additional.get("supported_technology_type"),
            description=props.get("description", ""),
        )
