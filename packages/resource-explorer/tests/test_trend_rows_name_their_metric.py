"""A trend row may name what its `value` is.

`was 189190480 7d ago` on every sub-resource row was total_size_bytes rendered
as a bare integer: the trend reader knew the metric (its own comment said so)
and the payload did not carry it, so the UI's formatter had a value and no
name. The reader now stamps `metric` on each row and the UI prefers a row's
own name over the caller's.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.repo_survey_definition_adapter import _sub_resource_survey_trend


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P", github_url="https://github.com/x/p", description=""))
    return r


def test_sub_resource_trend_rows_name_total_size_bytes(registry):
    registry.upsert_metric("p", "repo_sub_resource_survey",
                           {"total_size_bytes": 189190480.0, "file_count": 6423.0},
                           surveyed_at="2026-09-01T00:00:00")
    registry.upsert_metric("p", "repo_sub_resource_survey",
                           {"total_size_bytes": 188999340.0, "file_count": 6421.0},
                           surveyed_at="2026-09-08T00:00:00")
    rows = _sub_resource_survey_trend(registry, "p")
    assert len(rows) == 2
    for r in rows:
        assert r["metric"] == "total_size_bytes"
        assert r["value"] > 1e8            # bytes, not a count
        assert r["file_count"] > 6000       # the context column survives
