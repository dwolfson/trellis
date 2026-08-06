"""
egeria_type_agent.py — Live structural answers for Egeria's own metadata type
system (subtypes, classifications), analogous to CodeIntelAgent's live-SQL
approach for Python/Java code structure.

Questions like "what are the subtypes of Collection" or "what classifications
apply to Project" were previously answered via DocAgent/RAG over chunked
markdown type docs — unreliable, since a long enumerable list (e.g. the
`0021-Collections.md` "Collection Subtypes" bullet list) gets shredded across
several 1000-char chunks and can lose the retrieval race to an unrelated doc
that happens to share a lexical phrase.

Egeria exposes this information directly and authoritatively via the Valid
Metadata OMVS (pyegeria.omvs.valid_metadata.ValidMetadataManager). This agent
calls it live instead of retrieving prose. Never raises; returns None on any
resolution/connection failure so the caller (rag_system.py) can fall back to
the existing CodeIntelAgent/RAG path unchanged.
"""
from __future__ import annotations

import re
from typing import Optional

from loguru import logger

from advisor.agents.base import BaseAdvisorAgent

# Forward phrasings ("types of X", "subtypes of X", "classifications of X") —
# each captures the type-name phrase following the trigger words. Checked in
# order so more specific phrasings (mentioning "classification") are captured
# correctly even though they'd also match a looser "types of" pattern.
_FORWARD_PATTERNS = [
    re.compile(r"\bclassifications?\s+(?:of|for|on)\s+(?:a|an|the)?\s*([a-zA-Z][a-zA-Z\s\-]*?)\b(?:\?|$|\.)", re.IGNORECASE),
    re.compile(r"\bvalid\s+classifications?\s+(?:of|for|on)?\s*(?:a|an|the)?\s*([a-zA-Z][a-zA-Z\s\-]*?)\b(?:\?|$|\.)", re.IGNORECASE),
    re.compile(r"\bsub-?\s?types?\s+of\s+(?:a|an|the)?\s*([a-zA-Z][a-zA-Z\s\-]*?)\b(?:\?|$|\.)", re.IGNORECASE),
    re.compile(r"\btypes?\s+of\s+(?:a|an|the)?\s*([a-zA-Z][a-zA-Z\s\-]*?)\b(?:\?|$|\.)", re.IGNORECASE),
    re.compile(r"\bkinds?\s+of\s+(?:a|an|the)?\s*([a-zA-Z][a-zA-Z\s\-]*?)\b(?:\?|$|\.)", re.IGNORECASE),
]

# Reversed phrasings ("project types", "collection sub-types", "the different
# project types") — trigger word comes after the type name instead of before.
# Captures up to 4 words immediately preceding the trigger; filler words are
# stripped from that window in _extract_type_phrase.
_REVERSED_TRIGGER = re.compile(
    r"((?:[a-zA-Z\-]+\s+){0,4}[a-zA-Z\-]+)\s+(?:sub-?\s?types?|types?|kinds?|classifications?)\b",
    re.IGNORECASE,
)

_TRAILING_STOPWORDS = {"are", "there", "is", "exist", "available", "in", "egeria", "supported", "does", "have", "has"}
_FILLER_WORDS = {
    "tell", "me", "about", "the", "a", "an", "different", "various", "all",
    "please", "describe", "explain", "what", "which", "some", "of", "for",
}


def _strip_filler(words: list[str]) -> list[str]:
    return [w for w in words if w.lower() not in _FILLER_WORDS]


def _extract_type_phrase(query: str) -> Optional[str]:
    """Pull the raw type-name phrase out of a 'subtypes of X' / 'types of X' /
    'classifications of X' / reversed 'X types' / 'X classifications' style
    query. Returns None if nothing matches."""
    for pattern in _FORWARD_PATTERNS:
        m = pattern.search(query)
        if m:
            phrase = m.group(1).strip()
            words = _strip_filler([w for w in phrase.split() if w.lower() not in _TRAILING_STOPWORDS])
            if words:
                return " ".join(words)

    m = _REVERSED_TRIGGER.search(query)
    if m:
        words = _strip_filler(m.group(1).strip().split())
        if words:
            return " ".join(words)
    return None


def _wants_classification(query: str) -> bool:
    return "classification" in query.lower()


