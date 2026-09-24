"""POST /api/feedback/answer used `registry.get(payload.slug)` (repo-only)
unconditionally, so a database/filesystem slug 404'd the whole route --
disagreeing with a database question's answer failed outright. A separate
helper, `_analyses_for_question()`, also hardcoded `get_questions("repo")`.

Mirrors tests/test_answer_feedback_gap.py's fixtures/style; the repo path
there is unchanged, this file is the database path that could not previously
succeed at all.
"""
from __future__ import annotations

import re as _re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from resource_explorer.config import FeedbackConfig
from resource_explorer.feedback_store import FeedbackStore
from resource_explorer.registry import DatabaseEntity


@pytest.fixture
def slug(request):
    return "ansfbdb_" + _re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:35]


@pytest.fixture
def reg(pg_registry, slug):
    pg_registry.register_database(DatabaseEntity(
        slug=slug, display_name=slug, db_type="postgresql",
        host="localhost", port=5432, database_name=slug,
    ))
    return pg_registry


@pytest.fixture
def client(tmp_path, reg, monkeypatch):
    store = FeedbackStore(db_path=str(tmp_path / "answer_feedback_db.db"))
    monkeypatch.setattr(
        "resource_explorer.feedback_store.FeedbackStore.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", store.__dict__) or None,
    )
    monkeypatch.setattr(
        "resource_explorer.web.routes.feedback.get_config",
        lambda: SimpleNamespace(feedback=FeedbackConfig(admin_token="t")),
    )
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, *a, **k: setattr(self, "__dict__", reg.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app), store


def _a_database_question() -> str:
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    entries = get_questions("database")
    if not entries:
        pytest.skip("no catalogued database questions")
    return entries[0]["question"]


class TestADatabaseSlugIsNoLongerRejected:
    def test_a_database_slug_used_to_404_and_now_does_not(self, client, slug):
        """Before this fix: `registry.get(slug)` only ever queried the
        repo-only `projects` table, so a database slug 404'd here even though
        the database exists (registered via `register_database` above)."""
        app_client, _ = client
        question = _a_database_question()
        resp = app_client.post("/api/feedback/answer", json={
            "slug": slug, "question": question, "verdict": "agree",
            "entity_type": "database",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_an_unknown_database_slug_still_404s(self, client):
        """The 404 guard must still work -- this fix widens WHICH table is
        checked, it does not remove the check."""
        app_client, _ = client
        resp = app_client.post("/api/feedback/answer", json={
            "slug": "not-a-real-database", "question": "does this even matter?",
            "verdict": "agree", "entity_type": "database",
        })
        assert resp.status_code == 404

    def test_no_entity_type_still_behaves_as_repo(self, client):
        """Omitting the new field must keep 404ing a database slug against
        the repo table -- unchanged default behaviour for every existing
        caller that predates `entity_type`."""
        app_client, _ = client
        resp = app_client.post("/api/feedback/answer", json={
            "slug": "not-a-real-repo", "question": "x", "verdict": "agree",
        })
        assert resp.status_code == 404


class TestDisagreementReadsTheDatabaseCatalog:
    def test_analyses_for_question_now_reads_the_database_catalog(self, slug):
        """`_analyses_for_question()` used to always read `get_questions("repo")`
        -- a database question worded differently from any repo question would
        resolve to `catalogued=[]`. Unit-level: exercises the helper directly,
        since the route-level disagree path below hits a SEPARATE, deeper,
        pre-existing bug this fix does not touch (see the test right after
        this one)."""
        from resource_explorer.surveyors.question_catalog_reader import get_questions
        from resource_explorer.web.routes.feedback import _analyses_for_question

        question = _a_database_question()
        expected = next(e for e in get_questions("database") if e["question"] == question)
        expected_ids = (expected.get("answering") or {}).get("analysis_ids") or []

        assert _analyses_for_question(question, "database") == expected_ids
        # And the OLD default (what every caller effectively got before this
        # fix) reads the repo catalog instead -- almost certainly not the
        # same list, which is the bug this pins.
        assert _analyses_for_question(question) == _analyses_for_question(question, "repo")

    def test_disagreeing_with_a_database_question_hits_a_separate_deeper_bug(self, client, slug):
        """FOUND, NOT FIXED (Tier 1 audit, 2026-09-23): this route's own fix
        (registry.get -> get_adapter(entity_type).get_entity, and
        _analyses_for_question(question, entity_type)) is correct and is what
        the test above pins. But `record_disagreement()` -> `registry.
        upsert_gap()` calls `self.get(slug)` INTERNALLY (registry.py) -- the
        exact same repo-only-table bug, one layer deeper, in a module this
        Tier 1 pass did not touch. A real disagreement with a database
        question's answer therefore still 500s today, past this fix's own
        404 guard. Documented here rather than silently left unasserted, per
        this task's found-but-deferred convention (see #4/#5 in the PR)."""
        app_client, _ = client
        question = _a_database_question()
        # TestClient re-raises an unhandled server-side exception rather than
        # turning it into a 500 response -- that IS the current behaviour:
        # this route's own 404 guard is fixed (see the class above), but
        # `registry.upsert_gap()`'s internal `self.get(slug)` still rejects
        # a database slug one layer down.
        with pytest.raises(ValueError, match="no such project"):
            app_client.post("/api/feedback/answer", json={
                "slug": slug, "question": question, "verdict": "disagree",
                "comment": "this looks wrong", "entity_type": "database",
            })
