"""Profile publish reshape (BRIEF-PROFILE-PUBLISH-RESHAPE, ruling 2026-10-22; owner's DDL go 2026-10-23).

Egeria's own survey re-links unchanged annotations to its new report and creates only changed ones; RE now does the
same for the value profile's per-column ResourceProfileAnnotations. Unchanged = the sha256 of the measure's canonical
JSON equals the hash on RE's own proof row of the last published annotation (`native_survey_annotations.content_hash`,
keyed by `item_key`), never a re-read of Egeria.

End to end through the real Survey press (the Q2 rig: real route, queue, executor, value profile, registry on temp
SQLite, database publisher) with Egeria faked by `create_autospec(<real pyegeria class>, spec_set=True)`, whose
`attach_annotation_to_report` is multi-link like Egeria's (a second attach of a pair makes a second relationship).
The fixture database has 5 measured columns (sales.orders x4, sales.empty x1).
"""
from __future__ import annotations

import copy
import json
import sqlite3
from unittest.mock import create_autospec

import pytest

from resource_explorer.surveyors.database.quality.profile_publish import (
    PROFILE_SHAPE_VERSION,
    RECREATED_NOTE,
    canonical_measures,
    content_hash,
    plan_profile_publish,
    profile_publish_words,
    table_of,
)
from resource_explorer.surveyors.database.quality.value_profile import ANALYSIS_STEP, measure_key, table_key
from resource_explorer.surveyors.survey_report import ResourceMeasureAnnotation, ResourceProfileAnnotation
from tests.test_engine_host_e4 import egeria  # noqa: F401 - fixture reused
from tests.test_quality_q2_survey_press_e2e import (  # noqa: F401 - fixtures and helpers reused
    _annotation_bodies,
    _by_class,
    _no_live_database,
    _press,
    _utc_minute,
    client,
    rig,
    world,
)
from tests.test_value_profile_quality_checks import PROFILE, SLUG, TIMEOUT, registry  # noqa: F401

PROFILE_EMPTY = PROFILE[("sales", "empty")]

PROFILE_CLASS = "ResourceProfileAnnotationProperties"


def _key(path: str) -> str:
    return measure_key(*path.split("."))


def _measure(path="sales.orders.id", value_count=None, **props) -> ResourceProfileAnnotation:
    json_properties = {"generalType": "N", "profileDates": {}, "sampleRatio": None, "ranAs": "surveyor"}
    json_properties.update(props)
    return ResourceProfileAnnotation(
        summary=f"Value profile: {path}", analysis_step=ANALYSIS_STEP, annotation_type_name="Value Profile",
        check_name="value_profile", item_key=_key(path), label="measured",
        value_count={"record_ct": 1000, "value_ct": 1000, "null_value_ct": 0} if value_count is None else value_count,
        json_properties=json_properties)


# ── the hash is faithful ───────────────────────────────────────────────────────────────────────────────────

def test_two_measures_differing_in_one_value_count_entry_hash_differently():
    a = _measure()
    b = _measure(value_count={"record_ct": 1000, "value_ct": 999, "null_value_ct": 0})
    assert canonical_measures(a) != canonical_measures(b)
    assert content_hash(a) != content_hash(b)


def test_two_equal_measures_hash_equally_and_the_full_compare_agrees():
    a, b = _measure(profileDates={"min_date": "2020-01-01"}), _measure(profileDates={"min_date": "2020-01-01"})
    assert a is not b
    assert content_hash(a) == content_hash(b)
    assert canonical_measures(a) == canonical_measures(b)          # the hash matches only what the full compare does


def test_a_reordered_json_properties_hashes_equally():
    a = _measure()
    b = _measure()
    b.json_properties = dict(reversed(list(a.json_properties.items())))
    b.value_count = dict(reversed(list(a.value_count.items())))
    assert list(a.json_properties) != list(b.json_properties)
    assert content_hash(a) == content_hash(b)


def test_who_ran_it_is_not_a_measure_but_a_date_or_a_present_absent_key_is():
    assert content_hash(_measure(ranAs="someone")) == content_hash(_measure(ranAs="else"))
    assert content_hash(_measure(profileDates={"max_date": "2026-10-01"})) != content_hash(
        _measure(profileDates={"max_date": "2026-10-02"}))
    assert content_hash(_measure(value_count={"value_ct": 0})) != content_hash(_measure(value_count={}))
    # numbers exactly: an int and a float are different measures, never equal by accident
    assert content_hash(_measure(value_count={"value_ct": 5})) != content_hash(_measure(value_count={"value_ct": 5.0}))


