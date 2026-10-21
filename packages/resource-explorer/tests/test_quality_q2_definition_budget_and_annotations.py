"""Quality slice Q2 (DESIGN-QUALITY-AT-SCALE-AND-TESTGEN.md 2.2, 2.6, 3 and the owner's 5 minutes per table), unit level:

- the DatabaseQualitySurvey definition: its three steps, their links, the reconciler's view of them, the generator;
- one QualityAnnotation per evaluated check, with Egeria's type and properties (QualityAnnotationProperties.java:
  qualityDimension, qualityDescription, qualityScore) and the ODCS dimension words;
- zero accepted checks ends survey-invalid with a sentence, never an empty completed report;
- "N of M annotations in Egeria" from what landed, including zero landed;
- the 5-minute per-table budget, on a fake clock that never sleeps: incomplete, no proposals, never zeros.

The Egeria boundary is faked only with `create_autospec(<real class>, spec_set=True)`, so every call binds the real
pyegeria signature. The route-level end to end is in test_quality_q2_survey_press_e2e.py.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from resource_explorer.surveyors.database.quality import run_checks
from resource_explorer.surveyors.database.quality.catalogue import (
    ODCS_DIMENSIONS,
    SLICE_1_TEST_TYPES,
    egeria_dimension,
    load_catalogue,
)
from resource_explorer.surveyors.database.quality.propose import run_propose
from resource_explorer.surveyors.database.quality.run_checks import (
    ANNOTATION_TYPE_NAME,
    NO_ACCEPTED_CHECKS,
    build_quality_annotations,
    run_quality_checks,
)
from resource_explorer.surveyors.database.quality.value_profile import (
    ProfileBounds,
    incomplete_reason,
    run_value_profile,
)
from tests.egeria_annotation_beans import ACCEPTED_FIELDS
from tests.test_value_profile_quality_checks import (  # noqa: F401 - fixtures and helpers reused
    BOUNDS,
    PROFILE,
    PROFILED_AT,
    SLUG,
    FakeConn,
    _accept,
    _by_key,
    _connect,
    _orders_measure,
    _profile,
    _propose,
    _rows,
    entity,
    registry,
)

PKG = Path(__file__).resolve().parent.parent
DEFS = PKG / "docs" / "dr-egeria" / "survey-definitions-database"
QUALITY = "DatabaseQualitySurvey"
STEPS = ["postgres_value_profile", "propose_quality_checks", "run_quality_checks"]


# ── the definition: three steps, authored, reconciled ───────────────────────────────────────────────────────

def test_the_definition_has_the_three_steps_in_order_and_the_reconciler_agrees():
    from resource_explorer import engine_host as eh
    from resource_explorer.surveyors import survey_definition_reconciler as rec
    from resource_explorer.surveyors.survey_definition_docs import documented_definitions

    doc = documented_definitions()[QUALITY]
    assert doc.resource_type == "database" and doc.survey_kind == "assessment"
    keys = [(doc.step_info.get(k, {}) or {}).get("re_analysis_step") for k in doc.steps]
    assert keys == STEPS
    # The links the document authors are exactly the chain First -> Next -> Next, each with guard Any.
    expected = rec.compute_expected_edges(QUALITY, STEPS)
    assert rec.expected_edges_from_document(QUALITY, doc) == expected and len(expected) == 2
    text = (DEFS / "database-survey-definition-quality.md").read_text()
    assert text.count("## Link First Process Step") == 1 and text.count("## Link Next Process Step") == 2
    # one executor per step, naming the engine and the request type of that step
    blocks = text.split("## Link Action to Action Executor")[1:]
    import re

    links = sorted((re.search(r"### Governance Action Type\n(\S+)", b).group(1),
                    re.search(r"### Governance Engine\n(\S+)", b).group(1),
                    re.search(r"### Request Type\n(\S+)", b).group(1)) for b in blocks)
    assert links == sorted((f"GovActionProcessStep::{QUALITY}::{k}", eh.ENGINE_QUALIFIED_NAME,
                            eh.request_type_for_step(k)) for k in STEPS)


def test_the_reconciler_finds_nothing_to_strip_on_the_authored_chain_and_flags_a_second_run_s_duplicates():
    """`reconcile_database_survey_definition_links.py` works from `compute_expected_edges` / the document: a live
    graph holding exactly the authored links is clean; the copy Dr.Egeria's non-idempotent Link Next Process Step
    makes on a second run is a duplicate to strip; a link that is not authored is stale."""
    from resource_explorer.surveyors import survey_definition_reconciler as rec

    qn = lambda k: f"GovActionProcessStep::{QUALITY}::{k}"          # noqa: E731
    live = [{"previousProcessStep": {"uniqueName": qn(a)}, "nextProcessStep": {"uniqueName": qn(b)},
             "nextProcessStepLinkGUID": f"l-{a}", "guard": "Any"} for a, b in zip(STEPS, STEPS[1:])]
    expected = rec.compute_expected_edges(QUALITY, STEPS)
    clean = rec.diff_links(live, expected, f"GovActionProcess::{QUALITY}")
    assert clean.to_remove == [] and clean.kept == 2
    again = rec.diff_links(live + [{**live[0], "nextProcessStepLinkGUID": "l-copy"}], expected, "p")
    assert [(r.reason, r.link_guid) for r in again.to_remove] == [("duplicate", "l-copy")]
    skipped = rec.diff_links(live + [{**live[0], "nextProcessStep": {"uniqueName": qn("postgres_value_profile")},
                                      "nextProcessStepLinkGUID": "l-wrong"}], expected, "p")
    assert [(r.reason, r.link_guid) for r in skipped.to_remove] == [("stale", "l-wrong")]


def test_the_committed_document_is_what_the_generator_writes():
    """`generate_database_survey_definition.py` run again changes nothing: the document, the CSV and the registry
    agree (the same hash-guarded generator the other three definitions come from)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_db_survey_def", PKG / "scripts" /
                                                  "generate_database_survey_definition.py")
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen              # the generator's dataclasses resolve their module by name
    try:
        spec.loader.exec_module(gen)
    finally:
        sys.modules.pop(spec.name, None)
    from resource_explorer.surveyors.dr_egeria_survey_publisher import generate_survey_definition_markdown

    quality = next(s for s in gen.SPECS if s.survey_group == QUALITY)
    assert quality.step_keys == STEPS and quality.output_filename == "database-survey-definition-quality.md"
    markdown = generate_survey_definition_markdown(
        survey_group=quality.survey_group, survey_display_name=quality.survey_display_name,
        technology_type=gen.TECHNOLOGY_TYPE, description=quality.description, steps=gen.build_steps(quality.step_keys),
        survey_kind=quality.survey_kind, answers_questions=[])
    assert (DEFS / quality.output_filename).read_text() == markdown
    batch = json.loads((DEFS / "_batch.json").read_text())
    assert quality.output_filename in batch["files"]
    assert batch["files"][-1] == "database-survey-definition-analysis.md"       # the canary's document stays last
    provenance = json.loads((DEFS / ".generated_database.json").read_text())
    import hashlib

    assert provenance[quality.output_filename] == hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def test_the_engine_host_declares_the_two_unheld_steps_and_holds_nothing():
    from resource_explorer import engine_host as eh

    text = (PKG / "docs" / "dr-egeria" / "engine-host" / "steps" / "database-steps.md").read_text()
    for key in STEPS:
        assert f"ResourceExplorerSurvey::{eh.request_type_for_step(key)}" in text, key
    assert eh.HELD_FROM_DECLARATION == {}
    assert all(eh.out_of_scope_reason(k) == "" for k in STEPS)


