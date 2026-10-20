"""Curate's Publish sends the stored column-profile verdicts (DESIGN-PUBLISHING-COLUMN-VERDICTS.md §1).

Until 2026-10-20 `publish_local_survey` rebuilt annotations from the kept survey blob only, so data-class and
reference-data verdicts reached Egeria only through a Survey Definition run, although #759 now stores them.
"""
from __future__ import annotations

import pytest
from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.database.column_profile_step import (
    column_match_from_row,
    column_match_rows,
    verdict_annotations_from_rows,
)
from resource_explorer.surveyors.survey_report import annotation_qualified_name

from tests.test_postgres_column_profile import _SCHEMA_INFO, _run

PREFIX = "Annotation::PostgreSQL::coco_ods::2026-10-20T01:00:00"
INVENTORY = {"public.customer.email", "public.customer.country", "public.customer.avatar"}


def _rows(profile=None):
    profile = profile or _run()[1]
    return column_match_rows(profile["matches"])


def _key(ann) -> tuple:
    return (ann.check_name, (ann.item_key or "").split("@", 1)[0], ann.summary, type(ann).__name__)


# ── the rebuild ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_stored_verdict_rebuilds_into_the_same_annotations_the_step_built():
    _, profile = _run()
    rebuilt = verdict_annotations_from_rows(column_match_rows(profile["matches"]), batch_surveyed_at="b1")
    # The step suppresses the proposal-fallback RFA when it could read the catalogue; this path never creates a
    # DRAFT element, so it may add one. Every annotation the step built is rebuilt, identically.
    step = {_key(a) for a in profile["annotations"]}
    again = {_key(a) for a in rebuilt["annotations"] if a.annotation_type_name != "ProposalFallback"}
    assert step == again


def test_a_row_round_trips_to_the_column_match_it_was_stored_from():
    _, profile = _run()
    for match, row in zip(profile["match_objects"], column_match_rows(profile["matches"]), strict=True):
        back = column_match_from_row(row)
        assert back.as_dict() == match.as_dict()


def test_each_verdict_carries_its_own_batch_date():
    rebuilt = verdict_annotations_from_rows(_rows(), batch_surveyed_at="2026-10-19T08:00:00")
    assert rebuilt["annotations"]
    assert all(a.json_properties["measuredAt"] == "2026-10-19T08:00:00" for a in rebuilt["annotations"])


def test_a_newer_batch_is_a_new_annotation_never_adopted_as_the_old_one():
    """The collision: a republished kept survey reuses its report, so without the batch in the identity a newer
    verdict for the same column would get the old annotation's name and Egeria would keep the old one."""
    old = verdict_annotations_from_rows(_rows(), batch_surveyed_at="2026-10-19T08:00:00")["annotations"]
    new = verdict_annotations_from_rows(_rows(), batch_surveyed_at="2026-10-20T08:00:00")["annotations"]
    old_names = {annotation_qualified_name(PREFIX, i, a) for i, a in enumerate(old)}
    new_names = {annotation_qualified_name(PREFIX, i, a) for i, a in enumerate(new)}
    assert old_names.isdisjoint(new_names)
    # ...and the same batch converges on the same names, so a republish of it adds nothing.
    same = verdict_annotations_from_rows(_rows(), batch_surveyed_at="2026-10-19T08:00:00")["annotations"]
    assert {annotation_qualified_name(PREFIX, i, a) for i, a in enumerate(same)} == old_names


def test_verdicts_for_columns_no_longer_in_the_inventory_are_dropped_and_counted():
    rebuilt = verdict_annotations_from_rows(_rows(), batch_surveyed_at="b1",
                                            inventory={"public.customer.email"})
    assert set(rebuilt["column_paths"]) == {"public.customer.email"}
    assert rebuilt["dropped_vanished"] == 2 and rebuilt["sent_columns"] == 1


# ── what publish_local_survey reads ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    reg.register_database(_entity())
    return reg


def _entity():
    return DatabaseEntity(slug="coco_ods", display_name="Coco ODS", db_type="postgresql", host="localhost",
                          egeria_host="host.docker.internal", port=5442, database_name="coco_pharma")


def test_no_stored_batch_is_none_stored_not_zero(registry):
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    got = EgeriaDatabaseSurveyor._stored_verdict_annotations(registry, "coco_ods", _SCHEMA_INFO)
    assert got["state"] == "none_stored" and got["annotations"] == []


