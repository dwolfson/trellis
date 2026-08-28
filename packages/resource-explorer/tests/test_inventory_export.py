"""Inventory export — the registrations that re-ingestion cannot rebuild."""
from __future__ import annotations

from unittest.mock import MagicMock

from resource_explorer.inventory_export import FORMAT_VERSION, export_inventory, verify


def _registry(repos=("a",), dbs=(), fss=(), investigations=(), members=None):
    r = MagicMock()
    r.list_all.return_value = [MagicMock(slug=s, github_url=f"u/{s}") for s in repos]
    r.list_databases.return_value = [MagicMock(slug=s) for s in dbs]
    r.list_filesystems.return_value = [MagicMock(slug=s) for s in fss]
    r.list_groups.return_value = []
    r.list_servers.return_value = []
    r.list_aliases.return_value = []
    r.list_investigations.return_value = [{"slug": s} for s in investigations]
    r.list_investigation_members.side_effect = lambda slug: (members or {}).get(slug, [])
    return r


class TestManifest:
    def test_counts_every_section(self):
        p = export_inventory(_registry(repos=("a", "b"), dbs=("d",)))
        assert p["manifest"]["repo"] == 2
        assert p["manifest"]["database"] == 1
        assert p["manifest"]["filesystem"] == 0

    def test_verify_passes_a_consistent_export(self):
        assert verify(export_inventory(_registry())) == []

    def test_verify_catches_a_manifest_that_lies(self):
        p = export_inventory(_registry(repos=("a", "b")))
        p["manifest"]["repo"] = 99
        assert any("manifest repo" in msg for msg in verify(p))

    def test_an_empty_export_is_refused(self):
        """The failure this module is shaped around: an export that captured
        nothing reads exactly like a correct export of an empty estate, and
        only says so at restore time."""
        problems = verify(export_inventory(_registry(repos=())))
        assert any("no resources of any kind" in m for m in problems)

    def test_format_version_mismatch_is_reported(self):
        p = export_inventory(_registry())
        p["format_version"] = 99
        assert any("format_version" in m for m in verify(p))


class TestInvestigationMembership:
    def test_members_are_captured(self):
        p = export_inventory(_registry(
            repos=("a",), investigations=("inv",),
            members={"inv": [{"entity_type": "repo", "entity_slug": "a"}]},
        ))
        assert p["investigations"][0]["members"] == [
            {"entity_type": "repo", "entity_slug": "a"}
        ]
        assert p["manifest"]["investigation_members"] == 1

    def test_dangling_member_is_reported(self):
        """A member pointing at a resource that is not in the export would
        restore into a broken investigation -- the exact state that had to be
        repaired by hand when a stale row was deleted."""
        p = export_inventory(_registry(
            repos=("a",), investigations=("inv",),
            members={"inv": [{"entity_type": "repo", "entity_slug": "gone"}]},
        ))
        assert any("unknown repo 'gone'" in m for m in verify(p))


class TestReproducibility:
    def test_two_exports_are_identical(self):
        """generated_at is injected, not read from the clock, so an unchanged
        inventory diffs clean. Otherwise every re-export looks like a change
        and nobody reads the diff."""
        a = export_inventory(_registry(repos=("b", "a")), generated_at="T")
        b = export_inventory(_registry(repos=("a", "b")), generated_at="T")
        assert a == b

    def test_ordering_is_deterministic(self):
        p = export_inventory(_registry(repos=("z", "a", "m")))
        assert [r["slug"] for r in p["resources"]["repo"]] == ["a", "m", "z"]

    def test_version_is_stamped(self):
        assert export_inventory(_registry())["format_version"] == FORMAT_VERSION