# ── QualityAnnotation: Egeria's type and properties ─────────────────────────────────────────────────────────

def _results(registry, entity, checks=None):
    _accept(registry, "sales.orders.order_id::Unique", "Unique")
    _accept(registry, "sales.orders.placed::Required", "Required")
    _accept(registry, "sales.orders.note::Missing_Pct", "Missing_Pct", baseline_ct=1000, baseline_value_ct=900,
            threshold_value=2, severity="warning")
    _accept(registry, "sales.orders.placed::Min_Date", "Min_Date", baseline_value="2020-01-01")
    _accept(registry, "sales.empty.d::Missing_Pct", "Missing_Pct", baseline_ct=10, baseline_value_ct=9,
            threshold_value=2, severity="warning")        # an empty table: measure undefined -> not established
    conn = FakeConn(checks=checks or {("sales", "orders"): {"record_ct": 1000, "measure": _orders_measure},
                                      ("sales", "empty"): {"record_ct": 0, "measure": lambda sql: None}})
    return run_quality_checks(entity, registry, _connect(conn), bounds=BOUNDS, surveyed_at="2026-10-20T13:00:00+00:00",
                              ran_as="surveyor")


def test_one_quality_annotation_per_evaluated_check_and_none_for_what_was_not_measured(registry, entity):
    _profile(registry, entity)
    out = _results(registry, entity)
    results = _by_key(registry, "database_quality_results")
    concluded = {k for k, r in results.items() if r["status"] in run_checks.CONCLUDED}
    assert concluded == {"sales.orders.order_id::Unique", "sales.orders.placed::Required",
                         "sales.orders.note::Missing_Pct"} and len(results) == 5
    # the undefined measure (empty table) and the check whose probe cannot run are result rows, never annotations
    assert results["sales.empty.d::Missing_Pct"]["status"] == "not_established"
    annotations = out["quality_annotations"]
    assert [a.item_key for a in annotations] == sorted(concluded)
    assert len({(a.check_name, a.item_key) for a in annotations}) == len(annotations)


