"""Tests for dr_egeria_survey_publisher — Analysis-step Egeria registration
plan, D1-D3 (docs/analysis-step-egeria-registration-plan.md). Pure string
generation, no live Egeria needed."""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.dr_egeria_survey_publisher import (
    PublishableStep,
    generate_survey_definition_markdown,
    render_link_first_block,
    render_link_next_block,
    render_process_block,
    render_step_block,
)


@pytest.fixture
def steps():
    return [
        PublishableStep("repo_health", "Activity/community scoring.", "Git Repository"),
        PublishableStep("repo_language", "Primary language classification.", "Git Repository"),
        PublishableStep("repo_license_classification", "SPDX license risk tier.", "Git Repository"),
    ]


class TestRenderStepBlock:
    def test_includes_required_headers(self, steps):
        block = render_step_block("RepoFullSurvey", "Repo Full Survey", steps[0])
        assert "## Create Governance Action Process Step" in block
        assert "### Display Name" in block
        assert "### Qualified Name" in block
        assert "GovActionProcessStep::RepoFullSurvey::repo_health" in block
        assert "### Description" in block
        assert "Activity/community scoring." in block

    def test_additional_properties_convention(self, steps):
        block = render_step_block("RepoFullSurvey", "Repo Full Survey", steps[0])
        assert "executes_at | resource-explorer" in block
        assert "supported_technology_type | Git Repository" in block
        assert "re_analysis_step | repo_health" in block

    def test_display_name_is_readable_not_raw_key(self, steps):
        block = render_step_block("RepoFullSurvey", "Repo Full Survey", steps[2])
        # step_key "repo_license_classification" -> title-cased, underscores to spaces
        assert "Repo License Classification" in block
        assert "repo_license_classification" not in block.split("### Description")[0].split("### Display Name")[1].split("###")[0]


class TestRenderProcessBlock:
    def test_includes_required_headers(self):
        block = render_process_block("RepoFullSurvey", "Repo Full Survey", "Git Repository", "desc")
        assert "## Create Governance Action Process" in block
        assert "GovActionProcess::RepoFullSurvey" in block
        assert "supported_technology_type | Git Repository" in block


class TestLinkBlocks:
    def test_link_first_references_process_and_first_step(self):
        block = render_link_first_block("RepoFullSurvey", "repo_health")
        assert "## Link First Process Step" in block
        assert "GovActionProcess::RepoFullSurvey" in block
        assert "GovActionProcessStep::RepoFullSurvey::repo_health" in block

    def test_link_next_default_guard_is_any(self):
        block = render_link_next_block("RepoFullSurvey", "repo_health", "repo_language")
        assert "GovActionProcessStep::RepoFullSurvey::repo_health" in block
        assert "GovActionProcessStep::RepoFullSurvey::repo_language" in block
        assert "### Guard\nAny" in block

    def test_link_next_custom_guard(self):
        block = render_link_next_block("RepoFullSurvey", "a", "b", guard="a-complete")
        assert "### Guard\na-complete" in block


class TestGenerateSurveyDefinitionMarkdown:
    def test_raises_on_empty_steps(self):
        with pytest.raises(ValueError):
            generate_survey_definition_markdown("X", "X", "Git Repository", "desc", [])

    def test_block_ordering_and_counts(self, steps):
        md = generate_survey_definition_markdown(
            "RepoFullSurvey", "Repo Full Survey", "Git Repository", "desc", steps,
        )
        # N step-create blocks + 1 process-create + 1 link-first + (N-1) link-next
        assert md.count("## Create Governance Action Process Step") == 3
        assert md.count("## Create Governance Action Process\n") == 1
        assert md.count("## Link First Process Step") == 1
        assert md.count("## Link Next Process Step") == 2

    def test_steps_created_before_process_and_links(self, steps):
        # dr_egeria's dispatcher processes commands in file order — steps
        # must exist before the process/links that reference their
        # qualified names.
        md = generate_survey_definition_markdown(
            "RepoFullSurvey", "Repo Full Survey", "Git Repository", "desc", steps,
        )
        last_step_create_idx = md.rindex("## Create Governance Action Process Step")
        process_create_idx = md.index("## Create Governance Action Process\n")
        link_first_idx = md.index("## Link First Process Step")
        assert last_step_create_idx < process_create_idx < link_first_idx

    def test_link_chain_follows_step_order(self, steps):
        md = generate_survey_definition_markdown(
            "RepoFullSurvey", "Repo Full Survey", "Git Repository", "desc", steps,
        )
        first_link_idx = md.index("## Link First Process Step")
        # first link must reference the first step in the given order
        first_link_block = md[first_link_idx:md.index("## Link Next Process Step")]
        assert "repo_health" in first_link_block
        # chain order: repo_health -> repo_language -> repo_license_classification
        first_next_idx = md.index("## Link Next Process Step")
        second_next_idx = md.rindex("## Link Next Process Step")
        first_next_block = md[first_next_idx:second_next_idx]
        assert "repo_health" in first_next_block and "repo_language" in first_next_block
        second_next_block = md[second_next_idx:]
        assert "repo_language" in second_next_block and "repo_license_classification" in second_next_block

    def test_single_step_produces_no_link_next(self):
        steps = [PublishableStep("only_step", "desc", "Git Repository")]
        md = generate_survey_definition_markdown("X", "X Survey", "Git Repository", "desc", steps)
        assert md.count("## Create Governance Action Process Step") == 1
        assert md.count("## Link First Process Step") == 1
        assert "## Link Next Process Step" not in md

    def test_blocks_separated_by_horizontal_rule(self, steps):
        md = generate_survey_definition_markdown(
            "RepoFullSurvey", "Repo Full Survey", "Git Repository", "desc", steps,
        )
        assert "___" in md