def test_the_shape_version_is_hashed_and_the_key_is_a_json_array():
    assert canonical_measures(_measure())["shape_version"] == PROFILE_SHAPE_VERSION
    assert _key("sales.orders.id") == '["sales","orders","id"]'
    # a dot inside a name is a different column, never the same key
    assert measure_key("a.b", "c", "d") != measure_key("a", "b.c", "d")
    assert table_of(measure_key("sales", "orders", "id")) == table_key("sales", "orders") == '["sales","orders"]'
    assert table_of("sales.orders.id") == "" and table_of(table_key("sales", "orders")) == ""


# ── round 2 (architect rulings 2026-10-24) ─────────────────────────────────────────────────────────────────

class _ClockConn:
    """The value profile's fake Postgres for a STATIC table whose `placed` column holds one date half an hour after
    the first profile: `future_date_ct` is computed from the `{RUN_DATE}` literal the statement carries, as Postgres
    would, so it moves with the clock while nothing in the table does."""

    PLACED = "2026-10-20 10:30:00"

    def __init__(self):
        from tests.test_value_profile_quality_checks import FakeConn

        self.inner = FakeConn(profile=copy.deepcopy(PROFILE))

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def execute_query_isolated(self, sql, params=()):
        import re

        rows = self.inner.execute_query_isolated(sql, params)
        run_date = re.search(r"> '(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'", sql)
        for alias in re.findall(r"AS (c\d+__future_date_ct)", sql):
            rows[0][alias] = int(self.PLACED > run_date.group(1))
        return rows


def _profile_at(registry, at: str) -> dict[str, ResourceProfileAnnotation]:
    from contextlib import contextmanager

    from resource_explorer.surveyors.database.quality.value_profile import run_value_profile
    from tests.test_value_profile_quality_checks import BOUNDS

    conn = _ClockConn()

    @contextmanager
    def connect():
        yield conn

    out = run_value_profile(registry.get_database(SLUG), registry, connect, bounds=BOUNDS, surveyed_at=at,
                            ran_as="surveyor", clock=lambda: 0.0)
    return {a.item_key: a for a in out["annotations"] if isinstance(a, ResourceProfileAnnotation)}


def test_two_profiles_of_a_static_table_an_hour_apart_hash_equal(registry):
    """Fail-on-purpose (ruling (b)): the table does not change between 10:00 and 11:00, but its one date passes
    'now' at 10:30, so `future_date_ct` goes 1 -> 0. Hashed or published in `value_count`, every date column would
    read as changed on every press of a live database."""
    first, later = _profile_at(registry, "2026-10-20T10:00:00+00:00"), _profile_at(registry, "2026-10-20T11:00:00+00:00")
    placed = _key("sales.orders.placed")
    # RE's own rows keep the relative measure for the Future_Date check, and it did move
    assert {r["column_name"]: r["future_date_ct"] for r in registry.query_detail_rows(
        "database_value_profiles", SLUG, "2026-10-20T10:00:00+00:00") if r["table_name"] == "orders"}["placed"] == 1
    assert {r["column_name"]: r["future_date_ct"] for r in registry.query_detail_rows(
        "database_value_profiles", SLUG, "2026-10-20T11:00:00+00:00") if r["table_name"] == "orders"}["placed"] == 0
    # the annotation carries neither the count nor a clock-dependent hash; it says what the bounds were as of when
    assert "future_date_ct" not in first[placed].value_count
    assert first[placed].json_properties["profileDates"]["asOf"] == "2026-10-20T10:00:00Z"
    assert later[placed].json_properties["profileDates"]["asOf"] == "2026-10-20T11:00:00Z"
    assert set(first) == set(later)
    for key in first:
        assert content_hash(first[key]) == content_hash(later[key]), key


def test_the_shape_version_moved_so_round_1_hashes_never_match():
    """Every round-1 proof row hashed a different shape (future_date_ct in it): the first round-2 publish creates
    each measure once rather than matching an old hash by accident."""
    assert PROFILE_SHAPE_VERSION == 2


def test_a_relative_measure_on_an_old_annotation_is_not_hashed_either():
    a = _measure(value_count={"record_ct": 10, "future_date_ct": 3}, profileDates={"max_date": "2026-01-01",
                                                                                     "asOf": "2026-10-20T10:00:00Z"})
    b = _measure(value_count={"record_ct": 10}, profileDates={"max_date": "2026-01-01", "asOf": "2026-10-24T21:09:00Z"})
    assert content_hash(a) == content_hash(b)
    assert content_hash(b) != content_hash(_measure(value_count={"record_ct": 10},
                                                    profileDates={"max_date": "2026-01-02"}))


