"""
Cross-cutting helpers shared by multiple `advisor/web/` route modules.

Extracted from `app.py` (TC-5, BACKLOG.md — router-per-domain refactor).
`admin.py` never needed a module like this because it is fully
self-contained; most of the *rest* of app.py's routes lean on shared,
stateful module-level things a straight per-route copy would either
duplicate (wrong: two report-catalog caches, two `_rag` singletons) or
silently fork (worse: two definitions that drift). Anything here is
imported by more than one route group, or is going to be once the
remaining domains (reports, plans, drafts, ...) are split out.

`advisor.web.app` re-exports these names via `from advisor.web.shared import
...` rather than deleting them from its own namespace — `advisor.rag_system`
imports `_intent_meta` as `from advisor.web.app import _intent_meta` (a live,
lazy import guarding a circular dependency), so that path must keep resolving
regardless of where the definition actually lives.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel


def _extended_feedback_path() -> Path:
    """Path to the extended-feedback JSONL log, under the resolved writable
    advisor data root (ADVISOR_DATA_PATH) rather than a bare relative
    ``data/`` path — see advisor.config.resolve_advisor_data_root()."""
    from advisor.config import resolve_advisor_data_root
    return resolve_advisor_data_root() / "feedback" / "feedback_extended.jsonl"


_STATIC = Path(__file__).parent / "static"
# Repo-level config/ since 2026-09-06 (moved out of advisor/configdata/).
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SPEC_FILES = [
    _REPO_ROOT / "config" / "report_specs" / "plain_spec_question_specs_batch1.json",
    _REPO_ROOT / "config" / "report_specs" / "report_specs_annotated.json",
]


# ── lazy RAG system ────────────────────────────────────────────────────────────

_rag = None


def _get_rag():
    global _rag
    if _rag is None:
        from advisor.rag_system import get_rag_system
        _rag = get_rag_system()
    return _rag


# ── request / response models ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    output_format: Optional[str] = None    # "LIST"|"TABLE"|"MERMAID"|"MD"|"JSON"|"DICT" — overrides auto-detect
    intent_override: Optional[str] = None  # "explanation" | "code_search" | "report" | "command" | "debugging"
    search_string: Optional[str] = None    # filter string for report queries (default "*")
    perspective: Optional[str] = None      # user role: "developer" | "data_engineer" | "data_steward" | "governance_officer"
    page_size: Optional[int] = None        # max graph nodes per report query (None → advisor.yaml default)
    draft_id: Optional[str] = None         # active planning session draft ID
    context: Optional[Dict[str, Any]] = None  # authoritative conversation context {task, draft_id, phase, ...}


class FeedbackRequest(BaseModel):
    query: str
    query_type: str
    vote: int                           # 1 = positive, 0 = neutral/partially correct, -1 = negative
    perspective: Optional[str] = None
    routing_agent: Optional[str] = None
    response_text: Optional[str] = None   # actual response shown to user
    intent_override: Optional[str] = None  # intent selector value from UI ("auto", "explain", etc.)


# ── intent → badge metadata ────────────────────────────────────────────────────

_INTENT_META: Dict[str, Dict[str, str]] = {
    "report":       {"label": "Report",      "color": "#f97316"},
    "command":      {"label": "Act",         "color": "#a855f7"},
    "explanation":  {"label": "Explain",     "color": "#3b82f6"},
    "comparison":   {"label": "Explain",     "color": "#3b82f6"},
    "best_practice":{"label": "Explain",     "color": "#3b82f6"},
    "code_search":  {"label": "Show me",     "color": "#10b981"},
    "example":      {"label": "Show me",     "color": "#10b981"},
    "relationship": {"label": "Reference",   "color": "#14b8a6"},
    "debugging":    {"label": "Troubleshoot","color": "#eab308"},
    "quantitative": {"label": "Reference",   "color": "#14b8a6"},
    "clarification":{"label": "Clarify",     "color": "#f59e0b"},
    "plan":              {"label": "Plan",        "color": "#8b5cf6"},
    "act_report_result": {"label": "Act",         "color": "#a855f7"},
    "create":            {"label": "Create",      "color": "#8b5cf6"},
    "create_disambiguation": {"label": "Create",  "color": "#8b5cf6"},
    "plan_clarification":{"label": "Planning",    "color": "#a78bfa"},
    "plan_executed":     {"label": "Executed",    "color": "#22c55e"},
    "general":      {"label": "Explain",     "color": "#3b82f6"},
    "code_intel":   {"label": "Inspect", "color": "#ec4899"},
    "code_help":    {"label": "Show me",     "color": "#10b981"},
}


def _intent_meta(query_type: str) -> Dict[str, str]:
    return _INTENT_META.get(query_type, {"label": query_type.title(), "color": "#64748b"})


# ── report catalog helpers ─────────────────────────────────────────────────────

_TOPIC_PATTERNS: List[tuple] = [
    (re.compile(r"glossar", re.I),           "Glossary"),
    (re.compile(r"collection|folder|namespace|results.set", re.I), "Collections"),
    (re.compile(r"governance.zone|governance.basics|governance.def|governance.polic|governance.control|governance.process", re.I), "Governance"),
    (re.compile(r"data.dict|data.spec|data.struct|data.field|data.class|data.grain|data.value|data.lens", re.I), "Data Structures"),
    (re.compile(r"digital.product|digital.subscript|digital.catalog", re.I), "Digital Products"),
    (re.compile(r"agreement|license|terms.and|regulation|certification", re.I), "Agreements & Compliance"),
    (re.compile(r"project|campaign|task", re.I),  "Projects"),
    (re.compile(r"actor|org.chart|user|team|my.user", re.I), "People & Organisations"),
    (re.compile(r"asset|tech.type|catalog.target", re.I), "Assets"),
    (re.compile(r"solution|information.supply|blueprint", re.I), "Solution Architecture"),
    (re.compile(r"external|related.media|cited", re.I), "External References"),
    (re.compile(r"comment|tag|rating|like", re.I), "Collaboration"),
    (re.compile(r"security|threat|access.control", re.I), "Security"),
]

_DEFAULT_TOPIC = "General"


def _topic_for(name: str) -> str:
    for pat, topic in _TOPIC_PATTERNS:
        if pat.search(name):
            return topic
    return _DEFAULT_TOPIC


def _is_dre(name: str) -> bool:
    return "-dre-" in name.lower()


# Canonical, ordered set of browser-renderable output formats. `value` is the
# token sent to pyegeria (via the fmt:'<value>' query tag); `label` is shown in
# the picker. A spec's declared `formats[].types` are intersected with this set
# (and `ALL` expands to all of it) to build a spec-aware dropdown.
_BROWSER_FORMATS: List[tuple] = [
    ("LIST",    "List — compact Markdown table"),
    ("TABLE",   "Table — structured data table"),
    ("REPORT",  "Report — full narrative (Mermaid, graphs)"),
    ("FORM",    "Form — Dr.Egeria editable form"),
    ("MERMAID", "Diagram — Mermaid graph"),
    ("HTML",    "HTML — rendered page"),
    ("MD",      "Markdown — simple"),
    ("DICT",    "Dict — materialized properties"),
    ("JSON",    "JSON — raw Egeria response"),
]
_BROWSER_FORMAT_VALUES = [v for v, _ in _BROWSER_FORMATS]


def _spec_supported_formats(name: str) -> List[str]:
    """Return the browser-renderable output formats a spec supports, in canonical
    order. Reads the in-process pyegeria registry; `ALL` expands to every browser
    format. Falls back to a safe default if the spec/registry is unavailable."""
    try:
        from pyegeria.view.base_report_formats import get_report_registry
        fs = get_report_registry().get(name)
        if fs is None:
            return list(_BROWSER_FORMAT_VALUES)
        declared = {
            t.upper()
            for fmt in (getattr(fs, "formats", []) or [])
            for t in (getattr(fmt, "types", []) or [])
        }
        if "ALL" in declared:
            return list(_BROWSER_FORMAT_VALUES)
        supported = [v for v in _BROWSER_FORMAT_VALUES if v in declared]
        # Always offer at least DICT so the report is runnable from the picker.
        return supported or ["DICT"]
    except Exception as exc:
        logger.debug(f"_spec_supported_formats({name}) failed: {exc}")
        return list(_BROWSER_FORMAT_VALUES)


def _catalog_formats(catalog: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Build {spec_name: [supported formats]} for every spec in the catalog."""
    formats: Dict[str, List[str]] = {}
    for names in catalog.values():
        for name in names:
            formats[name] = _spec_supported_formats(name)
    return formats


