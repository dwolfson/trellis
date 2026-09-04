"""
DraftManager — lifecycle management for in-progress plan Q&A sessions.

Draft specs are stored as JSON in ~/egeria-plans/drafts/.
Each draft captures the full conversation state so planning sessions
can be paused, resumed, rewound (Back), or abandoned (Start Over).

Draft spec schema:
  draft_id          — unique ID (timestamp + slug)
  title             — plan title (may be provisional)
  phase             — current state machine phase
  phase_label       — human-readable "where you are"
  mode              — "basic" | "advanced"
  perspective       — active user role
  original_query    — verbatim user request that started the plan
  template_name     — name of plan template used as starting point (or null)
  commands_identified — list of {action, display_name, description, rationale, pre_filled}
  answers           — {action: {field: value}} accumulated so far
  pending_questions — {required: [...], optional: [...]}
  doc_id            — set after the plan document is generated (inbox doc_id)
  history_stack     — list of snapshot dicts for Back navigation
  created_at        — Unix timestamp
  updated_at        — Unix timestamp
  summary_of_answers — short markdown recap shown on resume
"""
from __future__ import annotations

import json
import re
import time
import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _drafts_path() -> Path:
    """Return path to the drafts folder, creating it if necessary."""
    base = Path.home() / "egeria-plans"
    default = base / "drafts"
    try:
        cfg_file = Path(__file__).parent / "configdata" / "advisor.yaml"
        with open(cfg_file) as f:
            cfg = yaml.safe_load(f)
        gp = cfg.get("governance_plans", {})
        p = Path(gp["drafts"]).expanduser() if "drafts" in gp else default
    except Exception:
        p = default
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slug(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:40].strip("_")


# ---------------------------------------------------------------------------
# Per-user namespacing — docs/design/SESSION_AND_INTERACTION_STATE.md's
# target layout: `~/egeria-plans/users/{user_id}/drafts/`, sibling to the
# shared drafts/ root above. See docs/runtime-architecture-plan.md §4.
# ---------------------------------------------------------------------------

def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.@-]", "_", user_id)[:100]


def _user_drafts_path(user_id: str) -> Path:
    p = _drafts_path().parent / "users" / _safe_user_id(user_id) / "drafts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _list_namespaced_user_ids() -> List[str]:
    users_dir = _drafts_path().parent / "users"
    if not users_dir.is_dir():
        return []
    return sorted(p.name for p in users_dir.iterdir() if p.is_dir())


_CURATOR_ROLES = {"admin", "curator"}


def _is_curator_role(role: Optional[str]) -> bool:
    return (role or "").lower() in _CURATOR_ROLES


# ---------------------------------------------------------------------------
# DraftManager
# ---------------------------------------------------------------------------