def _proposals(digest="d1", run_id="2026-10-24T21:09:00", proposed=3):
    from resource_explorer.surveyors.database.quality import propose
    from resource_explorer.surveyors.survey_report import RequestForActionAnnotation

    return RequestForActionAnnotation(
        summary=f"{proposed} quality checks proposed for coco", analysis_step=propose.ANALYSIS_STEP,
        annotation_type_name="Proposed Quality Checks", check_name=propose.CHECK_NAME, item_key=propose.ITEM_KEY,
        label="proposed", action_requested=f"review {proposed} proposed quality checks in Resource Explorer",
        action_target_name="coco", explanation=f"Resource Explorer proposed {proposed} quality checks in run {run_id}.",
        additional_properties={"runId": run_id, "proposedChecks": str(proposed), "proposedChecksDigest": digest})


def test_the_proposals_request_compares_on_its_checks_never_on_its_run():
    from resource_explorer.surveyors.database.quality.profile_publish import PROPOSALS, relink_kind

    assert relink_kind(_proposals()) == PROPOSALS
    assert content_hash(_proposals(run_id="a")) == content_hash(_proposals(run_id="b"))
    assert content_hash(_proposals(digest="d1")) != content_hash(_proposals(digest="d2"))   # same count, other checks
    assert content_hash(_proposals(proposed=3)) != content_hash(_proposals(proposed=4))


def test_the_proposals_request_is_planned_against_its_own_steps_proof_rows():
    from resource_explorer.surveyors.database.quality import propose

    req = _proposals()
    others = {propose.ANALYSIS_STEP: {"report_guid": "r1", "report_at": "2026-10-24T21:09:00",
                                      "measures": {propose.ITEM_KEY: {"annotation_guid": "g-rfa",
                                                                      "content_hash": content_hash(req)}}}}
    plan = plan_profile_publish([_measure(), req], None, others)
    assert plan.relink == {1: "g-rfa"} and plan.create == [0]
    assert plan.steps == {0: ANALYSIS_STEP, 1: propose.ANALYSIS_STEP}
    assert plan.previous_by_step == {propose.ANALYSIS_STEP: ("r1", "2026-10-24T21:09:00")}
    # a key in the value profile's proof rows is never the request's, even if equal text
    assert plan_profile_publish([req], {"report_guid": "r0", "report_at": "x", "measures": {
        propose.ITEM_KEY: {"annotation_guid": "wrong", "content_hash": content_hash(req)}}}).relink == {}


def test_a_not_profiled_table_relinks_when_its_reason_is_the_same_and_is_never_no_longer_measured():
    slow = _not_profiled("s.slow")
    previous = {"report_guid": "r1", "report_at": "2026-10-24T21:09:00",
                "measures": {table_key("s", "slow"): {"annotation_guid": "g-slow-t", "content_hash": content_hash(slow)},
                             table_key("s", "fast"): {"annotation_guid": "g-fast-t", "content_hash": "h"}}}
    plan = plan_profile_publish([slow, _not_profiled("s.other", reason="permission denied")], previous)
    assert plan.relink == {0: "g-slow-t"} and plan.create == [1]
    # s.fast was not profiled last time and is profiled now: nothing is "no longer measured" for a table key
    assert plan.gone == {} and plan.not_measured == {}
    changed = _not_profiled("s.slow", reason="permission denied")
    assert plan_profile_publish([changed], previous).relink == {}


def test_the_card_names_the_previous_report_by_date_and_time_utc():
    counts = {"rows": 2, "published": 2, "created": 1, "relinked": 1, "no_longer_measured": 0}
    for stored, shown in (("2026-10-24T21:09:41.123456", "2026-10-24 21:09Z"),     # RE's naive UTC
                          ("2026-10-24T23:09:00+02:00", "2026-10-24 21:09Z"),      # an offset, converted
                          ("2026-10-24T21:09:00Z", "2026-10-24 21:09Z")):
        assert profile_publish_words({**counts, "previous_report_at": stored}) == (
            f"2 measures published · 1 changed since {shown} · 1 re-used · 0 no longer measured")
    # a time that cannot be read is shown as stored, never a guessed one
    assert " · 1 changed since sometime · " in profile_publish_words({**counts, "previous_report_at": "sometime"})


def _not_profiled(table: str, reason: str = "canceling statement due to statement timeout"
                  ) -> ResourceMeasureAnnotation:
    return ResourceMeasureAnnotation(summary=f"Value profile: {table} not profiled (not_measured)",
                                     analysis_step=ANALYSIS_STEP, annotation_type_name="Value Profile",
                                     check_name="value_profile", item_key=table_key(*table.split(".")),
                                     label="not_measured", confidence=0, explanation=reason,
                                     resource_properties={"state": "not_measured", "reason": reason})


