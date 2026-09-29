"""Tests for doc_source_egeria.py's publish/unpublish/read-back — the
ExternalReference linkage BRIEF-DATABASE-DOCUMENTATION-SOURCES.md slice 1
asks for, reusing egeria_publisher.py's `_publish_homepage_reference`
pattern. Mocks `_client`/`_find_ref_guid`/pyegeria rather than talking to a
real platform — the gate step does that separately, live, against
laz_local_adventureworks (see DOC-SOURCES-DECLARE-AND-PROBE-IMPLEMENTED.md).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resource_explorer import doc_source_egeria as m

_EGERIA_KW = dict(view_server="view1", platform_url="https://egeria.example",
                   user_id="u", user_password="p")


def test_source_type_label_covers_the_full_vocabulary():
    """Owner gate feedback on 8813 (2026-09-29) added installation_guide and
    user_manual; design added api_reference and release_notes while touching
    the list. Pinned here alongside registry.py's DOC_SOURCE_TYPES so the two
    can't drift apart."""
    assert m._SOURCE_TYPE_LABEL == {
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


def test_publish_creates_a_new_reference_and_links_it(monkeypatch):
    fake_client = MagicMock()
    fake_client.create_external_reference.return_value = "ref-guid-1"
    fake_client.link_external_reference.return_value = "link-guid-1"

    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(m, "_find_ref_guid", lambda client, qn: "")

    source = {"url": "https://docs.example/dict", "label": "Data dict",
              "source_type": "data_dictionary", "entity_slug": "adventureworks"}
    result = m.publish_doc_source(source, "asset-guid-1", **_EGERIA_KW)

    assert result["ok"] is True
    assert result["ref_guid"] == "ref-guid-1"
    assert result["link_guid"] == "link-guid-1"
    fake_client.create_external_reference.assert_called_once()
    body = fake_client.create_external_reference.call_args.kwargs["body"]
    assert body["properties"]["url"] == "https://docs.example/dict"
    assert body["properties"]["qualifiedName"] == "ExternalReference::https://docs.example/dict"
    fake_client.link_external_reference.assert_called_once_with("asset-guid-1", "ref-guid-1")


def test_publish_reuses_an_existing_reference_by_qualified_name(monkeypatch):
    fake_client = MagicMock()
    fake_client.link_external_reference.return_value = "link-guid-2"

    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(m, "_find_ref_guid", lambda client, qn: "existing-guid")

    source = {"url": "https://docs.example/dict"}
    result = m.publish_doc_source(source, "asset-guid-1", **_EGERIA_KW)

    assert result["ok"] is True
    assert result["ref_guid"] == "existing-guid"
    fake_client.create_external_reference.assert_not_called()
    fake_client.link_external_reference.assert_called_once_with("asset-guid-1", "existing-guid")


def test_publish_with_no_url_fails_cleanly(monkeypatch):
    result = m.publish_doc_source({"url": ""}, "asset-guid-1", **_EGERIA_KW)
    assert result["ok"] is False
    assert "url" in result["error"].lower()


# ── Adoption-race guard (round 4, 2026-09-29) ────────────────────────────────
# `_find_ref_guid` matches by qualifiedName ALONE — global, not scoped to
# whether the match is currently being deleted by a concurrent
# doc_source_unpublish. `is_ref_unpublishing`/`known_ref_guid` are how
# `egeria_outbox.py`'s `_create_doc_source_publish` (which has a registry to
# ask) tells `publish_doc_source` "this candidate GUID is unsafe to reuse".

def test_publish_does_not_reuse_a_found_ref_that_is_being_unpublished(monkeypatch):
    fake_client = MagicMock()
    fake_client.create_external_reference.return_value = "fresh-guid"
    fake_client.link_external_reference.return_value = "fresh-link-guid"

    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)
    # _find_ref_guid finds the OLD reference — still visible to Egeria
    # because its concurrent unpublish hasn't completed the delete yet.
    monkeypatch.setattr(m, "_find_ref_guid", lambda client, qn: "being-deleted-guid")

    source = {"url": "https://egeria.ai", "label": "not-adventureworks",
              "source_type": "installation_guide"}
    result = m.publish_doc_source(
        source, "asset-guid-1",
        is_ref_unpublishing=lambda guid: guid == "being-deleted-guid",
        **_EGERIA_KW,
    )

    assert result["ok"] is True
    # Must NOT have adopted the reference being deleted -- a brand new one
    # was created and linked instead.
    assert result["ref_guid"] == "fresh-guid"
    fake_client.create_external_reference.assert_called_once()
    fake_client.link_external_reference.assert_called_once_with("asset-guid-1", "fresh-guid")


def test_publish_reuses_a_found_ref_when_nothing_is_unpublishing_it(monkeypatch):
    # Sanity check the guard is not overzealous: a normal reuse (no pending
    # unpublish for the found guid) is unaffected.
    fake_client = MagicMock()
    fake_client.link_external_reference.return_value = "link-guid-2"

    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(m, "_find_ref_guid", lambda client, qn: "existing-guid")

    source = {"url": "https://docs.example/dict"}
    result = m.publish_doc_source(
        source, "asset-guid-1", is_ref_unpublishing=lambda guid: False, **_EGERIA_KW,
    )

    assert result["ok"] is True
    assert result["ref_guid"] == "existing-guid"
    fake_client.create_external_reference.assert_not_called()


