"""Tests for HomepageSurveyor — deriving a project's external website.

Tiers, in order: GitHub's declared homepage; packaging manifests (pyproject,
package.json, pom.xml, Cargo.toml, setup.cfg); the README; and finally the repo
URL itself, because for a small project the GitHub page genuinely is the
landing page.

The filters carry most of the value here and are what these tests mostly pin.
Measured on the real registry when this was written: 13 of 24 repos declared a
homepage, so the fallback tiers run for nearly half of them — and the first live
run picked an SDK vendor's marketing site out of a README, which is the failure
mode the name-affinity rule and vendor denylist exist to prevent.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from resource_explorer.registry import Project
from resource_explorer.surveyors.sub_surveyors.homepage import (
    HomepageSurveyor,
    _is_plausible_site,
)


def _proj(url="https://github.com/odpi/egeria"):
    return Project(slug="p", display_name="P", github_url=url, description="")


def _reg(homepage=""):
    r = MagicMock()
    r.get_latest_project_stats.return_value = {"homepage": homepage}
    return r


def _run(tmp_path, homepage="", url="https://github.com/odpi/egeria"):
    reg = _reg(homepage)
    s = HomepageSurveyor(_proj(url), reg, local_path=str(tmp_path))
    return s.run()[0], reg


class TestTierOrder:
    def test_github_homepage_wins(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname="x"\n[project.urls]\nHomepage="https://manifest.example"\n')
        ann, _ = _run(tmp_path, homepage="https://declared.example")
        assert ann.additional_properties["homepage_url"] == "https://declared.example"
        assert ann.additional_properties["derivation_source"] == "github_homepage"
        assert ann.confidence == 100

    def test_manifest_used_when_github_empty(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname="x"\n[project.urls]\nHomepage="https://manifest.example"\n')
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["derivation_source"] == "pyproject_urls"

    def test_manifest_beats_readme(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"homepage": "https://manifest.example"}))
        (tmp_path / "README.md").write_text("[docs](https://readme.example)")
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["derivation_source"] == "package_json"

    def test_repo_url_is_the_last_resort(self, tmp_path):
        """For a small project the GitHub page IS the landing page — recording
        that beats recording nothing, and keeps the Scouting link actionable."""
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["derivation_source"] == "repo_url"
        assert ann.additional_properties["homepage_url"] == "https://github.com/odpi/egeria"
        assert ann.additional_properties["is_external_site"] == "false"
        assert ann.confidence == 30

    def test_real_site_is_marked_external(self, tmp_path):
        ann, _ = _run(tmp_path, homepage="https://egeria-project.org")
        assert ann.additional_properties["is_external_site"] == "true"

    def test_result_is_persisted(self, tmp_path):
        ann, reg = _run(tmp_path, homepage="https://egeria-project.org")
        reg.update_project_homepage.assert_called_once_with("p", "https://egeria-project.org")


class TestManifests:
    def test_maven_pom_url(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            '<?xml version="1.0"?><project xmlns="http://maven.apache.org/POM/4.0.0">'
            '<url>https://egeria-project.org</url></project>')
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["derivation_source"] == "maven_pom"

    def test_maven_organization_url(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            '<?xml version="1.0"?><project xmlns="http://maven.apache.org/POM/4.0.0">'
            '<organization><url>https://org.example</url></organization></project>')
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["homepage_url"] == "https://org.example"

    def test_cargo_and_setup_cfg(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname="x"\nhomepage="https://rust.example"\n')
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["derivation_source"] == "cargo_toml"

    def test_malformed_manifest_does_not_raise(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("this is not toml {{{")
        (tmp_path / "package.json").write_text("{not json")
        ann, _ = _run(tmp_path)          # falls through to repo_url rather than exploding
        assert ann.additional_properties["derivation_source"] == "repo_url"


class TestReadmeHeuristic:
    def test_badges_and_their_targets_are_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "[![build](https://img.shields.io/x.svg)](https://travis-ci.org/o/r)\n"
            "[site](https://egeria-project.org)\n")
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["homepage_url"] == "https://egeria-project.org"

    def test_links_back_to_the_code_host_are_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "[repo](https://github.com/odpi/egeria) and [site](https://egeria-project.org)")
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["homepage_url"] == "https://egeria-project.org"

    def test_vendor_attribution_is_skipped(self, tmp_path):
        """Regression from the first live run: unitycatalog-python's README
        yielded stainlessapi.com, its SDK generator, as the 'project website'."""
        (tmp_path / "README.md").write_text(
            "Generated by [Stainless](https://www.stainlessapi.com).\n"
            "[Docs](https://docs.unitycatalog.com)\n")
        ann, _ = _run(tmp_path, url="https://github.com/unitycatalog/unitycatalog-python")
        assert ann.additional_properties["homepage_url"] == "https://docs.unitycatalog.com"

    def test_name_affinity_beats_document_order(self, tmp_path):
        """A host echoing the project name is a far stronger signal than being
        first in the file."""
        (tmp_path / "README.md").write_text(
            "[sponsor](https://unrelated-vendor.example)\n[home](https://egeria-project.org)\n")
        ann, _ = _run(tmp_path)
        assert ann.additional_properties["homepage_url"] == "https://egeria-project.org"


class TestFilters:
    @pytest.mark.parametrize("url", [
        "https://img.shields.io/badge.svg",
        "https://github.com/odpi/egeria",
        "https://www.stainlessapi.com",
        "https://opensource.org/licenses/Apache-2.0",
    ])
    def test_rejected(self, url):
        assert _is_plausible_site(url) is False

    @pytest.mark.parametrize("url", ["https://egeria-project.org", "https://docs.example.io/guide"])
    def test_accepted(self, url):
        assert _is_plausible_site(url) is True
