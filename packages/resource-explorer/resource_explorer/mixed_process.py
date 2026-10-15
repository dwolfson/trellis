"""Engine host, step 4: one mixed Egeria process, a native survey step chained to an RE step.

Design: `docs/design-notes/SLICE-ENGINE-HOST-STEP4-MIXED-PROCESS.md` (case 2 of
`DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md`, §4.1 "mixed processes").

`GovActionProcess::ResourceExplorer::PostgresSurveyThenDerived` has two steps: Egeria's own PostgreSQL survey
(engine `PostgreSQLSurvey`, Java) and then RE's `re-database-staleness` (RE's engine host), linked by one
`NextGovernanceActionProcessStep` with guard `survey-completed`, mandatory. Egeria evaluates the guard and carries
the action targets; RE runs step 2 exactly as it runs any engine action (`engine_host.py`), reading the step-1
report it is handed as the `surveyReport` action target.

This module holds:

* `MIXED_PROCESSES`, the one registry entry the declaration generator (`scripts/generate_engine_host_declaration.py
  --mixed-process`) renders from, and its test holds the committed document to;
* the reader of an engine action's neighbourhood (`read_action_graph`, one `get_all_related_elements` call) that the
  engine host uses to refuse a step 2 whose previous step did not complete with the link's guard (§5.2 test 4);
* the reader of one process run (`read_process_run`) and the grouping of engine actions into one run line per
  process instance (`group_by_process`, `run_line_words`): M4, what Understanding shows.

Shapes are the ones captured live (read-only) on 2026-10-15, M2: `tests/fixtures/egeria_6_2/engine_action__*` and
`process_instance__*`. What they settled:

* every engine action of a process run carries an `Anchors` classification whose anchor is the
  `GovernanceActionProcessInstance`, and a `processName` that is the instance's qualifiedName
  (`<process qualifiedName>@<start ms>::<uuid>`);
* actions are linked by `ControlFlow` relationships carrying `guard` and `mandatoryGuard` (end 1 = the earlier
  action); the instance links to the FIRST action by `ActionRequester`;
* the native survey service does NOT add a `surveyReport` target to its own action: it passes the report GUID as a new
  action target to the NEXT action, which carries `surveyReport` and the original asset target under the name the
  process was started with (`newAsset` in the native create-and-survey process).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

#: The kind `technology_type_processes.yaml` lists a mixed process under.
KIND_MIXED_PROCESS = "mixed_process"

#: The survey guard a mixed process chains on, and the action-target name a native survey hands the next step.
SURVEY_COMPLETED = "survey-completed"
SURVEY_REPORT_TARGET = "surveyReport"

#: Egeria's terminal "it worked" word for an engine action, and its "still going" words.
_DONE = "COMPLETED"
_ACTIVE = frozenset({"REQUESTED", "APPROVED", "WAITING", "ACTIVATING", "IN_PROGRESS"})

#: An instance is read by following ControlFlow from its first action; a run longer than this is not one RE declared.
MAX_STEPS = 20


@dataclass(frozen=True)
class ProcessStep:
    number: int
    qualified_name: str              # the GovernanceActionProcessStep
    display_name: str
    description: str
    #: The GovernanceActionType this step stands for (the content pack's, or RE's). A process step cannot point at a
    #: type in Egeria; it carries the type's executor instead (`governance_engine` + `request_type`), and names the
    #: type in its Additional Properties.
    governance_action_type: str
    governance_engine: str
    request_type: str
    runs_on: str                     # "egeria" (a Java engine host) | "resource-explorer" (RE's engine host)
    label: str                       # what the run line calls the step

    @property
    def produced_guards(self) -> tuple[str, ...]:
        from resource_explorer.engine_host import SURVEY_GUARDS

        return SURVEY_GUARDS


@dataclass(frozen=True)
class ProcessLink:
    from_step: int
    to_step: int
    guard: str
    mandatory: bool


@dataclass(frozen=True)
class MixedProcess:
    key: str
    qualified_name: str
    display_name: str
    #: The run line's name for the process ("Postgres survey then derived").
    short_name: str
    description: str
    entity_type: str
    steps: tuple[ProcessStep, ...]
    links: tuple[ProcessLink, ...]

    def step(self, number: int) -> ProcessStep:
        return next(s for s in self.steps if s.number == number)

    @property
    def first_step(self) -> ProcessStep:
        return self.step(min(s.number for s in self.steps))

    @property
    def re_steps(self) -> tuple[ProcessStep, ...]:
        return tuple(s for s in self.steps if s.runs_on == "resource-explorer")


def _postgres_survey_then_derived() -> MixedProcess:
    from resource_explorer import engine_host as eh

    qn = "GovActionProcess::ResourceExplorer::PostgresSurveyThenDerived"
    step_qn = "GovActionProcessStep::ResourceExplorer::PostgresSurveyThenDerived::"
    derive_rt = "re-database-staleness"
    return MixedProcess(
        key="postgres_survey_then_derived",
        qualified_name=qn,
        display_name="Postgres survey then derived",
        short_name="Postgres survey then derived",
        description=("Egeria's own PostgreSQL survey of the database, then Resource Explorer's database staleness "
                     "derived from the report that survey just wrote. Step 2 runs only when step 1 completes "
                     "survey-completed."),
        entity_type="database",
        steps=(
            ProcessStep(1, step_qn + "1-PostgreSQLSurvey", "Postgres survey then derived — 1 PostgreSQL survey",
                        "Egeria's native PostgreSQL database survey (Java, the content pack's PostgreSQLSurvey "
                        "engine).",
                        # The content pack's type, as RE's own Run initiates it (technology_type_processes.yaml);
                        # its executor read live (M2, 2026-10-15): engine PostgreSQLSurvey, survey-postgres-database.
                        governance_action_type="PostgreSQLSurvey::survey-postgres-database",
                        governance_engine="PostgreSQLSurvey", request_type="survey-postgres-database",
                        runs_on="egeria", label="PostgreSQLSurvey"),
            ProcessStep(2, step_qn + "2-" + derive_rt, "Postgres survey then derived — 2 database staleness",
                        "Resource Explorer's database staleness, derived from step 1's survey report (the "
                        "surveyReport action target). Run by Resource Explorer's engine host.",
                        governance_action_type=eh.governance_action_type_qn_for(derive_rt),
                        governance_engine=eh.ENGINE_QUALIFIED_NAME, request_type=derive_rt,
                        runs_on="resource-explorer", label=derive_rt),
        ),
        links=(ProcessLink(1, 2, SURVEY_COMPLETED, True),),
    )


#: The mixed processes RE declares. One in this slice (§5.4: re-db-derived as step 2 is step 5).
MIXED_PROCESSES: dict[str, MixedProcess] = {"postgres_survey_then_derived": _postgres_survey_then_derived()}


def by_qualified_name(qualified_name: str) -> MixedProcess | None:
    return next((p for p in MIXED_PROCESSES.values() if p.qualified_name == qualified_name), None)


def process_for_instance_name(process_name: str) -> MixedProcess | None:
    """The declared process an instance's qualifiedName (`<process QN>@<start>::<uuid>`) belongs to."""
    return by_qualified_name((process_name or "").split("@", 1)[0])