def test_the_plan_relinks_the_unchanged_creates_the_changed_and_new_and_names_the_gone():
    same, changed, new = _measure("s.t.a"), _measure("s.t.b", value_count={"value_ct": 2}), _measure("s.t.c")
    previous = {"report_guid": "r1", "report_at": "2026-10-22T10:00:00",
                "measures": {_key("s.t.a"): {"annotation_guid": "g-a", "content_hash": content_hash(same)},
                             _key("s.t.b"): {"annotation_guid": "g-b", "content_hash": content_hash(_measure("s.t.b"))},
                             _key("s.t.gone"): {"annotation_guid": "g-gone", "content_hash": "x"},
                             _key("s.slow.x"): {"annotation_guid": "g-slow", "content_hash": "y"},
                             _key("s.t.counted"): {"annotation_guid": "g-counted", "content_hash": "z"}},
                "gone_keys": {_key("s.t.counted")}}
    other = object()                                                   # any other annotation is never planned
    plan = plan_profile_publish([other, same, changed, new, _not_profiled("s.slow")], previous)
    assert plan.relink == {1: "g-a"}
    assert plan.create == [2, 3, 4]                                    # the table not profiled is new: created
    assert plan.keys[4] == table_key("s", "slow") and plan.steps[4] == ANALYSIS_STEP
    assert plan.gone == {_key("s.t.gone"): "g-gone"}                 # counted once: s.t.counted already was
    assert plan.not_measured == {_key("s.slow.x"): "g-slow"}         # its table was not profiled: not a drop
    assert plan_profile_publish([same], None).relink == {}            # nothing published before: all created
    plan.recreate([1])
    assert plan.relink == {} and plan.recreated == {1} and plan.create == [1, 2, 3, 4]


def test_the_card_line_words():
    assert profile_publish_words({"rows": 0}) == ""
    assert profile_publish_words({"rows": 5, "published": 5, "created": 5, "relinked": 0, "no_longer_measured": 0,
                                  "previous_report_at": ""}) == "5 measures published · first profile published"
    assert profile_publish_words({"rows": 5, "published": 4, "created": 1, "relinked": 3, "no_longer_measured": 1,
                                  "previous_report_at": "2026-10-22T10:00:00"}) == (
        "4 measures published · 1 changed since 2026-10-22 10:00Z · 3 re-used · 1 no longer measured")
    assert profile_publish_words({"rows": 5, "published": 4, "created": 0, "relinked": 4, "no_longer_measured": 0,
                                  "not_measured_this_run": 1, "previous_report_at": "2026-10-22T10:00:00"}) == (
        "4 measures published · 0 changed since 2026-10-22 10:00Z · 4 re-used · 0 no longer measured"
        " · 1 not measured this run")


def test_the_card_line_names_a_recreated_measure_and_does_not_call_it_changed():
    counts = {"rows": 5, "published": 5, "created": 1, "recreated": 1, "changed": 0, "relinked": 4,
              "no_longer_measured": 0, "previous_report_at": "2026-10-22T10:00:00"}
    assert profile_publish_words(counts) == (
        "5 measures published · 0 changed since 2026-10-22 10:00Z · 4 re-used"
        " · 1 re-created (the re-used annotation was gone) · 0 no longer measured")


# ── the read-first guard ───────────────────────────────────────────────────────────────────────────────────

def _surveyor_with(held: list[dict] | None):
    from pyegeria import DataDiscovery

    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    s = EgeriaDatabaseSurveyor.__new__(EgeriaDatabaseSurveyor)
    s._discovery = create_autospec(DataDiscovery, spec_set=True, instance=True)
    s._report_annotations = lambda report_guid: held
    return s


def test_a_report_that_already_links_the_annotation_gets_no_second_reported_annotation():
    s = _surveyor_with([{"guid": "g-a", "qualified_name": "Annotation::x"}])
    out = s._relink_unchanged("report-2", {0: "g-a", 1: "g-b", 2: "g-b"})
    assert out == {0: "already_linked", 1: "relinked", 2: "already_linked"}
    # exactly one create per pair, with the real signature (autospec, spec_set)
    calls = s._discovery.attach_annotation_to_report.call_args_list
    assert [(c.args[0], c.args[1]) for c in calls] == [("report-2", "g-b")]
    assert calls[0].kwargs["body"]["properties"]["class"] == "ReportedAnnotationProperties"


