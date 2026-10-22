"""Exact qualifiedName -> GUID, through Egeria's unique-name read.

Why this exists (live 2026-10-21/22): `get_guid_for_name(qn, property_name=["qualifiedName"])` goes to
`classification-explorer/elements/by-exact-property-value`, which on a Postgres repository builds one giant OR
list of candidate GUIDs and hydrates them all. It timed out at 30 s on every adoption lookup and blocked every
new publish; its cost grows with the repository. `MetadataExpert.get_metadata_element_by_unique_name` is a
direct unique-name read (under 0.1 s, found or missing, on the same repository at the same time).

Contract of `guid_by_qualified_name`:

  * found                  -> the element's GUID (a str);
  * Egeria's explicit "No elements found" answer -> None (the ONLY absent answer);
  * anything else          -> RAISES. A raised pyegeria exception propagates unchanged (so the caller's own
    `egeria_absence.is_absent` / could-not-check handling still applies), an answer of an unknown shape raises
    `QualifiedNameLookupError`. A failed lookup is never "absent": absent licenses a create.
  * two elements holding the name -> `QualifiedNameAmbiguous` (Egeria's 404 `OMAG-GENERIC-HANDLERS-404-002`,
    which pyegeria raises as a NotFound and which must NOT read as absent);
  * with `type_name`, the element's type (or one of its supertypes) must match; a mismatch raises
    `QualifiedNameTypeMismatch`. qualifiedName is unique across Egeria, so another type holding the name means
    a create would be refused or duplicate: the caller must not read it as "absent".

Call sites never string-match the answer.
"""
from __future__ import annotations

import re

from resource_explorer.egeria_absence import MISS_ANSWERS, MULTIPLE_ENTITIES_FOUND_MESSAGE_ID, egeria_message_id

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_MISSES = {m.lower() for m in MISS_ANSWERS}


class QualifiedNameLookupError(RuntimeError):
    """The unique-name read gave an answer that is neither an element nor Egeria's explicit miss."""


class NoAnswer(QualifiedNameLookupError):
    """The read returned nothing at all (None). `no_answer` lets `egeria_absence.lookup_could_not_be_made` say
    "Egeria gave no answer", as it does for a look-up that returned None."""

    no_answer = True


class QualifiedNameTypeMismatch(QualifiedNameLookupError):
    """An element holds this qualifiedName but is not of the type asked for."""


class QualifiedNameAmbiguous(QualifiedNameLookupError):
    """Two or more elements hold this qualifiedName. Egeria's unique-name read refuses with
    `OMAG-GENERIC-HANDLERS-404-002` (HTTP 404, which pyegeria raises as a NotFound): that is "there is more than
    one", never "there is none", so nothing is adopted or created. Carries the original exception."""

    def __init__(self, message: str, original: BaseException | None = None):
        super().__init__(message)
        self.original = original
        self.__cause__ = original


def _is_miss(answer) -> bool:
    return isinstance(answer, str) and answer.strip().rstrip(".").strip().lower() in _MISSES


def _guid_of(answer: dict) -> str:
    """LIVE (fixtures/egeria_6_2): top-level `elementGUID`; `elementHeader.guid` is the asset-graph shape."""
    header = answer.get("elementHeader")
    return str(answer.get("elementGUID") or (header.get("guid") if isinstance(header, dict) else "") or "").strip()


def _type_names(answer: dict) -> set[str]:
    """LIVE: top-level `type` {typeName, superTypeNames}; `elementHeader.type` is the asset-graph shape."""
    kind = answer.get("type")
    if not isinstance(kind, dict):
        header = answer.get("elementHeader")
        kind = header.get("type") if isinstance(header, dict) else None
    names: set[str] = set()
    if isinstance(kind, dict):
        if kind.get("typeName"):
            names.add(str(kind["typeName"]))
        supers = kind.get("superTypeNames")
        if isinstance(supers, (list, tuple)):
            names.update(str(x) for x in supers if isinstance(x, str))
    return names


def guid_by_qualified_name(expert, qualified_name: str, *, type_name: str | None = None) -> str | None:
    """The GUID of the element whose qualifiedName is EXACTLY `qualified_name`, None for Egeria's explicit
    "No elements found", and a raise for everything else (see the module docstring)."""
    try:
        answer = expert.get_metadata_element_by_unique_name(qualified_name, property_name="qualifiedName")
    except Exception as exc:
        # Matched on Egeria's message id, never its English. Any other exception propagates unchanged.
        if egeria_message_id(exc) == MULTIPLE_ENTITIES_FOUND_MESSAGE_ID:
            raise QualifiedNameAmbiguous(
                f"more than one element holds the qualifiedName {qualified_name!r} "
                f"({MULTIPLE_ENTITIES_FOUND_MESSAGE_ID}): {' '.join(str(exc).split())[:200]}", exc) from exc
        raise
    if _is_miss(answer):
        return None
    if answer is None:
        raise NoAnswer(f"no answer for {qualified_name!r}")
    if not isinstance(answer, dict) or not answer:
        raise QualifiedNameLookupError(f"unexpected answer for {qualified_name!r}: {answer!r:.120}")
    guid = _guid_of(answer)
    if not _GUID.match(guid):
        raise QualifiedNameLookupError(f"the answer for {qualified_name!r} carries no element GUID")
    if type_name:
        have = _type_names(answer)
        if type_name not in have:
            raise QualifiedNameTypeMismatch(
                f"{qualified_name!r} is held by element {guid} of type {sorted(have) or 'unknown'}, "
                f"not {type_name}: nothing is adopted or created")
    return guid
