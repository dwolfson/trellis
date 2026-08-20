"""Detect when RE's cached Egeria GUIDs no longer refer to anything.

RE caches Egeria GUIDs — `egeria_asset_guid` on each entity, and the report,
per-file and annotation GUIDs beneath it — and every survey/publish path trusted
them unconditionally. Reset Egeria's repository independently of RE's registry
(a quickstart platform restart does exactly this for custom-authored elements)
and the next run fails with `SERVER_ERROR_500`, which reaches the UI verbatim:
five hundred words of Java stack naming `OMRS-REPOSITORY-404-002` somewhere in
the middle, and nothing a user can act on. Reported 2026-07-21.

**Detect, don't auto-resolve.** A stale root GUID means the whole Egeria-side
lineage RE cached beneath it is unverifiable — not automatically wrong, and not
safely recreatable in place. Silently recreating would duplicate Egeria elements
and discard catalog history that may still matter, and it would do so at exactly
the moment nobody was watching. So this module's job ends at: recognise the
condition, record it, say what happened, and stop. The three resolutions
(republish from local data / re-survey from scratch / discard locally) are
deliberately a human's choice, because only a human knows whether the underlying
resource also changed or only Egeria's copy was reset.

The distinction that makes this worth detecting separately from any other Egeria
failure: an unknown GUID is not a transient fault. Retrying cannot fix it, and
treating it as a generic error means the operation keeps failing the same way
forever with no indication of why.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

log = logging.getLogger(__name__)

# Egeria's own error codes for "the GUID you gave me is not in this repository".
# These are stable identifiers in Egeria's message catalogue, which is why they
# are the primary signal rather than the surrounding prose:
#   OMRS-REPOSITORY-404-002 — entity not known to the repository
#   OMRS-REPOSITORY-404-007 — entity proxy / referenced entity not known
#   OMAG-COMMON-404-003     — the view-service-level "unknown identifier" wrapper
_UNKNOWN_GUID_CODES = (
    # Confirmed live 2026-08-20 by asking this deployment's Egeria for a GUID
    # that cannot exist. The real response nests two of these: the outer handler
    # code, and the repository's own inside `exceptionErrorMessage`.
    "OMRS-REPOSITORY-404-002",          # entity not known to the repository
    "OMAG-REPOSITORY-HANDLER-404-007",  # "<Type> entity with unique identifier ... not found"
    "OMRS-REPOSITORY-404-007",          # entity proxy / referenced entity not known
    "OMAG-COMMON-404-003",              # view-service-level unknown-identifier wrapper
)

# Prose fallbacks. Kept deliberately narrow: a broad phrase like "not found"
# would also swallow "no elements matched your search", which is an ordinary
# empty result and emphatically not a divergence. Marking a healthy entity as
# stale is the more damaging error of the two — it sends someone to reconcile a
# catalog that was fine.
_UNKNOWN_GUID_PHRASES = (
    "is not known to the open metadata repository",
    "unknown entity",
    "entity proxy",
)


def is_unknown_guid_error(exc: BaseException) -> bool:
    """True when this exception means "that GUID does not exist here".

    Matches on message content rather than exception type because the condition
    does not surface consistently. Probed live 2026-08-20: an AssetMaker read of
    a nonexistent GUID raises a typed PyegeriaNotFoundException — but the case
    that motivated this arrived as a generic API exception carrying a 500, with
    the real 404 code buried in the server's nested message. Type alone would
    miss that one; the codes appear in both.

    (Noted while probing, not acted on here: that typed response labels itself
    `CLIENT_ERROR_400` in its first line while `relatedHTTPCode` is 404. A
    pyegeria-side inconsistency, and another reason not to key on status.)
    """
    text = str(exc)
    if any(code in text for code in _UNKNOWN_GUID_CODES):
        return True
    lowered = text.lower()
    return any(phrase in lowered for phrase in _UNKNOWN_GUID_PHRASES)


class StaleEgeriaLinkageError(Exception):
    """RE's cached Egeria GUID for an entity no longer exists in Egeria.

    Raised in place of the opaque server error so the failure names the entity,
    the GUID that went missing, and what can be done about it — the whole point
    of detecting this separately.
    """

    def __init__(self, entity_type: str, entity_slug: str, stale_guid: str,
                 original: BaseException | None = None) -> None:
        self.entity_type = entity_type
        self.entity_slug = entity_slug
        self.stale_guid = stale_guid
        self.original = original
        super().__init__(
            f"Egeria no longer has the element RE recorded for {entity_type} "
            f"'{entity_slug}' (GUID {stale_guid or 'unknown'}). Egeria's repository "
            "has most likely been reset independently of Resource Explorer. RE has "
            "kept its local survey results and marked this catalog link as stale "
            "rather than guessing: re-creating the element automatically could "
            "duplicate Egeria records and discard catalog history. Choose republish "
            "(re-publish the results RE already holds), re-survey (start over, if "
            "the resource itself may also have changed), or discard."
        )


def note_divergence(
    registry, entity_type: str, entity_slug: str, entity_name: str,
    stale_guid: str, exc: BaseException,
) -> StaleEgeriaLinkageError:
    """Record a detected divergence and return the error to raise.

    Returns rather than raises so the caller keeps its own `raise ... from exc`
    and the original traceback survives — the server-side detail is still the
    only evidence of what Egeria actually said, and throwing it away in favour
    of a friendlier message would make the next report unreproducible.

    Best-effort on both writes: failing to record the divergence must not
    replace it with a different, more confusing failure.
    """
    detail = str(exc)[:2000]
    try:
        registry.mark_egeria_linkage_stale(entity_type, entity_slug, stale_guid, detail)
    except Exception:
        log.exception("Could not record Egeria linkage divergence for %s/%s",
                      entity_type, entity_slug)

    # Delivered as an RFA because it is precisely a request for a human action,
    # and the drawer that shows them already exists. This is a notification, not
    # the decision surface: RFA responses are defer/reassign/complete, which
    # cannot express a three-way choice between republish, re-survey and discard.
    try:
        from resource_explorer.activity_logger import log_rfa

        log_rfa(
            registry=registry,
            entity_type=entity_type,
            entity_slug=entity_slug,
            entity_name=entity_name or entity_slug,
            status="error",
            summary=f"Egeria catalog link for '{entity_name or entity_slug}' is stale",
            detail=(
                f"RE's stored Egeria GUID ({stale_guid or 'unknown'}) is not known to "
                "the repository, so surveys and publishes for this resource will keep "
                "failing until the link is reconciled. Local survey results are "
                "untouched. Resolve it from the resource's Egeria panel: republish, "
                "re-survey, or discard."
            ),
        )
    except Exception:
        log.exception("Could not raise an RFA for Egeria linkage divergence %s/%s",
                      entity_type, entity_slug)

    return StaleEgeriaLinkageError(entity_type, entity_slug, stale_guid, exc)


@contextmanager
def guard_linkage(registry, entity_type: str, entity_slug: str, entity_name: str,
                  stale_guid: str):
    """Wrap work that depends on a cached Egeria GUID.

    Any exception meaning "that GUID does not exist" is recorded and re-raised as
    StaleEgeriaLinkageError; everything else propagates untouched. Wrapping the
    whole operation rather than each individual pyegeria call is deliberate — the
    cached root GUID is threaded into many calls beneath the entry point, and the
    answer is the same wherever it surfaces.

    Does nothing when there is no cached GUID: without one there is no stale
    linkage to detect, and any failure is an ordinary one.
    """
    if not stale_guid:
        yield
        return
    try:
        yield
    except StaleEgeriaLinkageError:
        raise
    except Exception as exc:
        if not is_unknown_guid_error(exc):
            raise
        raise note_divergence(
            registry, entity_type, entity_slug, entity_name, stale_guid, exc) from exc
