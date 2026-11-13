"""Report-spec authoring on pyegeria's authoring API (the EA re-base prototype, behind a flag).

`EA_SPEC_AUTHORING_V2=1` turns it on. Off (the default), nothing here is on any path and EA behaves as
before. On, the report-spec elicitor keeps its conversation and EA's canvas, and hands these to pyegeria:

- **Grounding.** The target type is resolved against Egeria's type system (pyegeria's Properties-class
  catalog and its registered specs); the find method and its scoping parameters come from the type's own
  registered spec, never from the LLM; columns are offered from, and kept only if they are, attributes of
  that type (or keys pyegeria's formatter derives). A key that isn't one is dropped and the reply says so.
- **Validation** is `pyegeria.authoring.validate` (the FormatSet model, attribute catalog, load-time
  resolution, and Dr.Egeria's validate when a runner is given), not `report_spec_parser.py`.
- **Serialization** is `pyegeria.authoring.serialize` (a `Create Report Spec` block carrying the spec's
  microflow), not the elicitor's `_generate_report_spec_md`; reading a document back is the microflow.
- **The answer** is `pyegeria.authoring.preview`: run as the signed-in user, structured TABLE, capped and
  saying so, never registered.

The spec stays a personal draft in EA's local stores (D16 is pyegeria's to wire later).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

FLAG = "EA_SPEC_AUTHORING_V2"

#: The generic finder for a type with no registered find spec (pyegeria's own "Dashboards" spec uses it).
GENERIC_FIND = "MetadataExpert.find_metadata_elements_with_string"

#: Common names the LLM uses that aren't Egeria's.
_ALIASES = {"Term": "GlossaryTerm", "DataProduct": "DigitalProduct", "Product": "DigitalProduct",
            "Subscription": "DigitalSubscription", "Metric": "GovernanceMetric", "Policy": "GovernancePolicy",
            "Control": "GovernanceControl", "DataProductCatalog": "DigitalProductCatalog"}

#: Find parameters the elicitor may set to apply a question's condition (pyegeria's FIND_PARAMETERS names).
CONDITION_PARAMS = ("search_string", "limit_result_by_status", "output_sort_order", "order_property_name")
STATUSES = ("DRAFT", "PREPARED", "PROPOSED", "APPROVED", "REJECTED", "APPROVED_CONCEPT", "UNDER_DEVELOPMENT",
            "DEVELOPMENT_COMPLETE", "APPROVED_FOR_DEPLOYMENT", "STANDBY", "ACTIVE", "FAILED", "DISABLED",
            "COMPLETE", "DEPRECATED", "OTHER")
SORT_ORDERS = ("ANY", "CREATION_DATE_RECENT", "CREATION_DATE_OLDEST", "LAST_UPDATE_RECENT",
               "LAST_UPDATE_OLDEST", "PROPERTY_ASCENDING", "PROPERTY_DESCENDING")


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in ("1", "true", "yes", "on")


# ── Grounding ────────────────────────────────────────────────────────────────

def _norm(name: Optional[str]) -> str:
    return re.sub(r"[\s_\-]+", "", name or "")


def _snake(key: str) -> str:
    from pyegeria.authoring.validate import _snake as s
    return s(key)


@lru_cache(maxsize=1)
def _registry_by_type() -> Dict[str, List[Tuple[str, Any]]]:
    """{normalised target type: [(label, FormatSet)]} for registered find specs runnable from a search
    string alone (a find method, no analytic routine, no required GUID)."""
    from pyegeria.view.base_report_formats import get_report_registry
    out: Dict[str, List[Tuple[str, Any]]] = {}
    for label, fs in get_report_registry().items():
        a = fs.action
        if not a or not a.function or getattr(a, "analytic_function", None):
            continue
        if set(a.required_params or []) - {"search_string"}:
            continue
        if not a.function.split(".")[-1].startswith("find_"):
            continue
        out.setdefault(_norm(fs.target_type), []).append((label, fs))
    return out


@lru_cache(maxsize=1)
def _all_registry_types() -> List[str]:
    from pyegeria.view.base_report_formats import get_report_registry
    return sorted({_norm(fs.target_type) for fs in get_report_registry().values() if fs.target_type})


@lru_cache(maxsize=1)
def _catalog() -> Dict[str, tuple]:
    from md_processing.md_processing_utils.properties_class_fields import PROPERTIES_CLASS_FIELDS
    return PROPERTIES_CLASS_FIELDS


def resolve_type(name: Optional[str]) -> Optional[str]:
    """Egeria's name for a type the LLM proposed ("Glossary Term" -> "GlossaryTerm"), or None."""
    n = _norm(name)
    n = _ALIASES.get(n, n)
    if not n:
        return None
    cat = _catalog()
    for cand in (n, n[:1].upper() + n[1:]):
        entry = cat.get(f"{cand}Properties")
        if entry and entry[0] == "entity":
            return cand
        if cand in _registry_by_type():
            return cand
    lowered = {k[:-len("Properties")].lower(): k[:-len("Properties")] for k, v in cat.items()
               if k.endswith("Properties") and v[0] == "entity"}
    return lowered.get(n.lower())


