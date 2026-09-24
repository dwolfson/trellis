"""GET /api/analyses/facts/{slug} and GET /api/analyses/facts both defaulted
`FactLayer()`/the default `analysis_ids` list to the repo's own maps
regardless of the resource actually asked about — same shape as the already-
fixed `answer_question()` route in this same file (see its own docstring).

Mirrors tests/test_fact_layer_resource_type_dispatch.py's style: the repo
path is unchanged (default `entity_type="repo"`), the database path is what
could not previously be expressed at all.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import DatabaseEntity, Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myrepo",
        display_name="My Repo",
        github_url="https://github.com/test/myrepo",
    ))
    r.register_database(DatabaseEntity(
        slug="mydb",
        display_name="My DB",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="mydb",
    ))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


class TestResourceFactsDefaultsToRepo:
    def test_no_entity_type_behaves_as_repo(self, client):
        """Every pre-existing caller omitted `entity_type` — must still work."""
        resp = client.get("/api/analyses/facts/myrepo")
        assert resp.status_code == 200
        assert resp.json()["subject"] == "myrepo"

    def test_default_ids_come_from_the_repo_map(self, client):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_RESULTS_MAP,
        )

        resp = client.get("/api/analyses/facts/myrepo")
        assert resp.status_code == 200
        facts = resp.json()["facts"]
        # One fact per default analysis id, same as before this fix existed.
        assert len(facts) == len(REPO_ANALYSIS_RESULTS_MAP)


class TestResourceFactsDatabaseDispatch:
    def test_a_database_slug_does_not_500(self, client):
        """Before this fix, `FactLayer()` always built its resource_type as
        'repo' and the default analysis_ids list always came from
        REPO_ANALYSIS_RESULTS_MAP -- a database slug still returned facts,
        but every one of them was read from the WRONG maps."""
        resp = client.get("/api/analyses/facts/mydb?entity_type=database")
        assert resp.status_code == 200
        assert resp.json()["subject"] == "mydb"

    def test_default_ids_come_from_the_database_map_not_the_repo_map(self, client):
        from resource_explorer.surveyors.database.survey_definition_adapter import (
            DATABASE_ANALYSIS_RESULTS_MAP,
        )
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_RESULTS_MAP,
        )

        resp = client.get("/api/analyses/facts/mydb?entity_type=database")
        assert resp.status_code == 200
        facts = resp.json()["facts"]
        assert len(facts) == len(DATABASE_ANALYSIS_RESULTS_MAP)
        assert len(DATABASE_ANALYSIS_RESULTS_MAP) != len(REPO_ANALYSIS_RESULTS_MAP), (
            "the two maps must differ in size for this test to actually "
            "distinguish 'read from database map' from 'read from repo map'"
        )


class TestBulkFactsResourceTypeDispatch:
    def test_no_entity_type_behaves_as_repo(self, client):
        resp = client.get("/api/analyses/facts?slugs=myrepo")
        assert resp.status_code == 200
        assert "myrepo" in resp.json()["subjects"]

    def test_a_database_slug_is_readable_when_entity_type_is_passed(self, client):
        resp = client.get("/api/analyses/facts?slugs=mydb&entity_type=database")
        assert resp.status_code == 200
        assert "mydb" in resp.json()["subjects"]
        assert not resp.json()["unreadable"]

    def test_states_only_projection_also_dispatches_by_entity_type(self, client):
        resp = client.get(
            "/api/analyses/facts?slugs=mydb&entity_type=database&states_only=true"
        )
        assert resp.status_code == 200
        assert "mydb" in resp.json()["states"]

    def test_default_ids_for_a_database_batch_come_from_the_database_map(self, client):
        from resource_explorer.surveyors.database.survey_definition_adapter import (
            DATABASE_ANALYSIS_RESULTS_MAP,
        )

        resp = client.get("/api/analyses/facts?slugs=mydb&entity_type=database")
        assert resp.status_code == 200
        assert resp.json()["analysis_ids"] == sorted(DATABASE_ANALYSIS_RESULTS_MAP)
