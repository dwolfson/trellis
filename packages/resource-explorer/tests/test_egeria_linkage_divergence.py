"""Egeria <-> RE divergence: detect a cached GUID that no longer exists.

Reported 2026-07-21: Egeria's repository was reset independently of RE's
registry, and the next filesystem resurvey failed with SERVER_ERROR_500 reaching
the UI verbatim — a Java stack with OMRS-REPOSITORY-404-002 buried in it and
nothing actionable. Retrying could never fix it, and nothing said why.

The design decision under test is "detect, don't auto-resolve": a stale root GUID
makes the whole Egeria-side lineage beneath it unverifiable, so recreating in
place risks duplicating elements and discarding catalog history. So detection
must record and report, and must not clear anything by itself.
"""
from __future__ import annotations

import pytest

from resource_explorer.egeria_linkage import (
    StaleEgeriaLinkageError,
    guard_linkage,
    is_unknown_guid_error,
)
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="myproj", display_name="My Proj",
                    github_url="https://github.com/o/myproj", description=""))
    return reg


# The shape actually reported: a 500 whose nested server message carries the 404.
REAL_ERROR = (
    "SERVER_ERROR_500 Egeria detected error: * relatedHTTPCode= `500` "
    "* exceptionErrorMessage= `OMRS-REPOSITORY-404-002 The entity identified with "
    "guid abc-123 is not known to the open metadata repository`"
)


# Captured verbatim 2026-08-20 by asking this deployment's live Egeria for a GUID
# that cannot exist (AssetMaker.get_asset_by_guid). Kept in full rather than
# paraphrased: the detector's whole job is to recognise what Egeria really says,
# and a hand-written approximation would let the two drift apart unnoticed.
LIVE_ERROR = """
=> \tCLIENT_ERROR_400
=>\tClient error occurred with status code `https://localhost:9443/servers/qs-view-server/api/open-metadata/asset-maker/assets/00000000-dead-beef-0000-000000000000/retrieve`.
\t* Egeria error information:
\t* relatedHTTPCode= `404`
\t* exceptionClassName= `org.odpi.openmetadata.frameworks.openmetadata.ffdc.InvalidParameterException`
\t* actionDescription= `getMetadataElementByGUID`
\t* exceptionErrorMessage= `OMAG-REPOSITORY-HANDLER-404-007 The Asset entity with unique identifier 00000000-dead-beef-0000-000000000000 is not found for method getMetadataElementByGUID of access service Open Metadata Store Services in open metadata server qs-metadata-store, error message was: OMRS-REPOSITORY-404-002 The entity identified with guid 00000000-dead-beef-0000-000000000000 passed on the getEntityDetail call is not known to the open metadata repository Enterprise`
"""


class TestDetection:

    def test_recognises_the_real_live_error(self):
        """Pinned to what the platform actually returned, not to a paraphrase.
        Note it labels itself CLIENT_ERROR_400 while relatedHTTPCode is 404 —
        one reason the detector keys on Egeria's message codes, not on status."""
        assert is_unknown_guid_error(Exception(LIVE_ERROR))

    def test_recognises_the_error_as_actually_reported(self):
        """Type-based detection would miss this: it arrives as a generic API
        error carrying a 500, with the real 404 code nested inside."""
        assert is_unknown_guid_error(Exception(REAL_ERROR))

    def test_recognises_the_bare_404_codes(self):
        assert is_unknown_guid_error(Exception("OMRS-REPOSITORY-404-007 ..."))
        assert is_unknown_guid_error(Exception("OMAG-COMMON-404-003 ..."))

    def test_an_empty_search_result_is_not_a_divergence(self):
        """The most damaging false positive available. "No elements found" is an
        ordinary empty result; treating it as divergence would send someone to
        reconcile a catalog that was never broken."""
        assert not is_unknown_guid_error(Exception("No elements found"))
        assert not is_unknown_guid_error(Exception("0 results returned for query"))

    def test_ordinary_failures_are_not_divergences(self):
        assert not is_unknown_guid_error(Exception("Connection refused"))
        assert not is_unknown_guid_error(Exception("SERVER_ERROR_500 JDBC-RESOURCE-"
                                                  "CONNECTOR-500-002 missing value for "
                                                  "column metadata_collection_guid"))


