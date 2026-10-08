"""Review follow-ups to the reset status words: parsed-UTC time comparison everywhere, the marker read across
node kinds, a badge-only marker that says what it rests on, publish flags corrected at read time, and the
legacy page never copying an `unbound` context onto other resources."""
from __future__ import annotations

from pathlib import Path

import pytest

from resource_explorer import catalogue_commit as cc
from resource_explorer import repo_publish
from resource_explorer.registry import DatabaseEntity
from resource_explorer.workflows import analysis as analysis_mod
from tests.test_board_summary_read_cost import _wire_one_analysis
from tests.test_egeria_reset_cleanup import RESET_ISO, applied, env, ins  # noqa: F401  (env is a fixture)

STATIC = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static"

# (published_at, expected state) against a reset at 2026-10-08T18:30:00 UTC
CASES = [
    ("2026-10-08T18:29:59+00:00", "published_earlier"),
    ("2026-10-08T18:30:00Z", "published"),
    ("2026-10-08 18:29:59.123", "published_earlier"),          # space separator, 3-digit fraction
    ("2026-10-08T18:30:00.500000", "published"),               # 6-digit fraction
    ("2026-10-08T14:00:00-05:00", "published"),                # 19:00 UTC; as TEXT it sorts before the reset
    ("2026-10-08T20:00:00+02:00", "published_earlier"),        # 18:00 UTC; as TEXT it sorts after the reset
    ("2026-10-08T18:29:00", "published_earlier"),              # naive: read as UTC, like every writer here
]


@pytest.mark.parametrize("published_at,expected", CASES)
def test_published_state_compares_parsed_utc_times(published_at, expected):
    assert cc.published_state(published_at, RESET_ISO) == expected


def test_the_reset_may_carry_an_offset_too_and_reset_since_read_agrees():
    assert cc.published_state("2026-10-08T18:00:00Z", "2026-10-08T20:30:00+02:00") == "published_earlier"
    assert cc.reset_since_read("2026-10-08T14:00:00-05:00", RESET_ISO) is False     # read 19:00 UTC, after
    assert cc.reset_since_read("2026-10-08T20:00:00+02:00", RESET_ISO) is True      # read 18:00 UTC, before
    assert cc.reset_since_read("2026-10-08 17:59:59.9", "2026-10-08T18:30:00Z") is True


def test_the_newest_marker_is_chosen_by_parsed_time_not_by_text(env):
    reg = env["reg"]
    for at in ("2026-10-08T19:30:00+02:00", "2026-10-08T18:00:00"):      # 17:30 UTC and 18:00 UTC
        reg.append_catalogue_commit_proof("repo2", proof="egeria_reset", node_kind="repo_report", read_at=at)
    assert reg.get_egeria_reset_at("repo2") == "2026-10-08T18:00:00"


def test_the_badge_only_marker_compares_parsed_times_and_says_it_is_a_claim(env):
    reg = env["reg"]
    with reg._conn() as c:
        for slug in ("early", "late"):
            c.execute("INSERT INTO projects (slug, display_name, github_url, created_at) VALUES (?, ?, ?, '2026-09-01')",
                      (slug, slug, f"https://x/{slug}"))
    ins(reg, "project_published_analyses", project_slug="early", analysis_id="a", egeria_report_guid="g",
        published_at="2026-10-08T20:00:00+02:00")      # 18:00 UTC: before the reset
    ins(reg, "project_published_analyses", project_slug="late", analysis_id="a", egeria_report_guid="g",
        published_at="2026-10-08T14:00:00-05:00")      # 19:00 UTC: after the reset
    applied(env)
    assert reg.get_egeria_reset_at("early") == RESET_ISO
    assert reg.get_egeria_reset_at("late") == ""
    text = [p for p in reg.list_catalogue_commit_proofs("early") if p["proof"] == "egeria_reset"][0]["detail"]["text"]
    assert "published claim before the reset (no proof rows)" in text
    # a resource WITH proofs keeps the plain text
    plain = [p for p in reg.list_catalogue_commit_proofs("repo1") if p["proof"] == "egeria_reset"][0]["detail"]["text"]
    assert "claim" not in plain


def test_a_repo_and_a_database_sharing_a_slug_both_read_the_one_marker(env):
    reg = env["reg"]
    with reg._conn() as c:
        c.execute("INSERT INTO projects (slug, display_name, github_url, created_at) "
                  "VALUES ('shared', 'S', 'https://x/s', '2026-09-01')")
    reg.register_database(DatabaseEntity(slug="shared", display_name="S", db_type="postgresql", host="localhost",
                                         port=5432, database_name="s"))
    reg.append_catalogue_commit_proof("shared", proof="database_published", node_kind="database",
                                      element_guid="g", read_at="2026-10-06T10:00:00")
    reg.append_catalogue_commit_proof("shared", proof="report_published", node_kind="repo_report",
                                      element_guid="g", read_at="2026-10-06T12:00:00")
    applied(env)
    markers = [p for p in reg.list_catalogue_commit_proofs("shared") if p["proof"] == "egeria_reset"]
    assert len(markers) == 1                                    # one per slug, keyed by node kind of the first
    assert repo_publish.publish_state(reg, "shared")["row"]["word"] == "reset"      # the repo reads it
    header = cc.derive_commit_state(reg, "shared", {"schemas": []})["header"]["text"]
    assert "Egeria was reset" in header                          # and so does the database


def test_a_persisted_board_gets_its_publish_flags_corrected_at_read_time(registry, monkeypatch):
    mock_reader, _ = _wire_one_analysis(monkeypatch)
    monkeypatch.setattr(
        "resource_explorer.surveyors.analysis_catalog_reader.get_analyses",
        lambda entity_type, **kw: [{"id": "db_classification", "name": "C", "description": "", "intent": "discovery",
                                    "annotation_types": ["ZZ"]}])
    registry.record_published_annotation_types("mydb", {"ZZ"})
    first = analysis_mod.build_survey_results(registry, "database", "mydb", include_empty=True, board_id="db_classification")
    assert first["dashboards"][0]["publish_stale"] is False
    registry.mark_egeria_linkage_stale("database_publish", "mydb", "guid-1")
    second = analysis_mod.build_survey_results(registry, "database", "mydb", include_empty=True, board_id="db_classification")
    assert mock_reader.call_count == 1                           # still the persisted fast path
    assert second["dashboards"][0]["publish_stale"] is True


@pytest.fixture
def registry(tmp_path):
    from resource_explorer.registry import ProjectRegistry
    r = ProjectRegistry(db_path=str(tmp_path / "b.db"))
    r.register_database(DatabaseEntity(slug="mydb", display_name="My DB", db_type="postgresql",
                                       host="localhost", port=5432, database_name="mydb"))
    return r


def test_the_legacy_page_never_copies_an_unbound_context_onto_other_resources():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    # the investigation label must not make an `unbound` investigation the session default ...
    assert ("inv.egeria_context.status !== 'unset' && inv.egeria_context.status !== 'unbound'") in html
    # ... and a session default that is `unbound` must not be POSTed to a resource
    assert "_sessionEgeriaProjectContext.status === 'unset' || _sessionEgeriaProjectContext.status === 'unbound'" in html