def source_report_steps() -> frozenset[str]:
    """The request types of RE steps that derive from the previous step's report (`surveyReport` target)."""
    return frozenset(s.request_type for p in MIXED_PROCESSES.values() for s in p.re_steps)


# ── reading an engine action's neighbourhood (M2 shapes) ───────────────────────

class ProcessUnreadable(RuntimeError):
    """Egeria's answer for an engine action or process instance was not an element graph."""


@dataclass
class Neighbour:
    guid: str
    guard: str = ""
    mandatory: bool = False
    status: str = ""
    completion_guards: list[str] = field(default_factory=list)
    request_type: str = ""


@dataclass
class EngineActionView:
    """One engine action as `get_all_related_elements(guid, graph_query_depth=1)` shows it."""
    guid: str
    status: str = ""
    request_type: str = ""
    requester: str = ""
    process_name: str = ""
    step_name: str = ""
    #: The GovernanceActionProcessInstance it is anchored to; "" for an action started alone.
    instance_guid: str = ""
    completion_guards: list[str] = field(default_factory=list)
    message: str = ""
    report_guids: list[str] = field(default_factory=list)
    targets: list[tuple[str, str]] = field(default_factory=list)
    previous: list[Neighbour] = field(default_factory=list)
    next: list[Neighbour] = field(default_factory=list)
    #: Set when the action's process could not be read: it renders alone, with "process unknown".
    unreadable: str = ""

    @property
    def report_guid(self) -> str:
        return self.report_guids[0] if len(set(self.report_guids)) == 1 else ""

    @property
    def succeeded(self) -> bool:
        return self.status == _DONE and SURVEY_COMPLETED in self.completion_guards

    @property
    def active(self) -> bool:
        return self.status in _ACTIVE


