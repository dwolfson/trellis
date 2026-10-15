"""Link an element to an ExternalReference once: the one place RE makes an `ExternalReferenceLink`.

`ExternalReferenceLink` is MULTI-LINK in Egeria (`OpenMetadataTypesArchive1_2`, `setMultiLink(true)`):
every link call creates another relationship between the same two elements, it is never merged or
refused. A read of dev Egeria on 2026-10-14 found 132 links, 87 of them duplicates: repo surveys made one
per run (the homepage publisher), Enrichment doc-source publish made a few, one from an outbox retry.

So RE links only after reading the reference's existing links and finding none to this element. Three
outcomes matter:

  already linked   a link between exactly these two exists: no call, its relationship GUID is returned
                   (the oldest by `versions.createTime` when duplicates are already there).
  linked           none exists: one link call, its relationship GUID returned.
  could not check  the read failed or gave an answer we cannot read: NO link. A missing link is
                   recoverable on the next publish; a duplicate is the bug.

The read is `MetadataExpert.get_related_metadata_elements(ref_guid, "ExternalReferenceLink", ...,
starting_at_end=2)`: the reference is end 2 of the type (end 1 is the referencing element). The live
answer is a dict with `elementList`; each entry carries `relationshipGUID`, `versions.createTime` and the
far end under `element` (or `relatedElement`) with a top-level `elementGUID`. An exhausted list is
pyegeria's "No elements found" (or "No elements returned" for an empty list).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

RELATIONSHIP_TYPE = "ExternalReferenceLink"
#: The reference sits at end 2 of ExternalReferenceLink; the referencing element at end 1.
REFERENCE_END = 2
PAGE_SIZE = 500
#: A bound on pages read; reaching it means the list could not be read to its end.
MAX_PAGES = 200

LINKED = "linked"
ALREADY_LINKED = "already linked"
COULD_NOT_CHECK = "could not check"
LINK_FAILED = "link failed"

#: pyegeria's end-of-list answers (`process_related_element_list`): no list at all, or an empty one.
_END_OF_LIST = ("no elements found", "no elements returned")


class _Unreadable(Exception):
    """The existing links could not be read to the end."""


@dataclass(frozen=True)
class LinkOutcome:
    outcome: str
    relationship_guid: str = ""
    error: str = ""

    @property
    def linked(self) -> bool:
        """True when a link between the two exists now (made here or found)."""
        return self.outcome in (LINKED, ALREADY_LINKED)


def _entry_element_guid(entry: dict) -> str:
    far = entry.get("element") or entry.get("relatedElement") or {}
    if not isinstance(far, dict):
        return ""
    return str(far.get("elementGUID") or (far.get("elementHeader") or {}).get("guid") or "").strip()


def _page_entries(answer) -> list[dict] | None:
    """The entries of one page, None at the end of the list; raises `_Unreadable` otherwise."""
    if isinstance(answer, str):
        if answer.strip().rstrip(".").strip().lower() in _END_OF_LIST:
            return None
        raise _Unreadable(f"unexpected answer {answer!r:.120}")
    if isinstance(answer, dict):
        entries = answer.get("elementList")
        if entries is None:
            raise _Unreadable(f"answer has no elementList (keys: {sorted(answer)[:8]})")
    elif isinstance(answer, list):
        entries = answer
    else:
        raise _Unreadable(f"unexpected answer type {type(answer).__name__}")
    if not isinstance(entries, list):
        raise _Unreadable("elementList is not a list")
    return entries or None


def existing_links(metadata_expert, element_guid: str, ref_guid: str, *,
                   page_size: int = PAGE_SIZE) -> list[dict]:
    """Every ExternalReferenceLink between `element_guid` and `ref_guid`, as the raw entries.
    Raises `_Unreadable` when the reference's links cannot be read to the end."""
    found: list[dict] = []
    start = 0
    for _ in range(MAX_PAGES):
        try:
            answer = metadata_expert.get_related_metadata_elements(
                ref_guid, RELATIONSHIP_TYPE, {"class": "ResultsRequestBody"},
                starting_at_end=REFERENCE_END, start_from=start, page_size=page_size)
        except Exception as exc:  # noqa: BLE001 - every failure is "could not check"
            raise _Unreadable(f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}") from exc
        entries = _page_entries(answer)
        if entries is None:
            return found
        for entry in entries:
            if not isinstance(entry, dict):
                raise _Unreadable("an entry is not an object")
            far = _entry_element_guid(entry)
            if not far:
                # It might be this element's link: never link past an entry we cannot attribute.
                raise _Unreadable("an entry carries no element GUID")
            if far == element_guid:
                found.append(entry)
        start += page_size
    raise _Unreadable(f"more than {MAX_PAGES} pages of links")


def _oldest(entries: list[dict]) -> dict:
    return min(entries, key=lambda e: str((e.get("versions") or {}).get("createTime") or "~"))


def link_external_reference_once(metadata_expert, external_references, element_guid: str, ref_guid: str,
                                 *, page_size: int = PAGE_SIZE) -> LinkOutcome:
    """Link `element_guid` to the ExternalReference `ref_guid` unless a link between exactly these two
    already exists. Never raises; failures come back as the outcome, logged at warning."""
    try:
        existing = existing_links(metadata_expert, element_guid, ref_guid, page_size=page_size)
    except _Unreadable as exc:
        words = (f"could not check for an existing ExternalReferenceLink from {element_guid} to "
                 f"{ref_guid} ({exc}), so no link was made: a duplicate is worse than a missing link")
        log.warning("%s", words)
        return LinkOutcome(COULD_NOT_CHECK, error=words)
    if existing:
        keep = _oldest(existing)
        rel = str(keep.get("relationshipGUID") or "")
        if len(existing) > 1:
            log.warning("%d ExternalReferenceLinks from %s to %s already exist (duplicates); "
                        "using the oldest, %s", len(existing), element_guid, ref_guid, rel or "(no GUID)")
        error = "" if rel else ("an ExternalReferenceLink already exists but Egeria's answer "
                                "carried no relationship GUID")
        return LinkOutcome(ALREADY_LINKED, relationship_guid=rel, error=error)
    try:
        rel = external_references.link_external_reference(element_guid, ref_guid) or ""
    except Exception as exc:  # noqa: BLE001 - returned for the caller to record
        words = f"could not link ExternalReference {ref_guid} to {element_guid}: {exc}"[:400]
        log.warning("%s", words)
        return LinkOutcome(LINK_FAILED, error=words)
    log.info("Linked ExternalReference %s to %s (relationship %s)", ref_guid, element_guid, rel or "?")
    return LinkOutcome(LINKED, relationship_guid=str(rel))