def test_a_refused_relink_is_refused_and_a_transport_failure_is_failed():
    from tests.test_engine_host_e4 import _refusal

    s = _surveyor_with([])
    s._discovery.attach_annotation_to_report.side_effect = [
        _refusal("OMAG-REPOSITORY-HANDLER-404-001", "no Annotation g-a", http=404), RuntimeError("timed out")]
    assert s._relink_unchanged("report-2", {0: "g-a", 1: "g-b"}) == {0: "refused", 1: "failed"}


def test_the_read_first_is_the_real_paged_read_of_the_report(monkeypatch):
    """`_report_annotations` through `reported_annotations` and `related_entries`, against an autospec'd
    MetadataExpert: the list is read page by page until Egeria's "No elements found"."""
    from pyegeria import DataDiscovery, MetadataExpert

    from resource_explorer.egeria_link_once import PAGE_SIZE
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor
    from tests.report_pages import related_entry

    expert = create_autospec(MetadataExpert, spec_set=True, instance=True)
    page = [related_entry("g-a", "Annotation", {"qualifiedName": "Annotation::a"}),
            related_entry("g-b", "Annotation", {"qualifiedName": "Annotation::b"})]
    expert.get_related_metadata_elements.side_effect = (
        lambda guid, rel, body=None, starting_at_end=0, start_from=0, page_size=0, **k:
        {"elementList": page} if start_from == 0 else "No elements found")
    s = EgeriaDatabaseSurveyor.__new__(EgeriaDatabaseSurveyor)
    s._discovery = create_autospec(DataDiscovery, spec_set=True, instance=True)
    s._metadata_expert = expert
    out = s._relink_unchanged("report-2", {0: "g-a", 1: "g-c"})
    assert out == {0: "already_linked", 1: "relinked"}
    assert [(c.args[0], c.args[1], c.kwargs["start_from"], c.kwargs["page_size"])
            for c in expert.get_related_metadata_elements.call_args_list] == [
        ("report-2", "ReportedAnnotation", 0, PAGE_SIZE), ("report-2", "ReportedAnnotation", PAGE_SIZE, PAGE_SIZE)]
    assert [c.args[1] for c in s._discovery.attach_annotation_to_report.call_args_list] == ["g-c"]


def test_a_report_whose_list_cannot_be_read_gets_no_blind_attach():
    s = _surveyor_with(None)
    assert s._relink_unchanged("report-2", {0: "g-a"}) == {0: "not_checked"}
    s._discovery.attach_annotation_to_report.assert_not_called()


def test_the_relationship_body_is_one_pyegeria_accepts():
    from pyegeria.models import NewRelationshipRequestBody

    body = {"class": "NewRelationshipRequestBody", "properties": {"class": "ReportedAnnotationProperties"}}
    assert NewRelationshipRequestBody.model_validate(body).properties["class"] == "ReportedAnnotationProperties"


# ── the DDL: two nullable TEXT columns, idempotent ─────────────────────────────────────────────────────────

NEW = ("item_key", "content_hash")


def _cols(reg) -> set[str]:
    with reg._conn() as conn:
        return reg._get_table_columns(conn, "native_survey_annotations")


def test_a_fresh_registry_has_the_columns_and_a_second_init_is_a_no_op(tmp_path):
    from resource_explorer.registry import ProjectRegistry

    path = str(tmp_path / "twice.db")
    first, second = _cols(ProjectRegistry(db_path=path)), _cols(ProjectRegistry(db_path=path))
    assert set(NEW) <= first and first == second


def test_an_existing_registry_gains_the_columns_and_its_rows_stay_null(tmp_path):
    from resource_explorer.registry import ProjectRegistry

    path = tmp_path / "old.db"
    reg = ProjectRegistry(db_path=str(path))
    reg.record_native_survey_report("ea-1", entity_type="database", slug="d", process_qualified_name="p",
                                    report_guid="r", report_at="t", read_at="t",
                                    annotations=[{"guid": "a1", "annotation_type": "X"}])
    con = sqlite3.connect(path)
    for col in NEW:
        con.execute(f"ALTER TABLE native_survey_annotations DROP COLUMN {col}")
    con.commit()
    con.close()
    again = ProjectRegistry(db_path=str(path))
    assert set(NEW) <= _cols(again)
    with again._conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT item_key, content_hash FROM native_survey_annotations").fetchall()]
    assert rows == [{"item_key": None, "content_hash": None}]           # a native row: never compared
    assert again.latest_profile_publish("database", "d", ANALYSIS_STEP) is None


def test_the_migration_is_idempotent_on_postgres(pg_registry, monkeypatch):
    from resource_explorer.registry import ProjectRegistry as PR

    assert "resource_explorer_test" in pg_registry.database_url             # the throwaway schema only
    before = _cols(pg_registry)
    assert set(NEW) <= before
    monkeypatch.setattr(PR, "_pg_schema_ready", set())
    assert _cols(PR(database_url=pg_registry.database_url)) == before


