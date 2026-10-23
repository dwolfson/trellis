"""The LANGUAGE tile and the Egeria publish make ONE choice of primary language (architect ruling 2026-10-23).

A measured value (RE's line census, by source files) beats GitHub's fetched by-bytes value when both exist, and
whatever is shown names its source. Live case: data_prep_kit read "HTML" from GitHub while the census measured
Python in 839 of 983 source files.
"""
from __future__ import annotations

from unittest.mock import create_autospec

import pytest
from fastapi.testclient import TestClient

from resource_explorer.primary_language import (
    GITHUB_SOURCE_ID, MEASURED_SOURCE_ID, choose_primary_language_from, publish_properties,
)
from resource_explorer.registry import Project, ProjectRegistry

CENSUS = {
    "surveyed_at": "2026-10-20T08:00:00",
    "detail": {"by_language": {
        "Python": {"files": 839, "code": 120000, "text_only": False},
        "HTML": {"files": 100, "code": 9000, "text_only": False},
        "Shell": {"files": 44, "code": 800, "text_only": False},
        # Text-only languages are not source files: never counted, never the answer.
        "Markdown": {"files": 5000, "code": 0, "text_only": True},
    }},
}
GITHUB = {"primary_language": "HTML", "fetched_at": "2026-10-19T07:00:00"}


class TestChooser:
    def test_classification_present_is_measured_with_its_basis(self):
        c = choose_primary_language_from(CENSUS, GITHUB)
        assert (c["value"], c["source"], c["chip"]) == ("Python", "measured", "measured")
        assert c["basis"] == "source files 839/983"
        assert c["source_id"] == MEASURED_SOURCE_ID
        assert c["hover"].startswith("measured · 839 of 983 source files · 2026-10-20")

    def test_absent_classification_falls_back_to_github(self):
        c = choose_primary_language_from({}, GITHUB)
        assert (c["value"], c["source"], c["chip"], c["basis"]) == ("HTML", "github", "GitHub", "bytes")
        assert c["source_id"] == GITHUB_SOURCE_ID
        assert c["hover"] == "GitHub · primary by bytes · fetched 2026-10-19"

    def test_a_census_of_only_text_files_is_not_a_measurement(self):
        only_text = {"surveyed_at": "x", "detail": {"by_language": {"Markdown": {"files": 9, "text_only": True}}}}
        assert choose_primary_language_from(only_text, GITHUB)["source"] == "github"

    def test_neither_is_not_measured_never_an_empty_measured(self):
        c = choose_primary_language_from({}, {})
        assert c["source"] == "" and c["value"] == "" and c["chip"] == ""
        assert publish_properties(c) == {"primary_language": "", "primary_language_source": "",
                                         "primary_language_basis": "", "as_of": ""}

    def test_disagreement_line_only_when_both_exist_and_differ(self):
        both = choose_primary_language_from(CENSUS, GITHUB)
        assert both["disagreement"] == "GitHub says HTML (by bytes)"
        assert both["hover"].endswith("\nGitHub says HTML (by bytes)")
        agree = choose_primary_language_from(CENSUS, {"primary_language": "Python", "fetched_at": "t"})
        assert agree["disagreement"] == "" and "GitHub says" not in agree["hover"]
        assert choose_primary_language_from(CENSUS, {})["disagreement"] == ""
        assert choose_primary_language_from({}, GITHUB)["disagreement"] == ""

    def test_a_tie_does_not_depend_on_dict_order(self):
        a = {"detail": {"by_language": {"Go": {"files": 3, "code": 10}, "Rust": {"files": 3, "code": 50}}}}
        b = {"detail": {"by_language": {"Rust": {"files": 3, "code": 50}, "Go": {"files": 3, "code": 10}}}}
        assert choose_primary_language_from(a, {})["value"] == choose_primary_language_from(b, {})["value"] == "Rust"


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "lang.db"))
    r.add(Project(slug="data_prep_kit", display_name="data-prep-kit",
                  github_url="https://github.com/data-prep-kit/data-prep-kit", description=""))
    with r._conn() as conn:
        conn.execute("INSERT INTO project_stats (project_slug, fetched_at, primary_language) VALUES (?, ?, ?)",
                     ("data_prep_kit", GITHUB["fetched_at"], GITHUB["primary_language"]))
    r.upsert_metric("data_prep_kit", "code_volume", {"code_lines": 129800}, detail=CENSUS["detail"],
                    surveyed_at=CENSUS["surveyed_at"])
    return r


class _Result:
    resource_slug = "data_prep_kit"
    project_display_name = "data-prep-kit"
    github_url = "https://github.com/data-prep-kit/data-prep-kit"


def test_publish_carries_the_tiles_choice_and_its_source(registry, monkeypatch):
    """Drive the real create path with an autospec'd AssetMaker: the asset's four additionalProperties are the
    chooser's, and its primary_language equals the value the scouting overview (the tile's payload) shows."""
    from pyegeria import AssetMaker

    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher

    maker = create_autospec(AssetMaker, instance=True, spec_set=True)
    maker.find_assets.return_value = []
    maker.find_software_capabilities.return_value = []
    maker.create_software_capability.return_value = "github-scl-guid"
    maker.create_asset.return_value = "new-asset-guid"
    pub = EgeriaPublisher.__new__(EgeriaPublisher)
    pub._asset_maker = maker
    pub._registry = registry
    pub.zone_names = None
    pub._zone_names = None

    assert pub._find_or_create_asset(_Result()) == "new-asset-guid"
    body = maker.create_asset.call_args.kwargs["body"]
    extra = body["properties"]["additionalProperties"]
    assert extra["primary_language"] == "Python"
    assert extra["primary_language_source"] == "resource-explorer:language_file_classification"
    assert extra["primary_language_basis"] == "source files 839/983"
    assert extra["as_of"] == CENSUS["surveyed_at"]

    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    from resource_explorer.web.app import app
    ov = TestClient(app).get("/api/projects/data_prep_kit/scouting-overview").json()
    assert ov["primary_language"] == extra["primary_language"]
    assert ov["language"]["source"] == "measured" and ov["language"]["chip"] == "measured"
    assert ov["language"]["disagreement"] == "GitHub says HTML (by bytes)"
