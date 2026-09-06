"""
Cached registry of known Egeria open-metadata type names.

Used to resolve free-text element-type mentions in natural-language queries
(e.g. "external references" -> "ExternalReference", "data products" ->
"DigitalProduct") against real Egeria type names, instead of naively taking
the first word after a verb -- which truncates multi-word type names and
sends Egeria's findElements call a type name it doesn't recognize.

The registry is built from the `target_type` field of every entry in
config/report_specs/report_specs_annotated.json (75 distinct Dr.Egeria
template target types as of Jul 2026) — a static, bundled list that works
even when Egeria itself isn't reachable (the exact scenario that surfaced
this bug). See BACKLOG.md IB-9 for optionally supplementing this from a live
Egeria type listing for full type-system coverage.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

# Repo-level config/ (2026-09-06): report specs moved out of the package to
# <repo>/config/report_specs/, shared across the workspace rather than owned by
# EA. Before the move there were two copies under advisor/configdata/ — a
# report_specs/ subdir and a bare file — and generate_question_specs.py wrote
# the bare one while this list preferred the subdir, so a regeneration updated
# a file the registry did not read. One home now; no fallback, because a
# fallback is what let them drift apart unnoticed.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_REGISTRY_CANDIDATES = [
    _REPO_ROOT / "config" / "report_specs" / "report_specs_annotated.json",
]

# Common industry terminology that doesn't textually match Egeria's own type name.
# Egeria calls it "DigitalProduct"; most people say "data product" — normalize both
# to the same key so free-text queries resolve correctly. Add more here as they
# surface; there's no general way to derive these without a synonym source.
_ALIASES: Dict[str, str] = {
    "dataproduct": "DigitalProduct",
    "dataproducts": "DigitalProduct",
}


def _normalize(s: str) -> str:
    """Lowercase, strip whitespace/hyphens/underscores, naive-singularize."""
    s = re.sub(r"[\s_\-]+", "", s.lower())
    if s.endswith("ies") and len(s) > 3:
        s = s[:-3] + "y"  # "glossaries" -> "glossary"
    elif s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s


@lru_cache(maxsize=1)
def _load_registry() -> Dict[str, str]:
    """
    Build {normalized_form: canonical_pascal_case_type_name}, cached for the process
    lifetime — the source file doesn't change at runtime.
    """
    registry: Dict[str, str] = {}
    data = None
    for path in _REGISTRY_CANDIDATES:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                break
            except Exception as exc:
                logger.warning(f"egeria_type_registry: failed to parse {path}: {exc}")

    if data is None:
        logger.warning("egeria_type_registry: no report_specs_annotated.json found; registry empty")
        return registry

    for entry in data.values():
        target_type = entry.get("target_type") if isinstance(entry, dict) else None
        if not target_type:
            continue
        pascal = target_type.replace(" ", "")  # "External Reference" -> "ExternalReference"
        registry[_normalize(target_type)] = pascal
        registry[_normalize(pascal)] = pascal

    for alias_norm, canonical in _ALIASES.items():
        registry[alias_norm] = canonical

    logger.info(f"egeria_type_registry: loaded {len(registry)} normalized type-name entries "
                f"({len(set(registry.values()))} distinct types)")
    return registry


def invalidate() -> None:
    """Clear the cached registry so the next lookup rebuilds from disk.

    Call after report_specs_annotated.json has been regenerated/edited so a
    running process picks up the change without a restart. Wired to
    POST /api/admin/maintenance/invalidate_index.
    """
    _load_registry.cache_clear()


def known_type_names() -> List[str]:
    """Return the distinct canonical (PascalCase) type names in the registry."""
    return sorted(set(_load_registry().values()))


def resolve_type_name(words: List[str]) -> Optional[str]:
    """
    Resolve a sequence of query words to a canonical Egeria type name.

    Tries the longest word-prefix first (up to 4 words), shrinking by one word at a
    time, so multi-word type names ("external reference(s)", "data product(s)")
    aren't truncated to their first word. Returns the canonical PascalCase type name
    (e.g. "ExternalReference") or None if nothing in the registry matches.
    """
    if not words:
        return None
    registry = _load_registry()
    for length in range(min(len(words), 4), 0, -1):
        candidate = " ".join(words[:length])
        norm = _normalize(candidate)
        if norm in registry:
            return registry[norm]
    return None