def _value(entry):
    """One property value from a propertyValueMap entry: primitive, enum, array or map."""
    if not isinstance(entry, dict):
        return entry
    if "primitiveValue" in entry:
        return entry["primitiveValue"]
    if "symbolicName" in entry:
        return entry["symbolicName"]
    if "arrayValues" in entry:
        inner = (entry.get("arrayValues") or {}).get("propertyValueMap") or {}
        return [_value(inner[k]) for k in sorted(inner, key=lambda k: int(k) if str(k).isdigit() else 0)]
    if "mapValues" in entry:
        inner = (entry.get("mapValues") or {}).get("propertyValueMap") or {}
        return {k: _value(v) for k, v in inner.items()}
    return None


def _props(element: dict) -> dict:
    pvm = ((element or {}).get("elementProperties") or {}).get("propertyValueMap") or {}
    return {k: _value(v) for k, v in pvm.items()}


def _rel_props(entry: dict) -> dict:
    rp = (entry or {}).get("relationshipProperties") or {}
    return dict(rp.get("propertiesAsStrings") or {})


def _guards(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v not in (None, "")]
    if isinstance(value, dict):
        return [str(v) for _k, v in sorted(value.items()) if v not in (None, "")]
    return []


def instance_of(element: dict) -> str:
    """The GovernanceActionProcessInstance an engine action is anchored to, or ""."""
    for c in (element or {}).get("classifications") or []:
        if c.get("classificationName") != "Anchors":
            continue
        props = ((c.get("classificationProperties") or {}).get("propertiesAsStrings") or {})
        if props.get("anchorTypeName") == "GovernanceActionProcessInstance":
            return str(props.get("anchorGUID") or "")
    return ""


def parse_action_graph(answer) -> EngineActionView:
    """Pure: one engine action from a `get_all_related_elements(guid, graph_query_depth=1)` answer."""
    if not isinstance(answer, dict) or not isinstance(answer.get("startingElement"), dict):
        raise ProcessUnreadable("Egeria answered the engine action's relationships with "
                                + " ".join(str(answer).split())[:200])
    start = answer["startingElement"]
    p = _props(start)
    view = EngineActionView(
        guid=str(start.get("elementGUID") or ""), status=str(p.get("activityStatus") or ""),
        request_type=str(p.get("requestType") or ""), requester=str(p.get("requesterUserId") or ""),
        process_name=str(p.get("processName") or ""), step_name=str(p.get("processStepName") or ""),
        instance_guid=instance_of(start), completion_guards=_guards(p.get("completionGuards")),
        message=str(p.get("completionMessage") or ""))
    for entry in answer.get("elementList") or []:
        rel = ((entry.get("type") or {}).get("typeName")) or ""
        other = entry.get("element") or {}
        guid = str(other.get("elementGUID") or "")
        if not guid:
            continue
        rp = _rel_props(entry)
        if rel == "ActionTarget" and not entry.get("elementAtEnd1"):
            view.targets.append((str(rp.get("actionTargetName") or ""), guid))
        elif rel == "ReportOriginator" and not entry.get("elementAtEnd1"):
            view.report_guids.append(guid)
        elif rel == "ControlFlow":
            op = _props(other)
            n = Neighbour(guid=guid, guard=str(rp.get("guard") or ""),
                          mandatory=str(rp.get("mandatoryGuard") or "").lower() == "true",
                          status=str(op.get("activityStatus") or ""),
                          completion_guards=_guards(op.get("completionGuards")),
                          request_type=str(op.get("requestType") or ""))
            (view.previous if entry.get("elementAtEnd1") else view.next).append(n)
    return view


