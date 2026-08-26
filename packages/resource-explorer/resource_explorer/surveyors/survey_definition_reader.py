"""
Reads "Survey Definitions" from Egeria — GovernanceActionProcess elements chained
to GovernanceActionType/GovernanceActionProcessStep steps via first/next-step
relationships — and parses them into a simple, ordered structure RE can execute
against.

Survey Definitions are authored *outside* RE entirely (as Dr.Egeria plans, see
docs/egeria-collaboration-and-survey-model.md section 6). This module is
read-only for authoring — it never creates a Survey Definition or its steps.
One narrow exception: reconcile_step_links() (docs/survey-question-context-plan.md
follow-up) deletes stale/duplicate step-to-step *link relationships* Dr.Egeria's
non-idempotent "Link Next Process Step" command can leave behind on a re-run —
cleanup of a known Dr.Egeria footgun, not new authoring. See
survey_definition_reconciler.py for the diff logic and why this exists.

Fully generic across resource types — this module has no knowledge of database,
repo, or filesystem specifics. Each step's Additional Properties convention keys
(executes_at, supported_technology_type, re_analysis_step) are parsed but not
interpreted here; interpretation is the executor's job.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_DEFAULT_PLATFORM_URL = "https://localhost:9443"
_DEFAULT_VIEW_SERVER = "qs-view-server"
_DEFAULT_USER = "erinoverview"
_DEFAULT_PASSWORD = "secret"

# ── D2/D3 (docs/survey-question-context-plan.md): short-TTL, module-level
# caches — SurveyDefinitionReader is constructed fresh per HTTP request
# (see web/routes/survey_definitions.py's _do()), so instance-level caching
# would never actually persist across requests; these live at module scope
# instead. Two different TTLs on purpose: a Question's Egeria GUID almost
# never changes once authored (long TTL is safe and saves a real lookup
# round-trip), while which Survey Definitions are scoped to it can change
# as Survey Definitions are authored/re-authored (short TTL, minutes not
# hours — matches D3's "Survey Definitions change rarely but not never").
_QUESTION_GUID_CACHE_TTL_SECONDS = 3600
_CANDIDATES_CACHE_TTL_SECONDS = 300
_question_guid_cache: dict[str, tuple[float, str | None]] = {}
_candidates_cache: dict[tuple, tuple[float, list]] = {}
_fetch_cache: dict[str, tuple[float, object]] = {}  # process_guid -> (cached_at, SurveyDefinition)


def clear_caches() -> None:
    """Testing hook — all three module-level caches are otherwise process-lifetime."""
    _question_guid_cache.clear()
    _candidates_cache.clear()
    _fetch_cache.clear()


# pyegeria's lookup helpers signal "nothing matched" by returning a human
# readable *string* ("No elements found") rather than None/"" — a truthy value
# that sails straight through an `or None` guard. Left unchecked it comes back
# as if it were a real GUID: resolve_question_guid() did exactly that, and the
# sentence then reached ClassificationExplorer.get_scoped_elements() as a URL
# path segment, producing a 404 that the caller's broad `except Exception`
# swallowed — so D2's scoped fast path silently degraded to the
# search_string="*" full scan on *every* call, with no error surfaced anywhere.
# Found by profiling the Survey tab, not by a failing test: the test fake
# returned None for a miss, i.e. it was better behaved than the real library.
#
# The rule is deliberately "contains no whitespace" rather than a full
# UUID-shape match. Every one of these sentinels is a human sentence, so
# whitespace catches the whole class; a stricter UUID regex would additionally
# risk rejecting a valid-but-unusually-formatted GUID, and that failure would
# be silent in exactly the same way this one was. Prefer the narrow rule that
# can only reject things a GUID can never be.
def _as_guid(value) -> str | None:
    """Return value if it can be a real Egeria GUID, else None."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or any(ch.isspace() for ch in candidate):
        return None
    return candidate

# Real response shape from GovernanceOfficer.get_governance_action_process_graph
# (renamed from get_governance_process_graph in an upcoming pyegeria release),
# confirmed against a live qs-view-server for both a single-step and a two-step
# chained Survey Definition (2026-07-07/08). This is a genuine graph
# representation — a flat node list plus a separate flat edge list — not a nested tree:
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


