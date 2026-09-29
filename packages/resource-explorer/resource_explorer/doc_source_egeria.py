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
                        user_id: str, user_password: str, display_name: str = "") -> dict:
    """Create (or reuse) an `ExternalReference` for one declared source and
    link it to `asset_guid`. Returns `{"ok": bool, "ref_guid": str,
    "link_guid": str, "error": str}` — never raises for an ordinary Egeria
    failure, so a batch of several sources can publish the ones that
    succeed and report the ones that didn't rather than aborting the whole
    publish (see module docstring)."""
    url = (source.get("url") or "").strip()
    if not url:
        return {"ok": False, "ref_guid": "", "link_guid": "", "error": "source has no URL"}
    qualified_name = _qualified_name(url)
    label = source.get("label") or urlparse(url).netloc or url
    source_type = source.get("source_type") or "other"
    type_label = _SOURCE_TYPE_LABEL.get(source_type, "documentation")
    try:
        client = _client(view_server, platform_url, user_id, user_password)
        ref_guid = _find_ref_guid(client, qualified_name)
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