class TestGuard:

    def test_records_the_divergence_and_raises_a_named_error(self, registry):
        with pytest.raises(StaleEgeriaLinkageError) as ei:
            with guard_linkage(registry, "repo", "myproj", "My Proj", "abc-123"):
                raise Exception(REAL_ERROR)

        assert ei.value.stale_guid == "abc-123"
        # The message has to name the resolutions; being told what broke without
        # being told what to do is the state this replaces.
        msg = str(ei.value)
        assert "republish" in msg and "re-survey" in msg and "discard" in msg

        row = registry.get_egeria_linkage("repo", "myproj")
        assert row["status"] == "stale" and row["stale_guid"] == "abc-123"

    def test_the_original_error_is_preserved(self, registry):
        """The server-side detail is the only evidence of what Egeria actually
        said — a friendlier message must not replace it."""
        with pytest.raises(StaleEgeriaLinkageError) as ei:
            with guard_linkage(registry, "repo", "myproj", "My Proj", "abc-123"):
                raise Exception(REAL_ERROR)
        assert "OMRS-REPOSITORY-404-002" in str(ei.value.__cause__)

    def test_it_does_not_clear_the_cached_guid(self, registry):
        """Detect, don't auto-resolve. The GUID is kept so a human can see what
        RE had, and so republish can report what it is replacing."""
        registry.set_egeria_asset_guid("myproj", "abc-123")
        with pytest.raises(StaleEgeriaLinkageError):
            with guard_linkage(registry, "repo", "myproj", "My Proj", "abc-123"):
                raise Exception(REAL_ERROR)
        assert registry.get_egeria_asset_guid("myproj") == "abc-123"

    def test_unrelated_failures_pass_straight_through(self, registry):
        with pytest.raises(ValueError):
            with guard_linkage(registry, "repo", "myproj", "My Proj", "abc-123"):
                raise ValueError("something else entirely")
        assert registry.get_egeria_linkage("repo", "myproj") is None

    def test_no_cached_guid_means_nothing_to_detect(self, registry):
        """Without a cached GUID there is no stale linkage — any failure is an
        ordinary one and must not be relabelled."""
        with pytest.raises(Exception) as ei:
            with guard_linkage(registry, "repo", "myproj", "My Proj", ""):
                raise Exception(REAL_ERROR)
        assert not isinstance(ei.value, StaleEgeriaLinkageError)
        assert registry.get_egeria_linkage("repo", "myproj") is None

    def test_a_divergence_raises_an_rfa(self, registry):
        with pytest.raises(StaleEgeriaLinkageError):
            with guard_linkage(registry, "repo", "myproj", "My Proj", "abc-123"):
                raise Exception(REAL_ERROR)
        rfas = [e for e in registry.list_activity(operation="rfa")]
        assert any("stale" in (e.get("summary") or "").lower() for e in rfas)


class TestGuardsAreActuallyInstalled:
    """The guard only helps at the paths that consume a cached GUID. These are
    the four the backlog named; a new one added without a guard would reintroduce
    the opaque failure at that path only."""

    @pytest.mark.parametrize("module_path,cls_name,method", [
        ("resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor",
         "EgeriaFileSystemSurveyor", "publish_step_annotations"),
        ("resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor",
         "EgeriaFileSystemSurveyor", "catalog_and_survey"),
        ("resource_explorer.surveyors.database.egeria_database_surveyor",
         "EgeriaDatabaseSurveyor", "publish_step_annotations"),
        ("resource_explorer.surveyors.database.egeria_database_surveyor",
         "EgeriaDatabaseSurveyor", "catalog_and_survey"),
        ("resource_explorer.surveyors.egeria_publisher", "EgeriaPublisher", "publish"),
    ])
    def test_entry_point_uses_the_guard(self, module_path, cls_name, method):
        import importlib
        import inspect

        cls = getattr(importlib.import_module(module_path), cls_name)
        src = inspect.getsource(getattr(cls, method))
        assert "guard_linkage" in src, (
            f"{cls_name}.{method} consumes a cached Egeria GUID but does not wrap the "
            "work in guard_linkage — a divergence there still surfaces as a raw "
            "server error.")


class TestResolveRoutes:
    """The "let a human choose" half. All three actions clear the unusable GUID
    — that is what unblocks the resource — and differ in what happens next."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from resource_explorer.web.app import app

        db = str(tmp_path / "t.db")

        def _reg(*a, **kw):
            return ProjectRegistry(db_path=db)

        monkeypatch.setattr("resource_explorer.web.routes.egeria.ProjectRegistry", _reg)
        reg = _reg()
        reg.add(Project(slug="myproj", display_name="My Proj",
                        github_url="https://github.com/o/myproj", description=""))
        reg.set_egeria_asset_guid("myproj", "abc-123")
        reg.mark_egeria_linkage_stale("repo", "myproj", "abc-123", "OMRS-REPOSITORY-404-002")
        return TestClient(app), reg

    def test_stale_linkages_are_listed(self, client):
        c, _ = client
        rows = c.get("/api/egeria/linkage/stale").json()
        assert [r["entity_slug"] for r in rows] == ["myproj"]
        assert rows[0]["stale_guid"] == "abc-123"

    def test_discard_clears_the_link_and_keeps_local_data(self, client):
        c, reg = client
        r = c.post("/api/egeria/linkage/repo/myproj/resolve", json={"action": "discard"})
        assert r.status_code == 200
        assert r.json()["asset_guid_cleared"] is True
        # The link is gone from both places it was recorded...
        assert reg.get_egeria_linkage("repo", "myproj") is None
        assert not reg.get_egeria_asset_guid("myproj")
        # ...and the wording says plainly that local results survived, because
        # "discard" is the one action a user could reasonably fear.
        assert "local survey results are untouched" in r.json()["next_step"].lower()

    def test_resolving_something_that_is_not_stale_is_a_404(self, client):
        c, _ = client
        assert c.post("/api/egeria/linkage/repo/other/resolve",
                      json={"action": "discard"}).status_code == 404

    def test_unknown_action_is_rejected_rather_than_guessed(self, client):
        c, _ = client
        r = c.post("/api/egeria/linkage/repo/myproj/resolve", json={"action": "fix"})
        assert r.status_code == 422
        assert "republish" in r.json()["detail"]

    def test_unknown_entity_type_is_rejected(self, client):
        c, _ = client
        assert c.post("/api/egeria/linkage/nonsense/myproj/resolve",
                      json={"action": "discard"}).status_code == 422
