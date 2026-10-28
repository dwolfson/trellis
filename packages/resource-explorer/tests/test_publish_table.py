"""Curate's publish table (declared extensibility slice 1, PR 2; DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-
CONFIDENCE.md §5 and the gate of §7).

The gate, by use, with no RE code written for the analysis: a step declared with two measures and no annotation
type appears as two rows reading "generic measure · no native type declared"; one is chosen Publish, rides in RE's
survey report, and reads back by name; adding the annotation type to the declaration changes the row's "writes as"
to the native type, and the next publish writes it so. Never reaches Egeria and never the shared registry: every
registry is a tmp SQLite file, and Egeria is a fake at the pyegeria client boundary (the surveyor's own publish and
read-back code is real).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from trellis_analytics.declaration import Declaration

from resource_explorer import publish_table as pt
from resource_explorer.facts import Fact
from resource_explorer.registry import DatabaseEntity, ProjectRegistry

SLUG = "coco_pharma"
SURVEYED_AT = "2026-10-27T09:00:00"
ABSENCE = {"not_measured": "Example step x has not run on this database.",
           "not_permitted": "The credential cannot read the tables example step x samples.",
           "not_applicable": "This database has no tables for example step x.",
           "measured_nothing": "Example step x ran and found no buckets."}


def _declaration(annotation: dict | None = None, kind: str = "distribution") -> Declaration:
    second = {"name": "rows_sampled", "unit": "rows", "as_of": "asOf", "value_field": "rows_sampled"}
    if annotation:
        second["annotation"] = annotation
    return Declaration.model_validate({
        "result_kind": kind,
        "measures": [{"name": "buckets", "unit": "buckets", "as_of": "asOf", "value_field": "buckets[]"}, second],
        "absence": ABSENCE,
        "extents": [{"name": "top", "fields": ["bucket", "count"], "rows": 10, "order": "by count, largest first",
                     "truncation": "{shown} of {total} buckets shown", "token_cost": 120,
                     "citation": "{analysis} · {scope} · as of {as_of}"}],
        "confidence": {"form": "estimated", "basis": "sample_ratio"},
        "answers": ["q-example-x"], "scope": "resource"})


def _entry(declaration, id_="example_step_x", name="Example Step X"):
    return SimpleNamespace(id=id_, name=name, declaration=declaration)


VALUE = {"buckets": [{"bucket": "a", "count": 3}, {"bucket": "b", "count": 2}], "rows_sampled": 1200,
         "sample_ratio": 0.1, "asOf": "2026-10-27T08:30:00"}


class FakeLayer:
    """The fact layer, answering from a dict: analysis id -> Fact."""

    def __init__(self, facts: dict[str, Fact]):
        self.facts = facts

    def fact(self, slug, analysis_id, level="resource"):
        return self.facts.get(analysis_id) or Fact(analysis_id=analysis_id, state="never_run")


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    reg.register_database(DatabaseEntity(slug=SLUG, display_name="Coco Pharma", db_type="postgresql",
                                         host="localhost", egeria_host="host.docker.internal", port=5442,
                                         database_name="coco_pharma"))
    return reg


@pytest.fixture
def declared(monkeypatch):
    """The catalogue the table reads: one entry, its declaration swappable; the fact layer answers VALUE."""
    world = {"entries": [_entry(_declaration())],
             "facts": {"example_step_x": Fact(analysis_id="example_step_x", state="measured", value=dict(VALUE),
                                               last_run_at="2026-10-27T08:31:00")}}
    monkeypatch.setattr(pt, "_entries", lambda entity_type: world["entries"])
    monkeypatch.setattr("resource_explorer.facts.FactLayer", lambda registry, resource_type: FakeLayer(world["facts"]))
    return world


def _rows(registry):
    return {r["measure"]: r for r in pt.build_rows(registry, "database", SLUG)["rows"]}


# ── the rows ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_two_declared_measures_are_two_generic_rows_with_unit_as_of_confidence_and_scope(registry, declared):
    rows = _rows(registry)
    assert set(rows) == {"buckets", "rows_sampled"}
    b, r = rows["buckets"], rows["rows_sampled"]
    assert b["value"] == 2 and b["value_words"] == "2 buckets"            # `buckets[]`: the list, counted
    assert r["value"] == 1200 and r["value_words"] == "1200 rows"
    for row in (b, r):
        assert row["analysis"] == "Example Step X"
        assert row["writes_as"]["words"] == pt.GENERIC_WORDS == "generic measure · no native type declared"
        assert row["as_of"] == "2026-10-27T08:30:00"
        assert row["confidence"]["words"] == "estimated · sample_ratio"
        assert row["scope"] == "resource"
        assert row["publishable"] and row["choice"] is None
        assert row["published"] == {"state": "local", "words": "local · not published"}


def test_a_proposal_is_not_on_the_table(registry, declared):
    declared["entries"] = [_entry(_declaration(kind="proposal"))]
    assert pt.build_rows(registry, "database", SLUG)["rows"] == []


def test_a_never_run_analysis_shows_its_declared_sentence_and_cannot_publish(registry, declared):
    declared["facts"] = {}
    row = _rows(registry)["buckets"]
    assert row["value"] is None and row["value_words"] == "—"
    assert row["absence"] == "not_measured" and row["absence_words"] == ABSENCE["not_measured"]
    assert not row["publishable"] and row["why_not"] == f"nothing to publish · {ABSENCE['not_measured']}"


def test_a_measured_result_without_the_field_is_measured_nothing_not_never_run(registry, declared):
    declared["facts"]["example_step_x"].value = {"asOf": "2026-10-27T08:30:00", "other": 1}
    row = _rows(registry)["rows_sampled"]
    assert row["absence"] == "measured_nothing" and row["absence_words"] == ABSENCE["measured_nothing"]


def test_a_number_without_its_as_of_does_not_publish(registry, declared):
    declared["facts"]["example_step_x"].value = {"rows_sampled": 5, "buckets": []}
    row = _rows(registry)["rows_sampled"]
    assert row["as_of"] == "" and not row["publishable"]
    assert row["why_not"] == "no as-of: a number never travels without its as-of"


def test_a_native_type_this_publisher_cannot_write_is_named_and_offers_keep_only(registry, declared):
    declared["entries"] = [_entry(_declaration({"type": "DataClassAnnotation"}))]
    row = _rows(registry)["rows_sampled"]
    assert row["writes_as"]["words"] == "DataClassAnnotation" and row["writes_as"]["route"] == "native"
    assert not row["publishable"] and "does not write DataClassAnnotation from a declaration yet" in row["why_not"]
    with pytest.raises(pt.ChoiceRefused, match="cannot publish"):
        pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="rows_sampled",
                       choice=pt.PUBLISH, author="dwolfson")
    kept = pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="rows_sampled",
                          choice=pt.KEEP, author="dwolfson")
    assert kept["choice"]["choice"] == pt.KEEP


def test_run_fields_resolve_from_the_run_the_reader_carried(registry, declared):
    """`run.read_snapshot`: a zero-fetch derivation's as-of is the newest stored row it read, carried by the reader
    under `_run`; `run.surveyed_at` falls back to the fact layer's run time."""
    dec = _declaration()
    dec.measures[0].as_of = "run.read_snapshot"
    dec.measures[1].as_of = "run.surveyed_at"
    declared["entries"] = [_entry(dec)]
    declared["facts"]["example_step_x"].value = {**VALUE, "_run": {"read_snapshot": "2026-10-20T07:00:00"}}
    rows = _rows(registry)
    assert rows["buckets"]["as_of"] == "2026-10-20T07:00:00"
    assert rows["rows_sampled"]["as_of"] == "2026-10-27T08:31:00"