def _split_perspectives(raw) -> list:
    """Additional Properties values arrive as a string; accept a list too.

    Egeria stores Additional Properties as strings, so a multi-valued one is a
    separated list by convention. Splits on comma and semicolon, trims, and
    drops blanks -- an author writing "Security, Steward" and one writing
    "Security;Steward" mean the same thing and must not produce a perspective
    literally named " Steward" that matches no filter.
    """
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = str(raw).replace(";", ",").split(",")
    seen: list = []
    for v in values:
        v = str(v).strip()
        if v and v not in seen:
            seen.append(v)
    return seen


class SurveyDefinitionReaderError(RuntimeError):
    """Raised when a Survey Definition can't be read, or is missing required data."""


class UnsupportedSurveyDefinitionError(SurveyDefinitionReaderError):
    """Raised when a fetched Survey Definition has a shape RE's executor can't run yet
    (e.g. guard-based branching — v1 only supports linear step sequences)."""


@dataclass
class StepLink:
    """One `NextGovernanceActionProcessStep` edge, with the routing values that
    were previously read and thrown away.

    Egeria's model routes on guards: a completing governance service *"optionally
    supplies one or more guards and a list of action targets for the subsequent
    governance action(s) to process"*. The coordinator of the run — a real engine
    host, or RE acting as a pseudo one — reads the step graph, runs a step, takes
    the guard it produced, and picks the next viable step. **Nothing needs to be
    persisted for that**; the guard is a routing signal held for the duration of
    the run, not an artifact recorded against the process.

    That reframing (Dan, 2026-08-24) retires the open question the backlog
    carried as "whether a locally-produced guard can be recorded against the
    process at all, given RE acts as its own engine host". It was the wrong
    question: recording is optional, coordinating is the point.
    """
    previous_guid: str
    next_guid: str
    guard: str = ""
    mandatory_guard: bool = False


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
    # 0462 attributes on GovernanceActionProcessStep itself. Present in the
    # payload and previously dropped on the floor — `producedGuards` is the
    # authored declaration of what this step can emit, which is what a
    # coordinator needs in order to know a guard is expected at all.
    produced_guards: list = field(default_factory=list)
    wait_time: int | None = None
    ignore_multiple_triggers: bool = False
    # Data flowing INTO this step. §0462 puts these on the
    # `GovernanceActionExecutor` relationship (`requestParameters`,
    # `requestParameterMap`/`Filter`, `actionTargetMap`/`Filter`) rather than on
    # the step entity, so whether they arrive depends on what the process-graph
    # API returns. Populated when present; left empty when not — and
    # `executor_present` says which, so an empty dict is never mistaken for
    # "this step declares no parameters".
    request_parameters: dict = field(default_factory=dict)
    action_targets: list = field(default_factory=list)
    executor_present: bool = False