def _is_runnable_spec(name: str) -> bool:
    """Return True if the spec has an action (can be executed standalone)."""
    try:
        from pyegeria.view.base_report_formats import get_report_registry
        spec = get_report_registry().get(name)
        if spec is None:
            return True  # unknown to registry — assume runnable, let executor decide
        return getattr(spec, "action", None) is not None
    except Exception:
        return True  # registry unavailable — assume runnable


def _load_report_catalog(include_dre: bool = False) -> Dict[str, List[str]]:
    """Return {topic: [spec_name, ...]}, runnable specs only.

    Primary source is pyegeria's own in-process report registry
    (get_report_registry(), which already combines built-ins, generated,
    config-loaded, and runtime-registered specs) — report specs are not all
    produced by the dr-egeria-command-sync JSON pipeline, so the catalog must
    not be JSON-file-only. The bundled JSON files below still supplement this
    for any name the registry doesn't (yet) know about, and are read fresh on
    every call, so a live-updated JSON file needs no server restart either.
    """
    catalog: Dict[str, List[str]] = {}
    seen: set = set()

    def _add(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        if not include_dre and _is_dre(name):
            return
        if not _is_runnable_spec(name):
            return
        topic = _topic_for(name)
        catalog.setdefault(topic, []).append(name)

    try:
        from pyegeria.view.base_report_formats import get_report_registry
        for name in get_report_registry().keys():
            _add(name)
    except Exception as exc:
        logger.debug(f"_load_report_catalog: pyegeria registry unavailable — {exc}")

    for path in _SPEC_FILES:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            for name in data:
                _add(name)
        except Exception as exc:
            logger.warning(f"Failed to load {path}: {exc}")

    # Sort within each topic
    for topic in catalog:
        catalog[topic].sort()
    return dict(sorted(catalog.items()))