def test_the_shipped_catalogue_builds_a_table_with_no_proposal_rows(registry):
    """Every database declaration in analysis_catalog.yaml, against a database with nothing surveyed: rows are
    built, none is a proposal, and with nothing measured none is publishable and each says why."""
    from resource_explorer.surveyors.analysis_catalog_reader import _load

    table = pt.build_rows(registry, "database", SLUG)
    proposals = {e.id for e in _load()["database"] if e.declaration and e.declaration.result_kind == "proposal"}
    assert table["rows"] and not {r["analysis_id"] for r in table["rows"]} & proposals
    for r in table["rows"]:
        assert r["writes_as"]["words"]
        assert r["publishable"] or r["why_not"]


# ── the choice ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_choice_is_signed_dated_and_the_newest_wins(registry, declared):
    pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="buckets",
                   choice=pt.PUBLISH, author="ann")
    row = pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="buckets",
                         choice=pt.KEEP, author="bob")
    assert row["choice"]["choice"] == pt.KEEP and row["choice"]["by"] == "bob" and row["choice"]["at"]
    assert pt.build_rows(registry, "database", SLUG)["chosen"] == 0
    # The choice is not scope: the selection record's scope reader never sees it.
    assert registry.current_resource_scope("database", SLUG) == {}


def test_a_choice_for_a_measure_no_declaration_names_is_refused(registry, declared):
    with pytest.raises(pt.ChoiceRefused, match="declares no measure 'nope'"):
        pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="nope",
                       choice=pt.PUBLISH, author="ann")
    with pytest.raises(pt.ChoiceRefused, match="not one of"):
        pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="buckets",
                       choice="maybe", author="ann")


