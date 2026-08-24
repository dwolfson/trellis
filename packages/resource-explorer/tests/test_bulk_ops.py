"""Bulk republish and deletion over many resources.

An Egeria reset makes every cataloged resource stale at once, so the
per-resource resolve means twenty clicks for one event. These are the same
operations over a list — and the interesting part is what they refuse to do.

Two properties are load-bearing and tested here rather than assumed:

  * **An explicit target list, never a derived one.** A sweep result and a work
    list are different things. `egeria-recheck` reports what it found at that
    moment; deriving "everything stale" inside a bulk delete would act on a list
    nobody read.
  * **Per-item isolation.** One resource failing must not abandon the other
    nineteen. This codebase already shipped a batch importer that stopped at its
    first repo and reported nothing (github/org_importer.py), and the failure was
    invisible because the thread simply died.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from resource_explorer.bulk_ops import (
    delete_in_egeria,
    delete_local,
    resolve_all,
)
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    for i in range(3):
        reg.add(Project(slug=f"p{i}", display_name=f"P{i}",
                        github_url=f"https://github.com/o/p{i}", description="",
                        collections=[f"p{i}_docs"]))
        reg.set_egeria_asset_guid(f"p{i}", f"guid-{i}")
        reg.mark_egeria_linkage_stale("repo", f"p{i}", f"guid-{i}", "gone")
    return reg


def _targets(*slugs):
    return [{"entity_type": "repo", "slug": s} for s in slugs]


class TestDryRunIsTheDefaultDirection:
    """Every operation must be inspectable before it is destructive."""

    def test_resolve_dry_run_changes_nothing(self, registry):
        r = resolve_all(registry, _targets("p0", "p1"), "republish", dry_run=True)
        assert r.succeeded == 2 and r.dry_run
        # The linkage rows and GUIDs are exactly as they were.
        assert len(registry.list_stale_egeria_linkages()) == 3
        assert registry.get_egeria_asset_guid("p0") == "guid-0"

    def test_delete_local_dry_run_removes_nothing(self, registry):
        r = delete_local(registry, _targets("p0"), dry_run=True)
        assert r.succeeded == 1
        assert registry.get("p0") is not None

    def test_delete_in_egeria_dry_run_calls_nothing(self, registry):
        """It must not even build a client, let alone delete — a dry run that
        connects is a dry run that can fail for reasons the real run would not."""
        with patch("pyegeria.AssetMaker") as AM:
            r = delete_in_egeria(registry, _targets("p0"), dry_run=True)
        AM.assert_not_called()
        assert r.succeeded == 1
        assert registry.get_egeria_asset_guid("p0") == "guid-0"

    def test_a_dry_run_reports_the_same_shape_as_the_real_thing(self, registry):
        """What you inspect has to be what happens, or the preview is theatre."""
        dry = delete_local(registry, _targets("p0"), dry_run=True).as_dict()
        real = delete_local(registry, _targets("p0"), dry_run=False).as_dict()
        assert set(dry) == set(real)
        assert {d["slug"] for d in dry["details"]} == {d["slug"] for d in real["details"]}


class TestPerItemIsolation:

    def test_one_failure_does_not_abandon_the_rest(self, registry):
        def flaky(reg, entity_type, slug, action):
            if slug == "p1":
                raise RuntimeError("boom")

        with patch("resource_explorer.bulk_ops._resolve_one", flaky):
            r = resolve_all(registry, _targets("p0", "p1", "p2"), "republish")

        assert r.succeeded == 2 and r.failed == 1
        failed = [d for d in r.details if d["result"] == "failed"]
        assert failed[0]["slug"] == "p1" and "boom" in failed[0]["message"]

    def test_every_requested_slug_appears_in_the_result(self, registry):
        """A partial run must be legible: seventeen succeeded and *which* three
        did not, rather than a single batch status."""
        with patch("resource_explorer.bulk_ops._resolve_one"):
            r = resolve_all(registry, _targets("p0", "p1", "p2"), "discard")
        assert {d["slug"] for d in r.details} == {"p0", "p1", "p2"}
        assert r.succeeded + r.failed + r.skipped == 3


class TestDeleteInEgeriaIsNarrow:
    """The one path that can destroy governance history, so it refuses more than
    it does."""

    def test_a_resource_with_no_cached_guid_is_skipped_not_searched(self, registry):
        """Without a GUID RE recorded, there is nothing RE can claim to have
        created — so it must not go looking for something by name to delete."""
        registry.add(Project(slug="nolink", display_name="N",
                             github_url="https://github.com/o/n", description=""))
        with patch("pyegeria.AssetMaker") as AM:
            AM.return_value.delete_asset.return_value = None
            r = delete_in_egeria(registry, _targets("nolink"), dry_run=False)

        AM.return_value.delete_asset.assert_not_called()
        assert r.skipped == 1
        assert "nothing RE recorded" in r.details[0]["message"]

    def test_it_deletes_exactly_the_recorded_guid(self, registry):
        with patch("pyegeria.AssetMaker") as AM:
            delete_in_egeria(registry, _targets("p0"), dry_run=False)
        AM.return_value.delete_asset.assert_called_once_with("guid-0")

    def test_the_local_guid_is_cleared_after_deleting(self, registry):
        """Leaving it would point at something that no longer exists — precisely
        the divergence this codebase spent the day learning to detect."""
        with patch("pyegeria.AssetMaker"):
            delete_in_egeria(registry, _targets("p0"), dry_run=False)
        assert not registry.get_egeria_asset_guid("p0")
        assert registry.get_egeria_linkage("repo", "p0") is None

    def test_res_own_data_survives(self, registry):
        """Deleting the catalog element must not delete the resource."""
        with patch("pyegeria.AssetMaker"):
            delete_in_egeria(registry, _targets("p0"), dry_run=False)
        assert registry.get("p0") is not None


class TestDeleteLocalLeavesEgeriaAlone:

    def test_it_never_calls_egeria(self, registry):
        """Local and catalog deletion are separate decisions; doing both from one
        button would make the narrower one impossible to choose."""
        with patch("pyegeria.AssetMaker") as AM, \
             patch("resource_explorer.bulk_ops._drop_collections"):
            delete_local(registry, _targets("p0"), dry_run=False)
        AM.assert_not_called()

    def test_it_drops_collections_and_the_row(self, registry):
        with patch("resource_explorer.bulk_ops._drop_collections") as drop:
            delete_local(registry, _targets("p0"), dry_run=False)
        drop.assert_called_once_with(["p0_docs"])
        assert registry.get("p0") is None

    def test_an_unregistered_slug_is_skipped_not_an_error(self, registry):
        r = delete_local(registry, _targets("never-existed"), dry_run=False)
        assert r.skipped == 1 and r.failed == 0


class TestActionValidation:

    def test_an_unknown_action_is_refused_before_anything_runs(self, registry):
        with pytest.raises(ValueError, match="unknown action"):
            resolve_all(registry, _targets("p0"), "obliterate")
