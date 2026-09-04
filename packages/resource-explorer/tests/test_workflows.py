"""The extracted workflows, called directly.

Step 2b moved the analysis-run, scouting-scan, GitHub-discovery and
curate-materialization flows out of `web/routes/` into
`resource_explorer/workflows/`. The route tests still exercise the routes; this
file exercises the workflow functions themselves, because they now have two
other callers (the Typer CLI and the run queue) that no route test covers.

The mocks are the ones the corresponding route tests already use — the point of
the move is that behaviour did not change, so the fixtures should not have had
to either.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "wf.db"))
    r.add(Project(
        slug="myproj", display_name="My Project",
        github_url="https://github.com/test/myproj", description="A test repo.",
    ))
    return r


class TestNoFastAPIInWorkflows:
    """The property that makes these callable from a CLI and a worker at all.

    Asserted structurally rather than trusted: an `from fastapi import
    HTTPException` added for one convenient early-return would re-couple the
    core to the web tier, and nothing else in the suite would notice — the
    routes would still pass, and the CLI would still import, because FastAPI is
    installed.
    """

    def test_no_workflow_module_imports_fastapi(self):
        import ast
        from pathlib import Path

        wf = Path(__file__).resolve().parents[1] / "resource_explorer" / "workflows"
        offenders = []
        for path in sorted(wf.glob("*.py")):
            # Parsed, not grepped: the package docstring explains at length why
            # FastAPI must stay out, and a substring check flags that prose as
            # the violation it is describing.
            for node in ast.walk(ast.parse(path.read_text())):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                if any(n.split(".")[0] in ("fastapi", "starlette") for n in names):
                    offenders.append(path.name)
        assert offenders == [], f"workflows importing fastapi: {sorted(set(offenders))}"


class TestAnalysisWorkflow:
    def _survey_result(self, annotations=1, errors=None):
        result = MagicMock()
        result.annotations = [{"a": i} for i in range(annotations)]
        result.errors = errors or []
        return result

    def test_the_ingest_branch_never_runs_a_survey(self, registry):
        """`action: "ingest"` re-embeds into pgvector; it is not a
        SurveyOrchestrator step, and treating it as one is how an unknown id
        used to reach the orchestrator."""
        from resource_explorer.workflows.analysis import run_analysis

        with patch("resource_explorer.ingestion.incremental.IncrementalIndexer") as Idx, \
             patch("resource_explorer.query_cache.QueryCache") as Cache, \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            result = run_analysis("myproj", "rag_ingestion", is_ingest=True,
                                  steps=None, registry=registry)
        assert result.status == "ok"
        assert "pgvector" in result.summary
        Idx.return_value.refresh.assert_called_once()
        Cache.return_value.invalidate_project.assert_called_once_with("myproj")
        Orch.assert_not_called()

    def test_an_unassigned_resource_never_attempts_publish(self, registry):
        """`published=None` is "never attempted", not "attempted and produced
        nothing" — the caller renders the two differently."""
        from resource_explorer.workflows.analysis import run_analysis

        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch, \
             patch("resource_explorer.surveyors.survey_report.summarise_annotations",
                   return_value=[]), \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as Pub:
            Orch.return_value.run.return_value = self._survey_result()
            result = run_analysis("myproj", "security_scan", is_ingest=False,
                                  steps=["repo_security"], registry=registry)
        assert result.status == "ok"
        assert result.published is None
        Pub.assert_not_called()

    def test_an_assigned_resource_publishes(self, registry):
        from resource_explorer.workflows.analysis import run_analysis

        registry.has_assigned_egeria_project = lambda *a, **k: True
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch, \
             patch("resource_explorer.surveyors.survey_report.summarise_annotations",
                   return_value=[]), \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as Pub:
            Orch.return_value.run.return_value = self._survey_result()
            result = run_analysis("myproj", "security_scan", is_ingest=False,
                                  steps=["repo_security"], registry=registry)
        assert result.published is True
        Pub.return_value.publish.assert_called_once()

    def test_a_publish_failure_does_not_fail_the_run(self, registry):
        """The findings are real and stored either way; `published=False` keeps
        the ☁ Publish button visible as the recovery path."""
        from resource_explorer.workflows.analysis import run_analysis

        registry.has_assigned_egeria_project = lambda *a, **k: True
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch, \
             patch("resource_explorer.surveyors.survey_report.summarise_annotations",
                   return_value=[]), \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as Pub:
            Orch.return_value.run.return_value = self._survey_result()
            Pub.return_value.publish.side_effect = RuntimeError("egeria down")
            result = run_analysis("myproj", "security_scan", is_ingest=False,
                                  steps=["repo_security"], registry=registry)
        assert result.status == "ok"
        assert result.published is False
        assert "auto-publish" in result.summary

    def test_a_missing_project_is_an_error_not_a_crash(self, registry):
        """A queue worker runs this minutes after the enqueue, so "the world has
        not moved" is a weaker assumption than it was when a route checked
        synchronously a moment earlier."""
        from resource_explorer.workflows.analysis import run_analysis

        result = run_analysis("ghost", "security_scan", is_ingest=False,
                              steps=["repo_security"], registry=registry)
        assert result.status == "error"
        assert "not found" in result.error

    def test_a_stage_batch_with_some_errors_and_some_output_is_not_a_failure(self, registry):
        from resource_explorer.workflows.analysis import run_stage_batch

        with patch("resource_explorer.surveyors.repo_survey_definition_adapter._run_batch",
                   return_value={"annotations": [{"a": 1}], "errors": ["step x blew up"]}), \
             patch("resource_explorer.surveyors.survey_report.summarise_annotations",
                   return_value=[]):
            result = run_stage_batch("myproj", "scouting", ["repo_health"], registry=registry)
        assert result.status == "ok", "11 of 12 steps' findings is not a failed batch"
        assert result.errors == ["step x blew up"]
        assert "1 error(s)" in result.summary

    def test_a_stage_batch_that_produced_nothing_is_a_failure(self, registry):
        from resource_explorer.workflows.analysis import run_stage_batch

        with patch("resource_explorer.surveyors.repo_survey_definition_adapter._run_batch",
                   return_value={"annotations": [], "errors": ["everything blew up"]}), \
             patch("resource_explorer.surveyors.survey_report.summarise_annotations",
                   return_value=[]):
            result = run_stage_batch("myproj", "scouting", ["repo_health"], registry=registry)
        assert result.status == "error"