class DraftManager:
    """CRUD for plan draft specs.

    Namespacing: an instance with no user_id (the module singleton every
    existing internal caller uses — rag_system.py, plan_elicitor.py,
    governance_plan_agent.py) reads/writes the shared root, unchanged. An
    instance constructed with a user_id (get_draft_manager(user_id=...))
    reads/writes that user's `users/{user_id}/drafts/` tree instead — used
    by the direct REST creation entry point (create_builder_draft) and by
    resolve_draft()/list_visible_drafts() below for ownership-aware reads.
    Chat-driven draft creation (PlanElicitor → DraftManager.create()) still
    goes through the shared singleton this pass — threading user_id through
    that whole pipeline is out of scope here; flagged as follow-on.
    """

    def __init__(self, user_id: Optional[str] = None) -> None:
        self._user_id = user_id
        self._root = _user_drafts_path(user_id) if user_id else _drafts_path()

    def _path(self, draft_id: str) -> Path:
        return self._root / f"{draft_id}.json"

    # ------------------------------------------------------------------
    # Create / Load / Save / Delete
    # ------------------------------------------------------------------

    def create(
        self,
        title: str,
        original_query: str,
        commands_identified: List[Dict],
        pending_questions: Dict,
        pre_filled_answers: Dict,
        mode: str = "basic",
        perspective: Optional[str] = None,
        template_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new draft spec, persist it, and return it."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        draft_id = f"draft_{ts}_{_slug(title)}"
        spec: Dict[str, Any] = {
            "draft_id": draft_id,
            "title": title,
            "phase": "elicit_required",
            "phase_label": "Answering required field questions",
            "mode": mode,
            "perspective": perspective,
            "original_query": original_query,
            "template_name": template_name,
            "commands_identified": commands_identified,
            "answers": pre_filled_answers,
            "pending_questions": pending_questions,
            "doc_id": None,
            "history_stack": [],
            "created_at": time.time(),
            "updated_at": time.time(),
            "summary_of_answers": "",
            "user_id": self._user_id,
        }
        self._write(spec)
        return spec

    def load(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Load a draft by ID. Returns None if not found."""
        p = self._path(draft_id)
        if not p.exists():
            logger.warning(f"DraftManager: draft {draft_id!r} not found")
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error(f"DraftManager: failed to load {draft_id}: {exc}")
            return None

    def save(self, spec: Dict[str, Any]) -> None:
        """Persist a draft spec (updates updated_at)."""
        spec["updated_at"] = time.time()
        self._write(spec)

    def update_doc_id(self, draft_id: str, new_doc_id: str) -> bool:
        """
        Update a draft's doc_id — e.g. after execution moves the plan from
        inbox to outbox under a new, timestamp-suffixed id. Without this,
        resuming a draft whose plan has since been executed hands back a
        doc_id that no longer exists anywhere. See BACKLOG.md.

        Returns True if the draft was found and updated.
        """
        spec = self.load(draft_id)
        if spec is None:
            return False
        spec["doc_id"] = new_doc_id
        self.save(spec)
        logger.info(f"DraftManager: updated {draft_id!r}.doc_id -> {new_doc_id!r}")
        return True

    def _find_repair_candidate(self, doc_id: str) -> Optional[str]:
        """
        Search outbox for the newest file sharing doc_id's pre-"_executed_"
        base name — the file a stale doc_id most likely got renamed to by a
        (re-)execution. Returns None if nothing matches.

        Filenames are fixed-width timestamps, so lexicographic sort is
        chronological — the last match is the most recent execution.
        """
        from advisor.governance_docs import get_doc_manager
        outbox_dir = get_doc_manager()._paths["outbox"]
        base_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        candidates = sorted(outbox_dir.glob(f"{base_id}_executed_*.md"))
        return candidates[-1].stem if candidates else None

    def resolve_live_doc_id(
        self, draft_id: str, spec: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Return draft_id's current doc_id, self-healing it in place if it's
        gone stale (see _find_repair_candidate). Every caller that's about to
        load/edit/execute a draft's document should resolve through here
        instead of reading spec["doc_id"] directly — that direct-read pattern
        is what let a stale pointer (created whenever a plan is executed
        through a path that doesn't thread draft_id all the way to
        GovernancePlanAgent.execute()) go unnoticed at each new call site.
        See BACKLOG.md.

        Pass spec if already loaded, to avoid a redundant disk read. Returns
        None if the draft doesn't exist or has no document yet. If the id is
        stale and no confident replacement is found, returns the original
        (stale) id unchanged — the caller's existing "not found" handling
        still applies for genuinely-deleted documents.
        """
        from advisor.governance_docs import get_doc_manager
        if spec is None:
            spec = self.load(draft_id)
        if spec is None:
            return None
        doc_id = spec.get("doc_id")
        if not doc_id:
            return None
        if get_doc_manager().folder_of(doc_id) is not None:
            return doc_id
        new_doc_id = self._find_repair_candidate(doc_id)
        if new_doc_id:
            self.update_doc_id(draft_id, new_doc_id)
            return new_doc_id
        return doc_id

    def sync_document(
        self, draft_id: str, spec: Dict[str, Any], new_content: str,
        edited_by: Optional[str] = None,
    ) -> Optional[str]:
        """
        Write new_content to draft_id's live plan document and persist the
        (possibly-mutated) spec together, as one operation.

        Replaces the "doc_manager.update(...) then separately dm.save(spec)"
        pattern repeated across plan_elicitor.py/app.py — the two calls were
        easy to get out of sync (e.g. saving the spec but silently skipping
        the document write when doc_id had gone stale, with no error
        surfaced). Resolves the live doc_id first, so a repaired id is
        reflected in both the write and the saved spec.

        Returns the doc_id actually written to, or None if there's no
        document yet or the write failed (document genuinely missing).
        """
        from advisor.governance_docs import get_doc_manager
        doc_id = self.resolve_live_doc_id(draft_id, spec=spec)
        if not doc_id:
            return None
        if not get_doc_manager().update(doc_id, new_content, edited_by=edited_by):
            return None
        spec["doc_id"] = doc_id
        self.save(spec)
        return doc_id

    def check_doc_ids(self, repair: bool = False) -> List[Dict[str, Any]]:
        """
        Find drafts whose doc_id no longer points at a real inbox/outbox file.

        This happens when a plan is executed (or re-executed) through a code
        path that doesn't thread draft_id through to
        GovernancePlanAgent.execute() — each execution renames the file with a
        fresh "_executed_<ts>" suffix, so a draft whose doc_id was never
        updated is left pointing at a filename that's since been superseded.
        See update_doc_id() and BACKLOG.md.

        For each stale draft, uses the same repair heuristic as
        resolve_live_doc_id() and repairs it in place when repair=True and an
        unambiguous candidate is found.

        Returns a list of {draft_id, doc_id, status, new_doc_id?} — status is
        one of "ok", "no_doc" (never generated — nothing to check), "repaired",
        or "unresolved" (stale but no confident replacement found; needs a
        human to look, e.g. via Recover from the plan's version history).
        """
        from advisor.governance_docs import get_doc_manager
        doc_manager = get_doc_manager()

        report: List[Dict[str, Any]] = []
        for path in sorted(self._root.glob("*.json")):
            draft_id = path.stem
            spec = self.load(draft_id)
            if spec is None:
                continue
            doc_id = spec.get("doc_id")
            if not doc_id:
                report.append({"draft_id": draft_id, "doc_id": None, "status": "no_doc"})
                continue
            if doc_manager.load(doc_id) is not None:
                report.append({"draft_id": draft_id, "doc_id": doc_id, "status": "ok"})
                continue

            entry: Dict[str, Any] = {"draft_id": draft_id, "doc_id": doc_id, "status": "unresolved"}
            new_doc_id = self._find_repair_candidate(doc_id)
            if new_doc_id:
                entry["new_doc_id"] = new_doc_id
                if repair:
                    self.update_doc_id(draft_id, new_doc_id)
                    entry["status"] = "repaired"
            report.append(entry)
        return report

    def delete(self, draft_id: str) -> bool:
        """Delete a draft. Returns True if found and deleted."""
        p = self._path(draft_id)
        if p.exists():
            p.unlink()
            logger.info(f"DraftManager: deleted {draft_id}")
            return True
        return False

    def _write(self, spec: Dict[str, Any]) -> None:
        p = self._path(spec["draft_id"])
        p.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # History (Back navigation)
    # ------------------------------------------------------------------

    def push_history(self, spec: Dict[str, Any]) -> None:
        """Snapshot current mutable state onto the history stack before advancing."""
        snapshot = {
            "phase": spec["phase"],
            "phase_label": spec["phase_label"],
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
        spec["answers"] = snapshot["answers"]
        spec["pending_questions"] = snapshot["pending_questions"]
        spec["summary_of_answers"] = snapshot.get("summary_of_answers", "")
        return True

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_drafts(self) -> List[Dict[str, Any]]:
        """Return metadata for all active drafts, newest first."""
        entries = []
        for jf in sorted(self._root.glob("draft_*.json"), reverse=True):
            try:
                spec = json.loads(jf.read_text(encoding="utf-8"))
                entries.append({
                    "draft_id":    spec["draft_id"],
                    "title":       spec.get("title", "(untitled)"),
                    "phase":       spec.get("phase", "unknown"),
                    "phase_label": spec.get("phase_label", ""),
                    "mode":        spec.get("mode", "basic"),
                    "updated_at":  spec.get("updated_at", 0),
                    "created_at":  spec.get("created_at", 0),
                })
            except Exception:
                pass
        return entries


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_dm: Optional[DraftManager] = None
_dm_by_user: Dict[str, DraftManager] = {}


def get_draft_manager(user_id: Optional[str] = None) -> DraftManager:
    """The shared-root singleton (no args — every existing internal caller
    uses this, unchanged), or a cached per-user instance when user_id is
    given (used by the direct REST routes and by resolve_draft()/
    list_visible_drafts() below)."""
    global _dm
    if user_id is None:
        if _dm is None:
            _dm = DraftManager()
        return _dm
    if user_id not in _dm_by_user:
        _dm_by_user[user_id] = DraftManager(user_id=user_id)
    return _dm_by_user[user_id]


def list_visible_drafts(user_id: Optional[str] = None,
                         role: Optional[str] = None) -> List[Dict[str, Any]]:
    """Drafts visible to this requester: shared always; the requester's own
    namespace when signed in; every namespace for a curator role. Each entry
    carries "owner" (None for shared). No-args call (anonymous) returns just
    the shared list — preserves `_anonymous_rag_mode`."""
    entries: List[Dict[str, Any]] = []
    for d in get_draft_manager(None).list_drafts():
        d["owner"] = None
        entries.append(d)
    seen_uids = set()
    if user_id:
        for d in get_draft_manager(user_id).list_drafts():
            d["owner"] = user_id
            entries.append(d)
        seen_uids.add(user_id)
    if _is_curator_role(role):
        for uid in _list_namespaced_user_ids():
            if uid in seen_uids:
                continue
            for d in get_draft_manager(uid).list_drafts():
                d["owner"] = uid
                entries.append(d)
    entries.sort(key=lambda d: d.get("updated_at", 0), reverse=True)
    return entries


def resolve_draft(draft_id: str, user_id: Optional[str] = None,
                   role: Optional[str] = None) -> Optional["tuple[DraftManager, Dict[str, Any]]"]:
    """Find draft_id across the namespaces this requester can see and
    return (its DraftManager, its spec) — or None if it doesn't exist OR
    exists but isn't visible to this requester (404, not 403 — avoids
    confirming another user's draft_id exists, same rule as the session
    store). Anonymous (user_id=None) sees the shared namespace only."""
    dm = get_draft_manager(None)
    spec = dm.load(draft_id)
    if spec is not None:
        return dm, spec
    if user_id:
        dm = get_draft_manager(user_id)
        spec = dm.load(draft_id)
        if spec is not None:
            return dm, spec
    if _is_curator_role(role):
        for uid in _list_namespaced_user_ids():
            if uid == user_id:
                continue
            dm = get_draft_manager(uid)
            spec = dm.load(draft_id)
            if spec is not None:
                return dm, spec
    return None


def create_builder_draft(title: str, perspective: Optional[str] = None,
                          user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new blank draft in builder mode (Plan Editor entry point).
    Shared by POST /api/drafts/builder and any chat-driven path (e.g. an
    explicit "...using the canvas" request) that wants to open the canvas
    directly without a separate modal round-trip.

    user_id, when given (the REST route passes the signed-in user), creates
    the draft in that user's namespace instead of the shared root.
    """
    title = (title or "Untitled Plan").strip() or "Untitled Plan"
    dm = get_draft_manager(user_id)
    spec = dm.create(
        title=title,
        original_query=f"[builder] {title}",
        commands_identified=[],
        pending_questions={"required": [], "optional": []},
        pre_filled_answers={},
        mode="basic",
        perspective=perspective,
    )
    spec["phase"] = "confirm_commands"
    spec["phase_label"] = "Building plan"
    spec["builder_mode"] = True
    dm.save(spec)
    return spec
