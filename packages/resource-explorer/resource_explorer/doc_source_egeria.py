"""Egeria linkage for declared documentation sources — the `egeria_linkage`
reuse the brief asks for (`BRIEF-DATABASE-DOCUMENTATION-SOURCES.md`, "Reuse,
not rebuild"; slice 1, "Declare and probe").

A declared source becomes an `ExternalReference` element attached to the
resource's Egeria asset when the resource is published — mirrors
`surveyors/egeria_publisher.py`'s `_publish_homepage_reference`, which does
exactly this for a project's homepage URL, down to the `ExternalReference::
<url>` qualified-name convention (so the two features never double-catalog
the same URL under two different names). That function lives on
`EgeriaPublisher` and is reached only through a repo survey publish; this
module is the standalone equivalent for a database/filesystem's
person-declared sources, called directly from `web/routes/doc_sources.py`
(on add + at publish time) rather than folded into a surveyor.

**Best-effort, deliberately.** A doc source failing to publish to Egeria
must not fail the resource's own publish, and removing one locally must not
fail because Egeria is unreachable — same rule `_publish_homepage_reference`
follows, for the same reason: the primary operation is the point, this is
an extra. Callers get a result dict with `ok`/`error` rather than an
exception for the common failure paths; only a bad GUID (nothing to detach)
is a programming error worth raising for.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_SOURCE_TYPE_LABEL = {
    "data_dictionary": "data dictionary",
    "design_notes": "design notes",
    "runbook": "runbook",
    "wiki": "wiki",
    "installation_guide": "installation guide",
    "user_manual": "user manual",
    "api_reference": "api reference",
    "release_notes": "release notes",
    "other": "documentation",
}


class RepoEgeriaConnectionView:
    """The Egeria connection a repo publishes doc sources through.

    E2 (2026-09-29). `Project` (a repo) carries no per-entity Egeria
    credentials the way `DatabaseEntity`/`FileSystemEntity` do — repo Egeria
    code (`web/routes/egeria.py`) reads them from the environment
    (`EGERIA_VIEW_SERVER`, `EGERIA_USER`, `EGERIA_USER_PASSWORD`,
    `EGERIA_PLATFORM_URL`). This is a read-only VIEW of that connection plus
    the repo's own asset GUID and display name, exposing the attribute names
    every doc-source call site already reads, so those sites need no repo
    special case. It is not a Project and does not pretend to be one.

    The password is never included in `repr()`/`str()`, so an accidental
    `log.info("%s", entity)` cannot leak it.
    """

    __slots__ = ("slug", "display_name", "egeria_asset_guid", "egeria_server",
                 "egeria_url", "egeria_user", "_egeria_password")

    def __init__(self, project, asset_guid: str = ""):
        import os

        self.slug = project.slug
        self.display_name = project.display_name
        self.egeria_asset_guid = asset_guid or getattr(project, "egeria_asset_guid", "") or ""
        self.egeria_server = os.getenv("EGERIA_VIEW_SERVER", "qs-view-server")
        self.egeria_url = os.getenv("EGERIA_PLATFORM_URL", "https://localhost:9443")
        self.egeria_user = os.getenv("EGERIA_USER", "erinoverview")
        self._egeria_password = os.getenv("EGERIA_USER_PASSWORD", "secret")

    @property
    def egeria_password(self) -> str:
        return self._egeria_password

    def __repr__(self) -> str:
        return (f"RepoEgeriaConnectionView(slug={self.slug!r}, server={self.egeria_server!r}, "
                f"url={self.egeria_url!r}, user={self.egeria_user!r}, "
                f"asset_guid={self.egeria_asset_guid!r})")

    __str__ = __repr__


def resolve_entity_for_doc_source(registry, entity_type: str, entity_slug: str):
    """The three entity kinds this feature supports (database, filesystem, repo), resolved the same way
    everywhere it's needed — `web/routes/doc_sources.py`'s `_resolve_entity`
    (which additionally turns a miss into an HTTP 404) and
    `egeria_outbox.py`'s `doc_source_publish`/`doc_source_unpublish`
    creators, which resolve the entity fresh at APPLY time rather than
    carrying its Egeria credentials in the outbox payload — a payload
    snapshot would go stale if the entity's credentials were edited between
    enqueue and a later retry, and this codebase already stores these
    credentials in the entity row itself (`registry.py`'s `DatabaseEntity`/
    `FileSystemEntity`), so re-reading them is one lookup, not a new store.
    Returns `None` for an entity_type this feature doesn't support or a slug
    that no longer resolves."""
    if entity_type == "database":
        return registry.get_database(entity_slug)
    if entity_type == "filesystem":
        return registry.get_filesystem(entity_slug)
    if entity_type == "repo":
        project = registry.get(entity_slug)
        if project is None:
            return None
        return RepoEgeriaConnectionView(project, registry.get_egeria_asset_guid(entity_slug) or "")
    return None


def _client(view_server: str, platform_url: str, user_id: str, user_password: str):
    from pyegeria import ExternalReferences

    client = ExternalReferences(view_server, platform_url, user_id, user_password)
    client.create_egeria_bearer_token()
    return client


def _qualified_name(url: str) -> str:
    # Same convention `_publish_homepage_reference` uses for the identical
    # element type, so a homepage and a declared doc source pointing at the
    # same URL resolve to the one Egeria element rather than two.
    return f"ExternalReference::{url}"


def ref_guid_exists(ref_guid: str, *, view_server: str, platform_url: str, user_id: str,
                     user_password: str) -> bool:
    """True when `ref_guid` still resolves to a real element in Egeria.

    Round 5 fix (2026-09-29): a stuck-row bug found live (b9925119…, database
    8813) traced to `publish_doc_source` trusting a stored `egeria_external_
    ref_guid` just because the row carried one — including one that had been
    genuinely DELETED from Egeria by an unrelated unpublish before the row's
    own self-heal re-queued it. The self-heal's publish attempt reused the
    dead guid, the link call against a nonexistent element failed silently
    (caught by the best-effort `try/except` around `link_external_reference`),
    and the outbox row still completed `done` — a permanent, silent no-op
    loop (see `_compute_egeria_state`'s self-heal, which re-queues the exact
    same shape every time it renders).

    This is the fix: before trusting ANY ref guid (whether `known_ref_guid`
    or one `_find_ref_guid` just looked up) as reusable, actually ask Egeria
    whether it still exists. Reuses `egeria_linkage.is_unknown_guid_error` —
    the same "does this cached GUID still resolve" detection
    `recheck_all_linkages` already uses for every other cached-GUID
    staleness check in this codebase — rather than inventing a second
    existence-check heuristic. `MetadataExpert.get_metadata_element_by_guid`
    is the same type-agnostic client `recheck_all_linkages` settled on (an
    `ExternalReference` is not an Asset, so `AssetMaker` would be the wrong
    client here too).

    On an UNRELATED failure (timeout, auth hiccup, transient network error —
    not a confirmed "not known to the repository" answer), this returns
    `False` rather than raising: "could not establish the guid is good" is
    treated the same as "not found" here, consistent with this codebase's
    established `credential_capability.py` rule ("on our failure to
    establish something, run the step") — a caller that cannot confirm an
    old reference is safe to reuse creates a fresh one rather than blocking
    or crashing the whole publish attempt on it.
    """
    if not ref_guid:
        return False
    from pyegeria.omvs.metadata_expert import MetadataExpert

    from resource_explorer.egeria_linkage import is_unknown_guid_error

    try:
        client = MetadataExpert(view_server, platform_url, user_id, user_password)
        client.create_egeria_bearer_token()
        element = client.get_metadata_element_by_guid(ref_guid)
    except Exception as exc:
        if is_unknown_guid_error(exc):
            log.info("doc source: ref %r no longer resolves in Egeria (confirmed not found)",
                      ref_guid)
        else:
            log.debug("doc source: could not verify ref %r exists (treating as unresolved): %s",
                       ref_guid, exc)
        return False
    # MetadataExpert's own "not found" sentinel is a bare string rather than
    # an exception for some call shapes (mirrors recheck_all_linkages's own
    # handling of the identical client).
    if isinstance(element, str) or not element:
        log.info("doc source: ref %r no longer resolves in Egeria (empty/string result)",
                  ref_guid)
        return False
    return True


def _find_ref_guid(client, qualified_name: str) -> str:
    """Existing ExternalReference by qualified name, or '' — mirrors
    `EgeriaPublisher._find_element_guid`, duplicated rather than imported
    because that one lives on a class built around a repo survey's own
    clients and identity, not something this standalone module should
    depend on just to reuse eleven lines.

    **Bounded via `concurrency.run_sync`, deliberately** — live-verified
    2026-09-28 (this slice's own gate check) that `AutomatedCuration.
    get_guid_for_name` can hang this exact way: `docs/process-model.md`
    §1.3's incident is `resolve_question_guid()` hung 15+s inside this
    same pyegeria call -> nest_asyncio -> run_until_complete frame, fixed
    everywhere else in this package by routing through the shared bounded
    pool rather than calling pyegeria synchronously from the caller's own
    thread. This function had the identical unguarded call and reproduced
    the identical hang (a doc-source publish holding a worker with no CPU
    activity, well past the 4s the probe budget alone would explain). Not
    a pyegeria fix — `feedback_pyegeria_gaps_tracking` policy is to log
    upstream gaps and wait for approval, not patch pyegeria directly — this
    is RE's own established containment for RE's own call site."""
    import re as _re

    from pyegeria import AutomatedCuration

    from resource_explorer.concurrency import run_sync

    uuid_re = _re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.IGNORECASE
    )

    def _lookup():
        curation = AutomatedCuration(client.view_server, client.platform_url,
                                      client.user_id, client.user_pwd)
        curation.create_egeria_bearer_token()
        return curation.get_guid_for_name(qualified_name)

    try:
        result = run_sync(_lookup, timeout=15.0)
    except Exception as exc:
        log.debug("doc source: could not look up %r: %s", qualified_name, exc)
        return ""
    if isinstance(result, list) and result:
        candidate = result[0] if isinstance(result[0], str) else result[0].get("guid", "")
        return candidate if uuid_re.match(candidate or "") else ""
    if isinstance(result, str) and uuid_re.match(result):
        return result
    return ""


def publish_doc_source(source: dict, asset_guid: str, *, view_server: str, platform_url: str,
                        user_id: str, user_password: str, display_name: str = "",
                        is_ref_unpublishing=None, known_ref_guid: str = "") -> dict:
    """Create (or reuse) an `ExternalReference` for one declared source and
    link it to `asset_guid`. Returns `{"ok": bool, "ref_guid": str,
    "link_guid": str, "error": str}` — never raises for an ordinary Egeria
    failure, so a batch of several sources can publish the ones that
    succeed and report the ones that didn't rather than aborting the whole
    publish (see module docstring).

    `is_ref_unpublishing` (optional `Callable[[str], bool]`) — the adoption-
    race guard (2026-09-29): `_find_ref_guid` matches by `qualified_name`
    alone (`ExternalReference::<url>`), which is GLOBAL — it does not check
    whether the match it found is currently being detached/deleted by a
    concurrent `doc_source_unpublish`. Passed by `egeria_outbox.py`'s
    `_create_doc_source_publish` as `registry.has_pending_unpublish_for_ref`
    bound to this entity, so this module stays standalone (no registry
    import — see module docstring) while still refusing to reuse a
    reference someone else is mid-way through deleting. A caller that
    doesn't pass one (e.g. `publish_local_doc_sources`'s full-publish sweep,
    which is not exposed to this specific race the same way) gets the old
    always-reuse behavior.

    `known_ref_guid` (round 4, 2026-09-29) — when the caller's own local row
    already carries a `egeria_external_ref_guid` (typically: adopted by a
    read-back, or a prior attempt that created the reference but crashed
    before linking it), pass it here to skip the `_find_ref_guid` lookup and
    go straight to linking THAT reference — the self-heal path
    (`_compute_egeria_state`) re-queues exactly this shape (ref present,
    link missing) and must NOT mint a second, independent `ExternalReference`
    for the same row when the first one is still perfectly good. Still
    subject to the same `is_ref_unpublishing` guard: a known ref_guid that
    turns out to have a pending/running unpublish is abandoned (falls
    through to the normal find-or-create flow below) rather than linked to a
    reference that may be deleted out from under it."""
    url = (source.get("url") or "").strip()
    if not url:
        return {"ok": False, "ref_guid": "", "link_guid": "", "error": "source has no URL"}
    qualified_name = _qualified_name(url)
    label = source.get("label") or urlparse(url).netloc or url
    source_type = source.get("source_type") or "other"
    type_label = _SOURCE_TYPE_LABEL.get(source_type, "documentation")
    try:
        client = _client(view_server, platform_url, user_id, user_password)
        ref_guid = (known_ref_guid or "").strip()
        if ref_guid and is_ref_unpublishing is not None and is_ref_unpublishing(ref_guid):
            log.info("doc source: known ref %r for %s has a pending/running unpublish — "
                      "abandoning it, looking up/creating fresh", ref_guid, qualified_name)
            ref_guid = ""
        if ref_guid and not ref_guid_exists(
            ref_guid, view_server=view_server, platform_url=platform_url,
            user_id=user_id, user_password=user_password,
        ):
            # Round 5 fix (2026-09-29): the row's own stored ref guid may
            # have been genuinely deleted from Egeria by something else
            # entirely (the b9925119… incident — an unrelated unpublish beat
            # this row's self-heal to it). A dead guid must not be reused —
            # see ref_guid_exists's own docstring.
            log.info("doc source: known ref %r for %s no longer exists in Egeria — "
                      "clearing it, looking up/creating fresh", ref_guid, qualified_name)
            ref_guid = ""
        if not ref_guid:
            ref_guid = _find_ref_guid(client, qualified_name)
        if ref_guid and is_ref_unpublishing is not None and is_ref_unpublishing(ref_guid):
            # This reference exists but is concurrently being torn down by a
            # pending/running unpublish — not safe to adopt (it may vanish
            # out from under the link we're about to create, or the unpublish
            # may run AFTER our link and delete the reference we just linked
            # to, leaving this source pointed at nothing). Treat it as
            # not-found: a fresh, independent ExternalReference is created
            # below instead of racing the one being deleted.
            log.info("doc source: found %r (%s) but it has a pending/running unpublish — "
                      "creating a new reference instead of adopting it", qualified_name, ref_guid)
            ref_guid = ""
        if ref_guid and not ref_guid_exists(
            ref_guid, view_server=view_server, platform_url=platform_url,
            user_id=user_id, user_password=user_password,
        ):
            # Same guard as above, applied to whatever _find_ref_guid just
            # found by qualifiedName — that lookup can also return a guid
            # that no longer resolves (e.g. deleted between the lookup index
            # and this read).
            log.info("doc source: found %r (%s) no longer exists in Egeria — "
                      "creating a new reference instead", qualified_name, ref_guid)
            ref_guid = ""
        if not ref_guid:
            body = {
                "class": "NewElementRequestBody",
                "properties": {
                    "class": "ExternalReferenceProperties",
                    "typeName": "ExternalReference",
                    "qualifiedName": qualified_name,
                    "displayName": label,
                    "description": (
                        f"{type_label.capitalize()} for "
                        f"{display_name or source.get('entity_slug', '')}, declared in "
                        "Resource Explorer."
                    ),
                    "url": url,
                    "referenceTitle": label,
                },
            }
            ref_guid = client.create_external_reference(body=body)
            log.info("Created ExternalReference %s for doc source %s", ref_guid, url)
        link_guid = ""
        link_error = ""
        try:
            link_guid = client.link_external_reference(asset_guid, ref_guid) or ""
        except Exception as exc:
            # A duplicate link on a re-publish is harmless to report but
            # must not lose the reference — same guard
            # `_publish_homepage_reference` applies for the identical case.
            # Recorded in `error` (distinct from failing `ok`) rather than
            # only logged: the reference was created/reused successfully,
            # so this is not a publish failure, but a caller inspecting
            # only `ok` must still be able to see that the LINK step is
            # the one that didn't happen (test_no_silent_success.py's
            # ratchet — a log-only broad except here would hide exactly
            # this from anything reading the return value).
            link_error = str(exc)[:300]
            log.debug("doc source: could not link %s to %s: %s", ref_guid, asset_guid, exc)
        return {"ok": True, "ref_guid": ref_guid, "link_guid": link_guid, "error": link_error}
    except Exception as exc:
        log.warning("doc source: could not publish ExternalReference for %s: %s", url, exc)
        return {"ok": False, "ref_guid": "", "link_guid": "", "error": str(exc)[:500]}


def unpublish_doc_source(ref_guid: str, asset_guid: str, *, view_server: str, platform_url: str,
                          user_id: str, user_password: str, delete: bool = True) -> dict:
    """Detach (and, by default, delete) the `ExternalReference` a removed
    doc source created. **Only this one reference** — `web/routes/
    doc_sources.py`'s DELETE handler calls this for exactly the GUID the
    removed row carried, never a sweep, so removing one source cannot take
    another's reference with it even if two sources happen to share a URL
    (an edge case this leaves alone rather than trying to detect, since a
    shared URL is not this slice's problem to solve)."""
    if not ref_guid:
        return {"ok": True, "error": ""}
    detach_error = ""
    try:
        client = _client(view_server, platform_url, user_id, user_password)
        if asset_guid:
            try:
                client.detach_external_reference(asset_guid, ref_guid)
            except Exception as exc:
                # Recorded, not only logged — same reasoning as
                # publish_doc_source's link_error above: the delete below
                # can still succeed, so this must not disappear from the
                # returned dict just because it didn't stop the overall
                # removal.
                detach_error = str(exc)[:300]
                log.debug("doc source: detach %s from %s failed (continuing to delete): %s",
                          ref_guid, asset_guid, exc)
        if delete:
            client.delete_external_reference(ref_guid)
        return {"ok": True, "error": detach_error}
    except Exception as exc:
        log.warning("doc source: could not remove ExternalReference %s: %s", ref_guid, exc)
        return {"ok": False, "error": str(exc)[:500]}


def read_back_doc_sources(asset_guid: str, *, view_server: str, platform_url: str,
                           user_id: str, user_password: str) -> list[dict]:
    """Every `ExternalReference` currently linked to `asset_guid` in Egeria
    — including one declared there by someone/something else, which is the
    read-back the brief asks for ("a source declared in Egeria by someone
    else appears here too"). Returns `[]`, not an exception, when the asset
    has no such links or Egeria cannot be reached — this is read-back for
    display, and a failed read-back should fall back to RE's own local
    rows, not break the Enrichment pane.
    """
    if not asset_guid:
        return []
    try:
        from pyegeria.omvs.metadata_expert import MetadataExpert

        client = MetadataExpert(view_server, platform_url, user_id, user_password)
        client.create_egeria_bearer_token()
        result = client.get_related_metadata_elements(
            asset_guid, "ExternalReferenceLink", {"class": "ResultsRequestBody"},
        )
    except Exception as exc:
        log.debug("doc source: read-back for %s failed: %s", asset_guid, exc)
        return []
    if isinstance(result, str) or not result:
        return []
    # Shape confirmed live against a real platform (this slice's gate check,
    # 2026-09-28) rather than assumed from the client's docstring, which
    # only sketches the response. `get_related_metadata_elements` returns
    # `{"startingElement": ..., "elementList": [...], "mermaidGraph": ...}`
    # -- NOT a bare list and NOT `{"elements": [...]}`, both of which an
    # earlier version of this function guessed and which silently returned
    # zero references every time (caught because the gate check asserts
    # presence, not absence -- see find-absence-as-answer). Each entry in
    # `elementList` is the RELATIONSHIP (`ExternalReferenceLink`) with the
    # far-end element nested under `element`, and that element's properties
    # live at `elementProperties.propertiesAsStrings` -- pyegeria's own
    # flattened string view of `propertyValueMap`, used here instead of
    # walking the typed `propertyValueMap` structure by hand.
    entries = result.get("elementList") if isinstance(result, dict) else result
    out = []
    for entry in entries or []:
        el = (entry or {}).get("element") or entry or {}
        guid = el.get("elementGUID", "")
        props = (el.get("elementProperties") or {}).get("propertiesAsStrings", {})
        url = props.get("url") or ""
        if not url:
            continue
        out.append({
            "ref_guid": guid,
            "url": url,
            "label": props.get("displayName") or props.get("referenceTitle") or "",
        })
    return out