class TestScoutingWorkflow:
    def test_an_egeria_definition_loss_falls_back_to_running_the_steps(self, registry):
        """Egeria-side Survey Definitions do not survive an Egeria database
        reset. Without the fallback that silently breaks Scouting Scan
        entirely — and the message has to SAY it ran locally, or a user
        reasonably concludes the Egeria route is fine."""
        from resource_explorer.surveyors.survey_definition_executor import (
            SurveyDefinitionExecutorError,
        )
        from resource_explorer.workflows.scouting import run_scouting_scan

        survey_result = MagicMock()
        survey_result.errors = []
        with patch("resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
                   side_effect=SurveyDefinitionExecutorError("no such definition")), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            Orch.return_value.run.return_value = survey_result
            result = run_scouting_scan("myproj", registry)
        assert result.status == "ok"
        assert "ran locally" in result.message
        assert Orch.return_value.run.call_args.kwargs["fast"] is True

    def test_the_fallback_failing_too_reports_both_causes(self, registry):
        from resource_explorer.surveyors.survey_definition_executor import (
            SurveyDefinitionExecutorError,
        )
        from resource_explorer.workflows.scouting import run_scouting_scan

        with patch("resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
                   side_effect=SurveyDefinitionExecutorError("no such definition")), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            Orch.return_value.run.side_effect = RuntimeError("github down")
            result = run_scouting_scan("myproj", registry)
        assert result.status == "error"
        assert "no such definition" in result.error
        assert "github down" in result.error

    def test_a_question_with_no_analyses_is_none_not_false(self):
        """"Nothing to check" and "checked and found nothing" are different
        answers, and the checklist renders them differently."""
        from resource_explorer.workflows.scouting import question_has_data

        assert question_has_data(MagicMock(), "myproj", []) is None

    def test_a_shaped_but_empty_payload_does_not_count_as_data(self):
        from resource_explorer.workflows.scouting import results_have_data

        assert results_have_data({"findings": [], "gap_count": 0}) is False
        assert results_have_data({"findings": [{"x": 1}], "gap_count": 0}) is True