def read_action_graph(expert, guid: str) -> EngineActionView:
    """One engine action and its neighbours (`MetadataExpert.get_all_related_elements`, read-only). Raises
    `ProcessUnreadable` for any answer that is not an element graph, so an unreadable action is never a lone one.
    Egeria's exact "No elements found" (an action with no relationship at all, so no previous step) is a lone action."""
    from resource_explorer.native_survey_run import is_exact_absent

    answer = expert.get_all_related_elements(guid, graph_query_depth=1)
    if is_exact_absent(answer):
        return EngineActionView(guid=guid)
    return parse_action_graph(answer)


def read_action_views(expert, guids: list[str]) -> list[EngineActionView]:
    """Each action's view; one that cannot be read is kept, marked `unreadable`, so it still renders (alone, with
    "process unknown") rather than disappearing."""
    out = []
    for guid in guids:
        try:
            out.append(read_action_graph(expert, guid))
        except Exception as exc:  # noqa: BLE001 -- shown as "process unknown", never dropped
            out.append(EngineActionView(guid=guid, unreadable=" ".join(f"{type(exc).__name__}: {exc}".split())[:200]))
    return out


def previous_step_refusal(view: EngineActionView) -> str:
    """Why an action of RE's must not run as a later process step, or "". An action with no previous action (started
    alone, or the first step) is fine. Otherwise EVERY previous action must be COMPLETED with the link's guard among
    its completion guards: Egeria should never create the action if not, so this pins RE's own refusal."""
    for prev in view.previous:
        if prev.status != _DONE or (prev.guard and prev.guard not in prev.completion_guards):
            return (f"previous step {prev.guid} is {prev.status or 'of unknown status'} with "
                    f"{', '.join(prev.completion_guards) or 'no guard'}, not {prev.guard or 'a completion'}")
    return ""


def read_process_run(expert, instance_guid: str) -> list[EngineActionView]:
    """Every engine action of one process instance, in run order: the first (ActionRequester from the instance),
    then each ControlFlow successor. Raises `ProcessUnreadable` when the instance or an action cannot be read."""
    from resource_explorer.native_survey_run import is_exact_absent

    answer = expert.get_all_related_elements(instance_guid, graph_query_depth=1)
    if is_exact_absent(answer):
        return []                     # the instance has no action linked yet
    if isinstance(answer, str):
        raise ProcessUnreadable(f"process instance {instance_guid}: {answer}")
    if not isinstance(answer, dict):
        raise ProcessUnreadable(f"process instance {instance_guid}: Egeria answered {type(answer).__name__}")
    queue = [str((e.get("element") or {}).get("elementGUID") or "") for e in answer.get("elementList") or []
             if ((e.get("type") or {}).get("typeName")) == "ActionRequester"
             and ((e.get("element") or {}).get("type") or {}).get("typeName") == "EngineAction"]
    seen: dict[str, EngineActionView] = {}
    while queue and len(seen) < MAX_STEPS:
        guid = queue.pop(0)
        if not guid or guid in seen:
            continue
        view = read_action_graph(expert, guid)
        seen[guid] = view
        queue.extend(n.guid for n in view.next)
    return list(seen.values())


# ── grouping into run lines (M4) ───────────────────────────────────────────────

@dataclass
class RunLine:
    """One run as Understanding shows it: the actions of one process instance, or one lone action."""
    instance_guid: str
    process_name: str
    steps: list[EngineActionView]
    note: str = ""

    @property
    def process(self) -> MixedProcess | None:
        return process_for_instance_name(self.process_name)

    @property
    def requester(self) -> str:
        return next((s.requester for s in self.steps if s.requester), "")