class EgeriaTypeAgent(BaseAdvisorAgent):
    """Live structural lookups against Egeria's Valid Metadata OMVS."""

    def __init__(self) -> None:
        from advisor.egeria_context import EgeriaContext
        self._context = EgeriaContext()
        self._cache: dict[tuple[str, str], object] = {}

    def system_prompt(self) -> str:
        # Unused — handle() is a hand-rolled dispatcher, no BeeAI loop (same
        # pattern as CodeIntelAgent). Present only to satisfy the abstract base.
        return "You answer structural questions about Egeria's own metadata type system."

    def tools(self) -> list:
        return []

    def _resolve_type_name(self, phrase: str, vmm) -> Optional[str]:
        """Canonicalize a free-text type phrase to a real Egeria type name.

        Tries the bundled registry first (fast, works offline), then confirms
        against the live instance via get_typedef_by_name — this also catches
        registry misses by trying a couple of naive casings directly against
        Egeria. Returns None if nothing resolves to a real type.
        """
        from advisor.egeria_type_registry import resolve_type_name

        words = phrase.replace("-", " ").split()
        candidates = []
        registry_hit = resolve_type_name(words)
        if registry_hit:
            candidates.append(registry_hit)

        # Naive fallbacks: PascalCase the whole phrase, and singular PascalCase
        # (strip a trailing 's') — covers common type names not yet in the
        # registry (which only covers report-spec target_types).
        pascal = "".join(w.capitalize() for w in words)
        candidates.append(pascal)
        if pascal.endswith("s") and len(pascal) > 1:
            candidates.append(pascal[:-1])

        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                typedef = vmm.get_typedef_by_name(candidate)
            except Exception as exc:
                logger.debug(f"EgeriaTypeAgent: get_typedef_by_name('{candidate}') failed: {exc}")
                continue
            if isinstance(typedef, dict) and typedef.get("name"):
                return typedef["name"]
        return None

    def _get_sub_types(self, vmm, type_name: str) -> list[str]:
        key = ("subtypes", type_name)
        if key not in self._cache:
            try:
                result = vmm.get_sub_types(type_name)
            except Exception as exc:
                logger.debug(f"EgeriaTypeAgent: get_sub_types('{type_name}') failed: {exc}")
                result = None
            defs = result.get("typeDefs", []) if isinstance(result, dict) else []
            self._cache[key] = sorted(
                (d.get("name"), d.get("description", "")) for d in defs if d.get("name")
            )
        return self._cache[key]

    def _get_classifications(self, vmm, type_name: str) -> list[str]:
        key = ("classifications", type_name)
        if key not in self._cache:
            try:
                result = vmm.get_valid_classification_types(type_name)
            except Exception as exc:
                logger.debug(f"EgeriaTypeAgent: get_valid_classification_types('{type_name}') failed: {exc}")
                result = None
            defs = result.get("typeDefs", []) if isinstance(result, dict) else []
            self._cache[key] = sorted(
                (d.get("name"), d.get("description", "")) for d in defs if d.get("name")
            )
        return self._cache[key]

    def handle(self, query: str) -> Optional[dict]:
        phrase = _extract_type_phrase(query)
        if not phrase:
            return None

        vmm = self._context._valid_metadata_manager()
        if vmm is None:
            logger.debug("EgeriaTypeAgent: no live Egeria connection — falling back")
            return None

        type_name = self._resolve_type_name(phrase, vmm)
        if not type_name:
            logger.debug(f"EgeriaTypeAgent: could not resolve '{phrase}' to a known Egeria type — falling back")
            return None

        sections = []

        subtypes = self._get_sub_types(vmm, type_name)
        classifications: list[tuple[str, str]] = []
        if not subtypes or _wants_classification(query):
            classifications = self._get_classifications(vmm, type_name)

        if subtypes:
            lines = [f"**Subtypes of `{type_name}`:**"]
            for name, desc in subtypes:
                lines.append(f"- **{name}**" + (f" — {desc}" if desc else ""))
            sections.append("\n".join(lines))

        if classifications:
            lines = [f"**Classifications applicable to `{type_name}`:**"]
            for name, desc in classifications:
                lines.append(f"- **{name}**" + (f" — {desc}" if desc else ""))
            sections.append("\n".join(lines))

        if not sections:
            response = (
                f"`{type_name}` is a real Egeria type, but it has no registered subtypes "
                f"or applicable classifications in this Egeria instance."
            )
        else:
            response = "\n\n".join(sections)

        return {
            "query": query,
            "response": response,
            "query_type": "code_intel",
            "sources": [],
            "num_sources": 0,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": 1.0,
            "context_length": len(response),
        }


_agent: Optional[EgeriaTypeAgent] = None


def get_egeria_type_agent() -> EgeriaTypeAgent:
    global _agent
    if _agent is None:
        _agent = EgeriaTypeAgent()
    return _agent