def test_a_quality_annotation_is_egerias_quality_annotation_with_its_three_fields(registry, entity):
    from resource_explorer.surveyors.annotation_props import EGERIA_PROPERTIES_CLASSES, build_annotation_props
    from resource_explorer.surveyors.survey_report import AnnotationType

    _profile(registry, entity)
    annotations = {a.item_key: a for a in _results(registry, entity)["quality_annotations"]}
    assert EGERIA_PROPERTIES_CLASSES[AnnotationType.QUALITY_SCORE] == "QualityAnnotationProperties"

    unique = build_annotation_props(annotations["sales.orders.order_id::Unique"], "Annotation::q::1")
    assert unique["class"] == "QualityAnnotationProperties" and unique["annotationType"] == ANNOTATION_TYPE_NAME
    assert unique["analysisStep"] == "run_quality_checks"
    assert (unique["qualityDimension"], unique["qualityScore"]) == ("uniqueness", 100)       # it held
    assert "pass" in unique["qualityDescription"] and "Severity error" in unique["qualityDescription"]
    required = build_annotation_props(annotations["sales.orders.placed::Required"], "Annotation::q::2")
    assert (required["qualityDimension"], required["qualityScore"]) == ("completeness", 0)   # it did not
    assert required["qualityDescription"].startswith("fail")
    warn = build_annotation_props(annotations["sales.orders.note::Missing_Pct"], "Annotation::q::3")
    assert (warn["qualityDimension"], warn["qualityScore"]) == ("completeness", 0)
    assert "warning" in warn["qualityDescription"]

    # the check's own detail rides in additionalProperties (map<string,string>), the bean keeps it
    detail = unique["additionalProperties"]
    assert detail["testType"] == "Unique" and detail["status"] == "pass" and detail["ruleSource"] == "unpublished"
    assert detail["checkKey"] == "sales.orders.order_id::Unique" and detail["measure"] == "0.0"
    assert all(isinstance(v, str) for v in detail.values())
    # no field is one Egeria's QualityAnnotationProperties would drop without saying so
    for body in (unique, required, warn):
        assert set(body) <= ACCEPTED_FIELDS["QualityAnnotationProperties"], set(body) - ACCEPTED_FIELDS[
            "QualityAnnotationProperties"]
    assert {"qualityDimension", "qualityDescription", "qualityScore"} <= ACCEPTED_FIELDS[
        "QualityAnnotationProperties"]