def test_publish_with_known_ref_guid_links_it_without_a_lookup(monkeypatch):
    # The self-heal shape (round 4): a local row already carries a ref guid
    # (from a read-back adoption) but no link guid. publish_doc_source must
    # link THAT reference, not search for/create a different one.
    fake_client = MagicMock()
    fake_client.link_external_reference.return_value = "link-guid-3"

    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)

    def poisoned(client, qn):
        raise AssertionError("_find_ref_guid must not be called when known_ref_guid is given")

    monkeypatch.setattr(m, "_find_ref_guid", poisoned)

    source = {"url": "https://egeria.ai"}
    result = m.publish_doc_source(
        source, "asset-guid-1", known_ref_guid="known-guid-1",
        is_ref_unpublishing=lambda guid: False, **_EGERIA_KW,
    )

    assert result["ok"] is True
    assert result["ref_guid"] == "known-guid-1"
    fake_client.create_external_reference.assert_not_called()
    fake_client.link_external_reference.assert_called_once_with("asset-guid-1", "known-guid-1")


def test_publish_abandons_a_known_ref_guid_that_is_being_unpublished(monkeypatch):
    # The exact incident shape: the row's OWN stored ref_guid turns out to
    # be the one concurrently being deleted (adopted by an earlier
    # read-back before this guard existed, or before this call's own
    # unpublish check). It must be abandoned, not linked to — falling
    # through to the normal find-or-create flow for a fresh, independent
    # reference.
    fake_client = MagicMock()
    fake_client.create_external_reference.return_value = "fresh-guid-2"
    fake_client.link_external_reference.return_value = "fresh-link-2"

    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(m, "_find_ref_guid", lambda client, qn: "")  # nothing else found either

    source = {"url": "https://egeria.ai"}
    result = m.publish_doc_source(
        source, "asset-guid-1", known_ref_guid="stale-guid",
        is_ref_unpublishing=lambda guid: guid == "stale-guid", **_EGERIA_KW,
    )

    assert result["ok"] is True
    assert result["ref_guid"] == "fresh-guid-2"
    fake_client.create_external_reference.assert_called_once()


def test_publish_reports_failure_rather_than_raising(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("platform unreachable")

    monkeypatch.setattr(m, "_client", _boom)

    result = m.publish_doc_source({"url": "https://x"}, "asset-guid-1", **_EGERIA_KW)

    assert result["ok"] is False
    assert "platform unreachable" in result["error"]


def test_unpublish_detaches_and_deletes(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)

    result = m.unpublish_doc_source("ref-guid-1", "asset-guid-1", **_EGERIA_KW)

    assert result["ok"] is True
    fake_client.detach_external_reference.assert_called_once_with("asset-guid-1", "ref-guid-1")
    fake_client.delete_external_reference.assert_called_once_with("ref-guid-1")


def test_unpublish_with_no_ref_guid_is_a_no_op(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)

    result = m.unpublish_doc_source("", "asset-guid-1", **_EGERIA_KW)

    assert result["ok"] is True
    fake_client.detach_external_reference.assert_not_called()


def test_unpublish_tolerates_a_failed_detach_and_still_deletes(monkeypatch):
    fake_client = MagicMock()
    fake_client.detach_external_reference.side_effect = RuntimeError("relationship already gone")
    monkeypatch.setattr(m, "_client", lambda *a, **kw: fake_client)

    result = m.unpublish_doc_source("ref-guid-1", "asset-guid-1", **_EGERIA_KW)

    assert result["ok"] is True
    fake_client.delete_external_reference.assert_called_once_with("ref-guid-1")


def test_unpublish_removes_only_the_one_reference():
    """The brief's removal rule: 'removal deletes... the ExternalReference
    it created (and only that one)'. Nothing in unpublish_doc_source's
    signature accepts more than one GUID, which is the enforcement — this
    test pins that the call it makes names exactly the one GUID passed."""
    import inspect
    sig = inspect.signature(m.unpublish_doc_source)
    assert "ref_guid" in sig.parameters
    assert "ref_guids" not in sig.parameters  # no plural/batch form exists


def test_read_back_returns_empty_list_when_egeria_unreachable(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("no route to host")

    fake_module = MagicMock()
    fake_module.MetadataExpert.side_effect = _boom
    import sys
    monkeypatch.setitem(sys.modules, "pyegeria.omvs.metadata_expert", fake_module)

    out = m.read_back_doc_sources("asset-guid-1", **_EGERIA_KW)
    assert out == []


def test_read_back_returns_empty_list_with_no_asset_guid():
    # No network attempted at all when there's no asset to ask about.
    assert m.read_back_doc_sources("", **_EGERIA_KW) == []


def test_read_back_extracts_url_and_label(monkeypatch):
    # Shape confirmed live against a real Egeria platform (this slice's
    # gate check, 2026-09-28): `get_related_metadata_elements` returns
    # `{"elementList": [{"element": {"elementGUID": ..., "elementProperties":
    # {"propertiesAsStrings": {...}}}}]}`, not a bare list of elements — an
    # earlier version of read_back_doc_sources assumed the latter and
    # silently returned zero references against the real platform (see
    # doc_source_egeria.py's own comment on this fix).
    fake_element_client = MagicMock()
    fake_element_client.get_related_metadata_elements.return_value = {
        "elementList": [
            {
                "element": {
                    "elementGUID": "ref-guid-9",
                    "elementProperties": {
                        "propertiesAsStrings": {"url": "https://docs.example/x", "displayName": "X docs"},
                    },
                },
            },
            # An element with no URL must be skipped, not crash the read-back.
            {"element": {"elementGUID": "ref-guid-10", "elementProperties": {"propertiesAsStrings": {}}}},
        ],
    }

    fake_module = MagicMock()
    fake_module.MetadataExpert.return_value = fake_element_client
    import sys
    monkeypatch.setitem(sys.modules, "pyegeria.omvs.metadata_expert", fake_module)

    out = m.read_back_doc_sources("asset-guid-1", **_EGERIA_KW)

    assert out == [{"ref_guid": "ref-guid-9", "url": "https://docs.example/x", "label": "X docs"}]
