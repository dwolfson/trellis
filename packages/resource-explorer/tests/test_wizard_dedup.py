"""Regression test for OnboardingWizard.run()'s duplicate-registration
hardening ("Scouting workflow redesign" plan, D7).

Root cause found live this session: OnboardingWizard._url_to_slug() doesn't
strip a trailing ".git" (unlike registry.get_by_github_url()'s own
normalization) — so "https://…/repo" and "https://…/repo.git" hash to two
different slugs ("repo" vs "repo_git"), and the pre-existing
`self.registry.exists(slug)` guard alone lets the second URL register as a
brand-new project instead of recognizing it as the same repo.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.cli.wizard import OnboardingWizard
from resource_explorer.configdata.collection_config import COLLECTION_TYPES
from resource_explorer.github.analyzer import IngestionPlan
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def wizard(registry):
    w = OnboardingWizard()
    w.registry = registry
    w.analyzer = MagicMock()
    w.analyzer.analyze.return_value = IngestionPlan(
        github_url="https://github.com/odpi/egeria-workspaces.git",
        display_name="Egeria Workspaces", description="", homepage_url="",
        proposed_collections=list(COLLECTION_TYPES.values())[:1], file_counts={},
    )
    w._trigger_ingestion = MagicMock()
    return w


class TestDuplicateRegistrationHardening:
    def test_git_suffixed_url_is_recognized_as_the_same_repo(self, wizard, registry):
        registry.add(Project(
            slug="egeria_workspaces", display_name="Egeria Workspaces",
            github_url="https://github.com/odpi/egeria-workspaces",
        ))

        with patch("resource_explorer.cli.wizard.Confirm.ask", return_value=False):
            wizard.run("https://github.com/odpi/egeria-workspaces.git", accept_all=False)

        all_projects = registry.list_all()
        assert len(all_projects) == 1
        assert all_projects[0].slug == "egeria_workspaces"

    def test_no_prior_registration_still_registers_normally(self, wizard, registry):
        wizard.run("https://github.com/odpi/egeria-workspaces.git", accept_all=True)
        assert registry.exists("egeria_workspaces_git")

    def test_subproject_registration_is_not_treated_as_a_duplicate(self, wizard, registry):
        # A second project scoped to a different subpath of the same URL is
        # legitimately a distinct entry — the URL-based dedup check must not
        # fire for it.
        registry.add(Project(
            slug="egeria_workspaces", display_name="Egeria Workspaces",
            github_url="https://github.com/odpi/egeria-workspaces",
        ))
        wizard.run(
            "https://github.com/odpi/egeria-workspaces", accept_all=True, subproject_path="commands",
        )
        assert registry.exists("egeria_workspaces_commands")