def _order(steps: list[EngineActionView]) -> list[EngineActionView]:
    """Run order inside one instance: an action after every action it follows (ControlFlow)."""
    by_guid = {s.guid: s for s in steps}

    def depth(s, seen=()):
        prev = [by_guid[p.guid] for p in s.previous if p.guid in by_guid and p.guid not in seen]
        return 1 + max((depth(p, (*seen, s.guid)) for p in prev), default=0)

    return sorted(steps, key=lambda s: (depth(s), s.guid))


def group_by_process(views: list[EngineActionView]) -> list[RunLine]:
    """Engine actions grouped by the process instance they are anchored to: one `RunLine` per instance with its
    actions in run order; an action with no instance is a line of its own; an action whose process could not be
    read (`unreadable`) is a line of its own with the note "process unknown". Input order of first appearance."""
    lines: dict[str, RunLine] = {}
    out: list[RunLine] = []
    for v in views:
        if v.unreadable:
            out.append(RunLine("", v.process_name, [v], note="process unknown"))
            continue
        if not v.instance_guid:
            out.append(RunLine("", "", [v]))
            continue
        line = lines.get(v.instance_guid)
        if line is None:
            line = lines[v.instance_guid] = RunLine(v.instance_guid, v.process_name, [])
            out.append(line)
        line.steps.append(v)
    for line in out:
        line.steps = _order(line.steps)
    return out


def _step_words(n: int, label: str, view: EngineActionView | None) -> str:
    if view is None:
        return f"step {n} {label}"
    if view.status == _DONE:
        rep = view.report_guid
        other = [g for g in view.completion_guards if g != SURVEY_COMPLETED]
        return (f"step {n} {label} ✓" + (f" {', '.join(other)}" if other else "")
                + (f" report {rep[:8]}" if rep else (" (no report linked)" if view.succeeded else "")))
    if view.active:
        if view.status in ("APPROVED", "REQUESTED"):
            return f"step {n} {label} not claimed yet"
        return f"step {n} {label} {'running' if view.status == 'IN_PROGRESS' else 'waiting'}"
    guard = ", ".join(view.completion_guards)
    return f"step {n} {label} ✗ {guard or view.status or 'status unknown'}"


def run_line_words(line: RunLine, *, started: str = "") -> str:
    """The run line: "Postgres survey then derived · step 1 PostgreSQLSurvey ✓ report cb92eedc · step 2
    re-database-staleness ✓ report 1a2b3c4d · started by peterprofile 10-15". A step Egeria never created after a
    failed step says "step 2 not started · step 1 failed", never "pending"."""
    process = line.process
    tail = []
    if line.requester:
        tail.append(f"started by {line.requester}" + (f" {started}" if started else ""))
    if process is None:
        parts = [line.process_name.split("@", 1)[0] or (line.steps[0].request_type if line.steps else "engine action")]
        parts += [_step_words(i + 1, s.request_type, s) for i, s in enumerate(line.steps)]
        if line.note:
            parts.append(line.note)
        return " · ".join(parts + tail)
    parts = [process.short_name]
    by_request = {s.request_type: s for s in line.steps}
    previous: EngineActionView | None = None
    previous_number = 0
    for step in sorted(process.steps, key=lambda s: s.number):
        view = by_request.get(step.request_type)
        if view is None and previous is not None and not previous.active and not previous.succeeded:
            parts.append(f"step {step.number} not started · step {previous_number} failed")
            break
        if view is None and previous is not None and previous.active:
            parts.append(f"step {step.number} {step.label} waits for step {previous_number}")
            break
        if view is None:
            parts.append(f"step {step.number} {step.label} not started yet")
            break
        parts.append(_step_words(step.number, step.label, view))
        previous, previous_number = view, step.number
    if line.note:
        parts.append(line.note)
    return " · ".join(parts + tail)


def run_line_dict(line: RunLine, *, started: str = "") -> dict:
    """The run line for a page: its words and each step's action, status, guards and report."""
    return {"instance_guid": line.instance_guid, "process_name": line.process_name, "note": line.note,
            "words": run_line_words(line, started=started),
            "steps": [{"action_guid": s.guid, "request_type": s.request_type, "status": s.status,
                       "guards": list(s.completion_guards), "report_guid": s.report_guid,
                       "message": s.message[:500]} for s in line.steps]}
