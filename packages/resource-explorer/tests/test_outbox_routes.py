"""The Publish Queue API — the detailed record behind an activity-log summary.

The activity log is an audit trail, one line per operation. It says *that* a
publish was incomplete; these routes say which elements, their qualifiedNames,
how many attempts each took and what Egeria actually said.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path/'t.db'}"
    monkeypatch.setenv("REGISTRY_DATABASE_URL", db_url)

    reg = ProjectRegistry(database_url=db_url)
    reg._init_schema()
    reg.add(Project(slug="p", display_name="p", github_url="https://github.com/o/p"))

    import resource_explorer.web.routes.outbox as outbox_routes
    monkeypatch.setattr(outbox_routes, "ProjectRegistry",
                        lambda *a, **k: ProjectRegistry(database_url=db_url))

    from resource_explorer.web.app import app
    return TestClient(app), reg


class TestListing:
    def test_it_returns_rows_counts_and_the_attempt_ceiling(self, client):
        c, reg = client
        reg.enqueue_outbox_element("repo", "p", "annotation", "Q::0", {"class": "X"}, run_id="r1")

        body = c.get("/api/outbox/").json()
        assert body["counts"] == {"pending": 1}
        assert len(body["rows"]) == 1
        assert body["rows"][0]["qualified_name"] == "Q::0"
        # The panel renders "attempts/N"; N has to come from the same constant
        # the retry policy uses, not a number copied into the frontend.
        assert body["max_attempts"] == ProjectRegistry.OUTBOX_MAX_ATTEMPTS

    def test_counts_cover_the_whole_table_not_the_filtered_page(self, client):
        c, reg = client
        dead = reg.enqueue_outbox_element("repo", "p", "annotation", "Q::0", {}, run_id="r1")
        reg.enqueue_outbox_element("repo", "p", "annotation", "Q::1", {}, run_id="r2")
        reg.mark_outbox_failed(dead, "x", max_attempts=1)

        body = c.get("/api/outbox/?status=pending").json()
        assert [r["qualified_name"] for r in body["rows"]] == ["Q::1"]
        assert body["counts"] == {"pending": 1, "dead": 1}, (
            "a panel filtered to pending must still report the dead row, or the "
            "filter silently becomes a claim that nothing is stuck"
        )

    def test_it_filters_by_run_so_an_activity_entry_can_link_to_its_own_publish(self, client):
        c, reg = client
        reg.enqueue_outbox_element("repo", "p", "annotation", "A::0", {}, run_id="run-a")
        reg.enqueue_outbox_element("repo", "p", "annotation", "B::0", {}, run_id="run-b")

        rows = c.get("/api/outbox/?run_id=run-b").json()["rows"]
        assert [r["qualified_name"] for r in rows] == ["B::0"]

    def test_an_unknown_status_is_rejected_rather_than_ignored(self, client):
        # Silently returning the unfiltered table would read as "nothing is
        # stuck" precisely when something is.
        c, _ = client
        res = c.get("/api/outbox/?status=nonsense")
        assert res.status_code == 400
        assert "nonsense" in res.json()["detail"]


class TestRetry:
    def test_a_dead_element_can_be_re_queued(self, client):
        c, reg = client
        row = reg.enqueue_outbox_element("repo", "p", "annotation", "Q::0", {}, run_id="r")
        reg.mark_outbox_failed(row, "permission denied", max_attempts=1)
        assert reg.outbox_counts() == {"dead": 1}

        assert c.post(f"/api/outbox/{row}/retry").status_code == 200
        assert reg.outbox_counts() == {"pending": 1}
        assert reg.claim_due_outbox_elements()[0]["attempts"] == 0

    def test_re_queueing_a_backing_off_element_is_refused(self, client):
        # "Retry" on a row that is merely waiting would discard its backoff.
        c, reg = client
        row = reg.enqueue_outbox_element("repo", "p", "annotation", "Q::0", {}, run_id="r")
        reg.mark_outbox_failed(row, "transient", max_attempts=9)

        res = c.post(f"/api/outbox/{row}/retry")
        assert res.status_code == 409
        assert "not dead" in res.json()["detail"]

    def test_an_unknown_element_is_404_not_409(self, client):
        c, _ = client
        assert c.post("/api/outbox/999999/retry").status_code == 404


class TestPurge:
    def test_it_removes_only_completed_rows(self, client):
        c, reg = client
        done = reg.enqueue_outbox_element("repo", "p", "annotation", "Q::0", {}, run_id="r")
        dead = reg.enqueue_outbox_element("repo", "p", "annotation", "Q::1", {}, run_id="r")
        reg.mark_outbox_done(done, "g")
        reg.mark_outbox_failed(dead, "x", max_attempts=1)
        with reg._conn() as conn:
            conn.execute("UPDATE egeria_outbox SET completed_at=? WHERE id=?",
                         ("2020-01-01T00:00:00", done))

        assert c.post("/api/outbox/purge?older_than_days=1").json()["removed"] == 1
        assert reg.outbox_counts() == {"dead": 1}
