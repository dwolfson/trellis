"""
ReportDraftManager — lifecycle management for in-progress report spec Q&A sessions.

Draft specs are stored as JSON in ~/egeria-reports/drafts/.
Each draft captures the conversation and elicitation state so sessions
can be paused, resumed, rewound (Back), or abandoned (Start Over).

Draft spec schema:
  draft_id          — unique ID (timestamp + slug)
  title             — report spec title
  phase             — current elicitation phase (e.g., 'confirm_action', 'elicit_columns', 'elicit_params', 'generate', 'refine')
  phase_label       — human-readable status/where you are
  original_query    — verbatim user request that started the session
  action_function   — Action Function (ClientClass.method)
  target_type       — Target Type (e.g. Asset, Project)
  columns           — List of column Dicts: {name, key, format, detail_spec, formats}
  answers           — {field: value} accumulated so far
  pending_questions — questions to ask
  doc_id            — set after the report spec document is generated
  history_stack     — list of snapshot dicts for Back navigation
  created_at        — Unix timestamp
  updated_at        — Unix timestamp
  summary_of_answers — short recap shown on resume
"""
from __future__ import annotations

import json
import re
import time
import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger


def _drafts_path() -> Path:
    """Return path to the reports drafts folder, creating it if necessary."""
    base = Path.home() / "egeria-reports"
    p = base / "drafts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slug(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:40].strip("_")


class ReportDraftManager:
    """CRUD for report spec drafts."""

    def __init__(self) -> None:
        self._root = _drafts_path()

    def _path(self, draft_id: str) -> Path:
        return self._root / f"{draft_id}.json"

    def create(
        self,
        title: str,
        original_query: str,
        action_function: Optional[str] = None,
        target_type: Optional[str] = None,
        columns: Optional[List[Dict[str, Any]]] = None,
        answers: Optional[Dict[str, Any]] = None,
        pending_questions: Optional[Dict[str, Any]] = None,
        content_filters: Optional[Dict[str, Any]] = None,
        shape_defaults: Optional[Dict[str, Any]] = None,
        performance_hints: Optional[Dict[str, Any]] = None,
        perspectives: Optional[List[str]] = None,
        questions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new report spec draft, persist it, and return it."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        draft_id = f"draft_report_{ts}_{_slug(title)}"
        spec: Dict[str, Any] = {
            "draft_id": draft_id,
            "title": title,
            "phase": "confirm_action",
            "phase_label": "Confirming action function and basic metadata",
            "original_query": original_query,
            "action_function": action_function,
            "target_type": target_type,
            "columns": columns or [],
            "content_filters": content_filters if content_filters is not None else {"search_string": "*"},
            "shape_defaults": shape_defaults or {},
            "performance_hints": performance_hints if performance_hints is not None else {"page_size": 100, "start_from": 0},
            "perspectives": perspectives or [],
            "questions": questions or [],
            "answers": answers or {},
            "pending_questions": pending_questions or {},
            "doc_id": None,
            "history_stack": [],
            "created_at": time.time(),
            "updated_at": time.time(),
            "summary_of_answers": "",
        }
        self._write(spec)
        return spec

    def load(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Load a report spec draft by ID. Returns None if not found."""
        p = self._path(draft_id)
        if not p.exists():
            logger.warning(f"ReportDraftManager: draft {draft_id!r} not found")
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error(f"ReportDraftManager: failed to load {draft_id}: {exc}")
            return None

    def save(self, spec: Dict[str, Any]) -> None:
        """Persist a draft spec (updates updated_at)."""
        spec["updated_at"] = time.time()
        self._write(spec)

    def delete(self, draft_id: str) -> bool:
        """Delete a report spec draft. Returns True if found and deleted."""
        p = self._path(draft_id)
        if p.exists():
            p.unlink()
            logger.info(f"ReportDraftManager: deleted {draft_id}")
            return True
        return False

    def _write(self, spec: Dict[str, Any]) -> None:
        p = self._path(spec["draft_id"])
        p.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

    def push_history(self, spec: Dict[str, Any]) -> None:
        """Snapshot current mutable state onto the history stack before advancing."""
        snapshot = {
            "phase": spec["phase"],
            "phase_label": spec["phase_label"],
            "columns": copy.deepcopy(spec["columns"]),
            "content_filters": copy.deepcopy(spec.get("content_filters", {})),
            "shape_defaults": copy.deepcopy(spec.get("shape_defaults", {})),
            "performance_hints": copy.deepcopy(spec.get("performance_hints", {})),
            "perspectives": copy.deepcopy(spec.get("perspectives", [])),
            "questions": copy.deepcopy(spec.get("questions", [])),
            "answers": copy.deepcopy(spec["answers"]),
            "pending_questions": copy.deepcopy(spec["pending_questions"]),
            "summary_of_answers": spec.get("summary_of_answers", ""),
        }
        spec["history_stack"].append(snapshot)

    def pop_history(self, spec: Dict[str, Any]) -> bool:
        """Restore the previous state from the history stack. Returns True if rewound."""
        if not spec["history_stack"]:
            return False
        snapshot = spec["history_stack"].pop()
        spec["phase"] = snapshot["phase"]
        spec["phase_label"] = snapshot["phase_label"]
        spec["columns"] = snapshot["columns"]
        spec["content_filters"] = snapshot.get("content_filters", {})
        spec["shape_defaults"] = snapshot.get("shape_defaults", {})
        spec["performance_hints"] = snapshot.get("performance_hints", {})
        spec["perspectives"] = snapshot.get("perspectives", [])
        spec["questions"] = snapshot.get("questions", [])
        spec["answers"] = snapshot["answers"]
        spec["pending_questions"] = snapshot["pending_questions"]
        spec["summary_of_answers"] = snapshot.get("summary_of_answers", "")
        return True

    def list_drafts(self) -> List[Dict[str, Any]]:
        """Return metadata for all active report drafts, newest first."""
        entries = []
        for jf in sorted(self._root.glob("draft_report_*.json"), reverse=True):
            try:
                spec = json.loads(jf.read_text(encoding="utf-8"))
                entries.append({
                    "draft_id":    spec["draft_id"],
                    "title":       spec.get("title", "(untitled)"),
                    "phase":       spec.get("phase", "unknown"),
                    "phase_label": spec.get("phase_label", ""),
                    "updated_at":  spec.get("updated_at", 0),
                    "created_at":  spec.get("created_at", 0),
                })
            except Exception:
                pass
        return entries


_rdm: Optional[ReportDraftManager] = None


def get_report_draft_manager() -> ReportDraftManager:
    global _rdm
    if _rdm is None:
        _rdm = ReportDraftManager()
    return _rdm