def test_a_file_system_shows_its_rows_but_cannot_publish_from_this_table_yet(tmp_path, declared):
    reg = ProjectRegistry(db_path=str(tmp_path / "fs.db"))
    table = pt.build_rows(reg, "filesystem", "share")
    assert table["press"] == pt.NOT_FOR_KIND_WORDS
    assert all(not r["publishable"] and r["why_not"] == pt.NOT_FOR_KIND_WORDS for r in table["rows"])


# ── the press: published, read back, and the native type ───────────────────────────────────────────────────────


class _Discovery:
    def __init__(self, held):
        self.held = held

    def create_annotation(self, body):
        qn = body["properties"]["qualifiedName"]
        self.held[qn] = {"guid": f"ann-{len(self.held)}", "body": body}
        return self.held[qn]["guid"]


class _Maker:
    def __init__(self):
        self.reports = {}

    def create_asset(self, body):
        guid = f"report-{len(self.reports)}"
        self.reports[body["properties"]["qualifiedName"]] = guid
        return guid


def _surveyor(monkeypatch, *, readable=True):
    """The real EgeriaDatabaseSurveyor down to `publish_annotations` and `_read_back`; the pyegeria clients are fakes
    and the report read lists what the fake holds (None: the read could not be made)."""
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    s = EgeriaDatabaseSurveyor.__new__(EgeriaDatabaseSurveyor)
    held: dict = {}
    s._asset_maker, s._discovery = _Maker(), _Discovery(held)
    s._find_element_guid = lambda name: (held.get(name) or {}).get("guid", "")
    s._report_annotations = (lambda guid: [{"qualified_name": q, "guid": h["guid"]} for q, h in held.items()]) \
        if readable else (lambda guid: None)
    monkeypatch.setattr(EgeriaDatabaseSurveyor, "catalog_and_survey", lambda self, **k: {"database_guid": "db-1"})
    return s, held


def _press(s, registry, surveyed_at=SURVEYED_AT):
    """The commit's step 3 as it runs it: publish the report with the declared measures, then record the proofs."""
    out = s.publish_local_survey(registry.get_database(SLUG), schema_info={}, schema_count=0, table_count=0,
                                 column_count=0, surveyed_at=surveyed_at, registry=registry,
                                 survey_after_catalog=False, declared_measures=True)
    counts = pt.record_proofs(registry, SLUG, out["declared_measures"]["sent"],
                              report_guid=out["report_element_guid"], curation_id="c1", recorded_by="dwolfson")
    return out, counts


def test_the_gate_one_measure_publishes_as_a_generic_measure_and_reads_back(registry, declared, monkeypatch):
    s, held = _surveyor(monkeypatch)
    pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="rows_sampled",
                   choice=pt.PUBLISH, author="dwolfson")
    assert pt.build_rows(registry, "database", SLUG)["chosen"] == 1

    out, counts = _press(s, registry)

    assert out["declared_measures"]["state"] == "sent" and counts == {"sent": 1, "read_back": 1}
    assert pt.step_words(counts) == "1 declared measure read back"
    qn = out["declared_measures"]["sent"][0]["qualified_name"]
    assert qn == f"Annotation::PostgreSQL::{SLUG}::{SURVEYED_AT}::declared_measure.example_step_x.rows_sampled"
    props = held[qn]["body"]["properties"]
    assert props["class"] == "ResourceMeasureAnnotationProperties"
    assert props["resourceProperties"] == {"rows_sampled": "1200", "unit": "rows"}
    extra = props["additionalProperties"]
    assert extra["declaredRoute"] == "generic" and extra["declaredRouteWords"] == pt.GENERIC_WORDS
    assert extra["unit"] == "rows" and extra["asOf"] == "2026-10-27T08:30:00" and extra["confidenceBasis"] == "sample_ratio"
    # Only the chosen measure went: the other row was not chosen and stays in RE.
    assert not [q for q in held if q.endswith("declared_measure.example_step_x.buckets")]

    rows = _rows(registry)
    assert rows["rows_sampled"]["published"]["state"] == "published"
    assert rows["rows_sampled"]["published"]["words"].startswith("published · read back ")
    assert rows["rows_sampled"]["published"]["guid"] == held[qn]["guid"]
    assert rows["buckets"]["published"]["state"] == "local"