def known_types() -> List[str]:
    """Types the elicitor may target: those with a registered find spec, Egeria's spelling."""
    out = []
    for t in _all_registry_types():
        r = resolve_type(t)
        if r and r not in out:
            out.append(r)
    return out


#: Types whose names are also words for what the user wants built or for "anything": "a report on ...",
#: "a dashboard for ...", "every element". They don't say what the report is about.
OUTPUT_WORDS = {"Report", "Dashboard", "Element", "Referenceable", "OpenMetadataRoot"}


def _singular(word: str) -> str:
    w = word.lower()
    for suf, rep_ in (("ies", "y"), ("sses", "ss"), ("s", "")):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)] + rep_
    return w


def types_named_in(text: str) -> List[str]:
    """Egeria types the text names outright ("data product catalogs" -> DigitalProductCatalog), longest
    phrase first. Used to keep the elicitor from asking which kind of element when the user said so."""
    known = set(known_types())
    words = [_singular(w) for w in re.findall(r"[A-Za-z]+", text or "")]
    found: List[str] = []
    for size in (3, 2, 1):
        for i in range(len(words) - size + 1):
            phrase = "".join(w.capitalize() for w in words[i:i + size])
            t = resolve_type(phrase)
            if t in OUTPUT_WORDS:
                continue
            if t and t in known and t not in found and not any(t in f for f in found):
                found.append(t)
    return found


def base_spec(type_name: str) -> Optional[Tuple[str, Any]]:
    """The registered spec a new spec for `type_name` borrows its find method from: `<Type>-DrE-Basic`
    when there is one, else the matching spec with the most columns."""
    specs = _registry_by_type().get(_norm(type_name)) or []
    if not specs:
        return None
    for label, fs in specs:
        if label.endswith("-DrE-Basic"):
            return label, fs
    return max(specs, key=lambda s: sum(len(f.attributes or []) for f in s[1].formats or []))


def find_action(type_name: str) -> Dict[str, Any]:
    """{"function", "spec_params", "from"}: how to find `type_name`, from its registered spec or the
    generic finder scoped by type. Never the LLM's guess."""
    base = base_spec(type_name)
    if base:
        label, fs = base
        params = {k: v for k, v in (fs.action.spec_params or {}).items() if not k.startswith("_")
                  and k != "output_format"}
        return {"function": fs.action.function, "spec_params": params, "from": label}
    return {"function": GENERIC_FIND, "spec_params": {"metadata_element_type": type_name},
            "from": "generic finder"}


def attribute_menu(type_name: str) -> List[Tuple[str, str]]:
    """[(key, label)] a column may use for `type_name`: the registered spec's own columns first (known to
    render), then the type's properties, then derived header keys."""
    from pyegeria.authoring.validate import DERIVED_KEYS
    out: Dict[str, str] = {}
    base = base_spec(type_name)
    if base:
        for f in base[1].formats or []:
            for c in f.attributes or []:
                if c.key and c.key not in out:
                    out[c.key] = c.name or c.key
    entry = _catalog().get(f"{type_name}Properties")
    if entry and entry[0] == "entity":
        for field in entry[1]:
            k = _snake(field)
            out.setdefault(k, k.replace("_", " ").title())
    for k in sorted(DERIVED_KEYS):
        out.setdefault(k, k.replace("_", " ").title())
    return list(out.items())


