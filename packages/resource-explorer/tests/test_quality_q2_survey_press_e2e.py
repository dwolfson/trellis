"""Quality slice Q2, end to end through the real route: the Survey press on DatabaseQualitySurvey.

POST /api/survey-definitions/database/{slug}/run enqueues a `survey_definition_run`; the queue's worker claims it and
runs the committed definition's three steps through the real executor, the real database adapter runners, the real
value profile, propose and run-checks code, the real registry (temp SQLite) and the real database survey publisher.

Faked only at the boundaries:
- the surveyed Postgres: `FakeConn` (the value-profile tests' canned answers);
- Egeria: every pyegeria client RE builds is `create_autospec(<real class>, spec_set=True)` behind
  `FakeEgeria` (test_engine_host_e4), whose annotation create keeps only the fields Egeria 6.2's bean has;
- reading the definition: `SurveyDefinitionReader.find_process_guid_by_name` / `.fetch` (autospec) answer from the
  COMMITTED document, which is what Egeria holds once the coordinator has applied it.

The first press has no accepted check and ends with the "no accepted checks" sentence and nothing in Egeria; the
second, after three proposals are accepted, leaves three QualityAnnotations under one SurveyReport that the test reads
back by GUID.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.surveyors.database.quality.run_checks import NO_ACCEPTED_CHECKS
from tests.egeria_annotation_beans import ACCEPTED_FIELDS
from tests.test_engine_host_e4 import _run_queue_once, egeria  # noqa: F401 - fixtures reused
from tests.test_value_profile_quality_checks import (  # noqa: F401 - fixtures and helpers reused
    PROFILE,
    SLUG,
    FakeConn,
    _connect,
    _orders_measure,
    registry,
)

QUALITY = "DatabaseQualitySurvey"
PRESSER = "peterprofile"


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    registry.update_database_credentials(SLUG, "surveyor", "stored-pass-0123456789")
    monkeypatch.setattr(type(registry), "has_assigned_egeria_project", lambda self, *a, **k: True)
    # signed in: the press publishes as the person who pressed it
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setattr("resource_explorer.auth.get_current_user",
                        lambda request: {"user_id": PRESSER, "egeria_token": "t"})
    from resource_explorer.web.app import app

    return TestClient(app)


@pytest.fixture
def world(registry, egeria, monkeypatch):
    """The Postgres and definition boundaries, and a connection that records every statement."""
    from resource_explorer.surveyors.database import connection
    from resource_explorer.surveyors.survey_definition_docs import documented_definitions
    from resource_explorer.surveyors.survey_definition_reader import (
        StepLink,
        SurveyDefinition,
        SurveyDefinitionReader,
        SurveyStep,
    )

    conn = FakeConn(profile=PROFILE, checks={("sales", "orders"): {"record_ct": 1000, "measure": _orders_measure}})
    monkeypatch.setattr(connection, "database_connection", lambda *a, **k: _connect(conn)())

    doc = documented_definitions()[QUALITY]
    steps = [SurveyStep(guid=f"guid-{k}", display_name=doc.step_info[k]["display_name"],
                        qualified_name=doc.step_info[k]["qualified_name"], executes_at=doc.step_info[k]["executes_at"],
                        re_analysis_step=doc.step_info[k]["re_analysis_step"],
                        supported_technology_type=doc.technology_type) for k in doc.steps]
    definition = SurveyDefinition(
        process_guid="guid-process", display_name=doc.display_name, qualified_name=f"GovActionProcess::{QUALITY}",
        supported_technology_type=doc.technology_type, steps=steps,
        links=[StepLink(f"guid-{a}", f"guid-{b}", guard) for a, b, guard in doc.links], survey_kind=doc.survey_kind)
    with patch.object(SurveyDefinitionReader, "find_process_guid_by_name", autospec=True,
                      side_effect=lambda self, name, *a, **k: "guid-process" if name == QUALITY else "") as find, \
            patch.object(SurveyDefinitionReader, "fetch", autospec=True,
                         side_effect=lambda self, guid, *a, **k: definition) as fetch:
        yield conn
    assert find.called and fetch.called


def _press(client, registry, *, as_engine: str = "resource-explorer") -> dict:
    """The Survey press: the real route, then the queue worker runs what the route queued. Returns the activity
    entry's stored detail, which is what the run modal renders."""
    resp = client.post(f"/api/survey-definitions/database/{SLUG}/run",
                       json={"survey_definition_ref": QUALITY, "engine": as_engine})
    assert resp.status_code == 200, resp.text
    queued = resp.json()
    assert queued["status"] == "started" and queued["run_id"] and queued["activity_id"]
    row = registry.list_runs(state="queued")[0]
    assert row["kind"] == "survey_definition_run" and json.loads(row["target"])["slug"] == SLUG
    assert _run_queue_once(registry) is not None
    entry = registry.get_activity(queued["activity_id"])
    return {"status": entry["status"], "summary": entry["summary"], **json.loads(entry["detail"])}


def _steps(detail: dict) -> dict:
    return {s["re_analysis_step"]: s for s in detail["steps"]}


def _accept_three_proposals(registry) -> list[str]:
    """What a steward does in Curate: accept three of the proposals the second step made."""
    proposals = {r["check_key"]: r for r in registry.query_detail_rows("database_quality_proposals", SLUG)}
    keys = ["sales.orders.order_id::Unique", "sales.orders.placed::Required", "sales.orders.note::Missing_Pct"]
    for key in keys:
        assert proposals[key]["state"] == "proposed", key
        registry.record_quality_verdict(SLUG, key, "accepted", proposals[key]["params_json"],
                                        proposal_id=proposals[key]["id"], decided_by="steward")
    return keys


