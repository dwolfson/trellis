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
from resource_explorer.surveyors.database.quality.value_profile import ANALYSIS_STEP, measure_key
from resource_explorer.surveyors.survey_report import ResourceMeasureAnnotation, ResourceProfileAnnotation
from tests.test_engine_host_e4 import egeria  # noqa: F401 - fixture reused
from tests.test_quality_q2_survey_press_e2e import (  # noqa: F401 - fixtures and helpers reused
    _annotation_bodies,
    _by_class,
    _no_live_database,
    _press,
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
    assert table_of(measure_key("sales", "orders", "id")) == "sales.orders" and table_of("sales.orders.id") == ""


def _not_profiled(table: str) -> ResourceMeasureAnnotation:
    return ResourceMeasureAnnotation(summary=f"Value profile: {table} not profiled (not_measured)",
                                     analysis_step=ANALYSIS_STEP, annotation_type_name="Value Profile",
                                     check_name="value_profile", item_key=table, label="not_measured")


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
    assert plan.create == [2, 3]
    assert plan.gone == {_key("s.t.gone"): "g-gone"}                 # counted once: s.t.counted already was
    assert plan.not_measured == {_key("s.slow.x"): "g-slow"}         # its table was not profiled: not a drop
    assert plan_profile_publish([same], None).relink == {}            # nothing published before: all created
    plan.recreate([1])
    assert plan.relink == {} and plan.recreated == {1} and plan.create == [1, 2, 3]


def test_the_card_line_words():
    assert profile_publish_words({"rows": 0}) == ""
    assert profile_publish_words({"rows": 5, "published": 5, "created": 5, "relinked": 0, "no_longer_measured": 0,
                                  "previous_report_at": ""}) == "5 measures published · first profile published"
    assert profile_publish_words({"rows": 5, "published": 4, "created": 1, "relinked": 3, "no_longer_measured": 1,
                                  "previous_report_at": "2026-10-22T10:00:00"}) == (
        "4 measures published · 1 changed since 2026-10-22 · 3 re-used · 1 no longer measured")
    assert profile_publish_words({"rows": 5, "published": 4, "created": 0, "relinked": 4, "no_longer_measured": 0,
                                  "not_measured_this_run": 1, "previous_report_at": "2026-10-22T10:00:00"}) == (
        "4 measures published · 0 changed since 2026-10-22 · 4 re-used · 0 no longer measured"
        " · 1 not measured this run")


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
        rows = [dict(r) for r in conn.execute(
            "SELECT detail_json, item_key, content_hash FROM native_survey_annotations WHERE report_guid = ?",
            (report_guid,)).fetchall()]
    out: dict[str, int] = {}
    for r in rows:
        detail = json.loads(r["detail_json"])
        outcome = detail["outcome"]
        out[outcome] = out.get(outcome, 0) + 1
        assert len(json.loads(r["item_key"])) == 3                        # every proof row names its column
        assert (r["content_hash"] is None) == (outcome in ("no_longer_measured", "not_measured_this_run"))
        if notes is not None and detail.get("note"):
            notes.append((outcome, detail["note"]))
    # the rows NOT on the report are not counted as on it
    on_report = sum(v for k, v in out.items() if k in ("created", "relinked"))
    assert registry.count_native_survey_annotations(report_guid) == on_report
    assert len(registry.query_native_survey_annotations(report_guid)) == on_report
    return out


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
    first_date = egeria.reports()[0][1]["properties"]["qualifiedName"].rsplit("::", 1)[1][:10]
    profile_on_r1 = {g for g in _reported_pairs(egeria, r1)
                     if egeria.elements[g]["body"]["properties"]["class"] == PROFILE_CLASS}

    # 2. second run, nothing changed: 0 created, all re-linked, and the fake received no profile create
    seen = set(egeria.elements)
    attaches = len(egeria.method_calls("attach_annotation_to_report"))
    second = _press(client, registry)
    r2 = egeria.reports()[1][0]
    assert _profile_creates(egeria, seen) == 0
    assert len(egeria.method_calls("attach_annotation_to_report")) - attaches == 5
    assert _proof(registry, r2) == {"relinked": 5}
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
    assert len(egeria.method_calls("attach_annotation_to_report")) - attaches == 4
    assert _proof(registry, r4) == {"relinked": 4, "not_measured_this_run": 1}
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
    assert " · 5 measures published · 1 changed since " in second["publish_state"]


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
    assert len(egeria.method_calls("attach_annotation_to_report")) - attaches == 4
    on_r2 = _reported_pairs(egeria, r2)
    assert len(on_r2) == len(set(on_r2))                                  # one ReportedAnnotation per pair
    assert _proof(registry, r2) == {"relinked": 5}
    assert second["publish_state"].endswith("· 5 re-used · 0 no longer measured")