def ground_columns(type_name: str, columns: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Columns kept for `type_name`, and words for each one dropped. A camelCase key becomes snake_case
    when that is the attribute; an unknown key is dropped, never sent to a run."""
    import difflib
    menu = dict(attribute_menu(type_name))
    kept, dropped, seen = [], [], set()
    for col in columns or []:
        key = str(col.get("key") or "").strip()
        name = str(col.get("name") or key).strip()
        for cand in (key, _snake(key), _snake(key.split(".")[-1])):
            if cand in menu:
                key = cand
                break
        else:
            near = difflib.get_close_matches(_snake(key.split(".")[-1]) if key else "", list(menu), n=1, cutoff=0.85)
            if not near:
                dropped.append(f"'{name}' ({key or 'no key'}) isn't an attribute of {type_name}")
                continue
            dropped.append(f"'{name}' ({key}) read as {near[0]}, the nearest attribute of {type_name}")
            key = near[0]
        if key in seen:
            continue
        seen.add(key)
        kept.append({**col, "name": name or menu[key], "key": key})
    if not kept:
        kept = [{"name": "Display Name", "key": "display_name"}, {"name": "Description", "key": "description"}]
        kept = [c for c in kept if c["key"] in menu] or [{"name": "Qualified Name", "key": "qualified_name"}]
    return kept, dropped


def condition_columns(type_name: str, columns: List[Dict[str, Any]], conditions: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`columns` plus a column for each condition applied, so the reader can see it was applied: the
    status for a status filter, the sort attribute for a property sort, the times for a time sort."""
    menu = dict(attribute_menu(type_name))
    have = {c["key"] for c in columns}
    want = []
    if conditions.get("limit_result_by_status"):
        want.append(next((k for k in ("status", "content_status", "deployment_status") if k in menu), None))
    if conditions.get("order_property_name"):
        want.append(_snake(str(conditions["order_property_name"])))
    order = str(conditions.get("output_sort_order") or "")
    if order.startswith("CREATION_DATE"):
        want.append("create_time")
    elif order.startswith("LAST_UPDATE"):
        want.append("update_time")
    out = list(columns)
    for k in want:
        if k and k in menu and k not in have:
            out.append({"name": menu[k], "key": k})
            have.add(k)
    return out


def ground_conditions(params: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """The find parameters a question's condition may set, checked against what the finder accepts."""
    out, notes = {}, []
    for k, v in (params or {}).items():
        if k not in CONDITION_PARAMS or v in (None, "", []):
            if k not in CONDITION_PARAMS:
                notes.append(f"'{k}' isn't a condition the finder takes")
            continue
        if k == "limit_result_by_status":
            vals = [str(x).upper() for x in (v if isinstance(v, list) else [v])]
            good = [x for x in vals if x in STATUSES]
            if good:
                out[k] = good
            if len(good) != len(vals):
                notes.append(f"status {', '.join(sorted(set(vals) - set(good)))} isn't an Egeria status")
        elif k == "output_sort_order":
            if str(v).upper() in SORT_ORDERS:
                out[k] = str(v).upper()
        else:
            out[k] = str(v)
    return out, notes


# ── Build, validate, serialize, read back ────────────────────────────────────

def label_for(spec: Dict[str, Any]) -> str:
    raw = spec.get("title") or spec.get("draft_id") or "ea-spec"
    return re.sub(r"[^A-Za-z0-9_.\-]+", "-", str(raw)).strip("-")[:80] or "ea-spec"


def build_format_set(spec: Dict[str, Any]):
    """A FormatSet from an elicitor draft: grounded type, its registered find method, grounded columns."""
    from pyegeria.view._output_format_models import ActionParameter, Column, Format, FormatSet
    target = spec.get("target_type")
    action = find_action(target)
    params = dict(action["spec_params"])
    params.update(spec.get("conditions") or {})
    cols = [Column(name=c["name"], key=c["key"]) for c in spec.get("columns") or []]
    return FormatSet(
        target_type=target,
        heading=(spec.get("answers") or {}).get("Heading") or label_for(spec),
        description=(spec.get("answers") or {}).get("Description") or "",
        formats=[Format(types=["ALL"], attributes=cols)],
        action=ActionParameter(function=action["function"], required_params=["search_string"],
                               spec_params=params),
    )


def spec_draft(spec: Dict[str, Any], fs=None):
    from pyegeria.authoring import SpecDraft
    return SpecDraft(label=label_for(spec), format_set=fs or build_format_set(spec))


def validate(spec: Dict[str, Any], *, client: Any = None, run: Any = None):
    from pyegeria.authoring import validate as pv
    return pv(spec_draft(spec), client, run=run)


def serialize(spec: Dict[str, Any]) -> str:
    from pyegeria.authoring import serialize as ps
    sd = spec_draft(spec)
    return ps(sd, title=f"# {sd.format_set.heading}")


def format_set_from_document(markdown: str, label: str):
    """The FormatSet a V2 document holds (its microflow), read with Dr.Egeria's own parser. Raises
    ValueError with words when the document isn't one."""
    from pyegeria.authoring.serialize import parsed_attributes
    from pyegeria.view.microflow import microflow_to_format_set, parse_microflow
    attrs = parsed_attributes(markdown).get("Create Report Spec")
    if not attrs:
        raise ValueError("the document has no Create Report Spec block")

    def val(name):
        v = attrs.get(name)
        return v.get("value") if isinstance(v, dict) else v
    mf, _, _ = parse_microflow(val("Microflow"))
    return microflow_to_format_set(mf, label=label, heading=val("Display Name"),
                                   description=val("Description") or "", target_type=val("Target Type Name"))


# ── The answer ───────────────────────────────────────────────────────────────

ANSWER_ROWS = 25


def answer(spec: Dict[str, Any], client: Any, *, max_rows: int = ANSWER_ROWS) -> Dict[str, Any]:
    """Run the spec as `client`'s user (structured TABLE, capped) and render it for the reply."""
    import time
    from pyegeria.authoring import preview
    t = time.time()
    try:
        prev = preview(spec_draft(spec), client=client, max_rows=max_rows, params={"start_from": 0})
    except Exception as exc:  # noqa: BLE001 -- the words go to the user
        return {"ok": False, "error": " ".join(str(exc).split())[:400], "s": round(time.time() - t, 2),
                "markdown": f"I couldn't run it: {' '.join(str(exc).split())[:300]}"}
    out = {"ok": True, **prev, "s": round(time.time() - t, 2)}
    out["markdown"] = render_markdown(prev)
    return out


def render_markdown(prev: Dict[str, Any]) -> str:
    """A markdown table of a preview, saying when it's capped or empty (egeria-table.js renders the
    structured result where the browser has it; this is the text everyone gets)."""
    res = prev.get("result") or {}
    notes = "; ".join(prev.get("notes") or [])
    if not isinstance(res, dict) or res.get("kind") != "table":
        body = (res.get("content") or res.get("message") or "") if isinstance(res, dict) else str(res)
        return f"{body}\n\n*{notes}*" if notes else str(body)
    cols = res.get("columns") or []
    keys = [c.get("key") if isinstance(c, dict) else c for c in cols]
    heads = [(c.get("label") or c.get("key")) if isinstance(c, dict) else c for c in cols]
    rows = res.get("rows") or []
    if not rows:
        return f"*No rows: {notes or 'ran, and found nothing'}.*"

    def cell(v):
        if isinstance(v, dict):
            v = v.get("display") or v.get("value") or v.get("text") or ""
        if isinstance(v, list):
            v = ", ".join(str(cell(x)) for x in v)
        return " ".join(str(v if v is not None else "").split()).replace("|", "\\|")[:120]
    lines = ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    for r in rows:
        vals = [r.get(k) for k in keys] if isinstance(r, dict) else list(r)
        lines.append("| " + " | ".join(cell(v) for v in vals) + " |")
    if notes:
        lines.append(f"\n*{notes}*")
    return "\n".join(lines)