def test_the_dimension_words_are_odcs_and_the_testgen_names_map_as_the_inventory_says():
    from resource_explorer.surveyors.database.quality.catalogue import EGERIA_DIMENSION

    assert egeria_dimension("Validity") == "conformity" and egeria_dimension("Recency") == "timeliness"
    assert egeria_dimension("Completeness") == "completeness" and egeria_dimension("Uniqueness") == "uniqueness"
    assert egeria_dimension("Timeliness") == "timeliness"
    assert egeria_dimension("Nonsense") == "" and egeria_dimension("") == ""
    assert EGERIA_DIMENSION == {"Validity": "conformity", "Recency": "timeliness"}
    # the seven RE ports, by the INVENTORY-TESTGEN-TEST-TYPES-MAPPED.md "Egeria dimension" column
    catalogue = load_catalogue()
    assert {t: egeria_dimension(catalogue[t].dimension).capitalize() for t in SLICE_1_TEST_TYPES} == {
        "Missing_Pct": "Completeness", "Required": "Completeness", "Required_No_Placeholder": "Completeness",
        "Row_Ct_Pct": "Completeness", "Unique": "Uniqueness", "Future_Date": "Timeliness", "Min_Date": "Conformity"}
    # and every word is one of Egeria's DataContractQualityDimension values (the Java enum, read from source)
    java = (Path(__file__).resolve().parents[4] / "egeria" / "open-metadata-implementation" / "frameworks" /
            "open-integration-framework" / "src" / "main" / "java" / "org" / "odpi" / "openmetadata" / "frameworks" /
            "integration" / "bitol" / "odcs" / "DataContractQualityDimension.java")
    if java.exists():
        import re

        assert set(re.findall(r'\(\s*"([a-z]+)"\s*,', java.read_text())) == set(ODCS_DIMENSIONS)
    else:
        assert ODCS_DIMENSIONS == {"accuracy", "completeness", "conformity", "consistency", "coverage",
                                   "timeliness", "uniqueness"}


def test_publishing_sends_the_real_create_annotation_signature_and_egerias_fields(registry, entity):
    """The fake binds `DataDiscovery.create_annotation`'s real signature (autospec, spec_set); what is sent is the
    body the bean would keep in full."""
    from pyegeria.omvs.data_discovery import DataDiscovery

    from resource_explorer.surveyors.annotation_props import publish_annotations

    _profile(registry, entity)
    annotations = _results(registry, entity)["quality_annotations"]
    discovery = create_autospec(DataDiscovery, spec_set=True, instance=True)
    discovery.create_annotation.side_effect = lambda body=None, **_: f"guid-{len(discovery.create_annotation.mock_calls)}"
    guids = publish_annotations(discovery, lambda name: "", annotations, "report-1", "Annotation::PostgreSQL::coco_ods::x")
    assert guids == ["guid-1", "guid-2", "guid-3"]
    sent = [c.kwargs["body"] for c in discovery.create_annotation.call_args_list]
    assert [b["properties"]["qualityDimension"] for b in sent] == ["completeness", "uniqueness", "completeness"] \
        or sorted(b["properties"]["qualityDimension"] for b in sent) == ["completeness", "completeness", "uniqueness"]
    for body in sent:
        assert body["class"] == "NewElementRequestBody" and body["parentGUID"] == "report-1"
        assert body["parentRelationshipTypeName"] == "ReportedAnnotation" and body["anchorGUID"] == "report-1"
        props = body["properties"]
        assert props["class"] == "QualityAnnotationProperties" and not set(props) - ACCEPTED_FIELDS[props["class"]]
        assert props["qualifiedName"].startswith("Annotation::PostgreSQL::coco_ods::x::quality_check::")
    real = inspect.signature(DataDiscovery.create_annotation)
    assert inspect.signature(discovery.create_annotation) == real.replace(parameters=list(real.parameters.values())[1:])


# ── zero accepted checks: survey-invalid with a sentence, never an empty completed report ───────────────────

def test_with_no_accepted_check_the_step_declines_with_the_sentence_and_runs_nothing(registry, entity):
    _profile(registry, entity)
    conn = FakeConn()
    out = run_quality_checks(entity, registry, _connect(conn), bounds=BOUNDS, surveyed_at="2026-10-20T13:00:00+00:00")
    assert out["skipped_by_design"] == NO_ACCEPTED_CHECKS and NO_ACCEPTED_CHECKS.startswith("no accepted checks")
    assert "quality_annotations" not in out and conn.statements == []
    assert registry.query_detail_rows("database_quality_results", SLUG) == []
    # a rejected check is not an accepted one
    registry.record_quality_verdict(SLUG, "sales.orders.order_id::Unique", "rejected", {})
    assert run_quality_checks(entity, registry, _connect(conn), bounds=BOUNDS)["skipped_by_design"]


