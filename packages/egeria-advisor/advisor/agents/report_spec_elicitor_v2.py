"""The report-spec elicitor on pyegeria's authoring API (EA re-base prototype; EA_SPEC_AUTHORING_V2=1).

Same conversation and phases as `report_spec_elicitor` (confirm_action -> elicit_columns -> generate ->
refine, with Back / Save & exit / Resume), and the same draft and document stores. What changes:

- the LLM proposes a target type from Egeria's types, a condition and columns, or asks ONE clarifying
  question when the request doesn't say what kind of thing it is about (phase "clarify");
- the find method and its scoping come from the type's registered spec (`spec_authoring_v2.find_action`);
- columns are grounded in the type's attributes; anything else is dropped and the reply says so;
- generation validates with pyegeria, serializes with pyegeria, and, when the caller is signed in, runs it
  as them and puts the answer in the reply;
- a refinement edits the draft (columns, condition) and regenerates, instead of the LLM rewriting markdown.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from advisor import spec_authoring_v2 as v2
from advisor.llm_client import get_planning_llm
from advisor.report_draft import get_report_draft_manager
from advisor.report_spec_docs import get_report_spec_doc_manager

#: Signed-in clients for live drafts, by draft id (never written to the draft file).
_CLIENTS: Dict[str, Any] = {}


def _json(raw: str) -> Any:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw).strip()
    m = re.search(r"[\[{].*[\]}]", raw, flags=re.S)
    return json.loads(m.group(0) if m else raw)


def _types_line() -> str:
    return ", ".join(v2.known_types())


def _menu_text(type_name: str, limit: int = 60) -> str:
    return "\n".join(f"- {k}: {label}" for k, label in v2.attribute_menu(type_name)[:limit])


_CONDITION_HELP = f"""Conditions you may set (leave out what the question doesn't ask for):
- "search_string": text the element's names must contain (default "*", everything)
- "limit_result_by_status": a list from {list(v2.STATUSES)}
- "output_sort_order": one of {list(v2.SORT_ORDERS)}; with PROPERTY_ASCENDING/DESCENDING also
  "order_property_name": the attribute to sort by"""


def start(elicitor, query: str, perspective: Optional[str] = None, egeria_client: Any = None) -> Dict[str, Any]:
    llm = get_planning_llm()
    prompt = f"""You help a user build an Egeria report that answers their question.
User request: "{query}"
Perspective: {perspective or "None"}

Egeria element types you can report on:
{_types_line()}

Decide first: does the request name or clearly imply a kind of element (projects, glossary terms, data
products, risks, metrics, assets, collections, subscriptions, ...)?
- YES: do NOT ask a question. Pick the closest type from the list and build the report, even when part of
  the condition can't be expressed (say so in "unmet"). "Which glossaries are approved?" -> Glossary.
  "Which teams have no leader?" -> Team, unmet: "no leader".
- NO, it names no kind of element at all ("tell me about our stuff", "what should I look at?",
  "is everything OK?"): do NOT guess. Ask ONE short clarifying question offering two or three readings.

{_CONDITION_HELP}

Respond ONLY with JSON, either
{{"clarify": "your one question"}}
or
{{"title": "short-slug-title", "heading": "Report heading", "description": "one sentence",
  "target_type": "one type from the list above",
  "conditions": {{}},
  "columns": [{{"name": "Column Label", "key": "snake_case_attribute"}}],
  "unmet": "any part of the question these conditions cannot apply (e.g. an absence), or null"}}
"""
    try:
        data = _json(llm.generate(prompt, temperature=0.1, max_tokens=700))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"v2 decompose failed: {exc}")
        data = {"clarify": "I couldn't work out what to report on. Which kind of element do you mean "
                           "(for example projects, glossary terms or digital products), and what about them?"}
    if data.get("clarify"):
        return _clarify(query, str(data["clarify"]))
    target = v2.resolve_type(data.get("target_type"))
    if not target:
        return _clarify(query, f"I don't know an Egeria type called '{data.get('target_type')}'. Which kind of "
                               f"element do you mean? For example: {', '.join(v2.known_types()[:12])}.")
    cols, dropped = v2.ground_columns(target, data.get("columns") or [])
    conditions, cnotes = v2.ground_conditions(data.get("conditions") or {})
    cols = v2.condition_columns(target, cols, conditions)
    action = v2.find_action(target)
    dm = get_report_draft_manager()
    spec = dm.create(title=data.get("title") or "custom_report", original_query=query,
                     action_function=action["function"], target_type=target, columns=cols,
                     answers={"Heading": data.get("heading"), "Description": data.get("description")})
    spec["conditions"] = conditions
    spec["unmet"] = data.get("unmet") if data.get("unmet") not in (None, "null", "") else None
    spec["v2"] = True
    spec["phase"] = "confirm_action"
    spec["phase_label"] = "Confirming report basic configuration"
    dm.save(spec)
    if egeria_client is not None:
        _CLIENTS[spec["draft_id"]] = egeria_client
    return confirm_response(elicitor, spec, notes=dropped + cnotes)


def _clarify(query: str, question: str) -> Dict[str, Any]:
    return {"query": query, "response": question, "query_type": "report_spec_clarification",
            "routing_agent": "report_spec_agent", "draft_id": None, "phase": "clarify", "can_go_back": False,
            "navigation": [], "next_context": None, "sources": [], "num_sources": 0, "retrieval_time": 0.0,
            "generation_time": 0.0, "avg_relevance_score": 0.0, "context_length": len(question)}


def _conditions_line(spec: Dict[str, Any]) -> str:
    c = spec.get("conditions") or {}
    return ", ".join(f"{k} = {v}" for k, v in c.items()) or "none (everything of this type)"


def confirm_response(elicitor, spec: Dict[str, Any], notes: Optional[List[str]] = None) -> Dict[str, Any]:
    from advisor.agents.report_spec_elicitor import _NAV_CONFIRM, _clarification_result
    action = v2.find_action(spec["target_type"])
    lines = [f"⚠️ Left out: {n}." for n in notes or []]
    lines += [f"### Proposed Report Spec: **{spec['answers'].get('Heading')}**\n",
              f"- **Target Type:** {spec.get('target_type')}",
              f"- **Found with:** `{action['function']}` (from {action['from']})",
              f"- **Condition:** {_conditions_line(spec)}",
              f"- **Description:** {spec['answers'].get('Description')}"]
    if spec.get("unmet"):
        lines.append(f"- **Not applied:** {spec['unmet']}")
    lines += ["\n---\n", "Does this look correct? Use the buttons below, or describe adjustments."]
    return _clarification_result(spec, "\n".join(lines), phase_override="confirm_action",
                                 can_go_back=bool(spec.get("history_stack")), nav=_NAV_CONFIRM)


def columns_response(elicitor, spec: Dict[str, Any], notes: Optional[List[str]] = None) -> Dict[str, Any]:
    from advisor.agents.report_spec_elicitor import _NAV_MIDDLE, _clarification_result
    lines = [f"⚠️ Left out: {n}." for n in notes or []]
    lines.append("### Columns Configuration\n")
    for i, col in enumerate(spec["columns"], 1):
        lines.append(f"**{i}. {col['name']}** — key: `{col['key']}`")
    lines += [f"\n**Condition:** {_conditions_line(spec)}", "\n---\n",
              "Does this look right? Use **Generate now**, or describe changes (only attributes of "
              f"{spec['target_type']} can be columns)."]
    return _clarification_result(spec, "\n".join(lines), phase_override="elicit_columns", can_go_back=True,
                                 nav=_NAV_MIDDLE)


def update_from_request(spec: Dict[str, Any], user_response: str) -> List[str]:
    """Apply a chat request to the draft's columns and condition, grounded. Returns notes."""
    llm = get_planning_llm()
    prompt = f"""Report on Egeria {spec['target_type']} elements.
Current columns: {json.dumps(spec['columns'])}
Current conditions: {json.dumps(spec.get('conditions') or {})}
User request: "{user_response}"

Columns can only use these attributes of {spec['target_type']} (key: label):
{_menu_text(spec['target_type'])}

{_CONDITION_HELP}

Return ONLY JSON: {{"columns": [{{"name": "...", "key": "..."}}], "conditions": {{}}}}
"""
    try:
        data = _json(llm.generate(prompt, temperature=0.1, max_tokens=700))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"v2 column update failed: {exc}")
        return ["I couldn't apply that change; please rephrase it"]
    notes: List[str] = []
    if isinstance(data, list):
        data = {"columns": data}
    if data.get("columns"):
        spec["columns"], dropped = v2.ground_columns(spec["target_type"], data["columns"])
        notes += dropped
    if "conditions" in data:
        spec["conditions"], cnotes = v2.ground_conditions(data.get("conditions") or {})
        notes += cnotes
    spec["columns"] = v2.condition_columns(spec["target_type"], spec["columns"], spec.get("conditions") or {})
    return notes