def test_the_gate_adding_the_annotation_type_makes_the_row_and_the_next_publish_native(registry, declared,
                                                                                       monkeypatch):
    s, held = _surveyor(monkeypatch)
    pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="rows_sampled",
                   choice=pt.PUBLISH, author="dwolfson")
    _press(s, registry)

    declared["entries"] = [_entry(_declaration({"type": "ResourceMeasureAnnotation",
                                                "properties": {"rows_sampled": "rowsSampled"}}))]
    row = _rows(registry)["rows_sampled"]
    assert row["writes_as"]["words"] == "ResourceMeasureAnnotation" and row["writes_as"]["route"] == "native"
    assert _rows(registry)["buckets"]["writes_as"]["words"] == pt.GENERIC_WORDS     # the other is unchanged

    out, counts = _press(s, registry, surveyed_at="2026-10-28T09:00:00")
    assert counts == {"sent": 1, "read_back": 1}
    props = held[out["declared_measures"]["sent"][0]["qualified_name"]]["body"]["properties"]
    assert props["class"] == "ResourceMeasureAnnotationProperties"
    assert props["resourceProperties"]["rowsSampled"] == "1200"            # the declared property map
    assert props["additionalProperties"]["declaredRoute"] == "native"
    assert "declaredRouteWords" not in props["additionalProperties"]
    assert out["declared_measures"]["sent"][0]["route"] == "native"


def test_a_report_that_cannot_be_read_back_leaves_sent_not_read_back_never_published(registry, declared,
                                                                                    monkeypatch):
    s, _ = _surveyor(monkeypatch, readable=False)
    pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="rows_sampled",
                   choice=pt.PUBLISH, author="dwolfson")
    _, counts = _press(s, registry)
    assert counts == {"sent": 1, "read_back": 0}
    assert pt.step_words(counts) == "0 of 1 declared measure read back"
    pub = _rows(registry)["rows_sampled"]["published"]
    assert pub["state"] == "not_read_back" and pub["why"] == "the report could not be read back"


def test_a_value_that_moved_since_the_publish_reads_changed_since_published(registry, declared, monkeypatch):
    s, _ = _surveyor(monkeypatch)
    pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="rows_sampled",
                   choice=pt.PUBLISH, author="dwolfson")
    _press(s, registry)
    declared["facts"]["example_step_x"].value = {**VALUE, "rows_sampled": 1300, "asOf": "2026-10-28T08:30:00"}
    pub = _rows(registry)["rows_sampled"]["published"]
    assert pub["state"] == "changed" and pub["words"].startswith("changed since published")


def test_nothing_chosen_adds_nothing_to_the_report_and_no_caller_but_the_commit_asks(registry, declared,
                                                                                    monkeypatch):
    s, held = _surveyor(monkeypatch)
    out, counts = _press(s, registry)
    assert out["declared_measures"] == {"state": "none_chosen", "sent": []} and counts["sent"] == 0
    pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="rows_sampled",
                   choice=pt.PUBLISH, author="dwolfson")
    # Any other publish of the survey (the retired route, the hybrid surveyor) does not ask for them.
    out = s.publish_local_survey(registry.get_database(SLUG), schema_info={}, schema_count=0, table_count=0,
                                 column_count=0, surveyed_at="2026-10-29T09:00:00", registry=registry,
                                 survey_after_catalog=False)
    assert out["declared_measures"]["state"] == "not_asked"
    assert not [q for q in held if "declared_measure." in q]


# ── the as-of seam (PR 1's gap §2.1) ─────────────────────────────────────────────────────────────────────────────


