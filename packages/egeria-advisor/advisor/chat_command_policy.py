"""Which Dr.Egeria commands a chat message may compose (EA's DrEgeriaActionAgent).

EA's action agent indexes pyegeria's packaged templates, advanced tier included. Some families must never be
composed from a chat message, however the confirm gate is answered: the MetadataExpert family changes Egeria's
type system and raw instances ("delete type def X", "delete instance <guid>"). Read-back
READBACK-metadata-expert-family-2026-11-13 §2.

Two sources, either one refuses:
  1. pyegeria's compact command specs: `chat_allowed: false`, on the command itself or at the top of its family's
     compact file. This is the long-term source (pyegeria is adding it to the MetadataExpert family).
  2. CHAT_DENIED_FAMILIES, by family name, until that flag ships in the pyegeria EA runs on. Keep a family here
     even after the flag ships: a pyegeria older than the flag must not reopen it.

Names compare without case, spaces, underscores or hyphens, so "MetadataExpert" (the template folder) and
"Metadata Expert" (a spec's family) are one family.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

from loguru import logger

#: Families no chat message composes, by name. See the module docstring for why this stays after the flag.
CHAT_DENIED_FAMILIES = frozenset({"metadataexpert"})


def _norm(name: Optional[str]) -> str:
    return re.sub(r"[\s_\-]+", "", name or "").lower()


def _compact_dir() -> Optional[Path]:
    try:
        import md_processing
    except ImportError:
        return None
    d = Path(md_processing.__file__).parent / "data" / "compact_commands"
    return d if d.is_dir() else None


def _commands(doc: dict):
    cmds = doc.get("commands") or []
    return cmds.values() if isinstance(cmds, dict) else cmds


@lru_cache(maxsize=1)
def _spec_flags() -> Tuple[frozenset, Dict[str, str]]:
    """(families pyegeria marks chat_allowed false, {command: its family} for commands marked so)."""
    families, commands = set(), {}
    d = _compact_dir()
    if d is None:
        return frozenset(), {}
    for f in sorted(d.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:   # a file we cannot read flags nothing; the deny-list still holds
            logger.warning(f"chat_command_policy: could not read {f.name}: {exc}")
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("chat_allowed") is False:
            families.add(_norm(doc.get("family")))
        for c in _commands(doc):
            if isinstance(c, dict) and c.get("chat_allowed") is False:
                commands[_norm(c.get("display_name"))] = c.get("family") or doc.get("family") or ""
    return frozenset(families), commands


def chat_refusal(command_name: str, family: Optional[str]) -> Optional[str]:
    """The sentence that refuses composing `command_name` from chat, or None when chat may compose it."""
    spec_families, spec_commands = _spec_flags()
    fam = _norm(family)
    if _norm(command_name) in spec_commands or (fam and fam in spec_families):
        why = "its Dr.Egeria specification marks it as not available from chat"
    elif fam in CHAT_DENIED_FAMILIES:
        why = (f"the {family} commands change Egeria's type system and raw instances, so they are kept out of "
               "chat actions")
    else:
        return None
    return (f"**{command_name}** can't be composed from a chat message: {why}. Nothing was composed or run. "
            "Use a reviewed Dr.Egeria document for it instead.")