def test_no_registry_is_not_read_never_none_stored():
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    assert EgeriaDatabaseSurveyor._stored_verdict_annotations(None, "coco_ods", _SCHEMA_INFO)["state"] == "not_read"


def test_the_latest_batch_is_read_and_checked_against_the_kept_inventory(registry):
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    registry.write_detail_rows("database_column_matches", "coco_ods", "2026-10-19T08:00:00", rows=_rows())
    got = EgeriaDatabaseSurveyor._stored_verdict_annotations(registry, "coco_ods", _SCHEMA_INFO)
    assert got["state"] == "sent" and got["batch"] == "2026-10-19T08:00:00"
    assert got["sent_columns"] == 3 and got["dropped_vanished"] == 0


def test_the_band_names_the_stored_batch(registry):
    from resource_explorer.single_publish import stored_verdicts_summary

    assert stored_verdicts_summary(registry, "coco_ods")["state"] == "none_stored"
    registry.write_detail_rows("database_column_matches", "coco_ods", "2026-10-19T08:00:00", rows=_rows())
    got = stored_verdicts_summary(registry, "coco_ods")
    assert got["state"] == "stored" and got["columns"] == 3 and "measured 10-19" in got["word"]


# ── through publish_local_survey ────────────────────────────────────────────────────────────────────────────


def test_publish_local_survey_sends_the_verdicts_and_links_them_to_committed_columns(registry, monkeypatch):
    from resource_explorer import egeria_link_once
    from resource_explorer.catalogue_gateway import schema_qualified_name, server_name_for
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    registry.write_detail_rows("database_column_matches", "coco_ods", "2026-10-19T08:00:00", rows=_rows())
    entity = _entity()
    sent: dict = {}

    def fake_publish(self, body, qualified_name, annotations, slug, surveyed_at, **_):
        sent["annotations"] = list(annotations)
        return {"report_guid": "report-1", "report_error": "", "annotation_error": "", "reused": False,
                "annotations_in_egeria": len(annotations)}

    # The committed schema's columns exist in Egeria (the cataloguer's names, confirmed live 2026-10-20) except
    # `avatar`, whose column element is absent; every published annotation resolves to a GUID.
    schema_qn = schema_qualified_name(server_name_for(entity), entity.database_name, "public")
    columns = {f"{schema_qn}::customer::email": "col-email", f"{schema_qn}::customer::country": "col-country"}

    def fake_find(self, name):
        if name in columns:
            return columns[name]
        return f"ann:{name}" if name.startswith("Annotation::") else ""

    links: list = []

    def fake_link_once(expert, *, relationship_type, read_guid, read_end, far_guid, create, what, **_):
        links.append((relationship_type, read_guid, read_end, far_guid))
        return egeria_link_once.LinkOutcome(egeria_link_once.LINKED, relationship_guid="rel")

    monkeypatch.setattr(EgeriaDatabaseSurveyor, "catalog_and_survey", lambda self, **k: {"database_guid": "db-1"})
    monkeypatch.setattr(EgeriaDatabaseSurveyor, "_publish_survey_report", fake_publish)
    monkeypatch.setattr(EgeriaDatabaseSurveyor, "_find_element_guid", fake_find)
    monkeypatch.setattr(EgeriaDatabaseSurveyor, "_metadata_expert_client", lambda self: object())
    monkeypatch.setattr(egeria_link_once, "link_once", fake_link_once)

    s = EgeriaDatabaseSurveyor(platform_url="https://localhost:9443", view_server="qs-view-server")
    out = s.publish_local_survey(entity, schema_info=_SCHEMA_INFO, schema_count=1, table_count=1, column_count=3,
                                 surveyed_at="2026-10-20T01:00:00", registry=registry, survey_after_catalog=False)

    verdict_types = {a.annotation_type_name for a in sent["annotations"]}
    assert {"DataClassMatch", "ColumnValueSample"} <= verdict_types
    assert out["verdicts"]["state"] == "sent" and out["verdicts"]["batch"] == "2026-10-19T08:00:00"
    links_by_column = {far for (_, _, _, far) in links}
    assert links_by_column == {"col-email", "col-country"}
    assert all(t == "AssociatedAnnotation" and end == 2 for (t, _, end, _) in links)
    counts = out["verdicts"]["column_links"]
    assert counts["linked"] == len(links) and counts["no_column_element"] > 0  # avatar has none