def test_the_executor_ends_the_step_skipped_with_the_sentence_and_publishes_nothing(registry, entity, monkeypatch):
    """The step's output is not a result: no publish is attempted for it, and its entry says why."""
    from resource_explorer.surveyors.database import survey_definition_adapter as db
    from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutor

    _profile(registry, entity)
    published: list = []

    def publisher(entity_, outputs, surveyed_at, registry_):
        published.append(outputs)
        return "report"

    monkeypatch.setattr(db, "database_connection", None, raising=False)
    from resource_explorer.surveyors.database import connection

    monkeypatch.setattr(connection, "database_connection", lambda *a, **k: _connect(FakeConn())())
    ran = SurveyDefinitionExecutor(registry).run_synthetic_step(
        entity_type="database", slug=SLUG, re_analysis_step="run_quality_checks", executes_at="resource-explorer",
        engine_override="resource-explorer", publisher=publisher, db_user="u", db_pwd="p")
    [step] = [s for s in ran["steps"] if s["re_analysis_step"] == "run_quality_checks"]
    assert step["status"] == "skipped_by_design" and step["detail"] == NO_ACCEPTED_CHECKS
    assert published == []


# ── "N of M annotations in Egeria", from what landed ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("landed,word,published", [
    (3, "published to Egeria · 3 of 3 annotations in Egeria", True),
    (2, "publish failed · 2 of 3 annotations in Egeria", True),
    (0, "publish failed · 0 of 3 annotations in Egeria", False),
])
def test_the_run_says_n_of_m_from_what_landed_including_none(registry, entity, monkeypatch, landed, word, published):
    from resource_explorer.surveyors.database import survey_definition_adapter as db
    from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutor
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinition, SurveyStep

    _profile(registry, entity)
    _accept(registry, "sales.orders.order_id::Unique", "Unique")
    _accept(registry, "sales.orders.placed::Required", "Required")
    _accept(registry, "sales.orders.note::Missing_Pct", "Missing_Pct", baseline_ct=1000, baseline_value_ct=900,
            threshold_value=2, severity="warning")
    from resource_explorer.surveyors.database import connection

    monkeypatch.setattr(connection, "database_connection", lambda *a, **k: _connect(FakeConn(
        checks={("sales", "orders"): {"record_ct": 1000, "measure": _orders_measure}}))())
    monkeypatch.setattr(registry, "has_assigned_egeria_project", lambda *a, **k: True)

    def fake_publish(entity_, outputs, surveyed_at, registry_, publish_out=None):
        built = [a for o in outputs for a in (o.get("quality_annotations") or [])]
        assert len(built) == 3
        publish_out["quality"] = {"built": len(built), "landed": landed}
        return "report-guid-1"

    monkeypatch.setattr(db._ADAPTER, "publish", fake_publish)
    survey_def = SurveyDefinition(process_guid="p", display_name="Database Quality Survey",
                                  qualified_name=f"GovActionProcess::{QUALITY}", supported_technology_type=None,
                                  steps=[SurveyStep(guid="s", display_name="run", qualified_name="s::run",
                                                    executes_at="resource-explorer",
                                                    re_analysis_step="run_quality_checks")])
    from resource_explorer.surveyors import survey_definition_executor as ex

    monkeypatch.setattr(ex, "person_write_refusal", lambda *a, **k: "", raising=False)
    monkeypatch.setattr("resource_explorer.workflows.curate.person_write_refusal", lambda *a, **k: "")
    result = SurveyDefinitionExecutor(registry)._execute(
        entity_type="database", slug=SLUG, entity=entity, survey_def=survey_def, process_guid="p", process_qn="qn",
        publish="wait", engine_override="resource-explorer", runner_kwargs={"db_user": "u", "db_pwd": "p"})
    assert result["publish_state"] == word
    assert result["published"] is published
    if landed < 3:
        assert any("did not all reach Egeria" in e for e in result["errors"])
    else:
        assert not result["errors"]


# ── the 5-minute per-table budget (owner, 2026-10-21): incomplete, no proposals, never zeros ─────────────────

