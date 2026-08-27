"""Tests for egeria_resync.py — currently just _scan_unlinked_members, the
one bug found live (2026-08-26): the scan reported the same "investigation
members that can be attached" finding forever, even immediately after a
successful relink_investigation_members repair had actually attached them
(22 linked, zero errors), because it only checked "does this member have an
asset" rather than "is this member already in the Collection". Confirmed via
`apply(['relink_investigation_members'])` followed by `scan()` against a real
Egeria instance — the finding persisted unchanged. Fixed to check actual
Collection membership via CollectionManager.get_member_list().

No other part of this module has test coverage yet — out of scope for this
bug fix, not an oversight being repeated here.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from resource_explorer.egeria_resync import EgeriaResync, ScanResult


def _investigation(slug):
    return {"slug": slug, "egeria_project_guid": f"proj-{slug}"}


def _resync_with(registry, member_list_return):
    r = EgeriaResync(registry=registry)
    r._clients = {"collection": MagicMock(get_member_list=MagicMock(return_value=member_list_return))}
    return r


class TestScanUnlinkedMembers:
    def test_a_member_already_in_the_collection_is_not_reported_again(self):
        """The regression guard. Before the fix, this returned the same
        finding whether or not the member had actually been linked."""
        registry = MagicMock()
        registry.list_investigations.return_value = [_investigation("q3")]
        registry.get_or_create_working_set.return_value = {"egeria_collection_guid": "coll-1"}
        registry.list_investigation_members.return_value = [
            {"entity_type": "repo", "entity_slug": "kafka"},
        ]
        registry.get.return_value = SimpleNamespace(egeria_asset_guid="asset-kafka")

        r = _resync_with(registry, member_list_return=[{"guid": "asset-kafka"}])
        finding = r._scan_unlinked_members(ScanResult())

        assert finding.items == []

    def test_a_member_with_an_asset_not_yet_in_the_collection_is_reported(self):
        registry = MagicMock()
        registry.list_investigations.return_value = [_investigation("q3")]
        registry.get_or_create_working_set.return_value = {"egeria_collection_guid": "coll-1"}
        registry.list_investigation_members.return_value = [
            {"entity_type": "repo", "entity_slug": "kafka"},
        ]
        registry.get.return_value = SimpleNamespace(egeria_asset_guid="asset-kafka")

        r = _resync_with(registry, member_list_return=[])  # collection is empty
        finding = r._scan_unlinked_members(ScanResult())

        assert finding.items == [{"investigation": "q3", "linkable": 1}]

    def test_a_member_with_no_asset_yet_is_never_reported_regardless_of_membership(self):
        registry = MagicMock()
        registry.list_investigations.return_value = [_investigation("q3")]
        registry.get_or_create_working_set.return_value = {"egeria_collection_guid": "coll-1"}
        registry.list_investigation_members.return_value = [
            {"entity_type": "repo", "entity_slug": "unpublished"},
        ]
        registry.get.return_value = SimpleNamespace(egeria_asset_guid="")  # not published

        r = _resync_with(registry, member_list_return=[])
        finding = r._scan_unlinked_members(ScanResult())

        assert finding.items == []

    def test_a_collection_whose_membership_cannot_be_read_goes_to_undetermined_not_items(self):
        """Reporting a repair as still-needed when we couldn't verify it's
        not already done would be a guess dressed as a fact — the same shape
        this module's docstring warns about for the other scans."""
        registry = MagicMock()
        registry.list_investigations.return_value = [_investigation("q3")]
        registry.get_or_create_working_set.return_value = {"egeria_collection_guid": "coll-1"}
        registry.list_investigation_members.return_value = [
            {"entity_type": "repo", "entity_slug": "kafka"},
        ]
        registry.get.return_value = SimpleNamespace(egeria_asset_guid="asset-kafka")

        r = EgeriaResync(registry=registry)
        r._clients = {"collection": MagicMock(get_member_list=MagicMock(side_effect=ConnectionError("down")))}
        res = ScanResult()
        finding = r._scan_unlinked_members(res)

        assert finding.items == []
        assert len(res.undetermined) == 1
        assert res.undetermined[0]["kind"] == "collection membership"

    def test_no_collection_guid_is_skipped_entirely(self):
        """Nothing to check membership against — same as before the fix."""
        registry = MagicMock()
        registry.list_investigations.return_value = [_investigation("q3")]
        registry.get_or_create_working_set.return_value = {}  # no collection yet
        registry.list_investigation_members.return_value = [
            {"entity_type": "repo", "entity_slug": "kafka"},
        ]

        r = _resync_with(registry, member_list_return=[])
        finding = r._scan_unlinked_members(ScanResult())

        assert finding.items == []
        r._clients["collection"].get_member_list.assert_not_called()