# ── end to end: the real press, twice, then a change, then a drop ──────────────────────────────────────────

def _profile_creates(egeria, since: set[str]) -> int:
    return sum(1 for g, e in egeria.elements.items() if g not in since and e["type"] == "Annotation"
               and (e["body"] or {}).get("properties", {}).get("class") == PROFILE_CLASS)


def _proof(registry, report_guid, *, notes: list | None = None) -> dict[str, int]:
    with registry._conn() as conn:
        every = [dict(r) for r in conn.execute(
            "SELECT detail_json, item_key, content_hash, annotation_type FROM native_survey_annotations "
            "WHERE report_guid = ?", (report_guid,)).fetchall()]
    rows = [r for r in every if r["annotation_type"] == "ResourceProfileAnnotation"]
    out: dict[str, int] = {}
    for r in rows:
        detail = json.loads(r["detail_json"])
        outcome = detail["outcome"]
        out[outcome] = out.get(outcome, 0) + 1
        assert len(json.loads(r["item_key"])) == 3                        # every proof row names its column
        assert (r["content_hash"] is None) == (outcome in ("no_longer_measured", "not_measured_this_run"))
        if notes is not None and detail.get("note"):
            notes.append((outcome, detail["note"]))
    # the rows NOT on the report are not counted as on it (the request's and any table's rows are on it too)
    on_report = sum(v for k, v in out.items() if k in ("created", "relinked")) + len(every) - len(rows)
    assert registry.count_native_survey_annotations(report_guid) == on_report
    assert len(registry.query_native_survey_annotations(report_guid)) == on_report
    return out


def _report_rows(registry, report_guid) -> list[dict]:
    with registry._conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT detail_json, annotation_type, analysis_step FROM native_survey_annotations "
            "WHERE report_guid = ?", (report_guid,)).fetchall()]


def _other_proof(registry, report_guid) -> dict[tuple[str, str], int]:
    """The proof rows of the re-linkable annotations that are not column measures: {(type, outcome): n}."""
    out: dict[tuple[str, str], int] = {}
    for r in _report_rows(registry, report_guid):
        if r["annotation_type"] != "ResourceProfileAnnotation":
            key = (r["annotation_type"], json.loads(r["detail_json"])["outcome"])
            out[key] = out.get(key, 0) + 1
    return out


def _relinked_rows(registry, report_guid) -> int:
    return sum(1 for r in _report_rows(registry, report_guid) if json.loads(r["detail_json"])["outcome"] == "relinked")


def test_only_the_gone_outcomes_have_an_item_key_and_no_content_hash(client, registry, egeria, world, rig):
    """The convention the changed/recreated query relies on: created and relinked proof rows always carry a hash."""
    _press(client, registry)
    r1 = egeria.reports()[0][0]
    egeria.archive(_profile_on(egeria, r1)[0])
    _press(client, registry)
    with registry._conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT detail_json, item_key, content_hash FROM native_survey_annotations").fetchall()]
    seen = set()
    for r in rows:
        outcome = json.loads(r["detail_json"])["outcome"]
        seen.add(outcome)
        if outcome in ("created", "relinked"):
            assert r["content_hash"]
        else:
            assert outcome in ("no_longer_measured", "not_measured_this_run")
            assert r["item_key"] and r["content_hash"] is None
    assert {"created", "relinked"} <= seen


def _reported_pairs(egeria, report_guid) -> list[str]:
    return [r["end2"] for r in egeria.relationships if r["type"] == "ReportedAnnotation" and r["end1"] == report_guid]