@dataclass
class SurveyDefinition:
    process_guid: str
    display_name: str
    qualified_name: str
    supported_technology_type: str | None
    steps: list = field(default_factory=list)  # list[SurveyStep], in execution order
    # list[StepLink] — the step-to-step edges WITH their guards. `steps` is the
    # linear execution order v1 runs; `links` is the authored topology, kept
    # whole so a coordinator can route on guards without re-fetching. Populated
    # even while the executor only walks a line.
    links: list = field(default_factory=list)
    description: str = ""  # author-provided, from Egeria's own Description attribute
    # Which UI surface this Survey Definition is meant for — "scouting" |
    # "discovery" | "automate_full" | ... — Additional Properties convention,
    # see dr_egeria_survey_publisher.render_process_block's docstring and
    # docs/discovery-automate-project-context-plan.md Part 1. None for
    # Survey Definitions authored before this convention existed.
    survey_kind: str | None = None
    #: Perspectives this survey is authored FOR, declared in Additional
    #: Properties as a comma-separated list (same convention survey_kind uses).
    #: Empty when the author declared none — callers then derive them from the
    #: survey's steps, which is a weaker but honest answer. Kept distinct from
    #: derived values so "the author said so" and "we worked it out" never merge.
    perspectives: list = field(default_factory=list)


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
        self._classification_explorer = None
        self._metadata_expert = None

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

    def _connect_classification_explorer(self):
        """Lazy, separate from connect() — only the D2 scoped-query path
        needs ClassificationExplorer (add_scope_to_element/get_scoped_elements/
        get_guid_for_name), so every other reader method stays unaffected if
        this client fails to construct for any reason."""
        if self._classification_explorer is not None:
            return self._classification_explorer
        from pyegeria.omvs.classification_explorer import ClassificationExplorer

        client = ClassificationExplorer(self.view_server, self.platform_url, self.user_id, self.user_password)
        client.create_egeria_bearer_token(self.user_id, self.user_password)
        self._classification_explorer = client
        return client

    def _connect_metadata_expert(self):
        """Lazy, separate from connect() — only reconcile_step_links() needs
        MetadataExpert.delete_related_elements(), the generic relationship-
        delete method (no dedicated "unlink process step" method exists in
        pyegeria — confirmed while building this)."""
        if self._metadata_expert is not None:
            return self._metadata_expert
        from pyegeria.omvs.metadata_expert import MetadataExpert

        client = MetadataExpert(self.view_server, self.platform_url, self.user_id, self.user_password)
        client.create_egeria_bearer_token(self.user_id, self.user_password)
        self._metadata_expert = client
        return client

    # ── discovery: find candidate Survey Definitions by Technology Type ────────

    def find_candidate_process_guids(self, technology_type: str, survey_kind: str | None = None) -> list:
        """Return every GovernanceActionProcess whose additionalProperties declare
        supported_technology_type == technology_type.

        survey_kind, when given, additionally filters to Survey Definitions
        whose Additional Properties declare that exact survey_kind — e.g. a
        Discovery-tier caller passes survey_kind="discovery" so an
        Automate-tier "run everything" bundle (survey_kind="automate_full")
        or a Scouting-tier coarse scan doesn't show up as a Discovery
        candidate. None (default) keeps the old behavior — every Survey
        Definition for the technology type, regardless of kind — for
        backward compatibility with callers that don't care (and with
        Survey Definitions authored before this convention existed, which
        have no survey_kind at all).

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

        D3-cached (docs/survey-question-context-plan.md) — this is the full
        `search_string="*"` scan D2's scoped path exists to avoid on the hot
        path, but it's kept as an explicit fallback (D2's own docstring), so
        it still deserves the same short-TTL cache rather than re-scanning
        every GovernanceActionProcess on every call.
        """
        cache_key = ("full_scan", technology_type, survey_kind)
        now = time.monotonic()
        cached = _candidates_cache.get(cache_key)
        if cached is not None and now - cached[0] < _CANDIDATES_CACHE_TTL_SECONDS:
            return cached[1]

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
                # graph_query_depth=0 is the single biggest lever on Survey-tab
                # load time: pyegeria defaults it to 3, which makes Egeria expand
                # each returned element's related-element graph 3 hops deep. This
                # loop reads nothing but element-local fields
                # (additionalProperties/qualifiedName/displayName + the header
                # GUID), so every one of those traversals was pure waste.
                # Measured live against a real server, 406 GovernanceActionProcess
                # elements: depth 3 = 18.9s, depth 1 = 18.9s, depth 0 = 0.20s
                # (~94x) — and all three return byte-identical results, same 406
                # elements and same 4 matching candidates. Note depth 1 costs the
                # same as 3: the cliff is "any traversal at all," not its depth,
                # so this must stay 0 rather than merely being lowered.
                # Per-step detail still costs a graph query, but that's paid
                # per-candidate in fetch(), only for the handful that matched.
                graph_query_depth=0,
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
                if survey_kind is not None and additional.get("survey_kind") != survey_kind:
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
            return candidates  # don't cache a failure — next call should retry live

        _candidates_cache[cache_key] = (now, candidates)
        return candidates

    # ── D2 (docs/survey-question-context-plan.md): scoped candidate lookup ──

    def resolve_question_guid(self, question_display_name: str) -> str | None:
        """Resolve a Question glossary term's GUID by its display name —
        long-TTL cached (Question terms are stable once authored via
        docs/dr-egeria/scouting-questions.md and siblings). Returns None if
        not found or on any lookup error (best-effort; a missing Question
        just means D2's scoped lookup contributes nothing for it, not a
        hard failure — the caller falls back to the full scan)."""
        now = time.monotonic()
        cached = _question_guid_cache.get(question_display_name)
        if cached is not None and now - cached[0] < _QUESTION_GUID_CACHE_TTL_SECONDS:
            return cached[1]

        guid: str | None = None
        try:
            client = self._connect_classification_explorer()
            guid = _as_guid(client.get_guid_for_name(
                question_display_name,
                property_name=["displayName"],
                type_name="GlossaryTerm",
            ))
        except Exception as exc:
            log.debug("resolve_question_guid(%r) failed: %s", question_display_name, exc)

        _question_guid_cache[question_display_name] = (now, guid)
        return guid

    def find_candidate_process_guids_by_questions(
        self, questions: list[str], technology_type: str, survey_kind: str | None = None,
    ) -> list:
        """D2's scoped alternative to find_candidate_process_guids()'s
        search_string="*" full-instance scan: given the Questions relevant
        to a phase/perspective (from question_catalog_reader.get_questions()),
        resolve each to its Egeria GUID and call
        ClassificationExplorer.get_scoped_elements(question_guid) — which
        returns every element linked via ScopedBy to that Question,
        constrained server-side to GovernanceActionProcess via
        metadataElementTypeName. Unions results across questions
        (a Survey Definition can answer more than one), dedupes by guid,
        then applies the same supported_technology_type/survey_kind filter
        find_candidate_process_guids() does — Additional Properties aren't
        part of the ScopedBy query itself, still need client-side filtering.

        Returns [] (not an error) if no question resolves to a real GUID —
        the caller decides whether to fall back to the full scan."""
        question_guids = [g for g in (self.resolve_question_guid(q) for q in questions) if g]
        if not question_guids:
            return []

        cache_key = (tuple(sorted(question_guids)), technology_type, survey_kind)
        now = time.monotonic()
        cached = _candidates_cache.get(cache_key)
        if cached is not None and now - cached[0] < _CANDIDATES_CACHE_TTL_SECONDS:
            return cached[1]

        by_guid: dict[str, dict] = {}
        try:
            client = self._connect_classification_explorer()
            for question_guid in question_guids:
                results = client.get_scoped_elements(
                    question_guid,
                    page_size=1000,
                    body={"class": "ResultsRequestBody", "metadataElementTypeName": "GovernanceActionProcess"},
                )
                if isinstance(results, str):
                    continue  # pyegeria returns a string ("No elements found") when empty
                for el in results or []:
                    props = el.get("properties", {}) or {}
                    additional = props.get("additionalProperties", {}) or {}
                    if additional.get("supported_technology_type") != technology_type:
                        continue
                    if survey_kind is not None and additional.get("survey_kind") != survey_kind:
                        continue
                    qn = props.get("qualifiedName")
                    if not qn:
                        continue
                    header = el.get("elementHeader", {}) or {}
                    guid = header.get("guid", "")
                    by_guid[guid] = {
                        "qualified_name": qn,
                        "display_name": props.get("displayName", qn),
                        "guid": guid,
                    }
        except Exception as exc:
            log.debug("find_candidate_process_guids_by_questions failed: %s", exc)
            return []

        candidates = list(by_guid.values())
        _candidates_cache[cache_key] = (now, candidates)
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

        D3-cached (docs/survey-question-context-plan.md) — same short TTL as
        the candidates caches, since this is the second live call per
        candidate the plan doc identified as part of the slow-Discovery-load
        root cause.
        """
        now = time.monotonic()
        cached = _fetch_cache.get(process_guid)
        if cached is not None and now - cached[0] < _CANDIDATES_CACHE_TTL_SECONDS:
            return cached[1]

        self.connect()
        raw = self._governance_officer.get_governance_action_process_graph(
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
        survey_def = self._parse_graph(graph)
        _fetch_cache[process_guid] = (now, survey_def)
        return survey_def

    # ── reconciliation: fix Dr.Egeria's non-idempotent Link commands ──────────

    def reconcile_step_links(self, process_guid: str, survey_group: str, step_keys: list[str], dry_run: bool = False):
        """Delete stale/duplicate step-to-step link relationships against
        live Egeria — see survey_definition_reconciler.py's module docstring
        for the full incident this exists to fix and prevent from
        recurring. Always fetches live (bypasses the fetch cache — reconciling
        against a stale cached graph would be pointless), and busts
        _fetch_cache for process_guid afterward so a subsequent .fetch()
        sees the reconciled graph rather than a pre-reconciliation cache hit.

        Returns a survey_definition_reconciler.ReconcileResult. Safe to call
        repeatedly — a fully-reconciled process is a no-op every time after
        the first."""
        from resource_explorer.surveyors.survey_definition_reconciler import compute_expected_edges, diff_links

        self.connect()
        process_qualified_name = f"GovActionProcess::{survey_group}"
        expected_edges = compute_expected_edges(survey_group, step_keys)

        try:
            raw = self._governance_officer.get_governance_action_process_graph(guid=process_guid, output_format="JSON")
            if isinstance(raw, str):
                import json as _json
                raw = _json.loads(raw)
            graph = raw.get("elementGraph") if isinstance(raw, dict) and "elementGraph" in raw else raw
            links = (graph or {}).get("processStepLinks") or []
        except Exception as exc:
            from resource_explorer.surveyors.survey_definition_reconciler import ReconcileResult
            return ReconcileResult(process_qualified_name=process_qualified_name, error=str(exc))

        result = diff_links(links, expected_edges, process_qualified_name)

        if not dry_run and result.to_remove:
            metadata_expert = self._connect_metadata_expert()
            # deleteMethod explicit and required — real pyegeria bug, tracked
            # as egeria-python's PYEGERIA_ISSUES.md ISSUE-63: unfixed,
            # metadata_expert.delete_related_elements() routed through
            # OpenMetadataDeleteRequestBody, which declared no deleteMethod
            # field at all, so a {"deleteMethod": "SOFT_DELETE"} key was
            # silently dropped by pydantic validation (PyegeriaModel's
            # extra='ignore') before the request ever reached the server —
            # every relationship this method deletes is a plain step-to-step
            # link with no lineage semantics, so the server's own default
            # (LookForLineage) was always rejected outright
            # (OMAG-COMMON-400-032) with no way to override it. Fixed
            # upstream (pyegeria >=6.0.18.x, confirmed live): the method now
            # routes through DeleteRelationshipRequestBody, which does
            # declare delete_method, so an explicit value here actually
            # reaches the server. The previous workaround here bypassed
            # pyegeria's model validation entirely via a raw
            # _async_make_request() call — no longer needed, removed.
            delete_body = {"class": "DeleteRelationshipRequestBody", "deleteMethod": "SOFT_DELETE"}
            for entry in result.to_remove:
                if not entry.link_guid:
                    continue
                try:
                    metadata_expert.delete_related_elements(entry.link_guid, body=delete_body)
                except Exception as exc:
                    log.warning(
                        "reconcile_step_links: failed to delete %s link %s -> %s (guid=%s): %s",
                        entry.reason, entry.prev_qualified_name, entry.next_qualified_name, entry.link_guid, exc,
                    )
            _fetch_cache.pop(process_guid, None)

        return result

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

        # Guards were previously read and discarded here: the payload carries
        # `guard` and `mandatoryGuard` on every link, a live read of Analysis
        # Survey returns them on all 9, and only the two GUIDs were kept. They
        # are what a coordinator routes on, so they are kept now — see StepLink.
        edges: dict = {}
        links: list = []
        for link in graph.get(_LINKS_KEY) or []:
            prev_guid = (link.get("previousProcessStep") or {}).get("guid")
            next_guid = (link.get("nextProcessStep") or {}).get("guid")
            if prev_guid and next_guid:
                edges.setdefault(prev_guid, []).append(next_guid)
                links.append(StepLink(
                    previous_guid=prev_guid, next_guid=next_guid,
                    guard=link.get("guard") or "",
                    mandatory_guard=bool(link.get("mandatoryGuard") or False),
                ))

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
            links=links,
            description=process_props.get("description", ""),
            survey_kind=process_additional.get("survey_kind"),
            perspectives=_split_perspectives(process_additional.get("perspectives")),
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

        executor = (element.get("governanceActionExecutor")
                    or props.get("governanceActionExecutor") or {})
        return SurveyStep(
            guid=header.get("guid", ""),
            display_name=props.get("displayName", qn),
            qualified_name=qn,
            additional_properties=additional,
            executes_at=executes_at,
            re_analysis_step=additional.get("re_analysis_step"),
            supported_technology_type=additional.get("supported_technology_type"),
            description=props.get("description", ""),
            produced_guards=list(props.get("producedGuards") or []),
            wait_time=props.get("waitTime"),
            ignore_multiple_triggers=bool(props.get("ignoreMultipleTriggers") or False),
            request_parameters=dict(executor.get("requestParameters") or {}),
            action_targets=list(executor.get("actionTargets")
                                or element.get("actionTargets") or []),
            executor_present=bool(executor),
        )
