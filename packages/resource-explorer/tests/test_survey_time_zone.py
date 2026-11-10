"""Survey times are written with a zone (docs/design-notes/BRIEF-CONTEXT-SECTION-AS-OF.md, PR B).

Before 2026-11 they were `datetime.utcnow().isoformat()`: UTC, but without a zone, so the closed-loop diagnosis
refused to read them as an as-of. Old rows keep that form; these tests pin that both forms live together safely:
the latest run still wins under string MAX, Egeria's names do not change between a live and a kept publish, and
the one reader that compared with a naive clock no longer raises.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.survey_time import as_utc_iso, now_utc, now_utc_iso


def test_the_helper_writes_a_zone():
    assert now_utc_iso().endswith("+00:00")
    assert now_utc().tzinfo is not None


def test_a_naive_utc_moment_becomes_the_same_instant_with_a_zone():
    assert as_utc_iso(datetime(2026, 11, 10, 12, 0, 0)) == "2026-11-10T12:00:00+00:00"  # noqa: DTZ001 - the legacy form
    assert as_utc_iso(datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)) == "2026-11-10T12:00:00+00:00"


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "reg.db"))
    reg.add(Project(slug="r", display_name="R", github_url="u", description=""))
    return reg


def _finding(label):
    return [{"check_name": "c", "label": label, "summary": label, "confidence": 100, "detail": {}}]


class TestTheRegistryDefaults:
    def test_a_finding_without_a_time_is_stamped_with_a_zone(self, registry):
        registry.upsert_finding("r", "cve_scan", _finding("x"))
        [row] = registry.query_findings("r", "cve_scan")
        assert row["surveyed_at"].endswith("+00:00")

    def test_a_metric_without_a_time_is_stamped_with_a_zone(self, registry):
        registry.upsert_metric("r", "website_ingestion", {"chunks": 3.0})
        assert str(registry.query_metrics("r", "website_ingestion")["surveyed_at"]).endswith("+00:00")


class TestOldAndNewRowsTogether:
    """`query_findings` returns the rows at MAX(surveyed_at), compared as strings."""

    def test_a_new_zoned_run_after_an_old_naive_one_is_the_latest(self, registry):
        registry.upsert_finding("r", "cve_scan", _finding("old"), surveyed_at="2026-11-09T10:00:00.123456")
        registry.upsert_finding("r", "cve_scan", _finding("new"), surveyed_at="2026-11-10T09:00:00.000001+00:00")
        assert [r["label"] for r in registry.query_findings("r", "cve_scan")] == ["new"]

    def test_within_one_second_the_later_instant_still_wins(self, registry):
        registry.upsert_finding("r", "cve_scan", _finding("old"), surveyed_at="2026-11-10T09:00:00.100000")
        registry.upsert_finding("r", "cve_scan", _finding("new"), surveyed_at="2026-11-10T09:00:00.200000+00:00")
        assert [r["label"] for r in registry.query_findings("r", "cve_scan")] == ["new"]


def test_a_kept_survey_publishes_under_the_same_egeria_name_as_the_live_run():
    """The orchestrator stores the zoned form; SurveyResult (which names Egeria's SurveyReport) stays naive, and
    to_result strips the zone back off, so the qualified name is the same either way."""
    from types import SimpleNamespace

    from resource_explorer.surveyors import survey_snapshot

    live = datetime(2026, 11, 10, 12, 0, 0, 123456)  # noqa: DTZ001 - surveyed_at_dt, naive by design
    stored = as_utc_iso(live)                                  # what the run writes
    snap = survey_snapshot.Snapshot(slug="r", surveyed_at=stored, steps={})
    result = survey_snapshot.to_result(SimpleNamespace(slug="r", display_name="R", github_url="u"), snap)
    assert result.surveyed_at == live and result.surveyed_at.isoformat() == live.isoformat()


def test_website_freshness_reads_both_forms_without_raising(registry):
    from resource_explorer.surveyors.sub_surveyors.website_ingestion import _already_ingested

    registry.add(Project(slug="s", display_name="S", github_url="u2", description=""))
    fresh = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None).isoformat()   # old form, recent
    registry.upsert_metric("r", "website_ingestion", {"chunks": 5.0}, detail={"collection": "site"},
                           surveyed_at=fresh)
    registry.upsert_metric("s", "website_ingestion", {"chunks": 5.0}, detail={"collection": "site"},
                           surveyed_at=now_utc_iso())
    slug, when = _already_ingested(registry, "site", "other")
    assert slug in ("r", "s") and when


def test_website_freshness_skips_a_stale_zoned_row(registry):
    from resource_explorer.surveyors.sub_surveyors.website_ingestion import _already_ingested

    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    registry.upsert_metric("r", "website_ingestion", {"chunks": 5.0}, detail=json.loads('{"collection": "site"}'),
                           surveyed_at=old)
    assert _already_ingested(registry, "site", "other") == (None, None)