def test_two_identical_presses_then_a_change_then_a_drop(client, registry, egeria, world, rig):
    # 1. first run: all created, 0 re-linked
    first = _press(client, registry)
    [(r1, _)] = egeria.reports()
    assert len(_by_class(_annotation_bodies(egeria, r1))[PROFILE_CLASS]) == 5
    assert _proof(registry, r1) == {"created": 5}
    assert first["publish_state"].endswith("· 5 measures published · first profile published")
    assert first["published"] is True
    first_date = _utc_minute(egeria.reports()[0][1]["properties"]["qualifiedName"].rsplit("::", 1)[1])
    profile_on_r1 = {g for g in _reported_pairs(egeria, r1)
                     if egeria.elements[g]["body"]["properties"]["class"] == PROFILE_CLASS}

    # 2. second run, nothing changed: 0 created, all re-linked, and the fake received no profile create
    seen = set(egeria.elements)
    attaches = len(egeria.method_calls("attach_annotation_to_report"))
    second = _press(client, registry)
    r2 = egeria.reports()[1][0]
    assert _profile_creates(egeria, seen) == 0
    assert _proof(registry, r2) == {"relinked": 5}
    # round 2: the four tables not profiled and the proposals request are unchanged too, so re-linked as well
    assert _other_proof(registry, r2) == {("ResourceMeasureAnnotation", "relinked"): 4,
                                          ("RequestForAction", "relinked"): 1}
    assert len(egeria.method_calls("attach_annotation_to_report")) - attaches == _relinked_rows(registry, r2) == 10
    on_r2 = _reported_pairs(egeria, r2)
    assert {g for g in on_r2 if egeria.elements[g]["body"]["properties"]["class"] == PROFILE_CLASS} == profile_on_r1
    assert len(on_r2) == len(set(on_r2))                                  # one ReportedAnnotation per pair
    # the read-back counts what the report holds, re-linked ones included: M + K = 0 + 5
    assert second["publish_state"].endswith(
        f"· 5 measures published · 0 changed since {first_date} · 5 re-used · 0 no longer measured")
    assert second["published"] is True and second["status"] != "error"
    # the re-linked annotations are the first report's, anchored there, now reported by both
    for g in profile_on_r1:
        assert sorted(r["end1"] for r in egeria.relationships
                      if r["type"] == "ReportedAnnotation" and r["end2"] == g) == sorted([r1, r2])

    # 3. one column changed: exactly that one created, the rest re-linked (on a copy: PROFILE is shared)
    world.profile = copy.deepcopy(world.profile)
    world.profile[("sales", "orders")]["columns"][3]["value_ct"] = 11
    seen = set(egeria.elements)
    third = _press(client, registry)
    r3 = egeria.reports()[2][0]
    assert _profile_creates(egeria, seen) == 1
    assert _proof(registry, r3) == {"created": 1, "relinked": 4}
    assert " · 5 measures published · 1 changed since " in third["publish_state"]
    assert third["publish_state"].endswith("· 4 re-used · 0 no longer measured")

    # 4. a table not profiled this time (it timed out): its column is NOT MEASURED THIS RUN, never "no longer
    # measured"; nothing written to Egeria for it
    world.profile[("sales", "empty")] = TIMEOUT
    seen, attaches = set(egeria.elements), len(egeria.method_calls("attach_annotation_to_report"))
    fourth = _press(client, registry)
    r4 = egeria.reports()[3][0]
    assert _profile_creates(egeria, seen) == 0
    assert len(egeria.method_calls("attach_annotation_to_report")) - attaches == _relinked_rows(registry, r4)
    assert _proof(registry, r4) == {"relinked": 4, "not_measured_this_run": 1}
    # the newly not-profiled table's annotation is created; the four that were already not profiled are re-linked
    assert {k: v for k, v in _other_proof(registry, r4).items() if k[0] == "ResourceMeasureAnnotation"} == {
        ("ResourceMeasureAnnotation", "created"): 1, ("ResourceMeasureAnnotation", "relinked"): 4}
    assert " · 4 measures published · 0 changed since " in fourth["publish_state"]
    assert fourth["publish_state"].endswith("· 4 re-used · 0 no longer measured · 1 not measured this run")
    assert registry.profile_publish_counts(r4, ANALYSIS_STEP)["published"] == 4

    # 5. it is profiled again, unchanged: re-linked from the last run that measured it, not created
    world.profile[("sales", "empty")] = PROFILE_EMPTY
    seen = set(egeria.elements)
    fifth = _press(client, registry)
    r5 = egeria.reports()[4][0]
    assert _profile_creates(egeria, seen) == 0
    assert _proof(registry, r5) == {"relinked": 5}
    assert fifth["publish_state"].endswith("· 5 re-used · 0 no longer measured")


def _drop_table(registry, schema: str, table: str, at="2026-10-20T09:30:00+00:00") -> None:
    """A later inventory batch without the table and its columns: the database no longer has it."""
    tables = [r for r in registry.query_detail_rows("database_tables", SLUG)
              if (r["schema_name"], r["table_name"]) != (schema, table)]
    cols = [r for r in registry.query_detail_rows("database_columns", SLUG)
            if (r["schema_name"], r["table_name"]) != (schema, table)]
    registry.write_detail_rows("database_tables", SLUG, at, rows=tables)
    registry.write_detail_rows("database_columns", SLUG, at, rows=cols)


