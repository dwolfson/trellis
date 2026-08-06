"""
ActionCatalog — loads and queries the Dr.Egeria action definitions from
config/dr_egeria_actions.yaml.

Provides:
  get_action_catalog()  → singleton ActionCatalog
  ActionCatalog.get(name)            → action definition dict or None
  ActionCatalog.find_by_alias(text)  → best-matching action name or None
  ActionCatalog.ordering_priority(name) → int (lower = must run first)
  ActionCatalog.supersedes(name)     → list of action names this replaces
  ActionCatalog.requires(name)       → list of action names that must precede
  ActionCatalog.narrative_template(name) → template string or ""
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger


def _catalog_path() -> Path:
    return Path(__file__).parent.parent / "config" / "dr_egeria_actions.yaml"


@lru_cache(maxsize=1)
def _load_raw() -> Dict[str, Any]:
    p = _catalog_path()
    try:
        with open(p) as f:
            return yaml.safe_load(f)
    except Exception as exc:
        logger.warning(f"ActionCatalog: failed to load {p}: {exc}")
        return {"actions": [], "ordering_priority": []}


class ActionCatalog:
    def __init__(self) -> None:
        raw = _load_raw()
        self._actions: Dict[str, Dict] = {
            a["name"]: a for a in (raw.get("actions") or [])
        }
        self._ordering: List[Dict] = raw.get("ordering_priority") or []
        # Build alias → name index (longest alias wins on ties)
        self._alias_index: List[tuple[str, str]] = []
        for action in self._actions.values():
            for alias in (action.get("aliases") or []):
                self._alias_index.append((alias.lower(), action["name"]))
        self._alias_index.sort(key=lambda x: -len(x[0]))

    # ── Lookup ──────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[Dict]:
        return self._actions.get(name)

    def all_names(self) -> List[str]:
        return list(self._actions.keys())

    def find_by_alias(self, text: str) -> Optional[str]:
        """Return the action name whose alias best matches text, or None."""
        t = text.lower()
        for alias, name in self._alias_index:
            if alias in t:
                return name
        return None

    # ── Rules ───────────────────────────────────────────────────────────────

    def ordering_priority(self, name: str) -> int:
        """Return ordering priority for this action (lower = must run first)."""
        low = name.lower()
        for rule in self._ordering:
            if re.search(rule["pattern"], low):
                return int(rule["priority"])
        return 500  # default: middle of the pack

    def supersedes(self, name: str) -> List[str]:
        """Return list of action names that `name` replaces."""
        action = self._actions.get(name)
        if not action:
            return []
        return [s["action"] for s in (action.get("supersedes") or [])]

    def is_superseded_by(self, name: str) -> Optional[str]:
        """If `name` is superseded by another action, return that action's name."""
        for aname, adef in self._actions.items():
            for sup in (adef.get("supersedes") or []):
                if sup["action"] == name:
                    return aname
        return None

    def requires(self, name: str) -> List[str]:
        action = self._actions.get(name)
        if not action:
            return []
        return list(action.get("requires") or [])

    def required_before(self, name: str) -> List[str]:
        action = self._actions.get(name)
        if not action:
            return []
        return list(action.get("required_before") or [])

    def container_for(self, name: str) -> List[str]:
        action = self._actions.get(name)
        if not action:
            return []
        return list(action.get("container_for") or [])

    def narrative_template(self, name: str) -> str:
        action = self._actions.get(name)
        if not action:
            return ""
        t = action.get("narrative_template") or ""
        return t.strip()

    def not_when(self, name: str) -> str:
        action = self._actions.get(name)
        return (action or {}).get("not_when", "").strip()

    def patterns(self, name: str) -> List[Dict]:
        action = self._actions.get(name)
        return list((action or {}).get("patterns") or [])


# ── Singleton ────────────────────────────────────────────────────────────────

_catalog: Optional[ActionCatalog] = None


def get_action_catalog() -> ActionCatalog:
    global _catalog
    if _catalog is None:
        _catalog = ActionCatalog()
    return _catalog