class TestDiscoveryWorkflow:
    def test_a_query_with_no_filters_is_refused(self):
        """Before the archived:false/fork:false defaults are appended — those
        are not user filters, so an otherwise-empty request would produce a
        valid-looking query matching everything."""
        from resource_explorer.workflows.discovery import (
            DiscoveryError,
            RepoSearchCriteria,
            build_query,
        )

        with pytest.raises(DiscoveryError, match="At least one search filter"):
            build_query(RepoSearchCriteria())

    def test_defaults_exclude_forks_and_archived(self):
        from resource_explorer.workflows.discovery import RepoSearchCriteria, build_query

        q = build_query(RepoSearchCriteria(keyword="egeria"))
        assert "archived:false" in q and "fork:false" in q

    def test_filters_become_qualifiers(self):
        from resource_explorer.workflows.discovery import RepoSearchCriteria, build_query

        q = build_query(RepoSearchCriteria(
            keyword="metadata", min_stars=50, language="python", org="odpi",
            topic="governance", license="apache-2.0", pushed_after="2026-01-01",
        ))
        for expected in ("metadata", "stars:>=50", "language:python", "org:odpi",
                         "topic:governance", "license:apache-2.0", "pushed:>2026-01-01"):
            assert expected in q

    def test_a_github_auth_failure_is_reported_as_upstream(self):
        from github import GithubException

        from resource_explorer.workflows.discovery import (
            DiscoveryError,
            RepoSearchCriteria,
            run_search_query,
        )

        registry = MagicMock()
        registry.get_setting.return_value = None
        with patch("resource_explorer.github.client.GitHubClient") as Client:
            Client.return_value.search_repos.side_effect = GithubException(403, {}, {})
            with pytest.raises(DiscoveryError) as exc:
                run_search_query(RepoSearchCriteria(keyword="x"), registry)
        assert exc.value.kind == "upstream"
        assert "GITHUB_TOKEN" in str(exc.value)

    def test_an_invalid_query_is_the_callers_problem_not_githubs(self):
        from github import GithubException

        from resource_explorer.workflows.discovery import (
            DiscoveryError,
            RepoSearchCriteria,
            run_search_query,
        )

        registry = MagicMock()
        registry.get_setting.return_value = None
        with patch("resource_explorer.github.client.GitHubClient") as Client:
            Client.return_value.search_repos.side_effect = GithubException(422, {}, {})
            with pytest.raises(DiscoveryError) as exc:
                run_search_query(RepoSearchCriteria(keyword="x"), registry)
        assert exc.value.kind == "bad_request"

    def test_expand_org_reports_truncation_rather_than_implying_completeness(self):
        """"I gave you 3 lines and got 214 repos" needs an explanation attached,
        and a capped expansion must never read as the whole account."""
        from resource_explorer.workflows.discovery import expand_org

        with patch("resource_explorer.github.client.GitHubClient") as Client:
            Client.return_value.search_repos.return_value = [
                {"html_url": f"https://github.com/o/r{i}"} for i in range(5)
            ]
            expansion = expand_org("o", limit=5)
        assert expansion.truncated is True
        assert len(expansion.urls) == 5

    def test_expand_org_reports_a_failure_instead_of_raising(self):
        from resource_explorer.workflows.discovery import expand_org

        with patch("resource_explorer.github.client.GitHubClient") as Client:
            Client.return_value.search_repos.side_effect = RuntimeError("network")
            expansion = expand_org("o")
        assert expansion.urls == []
        assert "network" in expansion.error

    def test_an_unknown_disposition_is_refused(self):
        from resource_explorer.workflows.discovery import DiscoveryError, set_disposition

        with pytest.raises(DiscoveryError, match="Invalid disposition"):
            set_disposition(MagicMock(), "https://github.com/a/b", "maybe")

    def test_a_valid_disposition_is_recorded_with_the_slug_when_known(self, registry):
        from resource_explorer.workflows.discovery import set_disposition

        result = set_disposition(registry, "https://github.com/test/myproj", "tracking")
        assert result["disposition"] == "tracking"
        assert registry.get_disposition("https://github.com/test/myproj")["disposition"] == "tracking"


class TestCurateWorkflow:
    def test_a_non_accepted_verdict_materializes_nothing(self, registry):
        from resource_explorer.workflows.curate import materialize_component_if_accepted

        assert materialize_component_if_accepted(
            registry, "repo", "myproj", "src/api", "rejected") is None

    def test_a_non_repo_entity_materializes_nothing(self, registry):
        """The materializer is wired for repos only — the one kind
        architecture_recovery runs against. Reusing it past what it was built
        for would be a silent wrong answer, not a missing feature."""
        from resource_explorer.workflows.curate import materialize_component_if_accepted

        assert materialize_component_if_accepted(
            registry, "database", "mydb", "public", "accepted") is None

    def test_a_missing_finding_is_an_error_not_a_silent_skip(self, registry):
        """The component's finding row can be gone — withdrawn since the review
        surface loaded. Saying so beats returning None, which the caller reads
        as "nothing to do"."""
        from resource_explorer.workflows.curate import materialize_component_if_accepted

        result = materialize_component_if_accepted(
            registry, "repo", "myproj", "src/api", "accepted")
        assert result["status"] == "error"
        assert "no component finding" in result["error"]

    def test_a_missing_candidate_blueprint_is_an_error(self, registry):
        from resource_explorer.workflows.curate import materialize_blueprint_if_accepted

        result = materialize_blueprint_if_accepted(
            registry, "repo", "myproj", "runtime", "Ingest", "accepted")
        assert result["status"] == "error"
        assert "no candidate_blueprint" in result["error"]