def test_the_zero_fetch_reader_carries_the_runs_read_snapshot(monkeypatch):
    from resource_explorer.surveyors.database import db_derived
    from resource_explorer.surveyors.database import survey_definition_adapter as sda

    monkeypatch.setattr(db_derived, "run_db_derived", lambda registry, slug: {
        "surveyed_at": "2026-10-27T12:00:00", "read_snapshot": "2026-10-20T07:00:00", "table_coverage": None,
        "derived": {"schema_diff": {"columns_added": [], "explanation": "x"}}})
    monkeypatch.setattr(sda, "_attach_container_credential_scope", lambda *a, **k: None)
    monkeypatch.setattr(sda, "_attach_coverage_status", lambda *a, **k: None)
    data = sda._db_derived_field_reader("schema_diff")(None, SLUG)
    assert data["_run"] == {"read_snapshot": "2026-10-20T07:00:00", "surveyed_at": "2026-10-27T12:00:00"}


def test_the_run_beside_the_payload_is_not_content_and_is_the_facts_as_of():
    from resource_explorer.facts import _has_content
    from resource_explorer.workflows.scouting import results_have_data

    only_run = {"_run": {"read_snapshot": "2026-10-20T07:00:00"}}
    assert not _has_content(only_run) and not results_have_data(only_run)
    f = Fact(analysis_id="schema_diff", state="measured", value={"n": 1, **only_run})
    assert f.as_of == "2026-10-20T07:00:00" and f.as_dict()["as_of"] == "2026-10-20T07:00:00"
    assert Fact(analysis_id="x", state="measured", last_run_at="2026-10-01").as_dict()["as_of"] == "2026-10-01"


def test_a_chosen_row_that_cannot_be_built_is_named_on_the_step_never_silently_dropped(registry, declared,
                                                                                      monkeypatch):
    pt.save_choice(registry, "database", SLUG, analysis_id="example_step_x", measure="rows_sampled",
                   choice=pt.PUBLISH, author="dwolfson")

    def boom(row):
        raise ValueError("no property map")

    monkeypatch.setattr(pt, "annotation_for", boom)
    got = pt.annotations_for(registry, SLUG)
    assert got["annotations"] == [] and got["not_built"] == [{"locator": "example_step_x/rows_sampled",
                                                             "why": "no property map"}]
    assert pt.step_words({"sent": 0, "read_back": 0}, got["not_built"]) == \
        "1 chosen not sent · could not be built (example_step_x/rows_sampled)"


# ── the routes ──────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(registry, declared, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer import auth
    from resource_explorer.web.app import app
    from resource_explorer.web.routes import catalogue_scope as scope_routes

    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setattr(scope_routes, "get_current_user", auth.get_current_user)
    authorized: list = []

    async def authorize(reg, entity_type, slug, publish=False):
        authorized.append((entity_type, slug, publish))

    monkeypatch.setattr("resource_explorer.web.routes.curate.authorize_resource_write", authorize)
    c = TestClient(app)
    c.authorized = authorized
    return c


def _as(user):
    from resource_explorer.auth import create_access_token

    return {"Authorization": "Bearer " + create_access_token(user_id=user, egeria_token="t")}


def test_the_table_reads_open_and_a_choice_needs_a_signed_in_author(client, registry):
    j = client.get(f"/api/publish-table/database/{SLUG}").json()
    assert [r["measure"] for r in j["rows"]] == ["buckets", "rows_sampled"]
    assert client.get("/api/publish-table/database/nope").status_code == 404
    assert client.get(f"/api/publish-table/repo/{SLUG}").status_code == 404

    body = {"analysis_id": "example_step_x", "measure": "rows_sampled", "choice": "publish"}
    r = client.put(f"/api/publish-table/database/{SLUG}/choice", json=body)
    assert r.status_code == 401 and "Sign in to" in r.json()["detail"]
    assert pt.current_choices(registry, "database", SLUG) == {}

    r = client.put(f"/api/publish-table/database/{SLUG}/choice", json={**body, "author": "mallory"},
                   headers=_as("alice"))
    assert r.status_code == 200 and r.json()["choice"]["by"] == "alice"           # a body author is ignored
    assert client.authorized == [("database", SLUG, False)]


def test_a_refused_choice_is_422_with_the_reason(client):
    r = client.put(f"/api/publish-table/database/{SLUG}/choice",
                   json={"analysis_id": "example_step_x", "measure": "nope", "choice": "publish"}, headers=_as("alice"))
    assert r.status_code == 422 and "declares no measure 'nope'" in r.json()["detail"]
