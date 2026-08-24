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
                "failing until the link is reconciled. Survey results and annotations "
                "are kept. Resolve it from Admin \u25b8 Egeria Links, or from the "
                "resource's own Scouting card: republish, re-survey, or discard."
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


def _iter_linked_resources(registry, entity_types):
    """Yield (entity_type, slug, display_name, guid) for every registered
    resource that carries a cached Egeria GUID, restricted to `entity_types`
    when given.

    Resources with no cached GUID are not yielded at all — there is nothing to
    check, and counting them as "ok" would misrepresent a sweep that never
    actually asked Egeria about them.
    """
    if entity_types is None or "repo" in entity_types:
        for project in registry.list_all():
            if project.egeria_asset_guid:
                yield "repo", project.slug, project.display_name, project.egeria_asset_guid

    if entity_types is None or "database" in entity_types:
        for db in registry.list_databases():
            if db.egeria_asset_guid:
                yield "database", db.slug, db.display_name, db.egeria_asset_guid

    if entity_types is None or "filesystem" in entity_types:
        for fs in registry.list_filesystems():
            if fs.egeria_asset_guid:
                yield "filesystem", fs.slug, fs.display_name, fs.egeria_asset_guid


def recheck_all_linkages(registry, *, entity_types=None, progress=None,
                          dry_run: bool = False) -> dict:
    """Proactively ask Egeria about every cached GUID instead of waiting for
    the next survey/publish to trip over one.

    Reactive detection (`guard_linkage`) only marks a linkage stale the next
    time something actually uses the cached GUID — which can be arbitrarily
    long after Egeria's repository was reset. This sweep closes that gap by
    checking every cached GUID up front, right after a reset, so `Admin ▸
    Egeria Links` reflects reality instead of staying empty until each
    resource happens to be surveyed again.

    Symmetric with `guard_linkage`/`note_divergence` in both directions: an
    unknown-GUID error records a divergence exactly as the reactive path
    would, and — the part the reactive path never does on its own — a GUID
    that now resolves clears any divergence previously recorded for it. Without
    that second half a fixed linkage stays listed as stale forever, since
    nothing else in RE clears an `egeria_linkage_status` row except the
    resolve-flow's explicit discard/republish/resurvey actions.

    Connection/auth failures are deliberately kept out of "stale": marking a
    resource stale sends a human to reconcile a catalog link that may be
    perfectly fine — Egeria was just unreachable for a moment. Only a
    confirmed "that GUID does not exist" answer (`is_unknown_guid_error`)
    counts as stale; anything else that goes wrong is counted separately.

    `progress`, if given, is called after each resource as
    `progress(checked, total, entity_type, slug)` — a hook for CLI output on a
    sweep of ~20 network calls.

    `dry_run=True` runs every probe (so counts reflect the real state) but
    skips both `mark_egeria_linkage_stale` and `clear_egeria_linkage_status`
    writes.
    """
    from pyegeria.omvs.metadata_expert import MetadataExpert

    from resource_explorer.config import get_config

    resources = list(_iter_linked_resources(registry, entity_types))
    total = len(resources)

    counts = {"checked": 0, "ok": 0, "stale": 0, "errors": 0, "skipped": 0, "details": []}

    # Skipped-count for entity types that exist but carry no GUID at all —
    # reported separately from "checked" for the same reason _iter_linked_resources
    # doesn't yield them: nothing was actually asked of Egeria for these.
    all_repo = registry.list_all() if (entity_types is None or "repo" in entity_types) else []
    all_db = registry.list_databases() if (entity_types is None or "database" in entity_types) else []
    all_fs = registry.list_filesystems() if (entity_types is None or "filesystem" in entity_types) else []
    counts["skipped"] = sum(
        1 for p in all_repo if not p.egeria_asset_guid
    ) + sum(
        1 for d in all_db if not d.egeria_asset_guid
    ) + sum(
        1 for f in all_fs if not f.egeria_asset_guid
    )

    if not resources:
        return counts

    # Built once for the whole sweep — creating a client per resource would
    # mean ~20 redundant bearer-token round trips for a check that is otherwise
    # one call each.
    # MetadataExpert, not AssetMaker — because what RE publishes for a repo is
    # not an Asset. Confirmed from the server 2026-08-21:
    #
    #     typeName   : SourceControlLibrary
    #     superTypes : ResourceManager, SoftwareCapability, Referenceable,
    #                  OpenMetadataRoot
    #
    # So `AssetMaker.get_asset_by_guid` correctly returns NotFound for it, and a
    # sweep built on that call marks every healthy repo stale the moment it is
    # republished — the false positive this module calls the more damaging
    # direction in three other places. Caught by republishing one repo for real
    # and watching the next sweep declare it gone.
    #
    # `get_metadata_element_by_guid` is type-agnostic and got all four probe
    # cases right: three genuinely deleted, one that exists.
    #
    # Worth knowing while reading this file: the naming lies throughout. The
    # column is `egeria_asset_guid`, the publisher method is
    # `_find_or_create_asset`, and neither is about an Asset. That is precisely
    # why reaching for AssetMaker felt natural.
    cfg = get_config().egeria
    element_client = MetadataExpert(cfg.view_server, cfg.platform_url,
                                 cfg.user_id, cfg.user_password)
    element_client.create_egeria_bearer_token()

    for entity_type, slug, display_name, guid in resources:
        detail = {"entity_type": entity_type, "slug": slug, "guid": guid}
        try:
            element = element_client.get_metadata_element_by_guid(guid)
            # A string result is this client's "not found" sentinel rather than an
            # exception, so an absent element must be turned into one — otherwise
            # a missing GUID reads as a successful check.
            if isinstance(element, str) or not element:
                raise LookupError(
                    f"OMRS-REPOSITORY-404-002 element {guid} is not known to the "
                    f"open metadata repository")
        except Exception as exc:
            if is_unknown_guid_error(exc):
                counts["stale"] += 1
                detail["result"] = "stale"
                detail["detail"] = str(exc)[:2000]
                if not dry_run:
                    # Records the row, deliberately WITHOUT note_divergence's
                    # per-resource RFA. A reset makes every cataloged resource
                    # stale at once, so one RFA each would put twenty near
                    # identical items in the drawer and bury whatever else is in
                    # there — the drawer is a queue of things a human should act
                    # on, and twenty rows describing one event is one thing to
                    # act on, not twenty. A single summary RFA is raised below.
                    registry.mark_egeria_linkage_stale(
                        entity_type, slug, guid, str(exc)[:2000])
            else:
                counts["errors"] += 1
                detail["result"] = "error"
                detail["detail"] = str(exc)[:2000]
                log.warning("Egeria recheck could not verify %s/%s (GUID %s): %s",
                           entity_type, slug, guid, exc)
        else:
            counts["ok"] += 1
            detail["result"] = "ok"
            if not dry_run:
                # Clears a previously-recorded divergence that has since been
                # fixed (republish/resurvey/manual repair, or Egeria's own
                # recovery). Without this half, the sweep can only ever add
                # rows, never remove ones that no longer apply.
                registry.clear_egeria_linkage_status(entity_type, slug)

        counts["checked"] += 1
        counts["details"].append(detail)
        if progress is not None:
            progress(counts["checked"], total, entity_type, slug)

    # One RFA for the sweep, not one per resource. Raised only when something was
    # actually found, and only on a real run — a dry run must leave no trace.
    if counts["stale"] and not dry_run:
        try:
            from resource_explorer.activity_logger import log_rfa

            names = ", ".join(d["slug"] for d in counts["details"]
                              if d["result"] == "stale")[:400]
            log_rfa(
                registry=registry,
                entity_type="repo",
                entity_slug="",
                entity_name="Egeria catalog links",
                status="error",
                summary=(f"{counts['stale']} Egeria catalog link(s) are stale "
                         f"— Egeria was most likely reset"),
                detail=(
                    f"A recheck sweep found {counts['stale']} of {counts['checked']} "
                    f"cached Egeria GUID(s) no longer known to the repository"
                    + (f", and could not verify {counts['errors']}" if counts["errors"] else "")
                    + ". Survey results and annotations are kept. Resolve them from "
                    "Admin \u25b8 Egeria Links — republish is usually right when only "
                    "Egeria was reset and the resources themselves have not changed.\n\n"
                    f"Affected: {names}"
                ),
            )
        except Exception:
            # Same rule as everywhere else here: failing to announce the finding
            # must not discard the finding, which is already recorded above.
            log.exception("Egeria recheck: could not raise the summary RFA")

    return counts
