"""Cancel a waiting or running Egeria survey action (an Egeria WRITE, as the signed-in person).

End to end through the real route, the real access decision, the real port and the real client factory. The
ONLY fake is the pyegeria client boundary: `pyegeria.AutomatedCuration` and `pyegeria.MetadataExpert` (and the
two access-check clients), each method bound against the INSTALLED pyegeria signature first, so a call the
real library would reject fails here too. Nothing here contacts Egeria.

What the real library says (pyegeria 6.2.1): `AutomatedCuration.cancel_engine_action(engine_action_guid: str)
-> None`.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import DatabaseEntity, ProjectRegistry

sys.path.insert(0, str(Path(__file__).parent))
pytestmark = pytest.mark.usefixtures("mock_egeria_client_connections")

from tests.zone_fakes import FakeEgeria, install  # noqa: E402
from tests.zone_fakes import element as _element  # noqa: E402

USER = "dana"
SURVEY = "PostgreSQLSurvey::survey-postgres-database"
G_OURS = "11111111-1111-1111-1111-111111111111"
G_OTHER = "22222222-2222-2222-2222-222222222222"      # another resource's action
G_DONE = "33333333-3333-3333-3333-333333333333"
URL = "/api/native-surveys/database/d/egeria-actions/{}/cancel"


def _sig(cls_path: str, name: str) -> inspect.Signature:
    module, _, cls = cls_path.rpartition(".")
    return inspect.signature(getattr(getattr(__import__(module, fromlist=[cls]), cls), name))


REAL_CANCEL = _sig("pyegeria.omvs.automated_curation.AutomatedCuration", "cancel_engine_action")
REAL_READ = _sig("pyegeria.omvs.metadata_expert.MetadataExpert", "get_metadata_element_by_guid")


def test_the_real_signature_is_what_the_fake_is_bound_to():
    assert list(REAL_CANCEL.parameters) == ["self", "engine_action_guid"]
    assert REAL_CANCEL.return_annotation in (None, "None")


class Egeria:
    """Egeria's engine actions, behind the two pyegeria classes the cancel path uses."""

    def __init__(self):
        self.status = {G_OURS: "IN_PROGRESS", G_OTHER: "IN_PROGRESS", G_DONE: "COMPLETED"}
        self.cancel_calls: list[tuple] = []         # (guid, user, token)
        self.reads: list[str] = []
        self.cancel_error: Exception | None = None
        self.ignore_cancel = False                  # Egeria accepts the call and the action keeps going

    def classes(self):
        eg = self

        class _Base:
            def __init__(self, view_server, platform_url, user_id, user_pwd=None, *a, **k):
                self.user, self.token = user_id, None

            def set_bearer_token(self, token):
                self.token = token

        class AutomatedCuration(_Base):
            def cancel_engine_action(self, *a, **k):
                REAL_CANCEL.bind(self, *a, **k)
                guid = (a or [k.get("engine_action_guid")])[0]
                eg.cancel_calls.append((guid, self.user, self.token))
                if eg.cancel_error:
                    raise eg.cancel_error
                if not eg.ignore_cancel:
                    eg.status[guid] = "CANCELLED"

        class MetadataExpert(_Base):
            def get_metadata_element_by_guid(self, *a, **k):
                REAL_READ.bind(self, *a, **k)
                guid = (a or [k.get("guid")])[0]
                eg.reads.append(guid)
                return {"elementProperties": {"propertyValueMap": {
                    "activityStatus": {"symbolicName": eg.status[guid]},
                    "completionMessage": {"primitiveValue": ""}}}}

        return AutomatedCuration, MetadataExpert


@pytest.fixture
def egeria(monkeypatch):
    eg = Egeria()
    cur, exp = eg.classes()
    monkeypatch.setattr("pyegeria.AutomatedCuration", cur)
    monkeypatch.setattr("pyegeria.MetadataExpert", exp)
    return eg


@pytest.fixture
def access(monkeypatch) -> FakeEgeria:
    return install(monkeypatch)                     # the access-check clients; no zone in use


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "c.db"))
    assert str(tmp_path) in r.database_url
    for slug in ("d", "other"):
        r.register_database(DatabaseEntity(slug=slug, display_name=slug, db_type="postgresql", host="h", port=5432,
                                           database_name=slug, db_user="u", db_password="pw",
                                           egeria_asset_guid=f"asset-{slug}"))
    for slug, guid, status in (("d", G_OURS, "IN_PROGRESS"), ("d", G_DONE, "COMPLETED"), ("other", G_OTHER, "IN_PROGRESS")):
        r.record_native_survey_submission("database", slug, SURVEY, ("2026-09-30T01:41:00" if guid == G_DONE else "2026-10-01T01:41:00"),
                                          engine_action_guid=guid, submitted_by=USER)
        r.record_native_survey_readback(guid, read_at="2026-10-11T12:00:00", status=status)
    return r


