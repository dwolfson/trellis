"""
PerspectiveManager — role perspectives from Egeria, with a built-in list as the fallback.

Priority:
  1. Live Egeria: ActorManager.find_perspectives(), read as the SIGNED-IN user (their bearer token),
     through EgeriaContext (get_pyegeria_platform_config for the platform). Never the service
     account's password and never mcp_servers.json (A-P1).
  2. configdata/perspectives.csv: the built-in list, used until Egeria answers.

The answer always says which it is (status()): "from Egeria", or "built-in list: Egeria not
reached: <reason>". Anonymous callers get the built-in list with "not signed in".

A successful Egeria load is cached for 24 hours. A failed one is retried by the next signed-in
call after RETRY_AFTER_SECONDS, so a sign-in after a failure isn't stuck on the built-in list for a
day. Refresh is non-blocking (daemon thread).
"""
from __future__ import annotations

import csv
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

_CACHE_TTL_SECONDS = 86_400  # 24 hours after a successful Egeria load
RETRY_AFTER_SECONDS = 60     # after a failed one

_CSV_PATH = Path(__file__).parent / "configdata" / "perspectives.csv"

SOURCE_EGERIA = "egeria"
SOURCE_BUILT_IN = "built_in"


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_perspectives: List[Dict] = []
_loaded_at: Optional[datetime] = None      # last SUCCESSFUL Egeria load
_attempted_at: Optional[datetime] = None   # last attempt, successful or not
_status: Dict[str, Optional[str]] = {"source": SOURCE_BUILT_IN,
                                     "message": "built-in list: Egeria not reached: not read yet"}
_refresh_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Built-in list
# ---------------------------------------------------------------------------