class _Clock:
    """A fake monotonic clock: it moves only when the fake connection says a statement took that long."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _SlowConn(FakeConn):
    """Each profile statement on the wide table takes `seconds` on the clock, unless Postgres would have cancelled it
    first: it honours the `SET LOCAL statement_timeout` it was given, so a chunk that needs longer than that timeout
    advances the clock by the timeout and raises, as the real server does."""

    def __init__(self, clock, *, seconds, **kw):
        super().__init__(**kw)
        self.clock, self.seconds = clock, seconds
        self.chunks = 0
        self.timeouts: list[int] = []
        self._timeout = None

    def execute_query(self, sql, params=()):
        if sql.startswith("SET LOCAL statement_timeout"):
            self._timeout = int(sql.rsplit("=", 1)[1]) // 1000
            self.timeouts.append(self._timeout)
        return super().execute_query(sql, params)

    def execute_query_isolated(self, sql, params=()):
        if '"sales"."wide"' in sql and "FROM pg_class" not in sql:
            self.chunks += 1
            if self._timeout is not None and self.seconds > self._timeout:
                self.clock.now += self._timeout
                raise TimeoutError("canceling statement due to statement timeout")
            self.clock.now += self.seconds
            return [{"record_ct": 1000, **{alias: 1 for alias in __import__("re").findall(r"AS (c\d+__[a-z_]+)", sql)}}]
        return super().execute_query_isolated(sql, params)


def _wide_registry(registry, columns=450):
    """`sales.wide`: 450 integer columns, so the profile reads it as three chunks of at most 200."""
    tables = registry.query_detail_rows("database_tables", SLUG)
    cols = registry.query_detail_rows("database_columns", SLUG)
    tables.append({"schema_name": "sales", "table_name": "wide", "table_type": "BASE TABLE", "row_count": 1000})
    cols += [{"schema_name": "sales", "table_name": "wide", "column_name": f"c{i}", "ordinal_position": i,
              "data_type": "integer", "base_type": "integer"} for i in range(columns)]
    registry.write_detail_rows("database_tables", SLUG, "2026-10-20T09:30:00+00:00", rows=tables)
    registry.write_detail_rows("database_columns", SLUG, "2026-10-20T09:30:00+00:00", rows=cols)


def _wide_profile(registry, entity, conn, clock, bounds):
    return run_value_profile(entity, registry, _connect(conn), bounds=bounds, surveyed_at=PROFILED_AT,
                             ran_as="surveyor", clock=clock)


def test_a_table_that_runs_past_five_minutes_is_incomplete_with_every_count_not_measured(registry, entity):
    _wide_registry(registry)
    clock = _Clock()
    conn = _SlowConn(clock, seconds=130, profile={k: v for k, v in PROFILE.items()}, reltuples={("sales", "wide"): 1000})
    bounds = ProfileBounds(max_table_rows=5_000_000, statement_timeout_seconds=600, table_budget_seconds=300)
    out = _wide_profile(registry, entity, conn, clock, bounds)
    wide = [r for r in registry.query_detail_rows("database_value_profiles", SLUG) if r["table_name"] == "wide"]
    # Chunks 1 and 2 took 260 s and finished; the third started with 40 s left, ran into it and was cancelled: the
    # whole table is incomplete, including the 400 columns whose counts had been read.
    assert len(wide) == 450
    assert {r["state"] for r in wide} == {"not_measured"}
    assert {r["reason"] for r in wide} == {"profile incomplete · exceeded 5 min · counts not measured"}
    assert all(r[m] is None for r in wide for m in ("record_ct", "value_ct", "distinct_value_ct", "null_value_ct"))
    assert incomplete_reason(300) == "profile incomplete · exceeded 5 min · counts not measured"
    [outcome] = [o for o in out["value_profile"]["tables_not_profiled"] if o["table"] == "sales.wide"]
    assert outcome["state"] == "not_measured" and "exceeded 5 min" in outcome["reason"]
    assert out["value_profile"]["bounds"]["table_budget_seconds"] == 300
    # the other tables are unaffected: the budget is per table
    orders = _rows(registry, "database_value_profiles")["sales", "orders", "order_id"]
    assert orders["state"] == "measured" and orders["record_ct"] == 1000


def test_the_budget_is_the_total_per_table_not_a_timeout_on_each_chunk(registry, entity):
    """Three chunks at 130 s each: each is far inside the 600 s statement timeout, yet the table exceeds its 300 s
    budget. Every chunk's statement timeout is capped at what is left of the table's budget (300, 170, 40 s)."""
    _wide_registry(registry)
    clock = _Clock()
    conn = _SlowConn(clock, seconds=130, profile=PROFILE, reltuples={("sales", "wide"): 1000})
    bounds = ProfileBounds(max_table_rows=5_000_000, statement_timeout_seconds=600, table_budget_seconds=300)
    _wide_profile(registry, entity, conn, clock, bounds)
    wide_timeouts = conn.timeouts[-3:]
    assert conn.chunks == 3 and wide_timeouts == [300, 170, 40]
    wide = [r for r in registry.query_detail_rows("database_value_profiles", SLUG) if r["table_name"] == "wide"]
    assert {r["state"] for r in wide} == {"not_measured"}
    assert {r["reason"] for r in wide} == {"profile incomplete · exceeded 5 min · counts not measured"}


def test_a_table_whose_budget_is_spent_between_chunks_starts_no_more_and_is_incomplete(registry, entity):
    _wide_registry(registry)
    clock = _Clock()
    conn = _SlowConn(clock, seconds=150, profile=PROFILE, reltuples={("sales", "wide"): 1000})
    bounds = ProfileBounds(max_table_rows=5_000_000, statement_timeout_seconds=600, table_budget_seconds=300)
    _wide_profile(registry, entity, conn, clock, bounds)
    wide = [r for r in registry.query_detail_rows("database_value_profiles", SLUG) if r["table_name"] == "wide"]
    assert {r["reason"] for r in wide} == {"profile incomplete · exceeded 5 min · counts not measured"}
    assert conn.chunks == 2                        # exactly 300 s were spent: the third chunk was never started


def test_an_ordinary_statement_timeout_inside_the_budget_is_still_a_plain_not_measured(registry, entity):
    """A chunk cancelled by the 60 s statement timeout with budget to spare is the slice-1 outcome, not 'incomplete':
    the two bounds say different things."""
    _wide_registry(registry)
    clock = _Clock()
    conn = _SlowConn(clock, seconds=100, profile=PROFILE, reltuples={("sales", "wide"): 1000})
    bounds = ProfileBounds(max_table_rows=5_000_000, statement_timeout_seconds=60, table_budget_seconds=300)
    _wide_profile(registry, entity, conn, clock, bounds)
    wide = [r for r in registry.query_detail_rows("database_value_profiles", SLUG) if r["table_name"] == "wide"]
    assert {r["state"] for r in wide} == {"not_measured"}
    assert all("statement timeout" in r["reason"] and "exceeded" not in r["reason"] for r in wide)


def test_a_table_that_finishes_inside_its_budget_is_measured(registry, entity):
    _wide_registry(registry)
    clock = _Clock()
    conn = _SlowConn(clock, seconds=60, profile=PROFILE, reltuples={("sales", "wide"): 1000})
    bounds = ProfileBounds(max_table_rows=5_000_000, statement_timeout_seconds=60, table_budget_seconds=300)
    _wide_profile(registry, entity, conn, clock, bounds)
    wide = [r for r in registry.query_detail_rows("database_value_profiles", SLUG) if r["table_name"] == "wide"]
    assert len(wide) == 450 and {r["state"] for r in wide} == {"measured"} and wide[0]["record_ct"] == 1000


def test_an_incomplete_table_gets_no_proposals_and_no_zero_ever(registry, entity):
    _wide_registry(registry)
    clock = _Clock()
    conn = _SlowConn(clock, seconds=200, profile=PROFILE, reltuples={("sales", "wide"): 1000})
    bounds = ProfileBounds(max_table_rows=5_000_000, statement_timeout_seconds=600, table_budget_seconds=300)
    _wide_profile(registry, entity, conn, clock, bounds)
    _propose(registry)
    rows = [r for r in registry.query_detail_rows("database_quality_proposals", SLUG) if r["table_name"] == "wide"]
    assert rows, "the table is accounted for"
    assert {r["state"] for r in rows} == {"not_established"}          # said, not proposed: never a proposal
    assert not any(r["state"] == "proposed" for r in rows)
    assert all("not profiled (not_measured" in r["reason"] and "exceeded 5 min" in r["reason"] for r in rows)
    # and the rest of the database still proposes
    assert any(r["state"] == "proposed" for r in registry.query_detail_rows("database_quality_proposals", SLUG))


def test_the_budget_is_a_setting_with_the_owner_s_five_minutes():
    from resource_explorer.config import ValueProfileSettings

    assert ValueProfileSettings().table_budget_seconds == 300
    assert ProfileBounds(1, 1).table_budget_seconds == 300


def test_profile_never_sleeps_on_its_own_clock(registry, entity, monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda *_: pytest.fail("the profile must never sleep"))
    _profile(registry, entity)