@pytest.fixture
def web(registry, monkeypatch):
    who = {"user_id": USER, "role": "user", "identity": True}
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    claims = lambda request: {"user_id": who["user_id"], "egeria_token": f"tok-{who['user_id']}", "role": who["role"]}  # noqa: E731
    monkeypatch.setattr("resource_explorer.auth.get_current_user", claims)
    from resource_explorer import auth as _auth

    real_identity = _auth.identity_from_claims
    monkeypatch.setattr("resource_explorer.auth.identity_from_claims",
                        lambda c: real_identity(c) if who["identity"] else None)
    from resource_explorer.web.app import app

    return TestClient(app), who


def _status(client, guid=G_OURS):
    rows = client.get("/api/native-surveys/database/d").json()["surveys"]
    return next(r for r in rows if r["qualified_name"] == SURVEY)["run"]


def test_success_cancels_as_the_caller_and_the_read_back_says_cancelled(web, egeria, access, registry):
    client, _ = web
    r = client.post(URL.format(G_OURS))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cancelled"] is True and body["egeria_status"] == "CANCELLED"
    # the write reached Egeria once, for this GUID, as THE PERSON (their token), never the daemon
    assert egeria.cancel_calls == [(G_OURS, USER, f"tok-{USER}")]
    # the read-back is the status refresh: it read the action and RE's row now carries what Egeria said
    assert egeria.reads == [G_OURS]
    row = next(x for x in registry.list_native_survey_runs("database", "d") if x["engine_action_guid"] == G_OURS)
    assert row["engine_action_status"] == "CANCELLED" and row["engine_action_read_at"] > "2026-10-11T12:00:01"
    run = next(s for s in body["surveys"] if s["qualified_name"] == SURVEY)["run"]
    assert run["state"] == "failed" and run["egeria_status"] == "CANCELLED" and run["message"] == "cancelled in Egeria"
    assert body["access_basis"] == "no_zones"
    # an activity entry was written (rule 16)
    with registry._conn() as conn:
        acts = [dict(x) for x in conn.execute("SELECT summary, status FROM activity_log").fetchall()]
    assert any(f"Cancelled Egeria action {G_OURS}" in a["summary"] and a["status"] == "ok" for a in acts), acts


def test_a_cancel_Egeria_accepts_but_does_not_report_is_not_called_cancelled(web, egeria, access):
    client, _ = web
    egeria.ignore_cancel = True
    body = client.post(URL.format(G_OURS)).json()
    assert body["cancelled"] is False and body["egeria_status"] == "IN_PROGRESS"


def test_anonymous_gets_401_and_nothing_is_sent(web, egeria, access):
    client, who = web
    who["identity"] = False
    r = client.post(URL.format(G_OURS))
    assert r.status_code == 401
    assert egeria.cancel_calls == [] and egeria.reads == []


def test_a_guid_that_is_not_this_resources_is_refused_before_egeria(web, egeria, access):
    client, _ = web
    for guid in (G_OTHER, "99999999-9999-9999-9999-999999999999"):
        r = client.post(URL.format(guid))
        assert r.status_code == 404, r.text
        assert "not one of the Egeria actions RE started" in r.json()["detail"]
    assert egeria.cancel_calls == [] and egeria.reads == []


def test_an_access_refusal_gives_the_word_and_sends_nothing(web, egeria, access):
    client, _ = web
    access.elements[G_OURS] = _element(G_OURS, zones=["sales-zone"])
    access.controls["sales-zone"] = {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}
    r = client.post(URL.format(G_OURS))
    assert r.status_code == 403
    assert r.json()["detail"].startswith(f"zone sales-zone does not grant {USER} ")
    assert egeria.cancel_calls == []
    # the operations Egeria checks for a cancel: read the element, then update its properties
    from resource_explorer.workflows import curate as wc
    assert ("element", G_OURS) in access.calls


def test_an_egeria_error_is_a_502_with_the_reason_and_the_row_still_says_running(web, egeria, access):
    client, _ = web
    egeria.cancel_error = RuntimeError("engine host unreachable")
    r = client.post(URL.format(G_OURS))
    assert r.status_code == 502 and "engine host unreachable" in r.json()["detail"]
    assert _status(client)["egeria_status"] == "IN_PROGRESS"          # nothing was guessed onto the row


def test_egeria_security_refusal_is_a_403_in_egerias_words(web, egeria, access):
    client, _ = web
    egeria.cancel_error = RuntimeError("OPEN-METADATA-SECURITY-403-002 user dana is not authorized to update")
    r = client.post(URL.format(G_OURS))
    assert r.status_code == 403 and "OPEN-METADATA-SECURITY-403" in r.json()["detail"]


def test_a_finished_action_cannot_be_cancelled(web, egeria, access):
    client, _ = web
    r = client.post(URL.format(G_DONE))
    assert r.status_code == 409 and "Egeria last said COMPLETED" in r.json()["detail"]
    assert egeria.cancel_calls == []
    # and a second press after a success is refused the same way
    assert client.post(URL.format(G_OURS)).status_code == 200
    assert client.post(URL.format(G_OURS)).status_code == 409
    assert len(egeria.cancel_calls) == 1