def retarget(spec: Dict[str, Any], user_response: str) -> List[str]:
    """A confirm-phase change: maybe a new target type (re-grounding the columns), heading or condition."""
    m = re.search(r"\btarget\s+type\s*(?:is|=|:|to|as)?\s*[\"']?([\w][\w\s]*?)(?:[\"'\.,]|$)", user_response,
                  re.IGNORECASE)
    notes: List[str] = []
    if m:
        t = v2.resolve_type(m.group(1).strip())
        if not t:
            return [f"'{m.group(1).strip()}' isn't an Egeria type I can report on"]
        spec["target_type"] = t
        spec["action_function"] = v2.find_action(t)["function"]
        spec["columns"], dropped = v2.ground_columns(t, spec.get("columns") or [])
        return dropped
    return update_from_request(spec, user_response) + notes


def generate(elicitor, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Validate with pyegeria; serialize with pyegeria; run as the user when signed in."""
    from advisor.agents.report_spec_elicitor import _NAV_FINAL
    dm = get_report_draft_manager()
    client = _CLIENTS.get(spec["draft_id"])
    run = None
    if client is not None:
        from pyegeria.authoring import inprocess_runner
        inner = inprocess_runner(client)
        run = lambda md, d: inner(md, "validate")  # noqa: E731 -- generation only ever validates
    result = v2.validate(spec, client=client, run=run)
    if not result.ok:
        dm.save(spec)
        lines = ["**This spec doesn't validate yet:**"] + [f"- {e}" for e in result.errors]
        resp = columns_response(elicitor, spec)
        resp["response"] = "\n".join(lines) + "\n\n" + resp["response"]
        resp["validation"] = result.model_dump()
        return resp
    content = v2.serialize(spec)
    doc_mgr = get_report_spec_doc_manager()
    if spec.get("doc_id") and doc_mgr.load(spec["doc_id"]) is not None:
        doc_mgr.update(spec["doc_id"], content)
        doc_id = spec["doc_id"]
    else:
        doc_id = doc_mgr.create(spec["title"], content)
    spec["doc_id"] = doc_id
    spec["format_set"] = v2.build_format_set(spec).model_dump(exclude_none=True)
    spec["phase"] = "refine"
    spec["phase_label"] = "Refinement session"
    dm.save(spec)
    out: Dict[str, Any] = {
        "query": spec["original_query"], "query_type": "report_spec_clarification",
        "routing_agent": "report_spec_agent", "draft_id": spec["draft_id"], "phase": "refine",
        "can_go_back": True, "navigation": _NAV_FINAL, "doc_id": doc_id, "next_context": None,
        "validation": result.model_dump(),
    }
    head = f"**{spec['answers'].get('Heading')}** (draft spec **{doc_id}**, validated with pyegeria)"
    if spec.get("unmet"):
        head += f"\n\n*Not applied:* {spec['unmet']}"
    if client is None:
        out["response"] = head + "\n\nSign in to see the answer here; you can run it with **Execute Spec**."
        return out
    ans = v2.answer(spec, client)
    out["answer"] = ans
    out["response"] = f"{head}\n\n{ans['markdown']}\n\n---\nTell me what to change, or save it."
    return out


def refine(elicitor, spec: Dict[str, Any], user_response: str) -> Dict[str, Any]:
    notes = update_from_request(spec, user_response)
    res = generate(elicitor, spec)
    if notes:
        res["response"] = "\n".join(f"⚠️ Left out: {n}." for n in notes) + "\n\n" + res["response"]
    return res
