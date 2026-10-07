"""Parity slice G1 (PI-001..PI-006): Egeria on a repository.

Publish whole and read back, the state words from proof rows only, the project-context gate, the
409 reuse, "Forget Egeria links" (RE's registry only), and the file-types preview-then-commit.
Everything runs on fakes: no Egeria, no network, a temp sqlite registry per test.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer import repo_publish as rp
from resource_explorer.registry import Project, ProjectRegistry

EGERIA_SENTENCE = ("OMAG-COMMON-409-001 The qualifiedName SurveyReport::x is not available for use. "
                   "Details follow in the second sentence.")


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(slug="myproj", display_name="My Project", github_url="https://github.com/test/myproj"))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    monkeypatch.setattr("resource_explorer.web.routes.egeria.get_current_user", lambda request: {"user_id": "dan"})
    from resource_explorer.web.app import app
    return TestClient(app)


def _result():
    r = MagicMock()
    r.annotations = ["a", "b", "c"]
    r.surveyed_at.isoformat.return_value = "2026-10-07T00:00:00"
    return r


def _publishers(registry, *, publish_guid="rep-1", reports=None, publish_exc=None, read_exc=None):
    """Patch the orchestrator and publisher; the publisher caches the asset GUID like the real one."""
    orch = patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator")
    pub = patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher")
    o, p = orch.start(), pub.start()
    o.return_value.run.return_value = _result()

    def _publish(result, *a, **k):
        if publish_exc:
            raise publish_exc
        registry.set_egeria_asset_guid("myproj", "asset-1")
        return publish_guid

    p.return_value.publish.side_effect = _publish
    p.return_value.report_reused = False
    if read_exc:
        p.return_value.get_survey_reports_by_guid.side_effect = read_exc
    else:
        p.return_value.get_survey_reports_by_guid.return_value = (
            reports if reports is not None else
            [{"guid": publish_guid, "qualified_name": "SurveyReport::x", "annotation_count": 3}])
    return o, p, (orch, pub)


@pytest.fixture
def stop():
    stops = []
    yield stops
    for s in stops:
        for x in s:
            x.stop()


# ── PI-001/PI-002: publish whole, then the state from proof rows ─────────────

class TestPublishWhole:
    def test_a_fresh_resource_has_no_row_and_is_not_in_egeria(self, client):
        s = client.get("/api/egeria/myproj/publish-state").json()
        assert s["in_egeria"] is False and s["asset_guid"] == ""
        assert s["row"]["word"] == "none" and s["can_publish_again"] is False

    def test_publish_is_read_back_before_the_word_says_published(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        o, p, s = _publishers(registry)
        stop.append(s)
        r = client.post("/api/egeria/myproj/publish-report", json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["row"]["word"] == "published" and body["row"]["report_guid"] == "rep-1"
        assert body["asset_guid"] == "asset-1" and body["in_egeria"] is True
        proofs = [x for x in registry.list_catalogue_commit_proofs("myproj") if x["node_kind"] == "repo_report"]
        assert [x["proof"] for x in proofs] == ["report_published"]
        assert proofs[0]["element_guid"] == "rep-1" and proofs[0]["target_guid"] == "asset-1"
        p.return_value.get_survey_reports_by_guid.assert_called_once_with("asset-1")   # read BY the asset's GUID
        o.return_value.run.assert_called_once_with("myproj", steps=None)               # whole report, never scoped
        assert body["can_publish_again"] is True

    def test_the_word_is_sent_not_published_when_the_read_does_not_show_the_report(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        _, _, s = _publishers(registry, reports=[])
        stop.append(s)
        body = client.post("/api/egeria/myproj/publish-report", json={}).json()
        assert body["row"]["word"] == "sent"
        kinds = [x["proof"] for x in registry.list_catalogue_commit_proofs("myproj")]
        assert "report_published" not in kinds and kinds == ["report_sent"]

    def test_a_failed_read_is_sent_with_the_reason_never_published(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        _, _, s = _publishers(registry, read_exc=RuntimeError("read timed out"))
        stop.append(s)
        body = client.post("/api/egeria/myproj/publish-report", json={}).json()
        assert body["row"]["word"] == "sent" and "read timed out" in body["row"]["sentence"]

    def test_egeria_refusing_is_not_published_and_the_full_sentence_is_stored(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        _, _, s = _publishers(registry, publish_exc=RuntimeError(EGERIA_SENTENCE))
        stop.append(s)
        body = client.post("/api/egeria/myproj/publish-report", json={}).json()
        assert body["ok"] is False and body["row"]["word"] == "not published"
        assert body["row"]["first"].startswith("OMAG-COMMON-409-001")
        stored = [x for x in registry.list_catalogue_commit_proofs("myproj") if x["proof"] == "read_failed"][0]
        assert stored["detail"]["error"] == EGERIA_SENTENCE                      # the FULL sentence, not the first
        assert body["row"]["sentence"] == EGERIA_SENTENCE

    def test_publish_again_is_a_second_press_that_adds_a_row_and_the_latest_wins(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        _, _, s = _publishers(registry)
        stop.append(s)
        client.post("/api/egeria/myproj/publish-report", json={})
        client.post("/api/egeria/myproj/publish-report", json={})
        proofs = [x for x in registry.list_catalogue_commit_proofs("myproj") if x["proof"] == "report_published"]
        assert len(proofs) == 2

    def test_zones_are_never_a_per_press_choice(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        _, p, s = _publishers(registry)
        stop.append(s)
        client.post("/api/egeria/myproj/publish-report", json={"zone_names": ["secret-zone"]})
        _, kwargs = p.call_args
        assert "zone_names" not in kwargs
        for call in p.return_value.publish.call_args_list:
            assert "zone_names" not in call.kwargs and len(call.args) == 1

    def test_signed_out_is_refused_and_nothing_is_sent(self, client, registry, monkeypatch, stop):
        monkeypatch.setattr("resource_explorer.web.routes.egeria.get_current_user", lambda request: None)
        registry.set_project_context("repo", "myproj", "personal")
        o, p, s = _publishers(registry)
        stop.append(s)
        assert client.post("/api/egeria/myproj/publish-report", json={}).status_code == 401
        p.return_value.publish.assert_not_called()

    def test_a_second_press_while_one_is_running_is_ignored_with_409(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        _, p, s = _publishers(registry)
        stop.append(s)
        gate = threading.Event()
        entered = threading.Event()

        def slow(result, *a, **k):
            entered.set()
            gate.wait(5)
            registry.set_egeria_asset_guid("myproj", "asset-1")
            return "rep-1"

        p.return_value.publish.side_effect = slow
        out = {}
        t = threading.Thread(target=lambda: out.update(first=client.post("/api/egeria/myproj/publish-report", json={})))
        t.start()
        assert entered.wait(5)
        second = client.post("/api/egeria/myproj/publish-report", json={})
        gate.set()
        t.join(5)
        assert second.status_code == 409
        assert out["first"].status_code == 200
        assert p.return_value.publish.call_count == 1


class TestReportReuseOnA409:
    def _publisher(self):
        from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
        pub = EgeriaPublisher.__new__(EgeriaPublisher)
        pub._registry = None
        pub._asset_maker = MagicMock()
        pub._automated_curation = MagicMock()
        return pub

    def _result(self):
        res = SimpleNamespace(resource_slug="myproj", project_display_name="My Project",
                              github_url="https://github.com/test/myproj", annotations=[], errors=[])
        res.surveyed_at = SimpleNamespace(isoformat=lambda: "2026-10-07T00:00:00")
        return res

    def test_the_name_is_taken_so_the_existing_report_is_reused_not_a_second_one(self):
        pub = self._publisher()
        pub._asset_maker.create_asset.side_effect = RuntimeError(
            "SERVER_ERROR_500 relatedHTTPCode 409 OMAG-COMMON-409-001 qualifiedName is not available for use")
        pub._find_element_guid = MagicMock(return_value="existing-report-guid")
        guid = pub._create_survey_report(self._result(), "asset-1")
        assert guid == "existing-report-guid"
        assert pub.report_reused is True
        pub._find_element_guid.assert_called_once_with("SurveyReport::GitHubRepo::myproj::2026-10-07T00:00:00")
        assert pub._asset_maker.create_asset.call_count == 1                       # no retry, no second create

    def test_any_other_failure_is_not_swallowed(self):
        pub = self._publisher()
        pub._asset_maker.create_asset.side_effect = RuntimeError("OMAG-REPOSITORY-500 the store is down")
        with pytest.raises(RuntimeError, match="the store is down"):
            pub._create_survey_report(self._result(), "asset-1")

    def test_a_duplicate_with_no_readable_report_fails_loud_it_does_not_invent_a_guid(self):
        pub = self._publisher()
        pub._asset_maker.create_asset.side_effect = RuntimeError("409 OMAG-COMMON-409-001 is not available for use")
        pub._find_element_guid = MagicMock(return_value="")
        with pytest.raises(RuntimeError, match="no report with that name"):
            pub._create_survey_report(self._result(), "asset-1")

    def test_the_reuse_is_recorded_on_the_proof_row(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        _, p, s = _publishers(registry)
        stop.append(s)
        p.return_value.report_reused = True
        body = client.post("/api/egeria/myproj/publish-report", json={}).json()
        assert body["reused"] is True and body["row"]["reused"] is True


# ── PI-006: the project-context gate ─────────────────────────────────────────

class TestProjectContextGate:
    def test_no_answer_is_428_with_the_two_choices_sentence_and_nothing_is_sent(self, client, registry, stop):
        o, p, s = _publishers(registry)
        stop.append(s)
        r = client.post("/api/egeria/myproj/publish-report", json={})
        assert r.status_code == 428
        assert r.json()["detail"] == "egeria_project_context_required"
        assert r.json()["sentence"] == ("no Egeria project context · bind this investigation to a project, "
                                        "or publish without one")
        p.return_value.publish.assert_not_called()
        assert registry.list_catalogue_commit_proofs("myproj") == []

    def test_publishing_without_one_records_the_choice_and_proceeds(self, client, registry, stop):
        _, p, s = _publishers(registry)
        stop.append(s)
        body = client.post("/api/egeria/myproj/publish-report", json={"without_project": True}).json()
        assert body["row"]["word"] == "published"
        assert registry.get_project_context("repo", "myproj")["status"] == "declined"
        assert body["project"]["word"] == "no project (chosen)"

    def test_a_bound_investigation_answers_and_the_row_names_the_project(self, client, registry, stop, monkeypatch):
        monkeypatch.setattr(ProjectRegistry, "inherited_egeria_project_context", lambda self, t, s, **k: {
            "egeria_project_guid": "g-1", "egeria_project_qualified_name": "Apollo::1",
            "_inherited_from_name": "Moonshot"})
        _, _, s = _publishers(registry)
        stop.append(s)
        r = client.post("/api/egeria/myproj/publish-report", json={})
        assert r.status_code == 200
        assert r.json()["project"]["name"] == "Apollo"            # first segment of the qualified name
        ctx = registry.get_project_context("repo", "myproj")
        assert ctx["status"] == "linked" and "Moonshot" in ctx["free_text_name"]

    def test_the_state_names_an_inherited_project_before_any_publish(self, client, registry, monkeypatch):
        monkeypatch.setattr(ProjectRegistry, "inherited_egeria_project_context", lambda self, t, s, **k: {
            "egeria_project_guid": "g-1", "egeria_project_qualified_name": "Apollo::1",
            "_inherited_from_name": "Moonshot"})
        s = client.get("/api/egeria/myproj/publish-state").json()
        assert s["project"]["name"] == "Apollo" and "Moonshot" in s["project"]["detail"]

    def test_the_state_says_no_project_when_nothing_answers(self, client):
        assert client.get("/api/egeria/myproj/publish-state").json()["project"]["word"] == "no project"


# ── PI-005: forget the cached links ──────────────────────────────────────────

class TestForgetLinks:
    def _published(self, client, registry, stop):
        registry.set_project_context("repo", "myproj", "personal")
        _, p, s = _publishers(registry)
        stop.append(s)
        client.post("/api/egeria/myproj/publish-report", json={})
        registry.record_egeria_survey("myproj", "2026-10-07T00:00:00", "rep-1", annotation_count=3)
        return p

    def test_it_clears_the_cached_guid_and_survey_history_in_re_only(self, client, registry, stop):
        self._published(client, registry, stop)
        assert registry.get_egeria_asset_guid("myproj") == "asset-1"
        with patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher",
                   side_effect=AssertionError("forgetting must never construct an Egeria client")):
            r = client.post("/api/egeria/myproj/forget-links")
        assert r.status_code == 200, r.text
        b = r.json()
        assert registry.get_egeria_asset_guid("myproj") in (None, "")
        assert registry.get_egeria_surveys("myproj") == []
        assert b["asset_guid_cleared"] is True and b["surveys_deleted"] >= 1
        assert b["forgot_asset_guid"] == "asset-1"
        assert b["in_egeria"] is False and b["row"]["word"] == "forgotten"
        assert b["sentence"] == ("Egeria is unchanged; Resource Explorer forgets its cached GUIDs and survey history "
                                 "for this resource and re-reads them on the next publish.")

    def test_the_forgetting_is_a_row_with_a_person_and_earlier_proofs_stay(self, client, registry, stop):
        self._published(client, registry, stop)
        client.post("/api/egeria/myproj/forget-links")
        proofs = [x for x in registry.list_catalogue_commit_proofs("myproj") if x["node_kind"] == "repo_report"]
        assert [x["proof"] for x in proofs] == ["report_published", "links_forgotten"]
        assert proofs[-1]["recorded_by"] == "dan" and proofs[-1]["detail"]["egeria_unchanged"] is True

    def test_it_never_archives_or_deletes_in_egeria(self):
        """No call in the module is named like an archive, a delete or a remove (docstrings excluded)."""
        import ast
        import inspect
        names = set()
        for n in ast.walk(ast.parse(inspect.getsource(rp))):
            if isinstance(n, ast.Attribute):
                names.add(n.attr)
            elif isinstance(n, ast.Name):
                names.add(n.id)
        bad = [x for x in names if any(w in x.lower() for w in ("archive", "delete", "remove", "detach"))]
        assert bad == []

    def test_publishing_again_after_forgetting_re_reads_the_asset(self, client, registry, stop):
        p = self._published(client, registry, stop)
        client.post("/api/egeria/myproj/forget-links")
        b = client.post("/api/egeria/myproj/publish-report", json={}).json()
        assert b["asset_guid"] == "asset-1" and b["row"]["word"] == "published"
        assert p.return_value.publish.call_count == 2

    def test_signed_out_is_refused_and_nothing_is_cleared(self, client, registry, monkeypatch, stop):
        self._published(client, registry, stop)
        monkeypatch.setattr("resource_explorer.web.routes.egeria.get_current_user", lambda request: None)
        assert client.post("/api/egeria/myproj/forget-links").status_code == 401
        assert registry.get_egeria_asset_guid("myproj") == "asset-1"


# ── PI-004: catalog selected file types ──────────────────────────────────────

class FakeFileTypes:
    def __init__(self):
        self.created, self.linked, self.existing = [], [], {}
        self.fail_create, self.fail_link, self.unreadable = set(), set(), set()

    def find(self, qn):
        return self.existing.get(qn, "")

    def create(self, body):
        qn = body["properties"]["qualifiedName"]
        label = body["properties"]["additionalProperties"]["file_type_label"]
        if label in self.fail_create:
            raise RuntimeError("OMAG-500 the create was refused. Context: more text")
        guid = f"ds-{label}"
        self.created.append(qn)
        self.existing[qn] = guid
        return guid

    def read(self, guid):
        return None if guid.split("ds-")[-1] in self.unreadable else {"guid": guid}

    def link(self, asset, ds, label):
        if label in self.fail_link:
            raise RuntimeError("OMAG-LINK-400 the relationship type does not allow this. Context: x")
        self.linked.append((asset, ds))


class TestFileTypes:
    def _seed(self, registry):
        with registry._conn() as conn:
            conn.execute("DELETE FROM project_file_type_counts WHERE project_slug = ?", ("myproj",))
        cols = None
        with registry._conn() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(project_file_type_counts)").fetchall()]
        for label, n in (("Python", 12), ("Markdown", 4)):
            row = {"project_slug": "myproj", "surveyed_at": "2026-10-07T00:00:00", "type_label": label,
                   "file_count": n, "source": "extension", "details_json": '{".py": 12}'}
            names = [c for c in cols if c in row]
            with registry._conn() as conn:
                conn.execute(f"INSERT INTO project_file_type_counts ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                             tuple(row[c] for c in names))

    def test_preview_sends_nothing_and_lists_what_would_be_created(self, client, registry):
        self._seed(registry)
        registry.set_egeria_asset_guid("myproj", "asset-1")
        b = client.get("/api/egeria/myproj/file-types").json()
        assert {t["label"] for t in b["types"]} == {"Python", "Markdown"}
        assert all(t["cataloged"] is False for t in b["types"]) and b["blocker"] == ""
        assert registry.list_catalogue_commit_proofs("myproj") == []

    def test_a_repository_not_in_egeria_has_a_blocker_and_the_commit_is_refused(self, client, registry):
        self._seed(registry)
        assert "publish the report first" in client.get("/api/egeria/myproj/file-types").json()["blocker"]
        r = client.post("/api/egeria/myproj/file-types/commit", json={"elements": [{"label": "Python", "file_count": 12}]})
        assert r.status_code == 409

    def test_commit_creates_reads_back_then_writes_the_row_by_guid(self, client, registry, monkeypatch):
        self._seed(registry)
        registry.set_egeria_asset_guid("myproj", "asset-1")
        fake = FakeFileTypes()
        monkeypatch.setattr(rp, "FileTypeGateway", lambda registry=None: fake)
        r = client.post("/api/egeria/myproj/file-types/commit",
                        json={"elements": [{"label": "Python", "file_count": 12, "extensions": [".py"]}]})
        assert r.status_code == 200, r.text
        item = r.json()["items"][0]
        assert item["state"] == "cataloged" and item["guid"] == "ds-Python"
        row = [x for x in registry.list_catalogue_commit_proofs("myproj") if x["node_kind"] == "file_type"][0]
        assert row["proof"] == "file_type_read_back" and row["element_guid"] == "ds-Python"
        assert row["target_guid"] == "asset-1" and row["detail"]["linked"] is True
        again = client.get("/api/egeria/myproj/file-types").json()["types"]
        assert [t["cataloged"] for t in again if t["label"] == "Python"] == [True]

    def test_pressing_again_adopts_the_existing_element_never_a_second_one(self, client, registry, monkeypatch):
        self._seed(registry)
        registry.set_egeria_asset_guid("myproj", "asset-1")
        fake = FakeFileTypes()
        monkeypatch.setattr(rp, "FileTypeGateway", lambda registry=None: fake)
        body = {"elements": [{"label": "Python", "file_count": 12}]}
        client.post("/api/egeria/myproj/file-types/commit", json=body)
        client.post("/api/egeria/myproj/file-types/commit", json=body)
        assert fake.created == ["DataSet::myproj::Python"]

    def test_a_create_refusal_writes_a_failed_row_with_the_full_sentence_and_no_success_row(self, client, registry, monkeypatch):
        self._seed(registry)
        registry.set_egeria_asset_guid("myproj", "asset-1")
        fake = FakeFileTypes()
        fake.fail_create.add("Python")
        monkeypatch.setattr(rp, "FileTypeGateway", lambda registry=None: fake)
        b = client.post("/api/egeria/myproj/file-types/commit", json={"elements": [{"label": "Python", "file_count": 1}]}).json()
        assert b["ok"] is False and b["items"][0]["words"] == "not cataloged · OMAG-500 the create was refused."
        proofs = [x for x in registry.list_catalogue_commit_proofs("myproj") if x["node_kind"] == "file_type"]
        assert [x["proof"] for x in proofs] == ["read_failed"]
        assert proofs[0]["detail"]["error"] == "OMAG-500 the create was refused. Context: more text"

    def test_an_element_that_cannot_be_read_back_is_not_a_success(self, client, registry, monkeypatch):
        self._seed(registry)
        registry.set_egeria_asset_guid("myproj", "asset-1")
        fake = FakeFileTypes()
        fake.unreadable.add("Python")
        monkeypatch.setattr(rp, "FileTypeGateway", lambda registry=None: fake)
        b = client.post("/api/egeria/myproj/file-types/commit", json={"elements": [{"label": "Python", "file_count": 1}]}).json()
        assert b["items"][0]["state"] == "failed"
        kinds = [x["proof"] for x in registry.list_catalogue_commit_proofs("myproj") if x["node_kind"] == "file_type"]
        assert kinds == ["read_failed"]

    def test_a_link_that_fails_says_cataloged_not_linked_and_keeps_the_sentence(self, client, registry, monkeypatch):
        self._seed(registry)
        registry.set_egeria_asset_guid("myproj", "asset-1")
        fake = FakeFileTypes()
        fake.fail_link.add("Python")
        monkeypatch.setattr(rp, "FileTypeGateway", lambda registry=None: fake)
        b = client.post("/api/egeria/myproj/file-types/commit", json={"elements": [{"label": "Python", "file_count": 1}]}).json()
        it = b["items"][0]
        assert it["state"] == "cataloged_unlinked"
        assert it["words"] == "cataloged, not linked to the repository · OMAG-LINK-400 the relationship type does not allow this."
        row = [x for x in registry.list_catalogue_commit_proofs("myproj") if x["node_kind"] == "file_type"][0]
        assert row["detail"]["linked"] is False and "Context: x" in row["detail"]["link_error"]

    def test_signed_out_is_refused(self, client, registry, monkeypatch):
        monkeypatch.setattr("resource_explorer.web.routes.egeria.get_current_user", lambda request: None)
        r = client.post("/api/egeria/myproj/file-types/commit", json={"elements": []})
        assert r.status_code == 401
