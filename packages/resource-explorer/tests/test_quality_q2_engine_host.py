"""Quality slice Q2, the engine host: the two steps that were held are now dispatched by Egeria.

The design's required test (DESIGN-QUALITY-AT-SCALE-AND-TESTGEN.md section 3, Q2): an engine action for
`run_quality_checks` on a database with ZERO accepted checks completes `survey-invalid` with a sentence naming why,
and creates no SurveyReport -- never an empty `survey-completed` report. With accepted checks it completes
`survey-completed` with one QualityAnnotation per evaluated check, in a report linked to the action, written as the
engine host for the requester (the identity of work Egeria dispatched).

Only the pyegeria boundary (test_engine_host_e4's `FakeEgeria`: autospec clients, strict annotation beans) and the
surveyed Postgres are faked; the sweep, the queue, the synthetic-step executor, the capability gate, the publisher and
the real run-checks code are real.
"""
from __future__ import annotations

import json

from tests.test_engine_host_case3 import (  # noqa: F401 - fixtures and helpers reused
    PASSWORD,
    _process_action,
    _with_credential,
    egeria,
    no_connection,
    reg,
)
from tests.test_engine_host_e4 import _daemon_user, _rows, _run_queue_once, _sweep
from tests.test_value_profile_quality_checks import FakeConn, _connect

QUALITY = "GovActionProcess::DatabaseQualitySurvey"
SLUG = "coco_pharma"
NO_ACCEPTED = "no accepted checks: accept proposals in Curate first; nothing was run"


def test_run_quality_checks_with_no_accepted_check_completes_survey_invalid_with_a_sentence(reg, egeria, no_connection):
    _with_credential(reg)
    _process_action(egeria, "ea-run", "run_quality_checks", definition=QUALITY, next_guards=())
    assert _sweep(reg).claimed == ["ea-run"]                   # unheld: claimed, not refused at the claim
    assert _run_queue_once(reg) is not None

    action = egeria.actions["ea-run"]
    done = action["completion"]
    assert done["status"] == "INVALID" and done["guards"] == ["survey-invalid", "Any"], done
    assert NO_ACCEPTED in done["message"] and done["message"].startswith("run_quality_checks did not run on coco_pharma")
    # never an empty completed report: no SurveyReport exists, no target carries one
    assert egeria.reports() == [] and done["targets"] == []
    [row] = _rows(reg)
    assert row["target"]["outcome"]["guard"] == "survey-invalid" and not row["target"]["outcome"]["report_guid"]
    assert "no stored schema inventory" not in done["message"]       # the sentence is this step's own, not db_derived's
    assert PASSWORD not in json.dumps(egeria.actions)


def test_run_quality_checks_with_accepted_checks_completes_survey_completed_with_one_annotation_per_check(
        reg, egeria, monkeypatch):
    from resource_explorer.surveyors.database import connection

    _with_credential(reg)
    params = {"baseline_ct": None, "baseline_value_ct": None, "baseline_value": None, "threshold_value": 0,
              "severity": "error", "profile_surveyed_at": "2026-10-14T09:00:00"}
    reg.record_quality_verdict(SLUG, "public.orders.order_id::Unique", "accepted", params, decided_by="steward")
    reg.record_quality_verdict(SLUG, "public.orders.customer_id::Required", "accepted", params, decided_by="steward")

    def measure(sql):
        return 0 if 'COUNT(DISTINCT "order_id")' in sql else 7          # Unique holds, Required fails (7 missing)

    conn = FakeConn(checks={("public", "orders"): {"record_ct": 40000, "measure": measure}})
    monkeypatch.setattr(connection, "database_connection", lambda *a, **k: _connect(conn)())
    _process_action(egeria, "ea-run", "run_quality_checks", definition=QUALITY, next_guards=())
    assert _sweep(reg).claimed == ["ea-run"]
    assert _run_queue_once(reg) is not None

    done = egeria.actions["ea-run"]["completion"]
    [(report_guid, report)] = egeria.reports()
    assert done["status"] == "ACTIONED" and done["guards"] == ["survey-completed", "Any"], done
    assert done["targets"] == [{"actionTargetName": "surveyReport", "actionTargetGUID": report_guid}]
    assert egeria.annotations_under(report_guid) == 2
    bodies = [e["body"]["properties"] for e in egeria.elements.values() if e["type"] == "Annotation"]
    assert sorted((b["qualityDimension"], b["qualityScore"]) for b in bodies) == [("completeness", 0),
                                                                                  ("uniqueness", 100)]
    assert {b["class"] for b in bodies} == {"QualityAnnotationProperties"} and egeria.dropped == []
    # work Egeria dispatched is the engine host's, not the queue's and not a person's session
    from resource_explorer.egeria_clients import DaemonReason

    writers = {(w.reason, w.client_user) for cls, method, w in egeria.calls if method == "create_annotation"}
    assert writers == {(DaemonReason.ENGINE_HOST.value, _daemon_user())}
    [row] = _rows(reg)
    assert row["target"]["outcome"]["annotation_count"] == 2
    assert row["target"]["outcome"]["annotations_in_egeria"] == 2
