"""
PerspectiveManager — loads role perspectives from Egeria (dynamic) with CSV fallback.

Priority:
  1. Live Egeria via ActorManager.find_perspectives() — refreshed in background
  2. config/perspectives.csv — always-available fallback

Cached for 24 hours; refresh is non-blocking (daemon thread).
"""
from __future__ import annotations

import csv
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

_CACHE_TTL_SECONDS = 86_400  # 24 hours

_CSV_PATH = Path(__file__).parent.parent / "config" / "perspectives.csv"
_MCP_CFG  = Path(__file__).parent.parent / "config" / "mcp_servers.json"


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_perspectives: List[Dict] = []
_loaded_at: Optional[datetime] = None
_refresh_lock = threading.Lock()


# ---------------------------------------------------------------------------
# CSV fallback
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
    return rows


# ---------------------------------------------------------------------------
# Egeria loader
# ---------------------------------------------------------------------------

def _egeria_conn() -> Dict[str, str]:
    try:
        cfg = json.loads(_MCP_CFG.read_text())
        env = cfg.get("mcpServers", {}).get("pyegeria", {}).get("env", {})
        return {
            "view_server":  env.get("EGERIA_VIEW_SERVER", ""),
            "platform_url": env.get("EGERIA_VIEW_SERVER_URL", ""),
            "user_id":      env.get("EGERIA_USER", ""),
            "user_pwd":     env.get("EGERIA_PASSWORD", ""),
        }
    except Exception:
        return {}


def _advisor_key(egeria_name: str) -> str:
    """Convert an Egeria perspective display name to an advisor_key."""
    return re.sub(r"\s+", "_", egeria_name.strip().lower())


def _load_from_egeria() -> List[Dict]:
    conn = _egeria_conn()
    if not all(conn.values()):
        logger.debug("PerspectiveManager: incomplete Egeria config — skipping live load")
        return []
    try:
        from pyegeria.egeria_tech_client import EgeriaTech
        client = EgeriaTech(**conn)
        client.create_egeria_bearer_token(conn["user_id"], conn["user_pwd"])

        raw = client.actor_mgr.find_perspectives(search_string="*", output_format="JSON")
        if not raw or not isinstance(raw, list):
            logger.debug(f"PerspectiveManager: find_perspectives returned {type(raw).__name__} — skipping")
            return []

        logger.info(f"PerspectiveManager: loaded {len(raw)} perspectives from Egeria")
        logger.debug(f"PerspectiveManager: sample perspective keys = {list(raw[0].keys()) if raw else []}")

        # Build CSV key map for matching
        csv_rows = {r["egeria_name"].lower(): r for r in _load_from_csv()}

        rows: List[Dict] = []
        for p in raw:
            egeria_name = (p.get("displayName") or p.get("display_name") or "").strip()
            if not egeria_name:
                continue

            # Try to match with CSV for advisor_key / tooltip
            csv_match = csv_rows.get(egeria_name.lower(), {})
            advisor_key = csv_match.get("advisor_key") or _advisor_key(egeria_name)

            # Extract linked questions if present
            questions: List[str] = []
            for key in ("questions", "linked_questions", "question_spec", "questionSpec"):
                val = p.get(key)
                if isinstance(val, list):
                    questions = [q.get("question") or q if isinstance(q, dict) else str(q)
                                 for q in val if q]
                    break

            rows.append({
                "advisor_key":  advisor_key,
                "display_name": csv_match.get("display_name") or egeria_name,
                "egeria_name":  egeria_name,
                "description":  p.get("description") or csv_match.get("description", ""),
                "tooltip":      csv_match.get("tooltip", ""),
                "questions":    questions,
                "source":       "egeria",
                "guid":         p.get("guid", ""),
            })

        return rows

    except Exception as exc:
        logger.info(f"PerspectiveManager: Egeria load failed [{type(exc).__name__}] — {exc}")
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _do_refresh() -> None:
    global _perspectives, _loaded_at
    with _refresh_lock:
        rows = _load_from_egeria()
        if not rows:
            rows = _load_from_csv()
        _perspectives = rows
        _loaded_at = datetime.now(timezone.utc)
        logger.info(
            f"PerspectiveManager: refreshed {len(_perspectives)} perspectives "
            f"(source: {_perspectives[0]['source'] if _perspectives else 'none'})"
        )


def _ensure_loaded() -> None:
    """Load perspectives if not yet loaded or cache expired."""
    global _perspectives, _loaded_at
    if _loaded_at is not None:
        age = (datetime.now(timezone.utc) - _loaded_at).total_seconds()
        if age < _CACHE_TTL_SECONDS:
            return
    # Non-blocking: kick off a background refresh; use CSV immediately if empty
    if not _perspectives:
        _perspectives = _load_from_csv()
    threading.Thread(target=_do_refresh, daemon=True).start()


def get_all() -> List[Dict]:
    """Return all known perspectives (at least the CSV set)."""
    _ensure_loaded()
    return list(_perspectives)


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
    """Force a refresh on the next call."""
    global _loaded_at
    _loaded_at = None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance_lock = threading.Lock()


def get_perspective_manager():
    """Return the module itself — stateless singleton pattern."""
    _ensure_loaded()
    import advisor.perspective_manager as _self
    return _self