def test_the_press_with_no_accepted_check_ends_on_the_sentence_and_writes_nothing_to_egeria(
        client, registry, egeria, world):
    detail = _press(client, registry)
    steps = _steps(detail)
    assert steps["postgres_value_profile"]["status"] == "ok" and steps["propose_quality_checks"]["status"] == "ok"
    # the third step is declined with the design's sentence: not run, not "ran and found nothing"
    assert steps["run_quality_checks"]["status"] == "skipped_by_design"
    assert steps["run_quality_checks"]["detail"] == NO_ACCEPTED_CHECKS
    assert NO_ACCEPTED_CHECKS.startswith("no accepted checks")
    # no empty report: nothing was published, and the run says so in words, not "published"
    assert egeria.reports() == [] and detail["egeria_report_guid"] == ""
    assert detail["publish_state"].startswith("nothing to publish · the quality steps built no QualityAnnotation")
    assert not any(s.startswith("SELECT COUNT(*) AS record_ct, ") for s in world.statements)   # no check was run
    assert registry.query_detail_rows("database_quality_results", SLUG) == []
    # the profile and the proposals did land in the registry: the press did the first two steps
    assert registry.query_detail_rows("database_value_profiles", SLUG)
    assert any(r["state"] == "proposed" for r in registry.query_detail_rows("database_quality_proposals", SLUG))


def test_accept_three_proposals_press_again_and_read_three_quality_annotations_back_by_guid(
        client, registry, egeria, world):
    first = _press(client, registry)
    assert _steps(first)["run_quality_checks"]["status"] == "skipped_by_design"
    keys = _accept_three_proposals(registry)

    detail = _press(client, registry)
    assert _steps(detail)["run_quality_checks"]["status"] == "ok"
    [(report_guid, report_body)] = egeria.reports()
    assert detail["egeria_report_guid"] == report_guid and detail["published"] is True
    # the words come from what landed: "N of M annotations in Egeria"
    assert detail["publish_state"] == "published to Egeria · 3 of 3 annotations in Egeria"

    # read the three annotations back by GUID, as the live gate does
    annotation_guids = [r["end2"] for r in egeria.relationships
                        if r["end1"] == report_guid and r["type"] == "ReportedAnnotation"]
    assert len(annotation_guids) == 3 and egeria.annotations_under(report_guid) == 3
    stored = {egeria.elements[g]["body"]["properties"]["additionalProperties"]["checkKey"]:
              egeria.elements[g]["body"] for g in annotation_guids}
    assert set(stored) == set(keys)
    for key, body in stored.items():
        assert body["anchorGUID"] == report_guid and body["isOwnAnchor"] is False
        props = body["properties"]
        assert props["class"] == "QualityAnnotationProperties"
        assert props["analysisStep"] == "run_quality_checks" and props["annotationType"] == "Database Quality Check"
        assert not set(props) - ACCEPTED_FIELDS["QualityAnnotationProperties"]
    unique = stored["sales.orders.order_id::Unique"]["properties"]
    assert (unique["qualityDimension"], unique["qualityScore"]) == ("uniqueness", 100)
    required = stored["sales.orders.placed::Required"]["properties"]
    assert (required["qualityDimension"], required["qualityScore"]) == ("completeness", 0)
    missing = stored["sales.orders.note::Missing_Pct"]["properties"]
    assert (missing["qualityDimension"], missing["qualityScore"]) == ("completeness", 0)
    assert egeria.dropped == [], "Egeria's bean would have dropped fields RE sent"
    # only the three evaluated checks are annotations: the report is the checks', not a re-statement of the schema
    assert {egeria.elements[g]["body"]["properties"]["class"] for g in annotation_guids} == {
        "QualityAnnotationProperties"}
    # Identity (owner rule "run as the initiating user"): a queued press commits as RE's queue identity with the
    # person who pressed it recorded as the requester (no token survives a queue), never as the engine host, which is
    # for work Egeria dispatched.
    from resource_explorer.egeria_clients import DaemonReason

    writers = [who for cls, method, who in egeria.calls if method == "create_annotation"]
    assert len(writers) == 3
    assert all(w.reason == DaemonReason.RUN_QUEUE.value and w.requested_by == PRESSER for w in writers), writers
    # and the results the annotations summarise are the registry's result rows
    results = {r["check_key"]: r["status"] for r in registry.query_detail_rows("database_quality_results", SLUG)}
    assert results == {"sales.orders.order_id::Unique": "pass", "sales.orders.placed::Required": "fail",
                       "sales.orders.note::Missing_Pct": "warning"}


def test_the_press_says_two_of_three_when_egeria_keeps_only_two(client, registry, egeria, world):
    _press(client, registry)
    _accept_three_proposals(registry)
    egeria.fail_nth["create_annotation"] = (2, RuntimeError("Egeria refused the second annotation"))

    detail = _press(client, registry)
    [(report_guid, _)] = egeria.reports()
    assert egeria.annotations_under(report_guid) == 2
    # never "published" for what did not land
    assert detail["publish_state"] == "publish failed · 2 of 3 annotations in Egeria"
    assert any("did not all reach Egeria" in e for e in detail["errors"])
    assert detail["status"] == "error"