def test_a_dropped_table_is_no_longer_measured_once(client, registry, egeria, world, rig):
    _press(client, registry)
    _drop_table(registry, "sales", "empty")
    second = _press(client, registry)
    r2 = egeria.reports()[1][0]
    assert _proof(registry, r2) == {"relinked": 4, "no_longer_measured": 1}
    assert second["publish_state"].endswith("· 4 re-used · 1 no longer measured")
    # the next run does not count the same drop again
    third = _press(client, registry)
    assert _proof(registry, egeria.reports()[2][0]) == {"relinked": 4}
    assert third["publish_state"].endswith("· 4 re-used · 0 no longer measured")


def _profile_on(egeria, report_guid) -> list[str]:
    return [g for g in _reported_pairs(egeria, report_guid)
            if egeria.elements[g]["body"]["properties"]["class"] == PROFILE_CLASS]


def test_a_relink_egeria_refuses_is_created_in_the_same_run(client, registry, egeria, world, rig):
    _press(client, registry)
    r1 = egeria.reports()[0][0]
    gone = _profile_on(egeria, r1)[0]
    egeria.archive(gone)                                                  # archived in Egeria since the last run
    seen = set(egeria.elements)
    second = _press(client, registry)
    r2 = egeria.reports()[1][0]
    assert _profile_creates(egeria, seen) == 1                            # created again, in this run
    notes: list = []
    assert _proof(registry, r2, notes=notes) == {"created": 1, "relinked": 4}
    assert notes == [("created", RECREATED_NOTE)]
    assert gone not in _reported_pairs(egeria, r2) and len(_profile_on(egeria, r2)) == 5
    assert second["published"] is True
    counts = registry.profile_publish_counts(r2, ANALYSIS_STEP)
    assert counts["created"] == 1 and counts["recreated"] == 1 and counts["changed"] == 0
    assert counts["published"] == 5
    assert " · 5 measures published · 0 changed since " in second["publish_state"]
    assert " · 4 re-used · 1 re-created (the re-used annotation was gone) · 0 no longer measured" in second["publish_state"]


def test_a_partial_relink_is_relinked_on_the_next_run_not_changed(client, registry, egeria, world, rig):
    _press(client, registry)
    # the second run: Egeria fails one re-link for a reason that is not "gone" (could not tell)
    attaches = len(egeria.method_calls("attach_annotation_to_report"))
    egeria.fail_nth["attach_annotation_to_report"] = (attaches + 2, RuntimeError("Egeria timed out"))
    seen = set(egeria.elements)
    second = _press(client, registry)
    r2 = egeria.reports()[1][0]
    assert _profile_creates(egeria, seen) == 0                            # not created: it may well be there
    assert _proof(registry, r2) == {"relinked": 4}                         # the read by GUID did not find it
    assert " · 4 measures published · 0 changed since " in second["publish_state"]
    del egeria.fail_nth["attach_annotation_to_report"]
    # the third run: its hash is unchanged, compared with run 1's row: re-linked, not "changed"
    seen = set(egeria.elements)
    third = _press(client, registry)
    r3 = egeria.reports()[2][0]
    assert _profile_creates(egeria, seen) == 0
    assert _proof(registry, r3) == {"relinked": 5}
    assert " · 5 measures published · 0 changed since " in third["publish_state"]
    assert third["publish_state"].endswith("· 5 re-used · 0 no longer measured")


def test_a_report_that_already_holds_a_pair_is_not_attached_again_end_to_end(client, registry, egeria, world, rig,
                                                                             monkeypatch):
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    _press(client, registry)
    held = _profile_on(egeria, egeria.reports()[0][0])[0]
    real = EgeriaDatabaseSurveyor._relink_unchanged

    def already_there(self, report_guid, pairs):
        # Egeria already holds one pair on the new report (a retried request landed): the read-first must see it
        egeria.relationships.append({"type": "ReportedAnnotation", "end1": report_guid, "end2": held,
                                     "guid": "pre-existing"})
        return real(self, report_guid, pairs)

    monkeypatch.setattr(EgeriaDatabaseSurveyor, "_relink_unchanged", already_there)
    attaches = len(egeria.method_calls("attach_annotation_to_report"))
    second = _press(client, registry)
    r2 = egeria.reports()[1][0]
    # every planned re-link but the one the report already held (4 measures + 4 tables + 1 request)
    assert len(egeria.method_calls("attach_annotation_to_report")) - attaches == _relinked_rows(registry, r2) - 1 == 9
    on_r2 = _reported_pairs(egeria, r2)
    assert len(on_r2) == len(set(on_r2))                                  # one ReportedAnnotation per pair
    assert _proof(registry, r2) == {"relinked": 5}
    assert second["publish_state"].endswith("· 5 re-used · 0 no longer measured")
