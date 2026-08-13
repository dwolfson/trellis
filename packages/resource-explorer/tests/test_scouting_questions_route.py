"""Tests for GET /{slug}/scouting-questions — the per-phase Question
checklist route (question_catalog_reader.py, Discovery-tier Part 3 plan).
No coverage existed for this route before this change.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        description="A test repo.",
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


class TestScoutingQuestionsRoute:
    def test_unknown_repo_returns_404(self, client):
        resp = client.get("/api/projects/not-a-real-repo/scouting-questions")
        assert resp.status_code == 404

    def test_defaults_to_scouting_phase(self, client):
        resp = client.get("/api/projects/myproj/scouting-questions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "scouting"
        assert data["questions"]
        assert all(
            q["asked_at"].lower() == "scouting" or q["answered_at"].lower() == "scouting"
            for q in data["questions"]
        )

    def test_phase_param_is_not_hardcoded_to_scouting(self, client):
        # Part 3 — the route (and its underlying reader) is phase-agnostic;
        # any of the 7 canonical intents works, not just scouting.
        resp = client.get("/api/projects/myproj/scouting-questions?phase=assessment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "assessment"
        assert data["questions"]
        assert all(
            q["asked_at"].lower() == "assessment" or q["answered_at"].lower() == "assessment"
            for q in data["questions"]
        )
        questions = {q["question"] for q in data["questions"]}
        assert "How mature is it?" in questions
        assert "What explicit license does the repository use, and are there non-standard or copyleft terms?" in questions

    def test_perspective_filter_narrows_results(self, client):
        unfiltered = client.get("/api/projects/myproj/scouting-questions?phase=assessment").json()
        filtered = client.get("/api/projects/myproj/scouting-questions?phase=assessment&perspectives=Security").json()
        assert len(filtered["questions"]) <= len(unfiltered["questions"])
        assert all("Security" in q["perspectives"] for q in filtered["questions"])

    def test_analysis_kind_question_gets_has_data_computed(self, client, registry):
        # license_classification has no findings yet -> has_data False, not None.
        resp = client.get("/api/projects/myproj/scouting-questions?phase=assessment")
        license_q = next(
            q for q in resp.json()["questions"]
            if q["question"].startswith("What explicit license")
        )
        assert license_q["kind"] == "analysis"
        assert license_q["has_data"] is False

        registry.upsert_finding(
            "myproj", "license_classification",
            [{"check_name": "license_risk_tier", "label": "permissive", "summary": "MIT", "confidence": 90}],
            surveyed_at="2026-08-01T00:00:00",
        )
        resp2 = client.get("/api/projects/myproj/scouting-questions?phase=assessment")
        license_q2 = next(
            q for q in resp2.json()["questions"]
            if q["question"].startswith("What explicit license")
        )
        assert license_q2["has_data"] is True

    def test_gap_kind_question_has_data_is_none(self, client):
        resp = client.get("/api/projects/myproj/scouting-questions?phase=analysis")
        gap_q = next(q for q in resp.json()["questions"] if q["question"] == "Are there outstanding CVEs?")
        assert gap_q["kind"] == "gap"
        assert gap_q["has_data"] is None
