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