def _load_from_csv() -> List[Dict]:
    rows: List[Dict] = []
    try:
        with open(_CSV_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not row.get("advisor_key"):
                    continue
                rows.append({
                    "advisor_key":  row["advisor_key"].strip(),
                    "display_name": row.get("display_name", "").strip(),
                    "egeria_name":  row.get("egeria_name", "").strip(),
                    "description":  row.get("description", "").strip(),
                    "tooltip":      row.get("tooltip", "").strip(),
                    "questions":    [],
                    "source":       "csv",
                })
    except Exception as exc:
        logger.warning(f"PerspectiveManager: CSV load failed — {exc}")
        return []
    return rows


# ---------------------------------------------------------------------------
# Egeria loader
# ---------------------------------------------------------------------------

def _advisor_key(egeria_name: str) -> str:
    """Convert an Egeria perspective display name to an advisor_key."""
    return re.sub(r"\s+", "_", egeria_name.strip().lower())


def _questions(element: Dict) -> List[str]:
    """The questions scoped to a perspective: its ScopedBy GlossaryTerms whose name is a question.
    (A perspective also scopes other elements, e.g. collections and dashboard placements.)"""
    out: List[str] = []
    for rel in element.get("scopedElements") or []:
        related = rel.get("relatedElement") or {}
        type_name = ((related.get("elementHeader") or {}).get("type") or {}).get("typeName")
        name = ((related.get("properties") or {}).get("displayName") or "").strip()
        if type_name == "GlossaryTerm" and name.endswith("?") and name not in out:
            out.append(name)
    return out


def rows_from_egeria(raw: List[Dict]) -> List[Dict]:
    """Perspective rows from a find_perspectives JSON answer (properties.* via _parse_element)."""
    from advisor.egeria_context import _parse_element
    csv_rows = {r["egeria_name"].lower(): r for r in _load_from_csv()}
    rows: List[Dict] = []
    for element in raw:
        if not isinstance(element, dict):
            continue
        parsed = _parse_element(element)
        props = element.get("properties") or {}
        egeria_name = (props.get("displayName") or parsed["display_name"] or "").strip()
        if not egeria_name:
            continue
        csv_match = csv_rows.get(egeria_name.lower(), {})
        rows.append({
            "advisor_key":  csv_match.get("advisor_key") or _advisor_key(egeria_name),
            "display_name": csv_match.get("display_name") or egeria_name,
            "egeria_name":  egeria_name,
            "description":  props.get("description") or csv_match.get("description", ""),
            "tooltip":      csv_match.get("tooltip", ""),
            "questions":    _questions(element),
            "source":       SOURCE_EGERIA,
            "guid":         parsed["guid"],
            "qualified_name": parsed["qualified_name"],
        })
    return rows


def load_from_egeria(egeria_credentials: Optional[Dict[str, str]]) -> tuple[List[Dict], Optional[str]]:
    """(rows, None) on success, or ([], reason) saying why Egeria gave no perspectives."""
    from advisor.egeria_context import EgeriaContext, failure_answer
    from advisor.egeria_signin import SIGN_IN_TO_READ_EGERIA
    if not egeria_credentials or not egeria_credentials.get("token"):
        # No signed-in token: do not fall back to the service account (A-P1).
        return [], f"not signed in. {SIGN_IN_TO_READ_EGERIA}"
    ctx = EgeriaContext(egeria_credentials=egeria_credentials)
    mgr = ctx._actor_manager()
    if not mgr:
        return [], _reason(ctx._not_read()["message"])
    try:
        raw = mgr.find_perspectives(search_string="*", output_format="JSON")
    except Exception as exc:
        logger.info(f"PerspectiveManager: Egeria load failed [{type(exc).__name__}] — {exc}")
        return [], _reason(failure_answer(exc, "perspectives")["message"])
    from pyegeria.core._globals import NO_ELEMENTS_FOUND
    if isinstance(raw, str) and raw.strip() == NO_ELEMENTS_FOUND:
        return [], f"Egeria holds no perspectives that {ctx.viewer} can see"
    if not isinstance(raw, list):
        return [], f"Egeria gave an unexpected answer to find_perspectives: {str(raw)[:120]!r}"
    rows = rows_from_egeria(raw)
    if not rows:
        return [], f"Egeria holds no named perspectives that {ctx.viewer} can see"
    logger.info(f"PerspectiveManager: loaded {len(rows)} perspectives from Egeria")
    return rows, None


def _reason(message: str) -> str:
    """'Egeria not reached: X' -> 'X' (the status line adds its own prefix)."""
    prefix = "Egeria not reached: "
    return message[len(prefix):] if message.startswith(prefix) else message


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _do_refresh(egeria_credentials: Optional[Dict[str, str]]) -> None:
    global _perspectives, _loaded_at, _attempted_at, _status
    with _refresh_lock:
        _attempted_at = datetime.now(timezone.utc)
        rows, reason = load_from_egeria(egeria_credentials)
        if rows:
            _perspectives = rows
            _loaded_at = _attempted_at
            _status = {"source": SOURCE_EGERIA, "message": "from Egeria"}
        elif _perspectives and _perspectives[0].get("source") == SOURCE_EGERIA:
            # Keep the last good Egeria list, and say the refresh failed.
            _status = {"source": SOURCE_EGERIA,
                       "message": f"from Egeria (as of {_loaded_at:%Y-%m-%d %H:%M} UTC); "
                                  f"the latest refresh failed: {reason}"}
        else:
            _perspectives = _load_from_csv()
            _status = {"source": SOURCE_BUILT_IN, "message": f"built-in list: Egeria not reached: {reason}"}
        logger.info(f"PerspectiveManager: {len(_perspectives)} perspectives, {_status['message']}")


def _ensure_loaded(egeria_credentials: Optional[Dict[str, str]] = None) -> None:
    """Load the built-in list at once if nothing is loaded, and start a background Egeria read when
    one is due and there is a signed-in caller to read as."""
    global _perspectives, _status
    now = datetime.now(timezone.utc)
    if not _perspectives:
        _perspectives = _load_from_csv()
    if _loaded_at is not None and (now - _loaded_at).total_seconds() < _CACHE_TTL_SECONDS:
        return
    if not (egeria_credentials and egeria_credentials.get("token")):
        if _status["source"] == SOURCE_BUILT_IN:
            from advisor.egeria_signin import SIGN_IN_TO_READ_EGERIA
            _status = {"source": SOURCE_BUILT_IN,
                       "message": f"built-in list: Egeria not reached: not signed in. {SIGN_IN_TO_READ_EGERIA}"}
        return
    if _attempted_at is not None and (now - _attempted_at).total_seconds() < RETRY_AFTER_SECONDS:
        return
    threading.Thread(target=_do_refresh, args=(egeria_credentials,), daemon=True).start()


def get_all(egeria_credentials: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Return all known perspectives (at least the built-in set). Pass the signed-in caller's
    credentials to let a due Egeria refresh run as them."""
    _ensure_loaded(egeria_credentials)
    return list(_perspectives)


def status() -> Dict[str, Optional[str]]:
    """{"source": "egeria" | "built_in", "message": "from Egeria" | "built-in list: Egeria not reached: <reason>"}"""
    return dict(_status)


def get_advisor_keys() -> List[str]:
    return [p["advisor_key"] for p in get_all()]


def egeria_name_for_key(advisor_key: str) -> Optional[str]:
    for p in get_all():
        if p["advisor_key"] == advisor_key:
            return p["egeria_name"]
    return None


def advisor_key_for_egeria_name(egeria_name: str) -> Optional[str]:
    name_lower = egeria_name.strip().lower()
    for p in get_all():
        if p["egeria_name"].lower() == name_lower:
            return p["advisor_key"]
    return _advisor_key(egeria_name)


def get_questions_for_key(advisor_key: str) -> List[str]:
    """Return questions linked to this perspective from Egeria (empty list from CSV)."""
    for p in get_all():
        if p["advisor_key"] == advisor_key:
            return p.get("questions", [])
    return []


def invalidate() -> None:
    """Force a refresh on the next signed-in call."""
    global _loaded_at, _attempted_at
    _loaded_at = None
    _attempted_at = None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def get_perspective_manager():
    """Return the module itself — stateless singleton pattern."""
    _ensure_loaded()
    import advisor.perspective_manager as _self
    return _self
